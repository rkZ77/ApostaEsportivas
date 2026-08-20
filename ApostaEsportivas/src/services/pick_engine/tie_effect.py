"""Efeito MEDIDO do contexto de confronto sobre cada mercado, por lado.

O QUE ESTE MODULO EXISTE PRA IMPEDIR
------------------------------------
Duas coisas, e as duas sao formas de narrativa:

  1. "Time precisa atacar -> aumenta Over" aplicado a qualquer mercado, em
     qualquer escopo, com um numero escolhido a dedo.
  2. O contrario disso, que era o estado ate 2026-08-19: o motor tinha o
     agregado na mao (match_context_model), sabia quem precisava reverter, e
     usava esse conhecimento SO' pra penalizar Under. Um "Escanteios Casa
     Over 4.5" num jogo em que o mandante precisa reverter um 0x1 recebia
     ajuste contextual de exatamente 0.0.

A MEDICAO QUE DEFINE AS CONSTANTES DAQUI
----------------------------------------
2026-08-19, sobre os jogos de VOLTA reais da base de producao (11 confrontos
com estatistica completa e perna comprovada pela inversao de mando), cada lado
comparado contra a PROPRIA media no MESMO mando -- sem esse casamento, "esta
atras" se confunde com "esta jogando em casa":

    familia      lado atras          lado na frente     agregado empatado
    corners      +1.98 (ep 1.18)     -1.66 (ep 1.52)    -0.64 (ep 0.99)
    shots        +2.95 (ep 1.61)     -0.30 (ep 2.61)    +0.49 (ep 1.66)
    goals        +1.16 (ep 0.47)     +0.11 (ep 0.48)    -0.18 (ep 0.37)
    fouls        -2.48 (ep 0.64)     -1.14 (ep 2.32)    +0.42 (ep 1.45)
    cards        -0.35 (ep 0.76)     -0.16 (ep 0.86)    +0.70 (ep 0.41)
    saves        -0.14 (ep 0.99)     -0.45 (ep 0.98)    -0.02 (ep 0.54)

TRES RESULTADOS CONTRARIAM O QUE A NARRATIVA DIRIA, E SAO O MOTIVO DE MEDIR:

  FALTAS CAEM pra quem precisa reverter (-2.48, o sinal mais forte da tabela,
  3.9 erros-padrao). Faz sentido depois de visto: quem persegue o resultado
  tem a bola, e quem tem a bola nao comete falta. O gate antigo tratava
  `fouls` como familia que SOBE quando o jogo abre.

  AGREGADO EMPATADO NAO DESLOCA VOLUME. E' o cenario de maior tensao, e
  stakes_score continua dizendo isso -- mas importancia da partida e volume de
  escanteio sao coisas diferentes. Os dois times se anulam e a partida sai
  parecida com uma partida comum. A unica excecao medida sao os CARTOES
  (+0.70 por lado, 1.7 ep), que e' exatamente o caso Fluminense x Vasco que
  originou o gate de contexto -- ele continua valendo, agora com numero.

  O EFEITO E' REDISTRIBUICAO, NAO CRIACAO. O total de escanteios da partida
  quase nao se move (+0.95, ep 1.04 -- indistinguivel de zero), enquanto os
  lados se movem +1.98 e -1.66. Por isso este modulo age em mercado DE TIME
  (Escanteios Casa/Visitante) e quase nao age em mercado de jogo inteiro: no
  total, os dois efeitos se cancelam, e aplicar o ajuste ali seria inventar
  volume que a medicao diz que nao existe.

COMO O AJUSTE VIRA PROBABILIDADE
--------------------------------
O efeito medido esta em CONTAGEM (escanteios, chutes), nao em probabilidade.
Converter um pelo outro na mao seria escolher um numero; aqui a conversao
passa pelo Poisson que o motor ja' usa: desloca-se o lambda da familia e
pergunta-se a diferenca de P(linha) entre o lambda deslocado e o original.

Isso torna o ajuste AUTO-LIMITADO, que e' a propriedade que o pedido exige:
uma linha longe do lambda quase nao se move por mais que o contexto empurre, e
uma linha no meio da distribuicao se move mais. O contexto nunca transforma
uma linha ruim numa boa -- ele so' corrige o quanto a linha ja' era plausivel.

Por cima disso ainda vem duas travas:
  - o encolhimento de amostra pequena (n=4 por celula assimetrica);
  - um teto duro por familia (TETO_DE_DELTA), com gols no teto mais apertado
    de todos, porque e' o mercado mais liquido e o de menor amostra propria.

O QUE ELE NAO FAZ
-----------------
Nao aprova nem reprova pick -- devolve um delta e o rastro. Nao age em familia
cujo efeito nao foi medido (saves entrou na medicao e ficou de fora por ela:
-0.14 com ep 0.99 e' zero). Nao age sem lambda: familia sem
expected_value_convergence nao tem por onde converter contagem em
probabilidade, e chutar essa conversao seria voltar a escolher numero.
"""
from __future__ import annotations

