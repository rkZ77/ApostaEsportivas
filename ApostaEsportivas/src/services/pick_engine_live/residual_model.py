"""Modelo residual: quanto AINDA falta acontecer nos minutos que sobraram.

A DIFERENCA DE PERGUNTA
-----------------------
O motor pre-jogo pergunta "quanto este confronto costuma produzir em 90
minutos" e responde com taxa historica. Aplicar essa taxa a um jogo aos 63
minutos afirma algo falso: metade do evento ja aconteceu e esta' no placar.

Aqui a pergunta e' outra: dado o que ja aconteceu e o tempo que resta, qual a
distribuicao do que ainda vem. A resposta e' um lambda residual, e a
probabilidade da linha sai de Poisson sobre O QUE FALTA pra bater a linha:

    faltam = linha - ja_observado
    P(Over linha) = P(X_restante > faltam)

E' esta subtracao que liga o modelo a' regra de liquidacao do projeto: o pick
e' graduado pelo TOTAL da partida (services/settlement.py), entao a estimativa
tambem tem que terminar em total, nunca em "eventos daqui pra frente".

COMO O LAMBDA RESIDUAL E' CONSTRUIDO
------------------------------------
    lambda = taxa_por_minuto x minutos_restantes x fator_ritmo x ajuste_estado

`taxa_por_minuto` NAO e' a taxa observada crua. Aos 15 minutos, um jogo com 3
escanteios tem taxa observada de 0.20/min, que projetada da' 18 escanteios --
absurdo estatistico de amostra curta, e exatamente o tipo de numero que
geraria pick de Over com falsa margem. A taxa e' encolhida em direcao ao
BASELINE (media da liga, ou a expectativa pre-jogo do confronto quando ela
existe):

    w = fracao_jogada / (fracao_jogada + FORCA_DO_PRIOR)
    taxa = w x taxa_observada + (1 - w) x taxa_baseline

O PESO NAO VEM DO RELOGIO, VEM DA DISPERSAO DA FAMILIA (2026-09-10)
-------------------------------------------------------------------
Ate' hoje o peso era `minuto / (minuto + 45)`: so' o relogio, igual pra toda
familia. Isso e' a mesma conta que `w = f / (f + 0.5)`, ou seja, o historico
inteiro dos dois times entrava valendo MEIO JOGO contra o que a partida tinha
mostrado ate' ali.

A conta certa e' a posterior Gama-Poisson, e ela ja' estava medida no projeto.
Se a contagem por partida tem dispersao phi (probability_model._DISPERSAO),
entao o lambda da partida varia em torno da media com forca de prior

    beta = 1 / (phi - 1)   jogos

e o peso do proprio jogo e' `f / (f + beta)`, com f = minuto/90. Nada aqui e'
escolhido: phi saiu da base de PROD em 2026-08-20 e beta e' consequencia dele.

O que os numeros dizem, comparado com o que o motor fazia:

    familia    phi   beta (jogos)    peso aos 45'      peso aos 45' (antes)
    gols      1.07      14.3             0.03                 0.50
    escanteio 1.82       1.22            0.29                 0.50
    cartao    2.28       0.78            0.39                 0.50
    faltas    3.12       0.47            0.51                 0.50

A linha de faltas e' a leitura do defeito: o motor tratava TODA familia como se
ela fosse tao superdispersa quanto falta. Gol e' quase Poisson (phi 1.07), o
que quer dizer que a variacao de gols entre partidas e' quase toda sorte, nao
diferenca real de jogo -- entao 36 minutos sem gol nao descrevem uma partida
truncada, descrevem a partida mais comum que existe. O motor lia esse vazio
como 44% da evidencia e cortava 44% do baseline.

A CALIBRACAO MEDIDA CONFIRMA A DERIVACAO. O comentario de
config.probabilidade_minima_por_familia registra 12.6pp de erro em gols contra
2.4pp em escanteios. E' exatamente a ordem da distancia entre o peso antigo e
este: gols estava 0.50 contra 0.03 (erro grande), escanteio 0.50 contra 0.29
(erro pequeno), e falta, que ja' estava no lugar certo, nunca apareceu na
lista.

E ISTO E' CONSISTENCIA, NAO OPINIAO NOVA. `dispersao_residual`, mais abaixo,
ja' descrevia a partida com este MESMO Gama-Poisson pra achar o phi do trecho
que falta -- ela usa `r = lambda_total / (phi_total - 1)`, que e' o mesmo beta
daqui multiplicado pelo lambda (r = lambda x beta). O modulo acreditava no
prior na hora de calcular a VARIANCIA do residual e ignorava esse mesmo prior
na hora de calcular a MEDIA dele. As duas pontas agora contam a mesma historia.

O QUE ISTO NAO DESLIGA: o que a partida mostrou continua entrando por dois
outros caminhos, que sao os canais certos pra mudanca de estado -- `ajuste_estado`
(placar, expulsao, pressao, necessidade) e `fator_ritmo`. E a projecao final
continua sendo `observado + lambda_residual`, entao um 3x0 continua projetando
em cima de 3. O que mudou e' so' a pergunta "este jogo tem lambda diferente do
que o historico dizia", e quem responde ela e' a dispersao.

`fator_ritmo` vem de rhythm_model (janela recente + tendencia) e `ajuste_estado`
sai daqui, combinando placar, expulsao com minuto e pressao ofensiva. O
baseline e' o ponto de partida; o comportamento atual e' o sinal principal.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao busca dado, nao le banco, nao decide pick. Recebe numeros e devolve
numeros, pra poder ser testado inteiro sem subir nada.
"""
from __future__ import annotations

