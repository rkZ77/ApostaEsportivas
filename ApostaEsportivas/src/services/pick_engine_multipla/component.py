"""A PERNA: calibracao, risco, qualidade de amostra e score individual.

O DEFEITO QUE ISTO FECHA
------------------------
A V1 escolhia a combinacao por `prob_combinada` (produto das `taxa_real`) com
desempate pela media dos `final_score`. Nenhum dos dois responde a pergunta que
um bilhete faz. `final_score` e' um score de RANQUEAMENTO DE MERCADO: ele existe
pra decidir se o jogo entrega gols ou escanteios, e por construcao ignora odd e
EV (ver ranking.final_score). Usar a media dele como qualidade do bilhete e'
usar um numero que nunca olhou pro preco pra julgar uma aposta. E `taxa_real`,
que e' probabilidade de verdade, entrava CRUA: uma perna com 4 jogos de amostra
afirmava o mesmo que uma com 40.

O QUE MUDA
----------
Cada perna passa a carregar, alem do que o motor ja' deu:

    probabilidade_calibrada   taxa_real encolhida pelo que a amostra sustenta
    sample_quality            0-1, da classe de amostra
    risk_score                0-1, do risco ja' classificado pelo motor
    projection_margin         a folga da projecao contra a linha, em sigmas
    component_score           o score composto que a multipla usa pra escolher

NADA DISSO RECALCULA O MOTOR. Probabilidade, EV, edge, confidence, risco e
projecao nascem no pre-jogo e chegam prontos; esta camada so' os LE e os
combina com pesos declarados. Recalcular aqui seria manter duas verdades sobre
o mesmo pick, e elas divergiriam na primeira mudanca de um lado so'.

POR QUE O ENCOLHIMENTO VAI PRO LIMITE INFERIOR DE WILSON
--------------------------------------------------------
A tentacao obvia seria encolher em direcao a probabilidade implicita do
mercado. Isso e' `market_anchor`, que existe no repo e esta' DESLIGADO
esperando CLV limpo -- ligar por tabela aqui seria ligar uma camada reprovada
por um caminho lateral. Wilson nao tem esse problema: ele nao traz informacao
de fora, so' cobra da propria amostra o que ela pode afirmar. Amostra grande
quase nao mexe; amostra de 5 jogos desce bastante, que e' exatamente a
correcao pedida ("5/5 nao vira 100%").
"""
from __future__ import annotations

from services.pick_engine import ranking
from services.pick_engine_multipla import config as cfg
from services.pick_engine_multipla import reasons


# ------------------------------------------------------------------- AMOSTRA
def classe_de_amostra(n) -> tuple[str, float]:
    """(rotulo, fator 0-1) da amostra desta perna."""
    total = int(n or 0)
    for piso, rotulo, fator in cfg.CLASSES_DE_AMOSTRA:
        if total >= piso:
            return rotulo, fator
    return "INSUFICIENTE", 0.15


# ------------------------------------------------------------------ CALIBRACAO
def probabilidade_calibrada(perna: dict) -> float:
    """taxa_real encolhida pelo que a amostra realmente sustenta.

    So' desce, nunca sobe: o limite inferior de Wilson e' por definicao <=
    a frequencia observada, e sem Wilson o ajuste e' um desconto. Uma camada
    que pudesse SUBIR probabilidade estaria criando elegibilidade a partir de
    incerteza, que e' o oposto do que ela existe pra fazer.
    """
    taxa = float(perna.get("taxa_real") or 0.0)
    rotulo, _fator = classe_de_amostra(perna.get("amostra"))

    wilson = perna.get("wilson") or {}
    inferior = wilson.get("lower")
    if inferior is None:
        desconto = cfg.DESCONTO_SEM_WILSON.get(rotulo, 0.06)
        return round(max(0.0, taxa - desconto), 4)

    peso = cfg.ENCOLHIMENTO_POR_CLASSE.get(rotulo, 0.70)
    calibrada = (1.0 - peso) * taxa + peso * float(inferior)
    # Wilson pode ficar ACIMA da taxa ponderada (a taxa ja' carrega peso de
    # adversario e recencia, o intervalo nao). Nesse caso nao ha' o que
    # encolher -- e subir seria inventar probabilidade.
    return round(min(taxa, calibrada), 4)