from services.pick_engine import probability_model

#: (media, erro_padrao) do deslocamento de contagem por lado, por papel no
#: agregado. Numeros CRUS da medicao -- o encolhimento acontece em
#: `_delta_de_contagem`, pra a tabela continuar auditavel contra a medicao
#: original quando ela for refeita com mais amostra.
_MEDIDO: dict[str, dict[str, tuple]] = {
    "corners": {"atras": (1.98, 1.18), "na_frente": (-1.66, 1.52)},
    "shots":   {"atras": (2.95, 1.61), "na_frente": (-0.30, 2.61)},
    "goals":   {"atras": (1.16, 0.47), "na_frente": (0.11, 0.48)},
    "fouls":   {"atras": (-2.48, 0.64), "na_frente": (-1.14, 2.32)},
    # cards e saves NAO tem entrada de papel de proposito: a medicao devolveu
    # zero pros dois nos lados assimetricos. Cartao aparece so' no bloco de
    # agregado empatado, abaixo.
}

#: Efeito medido POR LADO no cenario de agregado empatado. Unica familia em
#: que ele existe -- ver a docstring do modulo.
_MEDIDO_EMPATADO: dict[str, tuple] = {
    "cards": (0.70, 0.41),
}

#: Amostra que sustenta cada celula assimetrica. Guardado pra o rastro poder
#: dizer em cima de quanta evidencia o ajuste foi feito -- quem le a
#: explicacao precisa saber que sao 4 jogos, nao 400.
AMOSTRA_ASSIMETRICA = 4
AMOSTRA_EMPATADO = 11

#: Desconto global aplicado DEPOIS do encolhimento estatistico. O encolhimento
#: por erro-padrao ja' pune a imprecisao da medicao; este fator pune outra
#: coisa, que nenhum erro-padrao captura: a medicao saiu de 11 confrontos de
#: Copa do Brasil, Sul-Americana e um estadual argentino, e esta sendo
#: extrapolada pra toda copa que o motor avaliar. Meio efeito e' o preco de
#: aplicar fora do universo medido.
FATOR_DE_EXTRAPOLACAO = 0.50

#: Teto duro do deslocamento de probabilidade, por familia. E' a ultima trava
#: e a que garante a regra do pedido -- "o contexto sozinho nao transforma uma
#: aposta ruim em boa". Gols tem o teto mais baixo: e' o mercado mais liquido
#: (a casa erra menos), o de maior alavancagem no EV e o de menor amostra
#: propria aqui.
TETO_DE_DELTA = {
    "goals": 0.02,
    "corners": 0.04,
    "shots": 0.04,
    "fouls": 0.04,
    "cards": 0.03,
}
TETO_PADRAO = 0.03

#: Escopo de jogo inteiro recebe uma FRACAO do efeito de lado, nao o efeito
#: inteiro: no total os dois lados se cancelam (medido: +0.95 com ep 1.04).
#: Nao e' zero cravado porque o cancelamento e' imperfeito -- quem ataca
#: produz mais do que quem recua deixa de produzir -- mas e' pequeno o
#: bastante pra nunca ser o fator que decide um pick de total.
FRACAO_DO_ESCOPO_TOTAL = 0.25

#: Penalidade de confidence quando a partida pertence a um regime que a
#: amostra historica nao descreve (volta de mata-mata com agregado aberto,
#: estimada com jogos de pontos corridos). Nao e' erro de precisao, e' erro de
#: universo -- a mesma razao do gate de contexto, na moeda certa: o gate mexe
#: na probabilidade, isto mexe em quanto se confia nela.
PENALIDADE_DE_REGIME_MAX = 0.05