import math

from services.pick_engine import probability_model as pm

#: Duracao regulamentar. Acrescimo NAO entra: a casa liquida o mercado com o
#: jogo inteiro, mas o tempo restante estimado tem que ser conservador --
#: contar acrescimo como tempo garantido inflaria todo Over.
MINUTOS_REGULAMENTARES = 90

#: Teto da forca do prior, em jogos. Existe so' por seguranca numerica: phi
#: chega a 1.00 em familia nao medida (`dispersao` devolve 1.0 por padrao) e
#: `1/(phi-1)` estouraria. Com 20 jogos o proprio jogo ainda pesa 2% aos 45',
#: que e' o comportamento certo pra uma familia sobre a qual nao ha medicao:
#: acredite no historico ate' provarem o contrario.
FORCA_MAXIMA_DO_PRIOR = 20.0

#: Piso da forca do prior, em jogos. Familia absurdamente dispersa nao pode
#: fazer o baseline sumir de vez -- meio jogo era o valor implicito da formula
#: antiga pra TODAS elas, e aqui ele vira o chao de uma so'.
FORCA_MINIMA_DO_PRIOR = 0.4

# O ponto neutro de cartao mora no pre-jogo (referee_model): e' o mesmo
# conceito nos dois motores, e duas constantes divergiriam no primeiro ajuste.
from services.pick_engine import referee_model

#: Media por partida quando nao ha baseline medido. Sao os numeros tipicos de
#: futebol de clubes; o pipeline sobrescreve com a media real da liga vinda de
#: `match_statistics` (custo zero de API) sempre que houver amostra.
BASELINE_PADRAO = {
    "corners": 10.2,
    "goals": 2.72,
    # Pontos de cartao por partida (amarelo=1, vermelho=2). O numero vem do
    # pre-jogo em vez de ser escolhido aqui: e' o MESMO ponto neutro que
    # referee_model usa pra encolher a media do arbitro, e duas constantes
    # diferentes pro mesmo conceito divergiriam no primeiro ajuste.
    "cards": referee_model._REFEREE_CARD_POINTS_BASELINE,
    # MEDIDOS EM 2026-09-04, contra 1.173 partidas encerradas de
    # `match_statistics` nas ligas do projeto. Entraram porque a ausencia deles
    # era o que segurava a familia de chutes fora da V1 ("Chutes e o resto
    # continuam fora ate' o residual estar medido", live_odds.FAMILIAS_V1) --
    # e porque o mercado ao vivo de chute de JOGADOR (148/153) so' pode ser
    # precificado sobre o residual do time.
    #
    #   chutes       26.04 por partida, dispersao (var/media) 2.07
    #   no alvo       8.54 por partida, dispersao 1.24
    #
    # Estar aqui NAO liga a familia: `FAMILIAS_V1` continua sem eles. E' o
    # insumo, nao a decisao.
    "shots": 26.04,
    "shots_on_target": 8.54,
    # MEDIDO EM 2026-09-04, mesma consulta e mesma base dos dois acima:
    # 24.82 faltas por partida em 1.189 encerradas, dispersao (var/media) 2.13.
    # O pre-jogo mediu 3.12 pro total (probability_model._DISPERSAO) contra
    # estas 2.13 -- recortes diferentes da mesma base, e quem manda no residual
    # continua sendo o _DISPERSAO do pre-jogo, pra as duas metades do projeto
    # nao divergirem no numero.
    "fouls": 24.82,
}