# ---------------------------------------------------------------------- RISCO
def nota_de_risco(perna: dict) -> float:
    """0-1, onde 1 e' risco BAIXO. Le a classificacao que o motor ja' fez --
    ela ja' cobra dispersao, amostra, data quality e projecao (ver
    confidence.classify_risk)."""
    return cfg.RISCO_PARA_NOTA.get((perna.get("risco") or "").upper(), 0.0)


def margem_de_projecao(perna: dict):
    """Folga da projecao contra a linha, em SIGMAS. None nas familias sem
    projecao (btts, resultado, handicap) -- ausencia e' neutra, nao favoravel."""
    projecao = perna.get("projecao") or {}
    return projecao.get("margem_em_sigmas")


def classe_de_projecao(perna: dict):
    return (perna.get("projecao") or {}).get("classe")


# --------------------------------------------------------------------- SCORE
def _normalizar(valor, piso, teto) -> float:
    if valor is None:
        return 0.5
    if teto <= piso:
        return 0.0
    return round(min(1.0, max(0.0, (float(valor) - piso) / (teto - piso))), 4)


def _nota_de_convergencia(perna: dict) -> float:
    """Duas estimativas independentes do valor esperado concordando e' o sinal
    mais barato de que a projecao nao depende de um jogo extremo. Ausente =
    0.5 (neutro), nunca 1.0."""
    conv = perna.get("convergence")
    if not conv:
        return 0.5
    diff = conv.get("diff_pct")
    if diff is None:
        return 1.0 if conv.get("converged") else 0.5
    # 0% de diferenca = 1.0; 30% ou mais = 0.0.
    return round(max(0.0, min(1.0, 1.0 - float(diff) / 0.30)), 4)


def component_score(perna: dict, config: cfg.MultiplaConfig | None = None) -> dict:
    """MULTIPLA_COMPONENT_SCORE, com as parcelas abertas.

    Devolve dict e nao float de proposito: a nota sozinha nao responde "por
    que esta perna perdeu pra aquela", e essa e' a pergunta que a auditoria
    faz. As parcelas vao inteiras pro log.
    """
    config = config or cfg.padrao()
    pesos = config.pesos_componente

    p_cal = probabilidade_calibrada(perna)
    _rotulo, fator_amostra = classe_de_amostra(perna.get("amostra"))

    parcelas = {
        "prob_calibrada": _normalizar(p_cal, cfg.PROB_PISO_ESCALA, cfg.PROB_TETO_ESCALA),
        "ev":             _normalizar(perna.get("ev"), 0.0, cfg.EV_SATURA_EM),
        "edge":           _normalizar(perna.get("edge"), 0.0, cfg.EDGE_SATURA_EM),
        "data_quality":   float(perna.get("data_quality_score") or 0.0),
        "sample_quality": fator_amostra,
        "convergence":    _nota_de_convergencia(perna),
        "risco":          nota_de_risco(perna),
    }

    score = sum(parcelas[k] * pesos.get(k, 0.0) for k in parcelas)

    # Projecao apertada custa pontos, nao elegibilidade: a reprovacao das
    # classes "em cima da linha"/"contra a linha" e' do gate, nao do score.
    if classe_de_projecao(perna) == cfg.CLASSE_DE_PROJECAO_PENALIZADA:
        score *= 0.95

    return {
        "score": round(min(1.0, max(0.0, score)), 4),
        "parcelas": {k: round(v, 4) for k, v in parcelas.items()},
        "probabilidade_calibrada": p_cal,
        "sample_quality": fator_amostra,
        "risk_score": round(1.0 - parcelas["risco"], 4),
        "projection_margin": margem_de_projecao(perna),
    }