def _encolher(media: float, erro_padrao: float) -> float:
    """Media encolhida em direcao a zero conforme a propria imprecisao.

    E' a media posterior sob um prior normal centrado em zero com variancia
    igual ao quadrado da media observada: media * m^2/(m^2 + ep^2). Efeito
    grande e preciso quase nao encolhe (faltas: 0.94 do valor); efeito do
    tamanho do proprio ruido encolhe pela metade ou mais. Sem isso, a celula
    de 4 jogos entraria com o mesmo peso da de 11.
    """
    if not erro_padrao:
        return media
    peso = (media ** 2) / ((media ** 2) + (erro_padrao ** 2))
    return media * peso * FATOR_DE_EXTRAPOLACAO


def _delta_de_contagem(familia: str, papel: str | None, magnitude: float) -> float:
    """Deslocamento esperado da contagem daquele lado, ja' encolhido e ja'
    escalado pelo tamanho da vantagem no agregado."""
    if papel == "empatado":
        medido = _MEDIDO_EMPATADO.get(familia)
    else:
        medido = (_MEDIDO.get(familia) or {}).get(papel or "")
    if not medido:
        return 0.0
    media, ep = medido
    return _encolher(media, ep) * max(0.0, min(magnitude, 1.0))


def _lado_do_escopo(familia: str, escopo: str | None) -> str | None:
    """Qual lado do confronto o mercado esta comprando.

    Direto pra quase tudo: "Escanteios Casa" compra o volume do mandante. A
    excecao e' `saves`, que compra o volume do ADVERSARIO -- defesa de goleiro
    e' consequencia do ataque do outro. Hoje isso nao muda nada na pratica
    (saves ficou fora da tabela por medicao), mas a inversao fica escrita: no
    dia em que houver amostra de defesa, o mapeamento nao pode nascer errado.
    """
    if escopo not in ("home", "away"):
        return None
    if familia == "saves":
        return "away" if escopo == "home" else "home"
    return escopo


def efeito(candidate: dict, contexto: dict | None) -> dict:
    """Deslocamento contextual deste candidato: probabilidade e confidence.

    Devolve sempre a mesma forma, com `aplicavel` dizendo se agiu e `motivo`
    dizendo por que nao -- "nao agiu" tem que ser tao legivel quanto "agiu",
    senao a camada vira caixa preta no dia em que alguem perguntar por que um
    pick de copa saiu igual a um de campeonato.
    """
    vazio = {
        "aplicavel": False, "delta_prob": 0.0, "delta_confianca": 0.0,
        "delta_lambda": 0.0, "papel": None, "escopo": None, "parcelas": [],
        "motivo": None,
    }
    if not contexto:
        return {**vazio, "motivo": "sem contexto de partida carregado"}

    tie = contexto.get("tie") or {}
    pressao = tie.get("pressao_por_lado") or {}
    if not pressao.get("aplicavel"):
        return {**vazio, "motivo": "confronto sem agregado conhecido"}

    familia = candidate.get("market_type")
    escopo = candidate.get("scope")
    direcao = (candidate.get("_direction") or "").strip().lower()
    if direcao not in ("over", "under"):
        return {**vazio, "motivo": "mercado sem direcao over/under"}

    lado = _lado_do_escopo(familia, escopo)
    papel = pressao.get(f"papel_{lado}") if lado else (
        pressao.get("papel_home") or pressao.get("papel_away"))
    delta_conta = _delta_de_contagem(familia, papel, pressao.get("magnitude", 0.0))

    if lado is None:
        # Mercado de jogo inteiro: os dois lados entram, e e' justamente por
        # isso que sobra pouco. Soma o deslocamento dos dois papeis em vez de
        # usar um so' -- e' o cancelamento medido, calculado em vez de suposto.
        d_home = _delta_de_contagem(familia, pressao.get("papel_home"),
                                    pressao.get("magnitude", 0.0))
        d_away = _delta_de_contagem(familia, pressao.get("papel_away"),
                                    pressao.get("magnitude", 0.0))
        delta_conta = (d_home + d_away) * FRACAO_DO_ESCOPO_TOTAL
        papel = "total"

    lam = ((candidate.get("convergence") or {}).get("expected_value")
           if candidate.get("convergence") else None)
    linha = candidate.get("_line_val")
    if lam is None or linha is None:
        return {**vazio, "papel": papel, "escopo": escopo,
                "motivo": "familia sem lambda proprio: nao ha como converter "
                          "deslocamento de contagem em probabilidade"}
    if not delta_conta:
        return {**vazio, "aplicavel": True, "papel": papel, "escopo": escopo,
                "motivo": "efeito medido nulo para esta familia neste papel"}

    p_base = probability_model.poisson_prob_for_line(lam, linha, direcao)
    p_novo = probability_model.poisson_prob_for_line(
        max(0.01, lam + delta_conta), linha, direcao)
    if p_base is None or p_novo is None:
        return {**vazio, "papel": papel, "escopo": escopo,
                "motivo": "linha fora do que o modelo Poisson responde"}

    teto = TETO_DE_DELTA.get(familia, TETO_PADRAO)
    delta_prob = max(-teto, min(p_novo - p_base, teto))

    parcelas = [{
        "sinal": "agregado_do_confronto",
        "papel": papel,
        "escopo": escopo or "total",
        "delta_lambda": round(delta_conta, 4),
        "delta_prob": round(delta_prob, 4),
        "no_teto": abs(p_novo - p_base) > teto,
        "amostra": AMOSTRA_EMPATADO if papel == "empatado" else AMOSTRA_ASSIMETRICA,
        "detalhe": _detalhe(tie, papel, escopo, familia, delta_conta),
    }]

    return {
        "aplicavel": True,
        "delta_prob": round(delta_prob, 4),
        "delta_confianca": -round(_penalidade_de_regime(tie, contexto), 4),
        "delta_lambda": round(delta_conta, 4),
        "papel": papel,
        "escopo": escopo,
        "parcelas": parcelas,
        "motivo": None,
    }