def minutos_restantes(minuto: int | None, status: str = "") -> int | None:
    """Minutos regulamentares que faltam. None quando nao da' pra saber.

    No intervalo (HT) a API para o relogio em 45; o restante e' o segundo
    tempo inteiro. Prorrogacao devolve 0: o mercado de tempo normal ja
    fechou e o motor nao opera nela.
    """
    if status == "HT":
        return 45
    if status in ("ET", "BT", "P"):
        return 0
    if minuto is None:
        return None
    return max(0, MINUTOS_REGULAMENTARES - int(minuto))


def forca_do_prior(familia: str | None) -> float:
    """Quantos JOGOS de historico o baseline vale, pra esta familia.

    beta = 1 / (phi - 1), da Gama-Poisson: a contagem por partida tem media mu
    e variancia mu + mu**2/alfa, entao phi = 1 + mu/alfa e beta = alfa/mu.
    Familia pouco dispersa e' familia cujo lambda quase nao muda de jogo pra
    jogo -- e prior que quase nao muda e' prior forte.
    """
    phi = pm.dispersao(familia, "total")
    beta = 1.0 / max(phi - 1.0, 1.0 / FORCA_MAXIMA_DO_PRIOR)
    return max(FORCA_MINIMA_DO_PRIOR, min(FORCA_MAXIMA_DO_PRIOR, beta))


def taxa_por_minuto(observado: int | None, minuto: int | None,
                    baseline_por_partida: float,
                    familia: str | None = None) -> dict | None:
    """Taxa estimada de eventos por minuto, encolhida contra o baseline.

    `familia` decide o quanto o proprio jogo pesa contra o historico, pela
    dispersao medida dela (ver o cabecalho e `forca_do_prior`). Sem familia o
    prior fica no teto, que e' o lado conservador: na duvida, o historico manda.

    Devolve o rastro completo (observada, baseline, peso, phi, forca do prior,
    final) porque cada numero destes precisa aparecer no engine_debug -- sem
    isso nao ha como auditar depois por que o motor projetou o que projetou.
    """
    if observado is None or minuto is None or minuto <= 0:
        return None
    if baseline_por_partida is None or baseline_por_partida <= 0:
        return None

    taxa_observada = observado / minuto
    taxa_baseline = baseline_por_partida / MINUTOS_REGULAMENTARES
    fracao_jogada = min(1.0, minuto / MINUTOS_REGULAMENTARES)
    beta = forca_do_prior(familia)
    peso = fracao_jogada / (fracao_jogada + beta)
    final = peso * taxa_observada + (1 - peso) * taxa_baseline
    return {
        "taxa_observada_min": round(taxa_observada, 5),
        "taxa_baseline_min": round(taxa_baseline, 5),
        "peso_observado": round(peso, 4),
        "dispersao_phi": round(pm.dispersao(familia, "total"), 3),
        "forca_do_prior_jogos": round(beta, 3),
        "taxa_estimada_min": round(final, 5),
    }


