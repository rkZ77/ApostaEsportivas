"""A COMBINACAO: montar, precificar e pontuar um bilhete candidato.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao escolhe quais bilhetes o dia publica -- isso e' portfolio.py. Aqui cada
combinacao e' avaliada SOZINHA, como se fosse a unica do dia. A separacao
existe porque as duas perguntas sao diferentes e se confundiam na V1: "este
bilhete e' bom?" e "este bilhete e' bom DEPOIS daquele outro que ja' saiu?".

A ORDEM NAO E' POR EV, E ISSO E' REGRA
--------------------------------------
Dentro de uma faixa de odd fixa, maximizar EV e' maximizar odd -- e odd alta
e' alerta, nao qualidade. O preco ELIMINA (faixa de odd total, faixa por perna,
casa unica) e nunca ORDENA. Quem ordena e' `combination_score`, cujo maior
peso e' o ELO MAIS FRACO: o bilhete so' paga se todas as pernas baterem, entao
a perna pior e' que descreve o bilhete, nao a media.

Uma odd de 2.95 com score 0.55 e' REJEITADA; uma de 2.02 com score 0.82 e'
excelente. A proximidade do teto nunca compra qualidade.
"""
from __future__ import annotations

from itertools import combinations as _combinacoes

from services.pick_engine import bet_house
from services.pick_engine.config import DEFAULT_CONFIG
from services.pick_engine_multipla import component, correlation
from services.pick_engine_multipla import config as cfg
from services.pick_engine_multipla import reasons


# ------------------------------------------------------------ DIVERSIFICACAO
def diversificacao(pernas) -> dict:
    """DIVERSIFICATION_SCORE: quantas apostas DIFERENTES o bilhete realmente
    tem. Quatro eixos, peso igual -- jogo, equipe, familia de mercado e liga.

    Peso igual e nao calibrado: nao ha' medicao propria dizendo qual eixo
    protege mais. Chutar pesos diferentes aqui seria fingir que ha'.
    """
    n = len(pernas)
    if n < 2:
        return {"score": 0.0, "jogos": n, "familias": n, "ligas": n, "times": n}

    jogos = {component.jogo(p) for p in pernas}
    familias = {component.familia(p) for p in pernas}
    ligas = {component.liga(p) for p in pernas}
    times = set()
    for p in pernas:
        times |= component.times(p)

    eixos = (
        len(jogos) / n,
        len(familias) / n,
        len(ligas) / n,
        len(times) / (2 * n),
    )
    return {
        "score": round(sum(eixos) / len(eixos), 4),
        "jogos": len(jogos),
        "familias": len(familias),
        "ligas": len(ligas),
        "times": len(times),
    }


# ----------------------------------------------------------------- MONTAGEM
def _excludente(pernas, config: cfg.MultiplaConfig) -> bool:
    """Pares que nem chegam a ser pontuados, pelos tetos de composicao."""
    jogos, times_vistos, familias_por_jogo = {}, {}, {}
    for p in pernas:
        j = component.jogo(p)
        jogos[j] = jogos.get(j, 0) + 1
        if jogos[j] > config.max_pernas_mesmo_jogo:
            return True
        chave = (j, component.familia(p))
        familias_por_jogo[chave] = familias_por_jogo.get(chave, 0) + 1
        if familias_por_jogo[chave] > 1:
            return True
        for t in component.times(p):
            times_vistos[t] = times_vistos.get(t, 0) + 1
            if times_vistos[t] > config.max_pernas_mesmo_time:
                return True
    return False