def _penalidade_de_regime(tie: dict, contexto: dict) -> float:
    """Quanto a partida foge do universo que gerou a amostra historica.

    Uma volta de mata-mata com agregado aberto nao e' uma partida da mesma
    populacao que os 15 jogos de campeonato que produziram a taxa. Isso e'
    incerteza, nao vies de direcao -- entao cobra CONFIDENCE, nao
    probabilidade. Cobrar dos dois lados seria contar o mesmo fato duas vezes:
    o deslocamento de direcao ja' saiu no delta_prob acima.
    """
    if not tie.get("is_jogo_de_volta"):
        return 0.0
    magnitude = (tie.get("pressao_por_lado") or {}).get("magnitude", 0.0)
    stakes = contexto.get("stakes", 0.5)
    # Escala nos dois eixos: quanto o confronto esta aberto e quanto ele vale.
    peso = min(1.0, magnitude) * min(1.0, max(0.0, (stakes - 0.5) / 0.5))
    return round(PENALIDADE_DE_REGIME_MAX * peso, 4)


def _detalhe(tie: dict, papel: str | None, escopo: str | None,
             familia: str, delta_conta: float) -> str:
    """Frase pronta pro rastro e pra explicacao do pick. Sempre com o numero
    junto -- afirmacao de contexto sem o deslocamento que ela produziu e'
    exatamente a narrativa que esta camada existe pra nao criar."""
    nomes_familia = {
        "corners": "escanteios", "shots": "finalizacoes", "goals": "gols",
        "fouls": "faltas", "cards": "cartoes", "saves": "defesas",
    }
    fam_txt = nomes_familia.get(familia, familia)
    faltam = tie.get("gols_para_reverter")
    if papel == "atras":
        situacao = f"lado que precisa de {faltam} gol(s) no agregado"
    elif papel == "na_frente":
        situacao = "lado que joga com a vantagem do agregado"
    elif papel == "empatado":
        situacao = "agregado empatado"
    else:
        situacao = "jogo inteiro, com os dois efeitos se cancelando"
    return (f"{situacao}: {fam_txt} deslocados em {delta_conta:+.2f} "
            f"por jogo pelo historico de jogos de volta")


def descrever(ef: dict | None) -> list:
    """Frases prontas pra 'Entenda esta analise'. Vazio quando o efeito nao
    agiu -- nao ha nada a contar."""
    if not ef or not ef.get("aplicavel") or not ef.get("delta_prob"):
        return []
    linhas = []
    for p in ef["parcelas"]:
        teto = " (no teto do ajuste contextual)" if p.get("no_teto") else ""
        linhas.append(
            f"{p['detalhe']} · ajuste de {p['delta_prob']*100:+.1f} ponto(s) "
            f"percentual(is) na probabilidade{teto}, medido em {p['amostra']} jogos"
        )
    if ef.get("delta_confianca"):
        linhas.append(
            f"confianca reduzida em {abs(ef['delta_confianca'])*100:.0f} ponto(s) "
            f"porque o historico vem de partidas sem agregado em jogo"
        )
    return linhas