def ajuste_estado(familia: str, estado: dict, pressao: dict | None = None,
                  eventos: dict | None = None, necessidade: dict | None = None,
                  confirmacao: dict | None = None) -> dict:
    """Multiplicador pelo ESTADO do jogo: placar, expulsao, pressao e
    necessidade do resultado.

    Cada termo e' pequeno, multiplicativo e explicado. Bem maior que 1 ou bem
    menor que 1 aqui seria chute com cara de modelo.

    O que esta' modelado, e por que:

    - FIM DE JOGO APERTADO abre a partida. Diferenca de 0 ou 1 gol depois dos
      70' muda o comportamento dos dois lados: quem perde se lanca, quem ganha
      contra-ataca.
    - JOGO RESOLVIDO (3+ de diferenca) desacelera. Ninguem forca mais nada.
    - ESCANTEIO SE CONCENTRA NO FIM, por efeito de cronometro: bola na area,
      rebote, lateral ofensivo.
    - EXPULSAO pesa pelo MINUTO em que aconteceu. Aos 20' ela muda 70 minutos
      de jogo; aos 85' quase nao muda nada. Sem /fixtures/events so' se sabe
      que houve, e ai o efeito entra pela metade -- metade da informacao falta.
    - PRESSAO ALTA sustenta volume; pressao baixa indica que o acumulado veio
      de rajada e tende a regredir. E' o termo que distingue "7 escanteios com
      12 finalizacoes" de "7 escanteios com 2 finalizacoes".
    """
    fatores: list[tuple[str, float]] = []

    minuto = estado.get("minuto")
    diferenca = estado.get("diferenca_gols")
    tarde = minuto is not None and int(minuto) >= 70

    if diferenca is not None:
        if diferenca >= 3:
            fatores.append(("jogo resolvido (3+ de diferenca)", 0.88))
        elif tarde and diferenca <= 1:
            fatores.append(("fim de jogo apertado", 1.12 if familia == "goals" else 1.08))

    if familia == "corners" and tarde:
        fatores.append(("escanteio se concentra no fim", 1.10))

    vermelho_min = (eventos or {}).get("vermelho_minuto")
    if vermelho_min is not None:
        restante = max(0.0, (MINUTOS_REGULAMENTARES - int(vermelho_min)) / MINUTOS_REGULAMENTARES)
        efeito = 1 + (0.12 if familia == "goals" else 0.05) * restante
        fatores.append((f"expulsao aos {int(vermelho_min)}'", round(efeito, 4)))
    elif estado.get("red_cards_total"):
        fatores.append(("expulsao sem minuto conhecido", 1.04))

    # NECESSIDADE DO RESULTADO, ja' cruzada com o placar de agora e pesada
    # pelo cronometro (need_model). E' o que o `diferenca_gols` acima nao
    # conseguia dizer: ele so' sabe se o jogo esta' apertado, nao se alguem
    # PRECISA muda-lo. Um 0x0 aos 80' com o mandante precisando reverter um
    # agregado e um 0x0 aos 80' entre dois times ja' classificados sao a mesma
    # coisa pro termo de placar e opostos aqui.
    #
    # O fator de confirmacao entra junto: se quem precisa nao esta' criando
    # nada em campo, a necessidade e' DESCONTADA em vez de aplicada -- o
    # contexto e' referencia, o campo e' o veredito.
    if necessidade and necessidade.get("intensidade"):
        efeito = 1 + (0.14 if familia == "goals" else 0.10) * necessidade["intensidade"]
        efeito *= (confirmacao or {}).get("fator", 1.0)
        fatores.append((f"necessidade do resultado ({necessidade.get('quem_precisa')})",
                        round(efeito, 4)))

    if pressao and pressao.get("total") is not None:
        # 0.50 e' a pressao de dois times medios (a escala de pressure_model
        # e' centrada nesse ponto). O desvio entra suavizado: pressao e' sinal,
        # nao veredito.
        desvio = (pressao["total"] - 0.50) / 0.50
        efeito = 1 + max(-0.18, min(0.18, desvio * 0.25))
        fatores.append((f"pressao {pressao.get('nivel_total')}", round(efeito, 4)))

    total = 1.0
    for _, f in fatores:
        total *= f
    # Teto duplo: nenhum conjunto de estados justifica mudar a projecao em
    # mais de um terco pra cima ou um quarto pra baixo.
    total = max(0.75, min(1.35, total))
    return {"fator": round(total, 4),
            "componentes": [{"motivo": m, "fator": f} for m, f in fatores]}


def lambda_residual(familia: str, observado: int | None, minuto: int | None,
                    status: str, baseline_por_partida: float,
                    fator_ritmo: dict | None = None,
                    ajuste: dict | None = None) -> dict | None:
    """O lambda do que ainda falta, com o rastro inteiro de como chegou nele.

    `fator_ritmo` vem de rhythm_model.fator_de_ritmo e `ajuste` de
    ajuste_estado() acima. Os dois sao opcionais: sem eles o modelo continua
    valido, so' mais cego -- e o rastro registra que foram neutros.
    """
    restantes = minutos_restantes(minuto, status)
    if restantes is None or restantes <= 0:
        return None
    taxa = taxa_por_minuto(observado, minuto, baseline_por_partida, familia)
    if taxa is None:
        return None

    ritmo_info = fator_ritmo or {"fator": 1.0, "motivo": "ritmo nao calculado"}
    estado_info = ajuste or {"fator": 1.0, "componentes": []}

    lam = (taxa["taxa_estimada_min"] * restantes
           * ritmo_info["fator"] * estado_info["fator"])
    return {
        "familia": familia,
        "observado": observado,
        "minuto": minuto,
        "minutos_restantes": restantes,
        "baseline_por_partida": round(baseline_por_partida, 3),
        **taxa,
        "ritmo": ritmo_info,
        "estado": estado_info,
        "lambda_residual": round(lam, 4),
        "projecao_total": round((observado or 0) + lam, 2),
    }