# ---------------------------------------------------------------------- GATE
def _risco_reprovado(risco: str, maximo: str) -> bool:
    ordem = ("BAIXO", "MEDIO", "ALTO")
    try:
        return ordem.index((risco or "ALTO").upper()) > ordem.index(maximo.upper())
    except ValueError:
        return True


def avaliar(perna: dict, config: cfg.MultiplaConfig | None = None) -> dict:
    """Enriquece a perna e diz se ela entra no pool de combinacoes.

    Devolve um dict NOVO (nunca muta o candidato do motor) com as chaves da
    V2 somadas as do candidato original, mais `aprovada` e `motivos`.

    NAO ha' short-circuit: uma perna reprovada carrega TODOS os motivos. E'
    o mesmo desenho de rank_all_candidates_debug, e existe pela mesma razao --
    "reprovou por amostra" esconde que ela tambem reprovaria por risco, e
    quem for calibrar o limiar de amostra descobriria isso tarde demais.
    """
    config = config or cfg.padrao()
    detalhe = component_score(perna, config)
    motivos = []

    ev = perna.get("ev")
    if ev is None or float(ev) <= config.min_ev_perna:
        motivos.append(reasons.PERNA_EV)

    edge = perna.get("edge")
    if edge is None or float(edge) < config.min_edge_perna:
        motivos.append(reasons.PERNA_EDGE)

    if float(perna.get("data_quality_score") or 0.0) < config.min_data_quality:
        motivos.append(reasons.PERNA_DATA_QUALITY)

    if detalhe["sample_quality"] < config.min_sample_quality:
        motivos.append(reasons.PERNA_SAMPLE)

    if _risco_reprovado(perna.get("risco"), config.risco_maximo):
        motivos.append(reasons.PERNA_RISCO)

    if detalhe["probabilidade_calibrada"] < config.min_prob_calibrada:
        motivos.append(reasons.PERNA_PROB_CALIBRADA)

    if classe_de_projecao(perna) in cfg.CLASSES_DE_PROJECAO_REPROVADAS:
        motivos.append(reasons.PERNA_PROJECAO)

    if detalhe["score"] < config.min_leg_score:
        motivos.append(reasons.PERNA_SCORE)

    return {
        **perna,
        "probabilidade_calibrada": detalhe["probabilidade_calibrada"],
        "sample_quality": detalhe["sample_quality"],
        "risk_score": detalhe["risk_score"],
        "projection_margin": detalhe["projection_margin"],
        "component_score": detalhe["score"],
        "component_parcelas": detalhe["parcelas"],
        "aprovada": not motivos,
        "motivos": motivos,
    }


def avaliar_pool(pernas: list, config: cfg.MultiplaConfig | None = None) -> tuple[list, list]:
    """(aprovadas, reprovadas), aprovadas ordenadas por component_score."""
    config = config or cfg.padrao()
    aprovadas, reprovadas = [], []
    for perna in pernas:
        avaliada = avaliar(perna, config)
        (aprovadas if avaliada["aprovada"] else reprovadas).append(avaliada)
    aprovadas.sort(key=lambda p: p["component_score"], reverse=True)
    return aprovadas, reprovadas


def familia(perna: dict) -> str:
    """Familia de correlacao do mercado da perna -- a mesma chave que o motor
    ja' usa pra decidir que duas linhas falam da mesma coisa."""
    return ranking.correlation_group(perna.get("market_type") or "")


def jogo(perna: dict):
    return (perna.get("_fixture") or {}).get("fixture_id")


def times(perna: dict) -> set:
    fx = perna.get("_fixture") or {}
    return {t for t in (fx.get("home_team_id"), fx.get("away_team_id")) if t}


def liga(perna: dict):
    return (perna.get("_fixture") or {}).get("league_id")
