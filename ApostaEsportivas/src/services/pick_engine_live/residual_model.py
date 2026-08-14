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
existe) com peso que cresce com o minuto:

    w = minuto / (minuto + MEIA_CONFIANCA)
    taxa = w x taxa_observada + (1 - w) x taxa_baseline

Aos 15' o jogo pesa 33%; aos 75', 71%. Mesma logica do encolhimento bayesiano
que o pre-jogo aplica (bayesian_model.shrink_taxa) -- amostra curta nao vira
convicção.

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

#: Ponto em que o proprio jogo passa a valer metade da estimativa.
#:
#: 45 (e nao 30) porque contagem de evento por partida REGRIDE forte: um jogo
#: com 7 escanteios aos 38' quase nunca termina no ritmo que vinha -- ele
#: termina perto de 15, nao de 20. Com 30 o proprio jogo pesava 56% aos 38' e
#: a projecao saia sistematicamente acima do que a partida entrega; com 45 ele
#: pesa 46% no mesmo minuto e ~62% aos 75', quando ja ha jogo suficiente pra
#: sustentar a discordancia.
#:
#: Numero de partida declarado, pra calibrar contra resultado medido.
MEIA_CONFIANCA = 45.0

#: Media por partida quando nao ha baseline medido. Sao os numeros tipicos de
#: futebol de clubes; o pipeline sobrescreve com a media real da liga vinda de
#: `match_statistics` (custo zero de API) sempre que houver amostra.
BASELINE_PADRAO = {
    "corners": 10.2,
    "goals": 2.72,
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


def taxa_por_minuto(observado: int | None, minuto: int | None,
                    baseline_por_partida: float) -> dict | None:
    """Taxa estimada de eventos por minuto, encolhida contra o baseline.

    Devolve o rastro completo (observada, baseline, peso, final) porque cada
    numero destes precisa aparecer no engine_debug -- sem isso nao ha como
    auditar depois por que o motor projetou o que projetou.
    """
    if observado is None or minuto is None or minuto <= 0:
        return None
    if baseline_por_partida is None or baseline_por_partida <= 0:
        return None

    taxa_observada = observado / minuto
    taxa_baseline = baseline_por_partida / MINUTOS_REGULAMENTARES
    peso = minuto / (minuto + MEIA_CONFIANCA)
    final = peso * taxa_observada + (1 - peso) * taxa_baseline
    return {
        "taxa_observada_min": round(taxa_observada, 5),
        "taxa_baseline_min": round(taxa_baseline, 5),
        "peso_observado": round(peso, 4),
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
    taxa = taxa_por_minuto(observado, minuto, baseline_por_partida)
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


def probabilidade_da_linha(lam: float, linha: float, direcao: str,
                           ja_observado: int) -> float | None:
    """P(total da partida bater a linha), a partir do lambda do que falta.

    A conversao e' a peca que mantem modelo e liquidacao falando do mesmo
    numero. Pick de "Over 9.5 escanteios" criado com 7 no placar precisa de
    mais de 2.5 escanteios, entao a pergunta virada pro Poisson e'
    P(X_restante > 2.5).

    Linha ja resolvida pelo placar devolve certeza pratica, nao 1.0 exato: EV
    infinito quebraria o gate seguinte. Quem corta esse caso e' o
    orquestrador, antes de chegar aqui.
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
        return pm.prob_over(faltam, lam)
    if faltam < 0:
        return 0.0001
    return pm.prob_under(faltam, lam)


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