def dispersao_residual(familia: str, baseline_por_partida: float | None,
                       lambda_residual_valor: float | None,
                       minutos_restantes_valor: int | None) -> float:
    """phi do que AINDA FALTA, derivado do phi da partida inteira.

    O pre-jogo mediu que escanteio tem variancia 1.82x a media
    (probability_model._DISPERSAO). Aqui a pergunta e' outra: quanto disso
    ainda vale depois de ver 40 minutos de jogo?

    NAO e' uma interpolacao inventada -- e' a preditiva posterior do MESMO
    modelo Gama-Poisson que produziu aquele numero. Se o ritmo da partida e'
    um multiplicador theta ~ Gama(r, r) sobre a taxa base, entao:

        contagem da partida inteira  ->  phi_total = 1 + lambda_total / r
        logo                              r = lambda_total / (phi_total - 1)

    Observar o primeiro trecho do jogo atualiza theta. A preditiva do trecho
    que falta e' Binomial Negativa com

        phi_restante = 1 + lambda_restante / (r + exposicao_ja_observada)

    onde a exposicao e' o lambda ESPERADO do trecho ja' jogado (o parametro de
    taxa da Gama posterior anda com a exposicao, nao com a contagem).

    O comportamento sai certo sozinho, sem nenhum ajuste manual -- escanteio
    com lambda 8.79 e phi 1.82 da' r = 10.7 e:

        minuto 15  ->  phi 1.60   (quase nada resolvido, quase o phi total)
        minuto 45  ->  phi 1.29
        minuto 80  ->  phi 1.05   (o jogo ja' se revelou, volta pra Poisson)

    E' por isso que o pre-jogo nao podia simplesmente emprestar o numero dele
    pro ao vivo: 1.82 aos 80 minutos seria descontar duas vezes uma incerteza
    que a partida ja' resolveu.
    """
    phi_total = pm.dispersao(familia, "total")
    if (phi_total <= 1.0 or not baseline_por_partida
            or not lambda_residual_valor or lambda_residual_valor <= 0):
        return 1.0
    r = baseline_por_partida / (phi_total - 1.0)
    restantes = max(0, min(MINUTOS_REGULAMENTARES, minutos_restantes_valor or 0))
    fracao_ja_jogada = 1.0 - (restantes / MINUTOS_REGULAMENTARES)
    exposicao = baseline_por_partida * max(0.0, fracao_ja_jogada)
    return round(1.0 + lambda_residual_valor / (r + exposicao), 4)


def probabilidade_da_linha(lam: float, linha: float, direcao: str,
                           ja_observado: int, phi: float = 1.0) -> float | None:
    """P(total da partida bater a linha), a partir do lambda do que falta.

    A conversao e' a peca que mantem modelo e liquidacao falando do mesmo
    numero. Pick de "Over 9.5 escanteios" criado com 7 no placar precisa de
    mais de 2.5 escanteios, entao a pergunta virada pro Poisson e'
    P(X_restante > 2.5).

    `phi` e' a dispersao do trecho que falta (ver dispersao_residual). O
    default 1.0 e' Poisson exato -- quem chamar sem ele ve o comportamento
    anterior a 2026-08-20.

    Linha ja resolvida pelo placar devolve certeza pratica, nao 1.0 exato: EV
    infinito quebraria o gate seguinte. Quem corta esse caso e' o
    orquestrador, antes de chegar aqui.

    LINHA QUARTER (.25/.75) e' meia aposta em cada linha vizinha · ver
    _prob_quarter. A casa cota gols ao vivo em quarter o tempo todo, e sem
    este ramo o motor lia "Over 3.75" como se fosse "Over 3.5".
    """
    if lam is None or lam < 0:
        return None
    direcao = (direcao or "").strip().lower()
    if direcao not in ("over", "under"):
        return None

    faltam = linha - ja_observado
    if direcao == "over":
        if faltam < 0:
            return 0.9999
        if _e_quarter(faltam):
            return _prob_quarter(faltam, lam, phi, "over")
        if _e_inteira(faltam):
            return _prob_inteira(faltam, lam, phi, "over")
        return pm.prob_over(faltam, lam, phi)
    if faltam < 0:
        return 0.0001
    if _e_quarter(faltam):
        return _prob_quarter(faltam, lam, phi, "under")
    if _e_inteira(faltam):
        return _prob_inteira(faltam, lam, phi, "under")
    return pm.prob_under(faltam, lam, phi)