def avaliar(pernas, config: cfg.MultiplaConfig | None = None) -> dict:
    """Precifica e pontua UMA combinacao. Sempre devolve dict -- reprovada
    tambem, com `motivos` preenchido, porque o dia sem bilhete precisa saber
    dizer por que.
    """
    config = config or cfg.padrao()
    # Perna que nao passou por component.avaliar entra enriquecida aqui. Nao
    # e' conveniencia: e' o que impede este modulo de ter DUAS entradas com
    # contratos diferentes -- uma que exige `component_score` e outra que
    # estoura com KeyError num campo que o chamador nao tinha como saber que
    # precisava existir.
    pernas = [p if "component_score" in p else component.avaliar(p, config)
              for p in pernas]
    motivos = []

    if _excludente(pernas, config):
        return {"aprovada": False, "motivos": [reasons.NO_MULTIPLA_HIGH_CORRELATION],
                "pernas": pernas}

    corr = correlation.do_combo(pernas)
    if corr["nivel"] == correlation.HIGH:
        return {"aprovada": False, "motivos": [reasons.NO_MULTIPLA_HIGH_CORRELATION],
                "pernas": pernas, "correlacao": corr}

    # CASA UNICA: o bilhete inteiro sai de uma casa so'. A casa e' escolhida
    # DEPOIS das pernas -- ela decide onde apostar, nunca o que entra. Quando
    # nenhuma casa cobre o bilhete, ele nao existe: preferimos o dia sem
    # bilhete a um bilhete que nao da' pra apostar.
    aplicado = bet_house.aplicar_casa(pernas, DEFAULT_CONFIG.min_odd, DEFAULT_CONFIG.max_odd)
    if aplicado is None:
        return {"aprovada": False, "motivos": [reasons.NO_MULTIPLA_NO_SINGLE_BOOKMAKER],
                "pernas": pernas, "correlacao": corr}
    pernas, casa, odd_total = aplicado
    pernas = list(pernas)

    if odd_total < config.odd_total_min:
        motivos.append(reasons.NO_MULTIPLA_ODD_BELOW_RANGE)
    if odd_total > config.teto_de_odd:
        motivos.append(reasons.NO_MULTIPLA_ODD_ABOVE_RANGE)

    prob_produto = 1.0
    prob_calibrada = 1.0
    for p in pernas:
        prob_produto *= float(p.get("taxa_real") or 0.0)
        prob_calibrada *= float(p.get("probabilidade_calibrada") or p.get("taxa_real") or 0.0)
    prob_final = correlation.prob_ajustada(prob_calibrada, corr)

    ev = round(prob_final * odd_total - 1.0, 4)
    fair_odd = round(1.0 / prob_final, 4) if prob_final > 0 else None
    edge = round(prob_final - (1.0 / odd_total), 4)

    scores = [p["component_score"] for p in pernas]
    elo = min(scores)
    div = diversificacao(pernas)

    pesos = config.pesos_combinacao
    parcelas = {
        "elo_mais_fraco":   elo,
        "media_das_pernas": sum(scores) / len(scores),
        "prob_combinada":   _normalizar(prob_final, cfg.PROB_COMBINADA_PISO_ESCALA,
                                        cfg.PROB_COMBINADA_TETO_ESCALA),
        "diversificacao":   div["score"],
        "correlacao":       corr["nota"],
    }
    score = round(min(1.0, max(0.0, sum(parcelas[k] * pesos.get(k, 0.0) for k in parcelas))), 4)

    if elo < config.min_leg_score:
        motivos.append(reasons.NO_MULTIPLA_WEAK_LEG)
    # Tripla exige TODAS as pernas fortes: duas boas e uma mediana e' o
    # desenho classico de bilhete que perde.
    if len(pernas) >= 3 and elo < cfg.MIN_LEG_SCORE_PARA_TRIPLA:
        motivos.append(reasons.NO_MULTIPLA_WEAK_LEG)
    if ev <= 0:
        motivos.append(reasons.NO_MULTIPLA_NEGATIVE_EV)
    if edge <= 0:
        motivos.append(reasons.NO_MULTIPLA_NEGATIVE_EDGE)
    if score < config.min_combination_score:
        motivos.append(reasons.NO_MULTIPLA_LOW_SCORE)
    if corr["nivel"] == correlation.UNKNOWN and score < config.min_combination_score + 0.05:
        # Correlacao desconhecida ja' pagou penalidade na probabilidade. Aqui
        # ela cobra o resto: sem folga de qualidade, desconhecido nao entra.
        motivos.append(reasons.NO_MULTIPLA_UNKNOWN_CORRELATION)

    return {
        "aprovada": not motivos,
        "motivos": motivos,
        "pernas": pernas,
        "casa": casa,
        "odd_total": round(float(odd_total), 2),
        "prob_produto": round(prob_produto, 4),
        "prob_calibrada": round(prob_calibrada, 4),
        "probabilidade": prob_final,
        "fair_odd": fair_odd,
        "edge": edge,
        "ev": ev,
        "score": score,
        "score_parcelas": {k: round(v, 4) for k, v in parcelas.items()},
        "faixa": cfg.faixa_de_score(score),
        "elo_mais_fraco": round(elo, 4),
        "correlacao": corr,
        "diversificacao": div,
        # RISCO DO BILHETE E' O DA PIOR PERNA, nunca a media: o bilhete cai
        # inteiro pelo elo mais fraco, e uma media diria que uma perna de
        # risco ALTO ao lado de uma BAIXA da' um bilhete medio.
        "risco": round(max(p["risk_score"] for p in pernas), 4) if pernas else None,
    }


def _normalizar(valor, piso, teto) -> float:
    if valor is None or teto <= piso:
        return 0.0
    return round(min(1.0, max(0.0, (float(valor) - piso) / (teto - piso))), 4)


def gerar(pool: list, config: cfg.MultiplaConfig | None = None,
          teto_do_pool: int = 30) -> tuple[list, list]:
    """Todas as combinacoes viaveis do pool, avaliadas.

    Devolve (aprovadas ordenadas por score, motivos vistos nas reprovadas).

    `teto_do_pool` corta o espaco de busca pelas MELHORES pernas, nao pelas
    primeiras: combinations(30, 3) sao 4.060 bilhetes, custo irrelevante, e
    combinations(60, 3) ja' seriam 34.220. O corte e' por component_score,
    entao alargar o pool so' adiciona pernas piores que as que ja' estao la'.
    """
    config = config or cfg.padrao()
    ordenado = sorted(pool, key=lambda p: p["component_score"], reverse=True)[:teto_do_pool]

    aprovadas, motivos = [], []
    for tamanho in config.tamanhos_permitidos:
        if len(ordenado) < tamanho:
            continue
        for combo in _combinacoes(ordenado, tamanho):
            avaliada = avaliar(combo, config)
            if avaliada["aprovada"]:
                aprovadas.append(avaliada)
            else:
                motivos.extend(avaliada["motivos"])

    # Ordem: score, depois probabilidade, depois diversificacao. A odd nao
    # entra em nenhum criterio de desempate -- ela ja' eliminou o que tinha
    # que eliminar na faixa.
    aprovadas.sort(
        key=lambda c: (c["score"], c["probabilidade"], c["diversificacao"]["score"]),
        reverse=True,
    )
    return aprovadas, motivos