def _e_quarter(linha: float) -> bool:
    """.25 ou .75 · a linha asiatica que vale metade em cada vizinha."""
    return abs((linha * 4) % 2) > 1e-9


def _e_inteira(linha: float) -> bool:
    """x.0 · a linha em que empatar exato DEVOLVE a aposta."""
    return abs(linha - round(linha)) < 1e-9


def _prob_inteira(faltam: float, lam: float, phi: float, direcao: str) -> float:
    """Probabilidade de uma linha REDONDA, condicionada a nao dar push.

    O QUE ESTAVA ERRADO (2026-09-10)
    --------------------------------
    "Escanteios Mais de 6.0" com 6 escanteios no fim NAO e' RED: a casa devolve
    a aposta, e `settlement._straight` ja' liquida isso certo (valor igual a'
    linha devolve fator 0 = PUSH). Quem nao sabia disso era o MODELO do ao
    vivo: ele lia a linha redonda com `pm.prob_over`, que conta o empate exato
    como derrota, e publicava P(X > 6) como se fosse a chance da aposta.

    A chance que interessa e' a condicional a a aposta ser DECIDIDA, porque o
    empate nao e' um desfecho ruim, e' um desfecho que nao acontece:

        P(green | nao push) = P(green) / (1 - P(empate exato))

    Esta e' a MESMA convencao que o pre-jogo aplica desde sempre em
    `pm.poisson_prob_for_line`, e a mesma que `_prob_quarter` aqui do lado ja'
    aplicava na vizinha inteira dela. O ao vivo era o unico caminho do projeto
    que lia uma linha redonda como se fosse meia.

    O ERRO SUBESTIMAVA, e por isso passou despercebido: probabilidade menor
    vira EV menor, e EV menor reprova no gate em vez de gerar pick ruim. O
    custo era pick que deveria existir e nao existia, e um numero na tela que
    nao era o mesmo numero que os outros motores publicam.

    Exemplo real (Sao Bernardo x Londrina, escanteios Mais de 6.0 aos 45' com
    3 no placar, lambda residual 3.2): 72.6% lido como 68.3%.

    O caso "so' pode empatar ou perder" sai certo sozinho: Under 6.0 com 6 no
    placar deixa `faltam` em 0, o numerador vira zero e a familia reprova no
    piso de probabilidade. Nao precisa de gate proprio.
    """
    push = pm.nb_pmf(int(round(faltam)), lam, phi)
    if direcao == "over":
        # prob_over ja' exclui o empate exato do numerador (usa floor).
        p = pm.prob_over(faltam, lam, phi)
    else:
        # prob_under INCLUI o empate exato -- tira ele antes de renormalizar.
        p = pm.prob_under(faltam, lam, phi) - push
    if push < 1.0:
        p = p / (1.0 - push)
    return round(max(0.0, min(1.0, p)), 6)


def _prob_quarter(linha: float, lam: float, phi: float, direcao: str) -> float:
    """Probabilidade de uma linha quarter, medida como o que ela e': METADE da
    aposta em cada linha vizinha.

    O BUG QUE ISTO CORRIGE (2026-09-10)
    -----------------------------------
    `pm.prob_under` diz na propria docstring que "linhas de aposta sao sempre
    .5" -- e' verdade no pre-jogo, e e' falso aqui. A casa cota gols AO VIVO em
    quarter o tempo todo: dos 168 picks ao vivo ja liquidados em PROD, 25
    tinham linha quarter, e os 25 eram de GOLS. Nenhum de escanteios.

    Como as duas funcoes usam `floor(linha)`, a linha quarter era silenciosamente
    trocada por uma vizinha .5 -- e QUAL vizinha depende do lado, o que faz o
    erro trocar de sinal sem nenhum aviso (lambda residual 1.8, sem observado):

        over  3.75   lia Over 3.5     0.109 -> 0.074   superestimava 3.5pp
        under 2.25   lia Under 2.5    0.731 -> 0.681   superestimava 4.9pp
        under 1.75   lia Under 1.5    0.463 -> 0.547   SUBestimava  8.5pp

    O caso do Over e' o mais caro porque e' o mais direto: "Over 3.75" contava
    X=4 como acerto CHEIO quando na verdade ele paga metade (Over 3.5 ganha,
    Over 4.0 devolve). O erro e' 0.5 * P(X=4), e perto da linha P(X=4) e' a
    maior massa da distribuicao inteira.

    Nao e' o mesmo achado da medicao de 09/09, e' uma segunda causa embaixo
    dela: la o problema era o modelo extrapolar o pico de ritmo (por isso gols
    so' entra em UNDER), aqui e' a conta da linha estar errada nos DOIS lados.
    As duas somam, e as duas continuam valendo depois desta correcao.

    Linha .5 nao muda em nada -- e' o que o teste protege.

    A convencao aqui e' a que o motor ja adota pra linha redonda em
    `pm.poisson_prob_for_line`: cada metade e' medida condicionada a NAO dar
    push. Meia aposta em cada uma, media simples -- e' o que a aposta e'.
    """
    baixa, alta = linha - 0.25, linha + 0.25   # ex.: 3.75 -> 3.5 e 4.0
    if direcao == "over":
        p_meia = pm.prob_over(baixa, lam, phi)
    else:
        p_meia = pm.prob_under(baixa, lam, phi)
    # A vizinha inteira empata na linha em vez de perder, e quem sabe disso e'
    # `_prob_inteira` -- a mesma funcao que a linha redonda sozinha usa. Em
    # 2026-09-10 esta conta estava escrita duas vezes, aqui e la'; duas copias
    # da mesma convencao divergem no primeiro ajuste.
    p_inteira = _prob_inteira(alta, lam, phi, direcao)
    return round(0.5 * p_meia + 0.5 * p_inteira, 6)


def encolher_contra_mercado(prob_modelo: float, prob_mercado: float | None,
                            minuto: int) -> dict:
    """Puxa a probabilidade do modelo em direcao a' do mercado.

    Mesmo principio do prior de mercado que o pre-jogo adotou em 2026-08-08
    (ver o comentario longo em pick_engine/orchestrator.py): na falta de
    evidencia propria forte, acredite no consenso. A diferenca e' o peso --
    aqui o mercado pesa MAIS, porque ao vivo ele e' mais afiado, e o que
    compra peso pro nosso lado e' o minuto: quanto mais jogo observado, mais
    o modelo tem direito a discordar.

        peso_modelo = minuto / (minuto + 45)

    Aos 20' o modelo vale 31%; aos 75', 63%. Sem mercado, devolve o modelo
    intacto.
    """
    if prob_mercado is None:
        return {"prob": round(prob_modelo, 4), "peso_modelo": 1.0,
                "prob_pre_encolhimento": None}
    peso = max(0, int(minuto)) / (max(0, int(minuto)) + 45.0)
    final = peso * prob_modelo + (1 - peso) * float(prob_mercado)
    return {
        "prob": round(final, 4),
        "peso_modelo": round(peso, 4),
        "prob_pre_encolhimento": round(prob_modelo, 4),
    }


def intervalo_poisson(lam: float, cobertura: float = 0.80) -> tuple[int, int]:
    """Faixa central de eventos restantes. So' pra exibicao e log -- ajuda a
    ler se o lambda faz sentido antes de olhar a probabilidade."""
    if lam is None or lam < 0:
        return (0, 0)
    resto = (1 - cobertura) / 2
    acumulado, baixo, alto = 0.0, 0, 0
    for k in range(0, 60):
        acumulado += pm.poisson_pmf(k, lam)
        if acumulado <= resto:
            baixo = k + 1
        if acumulado >= 1 - resto:
            alto = k
            break
    else:
        alto = math.ceil(lam * 2)
    return (baixo, max(baixo, alto))
