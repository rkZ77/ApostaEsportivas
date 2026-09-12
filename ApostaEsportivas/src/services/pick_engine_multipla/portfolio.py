"""DAILY_MULTIPLE_PORTFOLIO: quantas multiplas de qualidade o dia tem.

A MUDANCA DE PERGUNTA
---------------------
A V1 perguntava "qual e' a melhor combinacao?" e repetia a pergunta na sobra
ate' o teto. Funciona, mas responde uma coisa de cada vez: nada no algoritmo
olhava pro CONJUNTO do dia. Dois bilhetes podiam sair concentrados na mesma
liga, na mesma familia de mercado ou girando em torno do mesmo jogo, e nenhum
passo do motor tinha como notar -- cada um deles, sozinho, era legitimo.

A V2 pergunta "quantas multiplas de qualidade existem hoje?", e a resposta
pode ser 0. Zero e' resposta valida e e' a resposta certa em dia ruim: nao
existe cota de publicacao a cumprir.

O ALGORITMO
-----------
    1. escolhe a melhor combinacao ainda viavel;
    2. remove as pernas dela do pool (exclusividade: dois bilhetes que
       dividem uma perna nao sao duas apostas, sao uma aposta com o dobro da
       exposicao -- o RED daquela perna derruba os dois juntos);
    3. penaliza o que ficou parecido com o que ja' saiu (mesmo jogo, mesma
       familia dominante) via OVERLAP_SCORE;
    4. repete ate' o teto do dia, que vem da OFERTA (config.teto_de_multiplas)
       e nao da vontade de publicar.

Isso e' o que faz o dia sair

    M1 = A+B    M2 = C+D    M3 = E+F

em vez de

    M1 = A+B    M2 = A+C    M3 = A+D

que e' tres vezes a mesma exposicao em A vendida como variedade.

REUSO E' EXCECAO E PAGA
-----------------------
Uma perna excepcional (score >= SCORE_PARA_REUSO_EXCEPCIONAL) pode aparecer
num segundo bilhete quando o pool nao oferece alternativa -- e o bilhete que
a reusa leva penalidade no score. Nunca uma terceira vez.
"""
from __future__ import annotations

from services.pick_engine_multipla import combination, component
from services.pick_engine_multipla import config as cfg
from services.pick_engine_multipla import reasons


def _familia_dominante(bilhete: dict) -> str:
    familias = [component.familia(p) for p in bilhete["pernas"]]
    return max(set(familias), key=familias.count) if familias else ""


def overlap(bilhete: dict, publicados: list) -> dict:
    """OVERLAP_SCORE: quanto este bilhete repete o que o dia ja' publicou.

    0.0 e' um bilhete que nao toca em nada do que ja' saiu. Tres eixos, e os
    tres somam: perna repetida (o pior), jogo repetido, familia dominante
    repetida.
    """
    if not publicados:
        return {"score": 0.0, "pernas_repetidas": 0, "jogos_repetidos": 0,
                "familia_repetida": 0}

    pernas_ja = set()
    jogos_ja = []
    familias_ja = []
    for b in publicados:
        for p in b["pernas"]:
            pernas_ja.add(_chave_da_perna(p))
            jogos_ja.append(component.jogo(p))
        familias_ja.append(_familia_dominante(b))

    repetidas = sum(1 for p in bilhete["pernas"] if _chave_da_perna(p) in pernas_ja)
    jogos_rep = sum(1 for p in bilhete["pernas"] if component.jogo(p) in jogos_ja)
    fam_rep = familias_ja.count(_familia_dominante(bilhete))

    n = len(bilhete["pernas"])
    score = min(1.0, repetidas / n + 0.5 * (jogos_rep / n) + 0.25 * min(1.0, fam_rep / 2))
    return {"score": round(score, 4), "pernas_repetidas": repetidas,
            "jogos_repetidos": jogos_rep, "familia_repetida": fam_rep}


def _chave_da_perna(perna: dict) -> tuple:
    return (component.jogo(perna), perna.get("market_type"), perna.get("value_label"))


def _viola_exposicao(bilhete: dict, publicados: list, config: cfg.MultiplaConfig) -> bool:
    """FIXTURE_EXPOSURE_LIMIT e a concentracao por familia de mercado."""
    contagem_jogo, contagem_familia = {}, {}
    for b in publicados:
        for j in {component.jogo(p) for p in b["pernas"]}:
            contagem_jogo[j] = contagem_jogo.get(j, 0) + 1
        fam = _familia_dominante(b)
        contagem_familia[fam] = contagem_familia.get(fam, 0) + 1

    for j in {component.jogo(p) for p in bilhete["pernas"]}:
        if contagem_jogo.get(j, 0) + 1 > config.limite_exposicao_por_jogo:
            return True
    fam = _familia_dominante(bilhete)
    if contagem_familia.get(fam, 0) + 1 > config.limite_exposicao_por_familia:
        return True
    return False


def exposicao_do_dia(publicados: list) -> dict:
    """DAILY_EXPOSURE_SCORE: quanto o dia depende de poucas coisas.

    1.0 seria o dia inteiro apostado no mesmo jogo. Vai pro log -- nao filtra
    nada sozinho, os filtros sao os limites por jogo e por familia.
    """
    if not publicados:
        return {"score": 0.0, "jogos": 0, "pernas": 0}
    pernas = [p for b in publicados for p in b["pernas"]]
    jogos = {component.jogo(p) for p in pernas}
    return {
        "score": round(1.0 - len(jogos) / len(pernas), 4) if pernas else 0.0,
        "jogos": len(jogos),
        "pernas": len(pernas),
    }


def montar(pool_aprovado: list, jogos_elegiveis: int,
           config: cfg.MultiplaConfig | None = None,
           vagas: int | None = None) -> dict:
    """O portfolio do dia.

    `pool_aprovado` sao as pernas que passaram no gate individual
    (component.avaliar_pool). `jogos_elegiveis` e' quantas PARTIDAS
    diferentes contribuiram com pelo menos uma dessas pernas -- e' ele que
    define o teto, e nao o numero de jogos do dia.

    `vagas` limita a mais (o dia ja' publicou alguns bilhetes numa execucao
    anterior): o teto conta o DIA, nunca a execucao.
    """
    config = config or cfg.padrao()
    teto = cfg.teto_de_multiplas(jogos_elegiveis, config)
    if vagas is not None:
        teto = min(teto, max(0, vagas))

    saida = {
        "games_available": jogos_elegiveis,
        "eligible_candidates": len(pool_aprovado),
        "max_multiples": teto,
        "multiples": [],
        "decision": "NO_MULTIPLA",
        "reason": reasons.NO_MULTIPLA_INSUFFICIENT_CANDIDATES,
    }

    if len(pool_aprovado) < 2 or teto <= 0:
        return saida

    restantes = list(pool_aprovado)
    reuso = {}
    publicados = []
    motivos_vistos = []

    while len(publicados) < teto and len(restantes) >= 2:
        candidatas, motivos = combination.gerar(restantes, config)
        motivos_vistos.extend(motivos)
        if not candidatas:
            break

        escolhida = None
        for bilhete in candidatas:
            ov = overlap(bilhete, publicados)
            if ov["pernas_repetidas"] and not _reuso_permitido(bilhete, reuso, config):
                motivos_vistos.append(reasons.NO_MULTIPLA_HIGH_OVERLAP)
                continue
            if _viola_exposicao(bilhete, publicados, config):
                motivos_vistos.append(reasons.NO_MULTIPLA_HIGH_OVERLAP)
                continue

            score_liquido = bilhete["score"] - ov["score"] * cfg.PENALIDADE_DE_REUSO
            if score_liquido < config.min_combination_score:
                # A penalidade de sobreposicao derrubou o bilhete abaixo do
                # piso: ele era bom sozinho e nao e' bom DEPOIS do que o dia
                # ja' publicou. E' exatamente a decisao que a V1 nao tomava.
                motivos_vistos.append(reasons.NO_MULTIPLA_LOW_SCORE)
                continue

            bilhete = {**bilhete, "overlap": ov, "score_liquido": round(score_liquido, 4)}
            escolhida = bilhete
            break

        if escolhida is None:
            break

        escolhida["id"] = f"MULTIPLA_{len(publicados) + 1}"
        escolhida["decision"] = "PICK"
        publicados.append(escolhida)

        usadas = {_chave_da_perna(p) for p in escolhida["pernas"]}
        for chave in usadas:
            reuso[chave] = reuso.get(chave, 0) + 1
        restantes = [p for p in restantes
                     if reuso.get(_chave_da_perna(p), 0) < config.max_reuso_da_perna]

    saida["multiples"] = publicados
    saida["exposure"] = exposicao_do_dia(publicados)
    if publicados:
        saida["decision"] = "PICK"
        saida.pop("reason", None)
    else:
        saida["reason"] = reasons.motivo_dominante(motivos_vistos)
    return saida


def resumo(portfolio: dict, data) -> dict:
    """O portfolio em forma serializavel -- o que vai pro log da execucao.

    Nao e' o que vai pro banco (isso e' `games` do pipeline, com a forma que o
    site ja' le). E' a foto da DECISAO: quantos jogos havia, quantos
    candidatos sobreviveram, qual era o teto e por que cada bilhete existe.
    Sem ela, "hoje nao saiu multipla" continua sendo uma frase sem resposta.
    """
    return {
        "date": str(data),
        "games_available": portfolio.get("games_available", 0),
        "eligible_candidates": portfolio.get("eligible_candidates", 0),
        "max_multiples": portfolio.get("max_multiples", 0),
        "decision": portfolio.get("decision", "NO_MULTIPLA"),
        **({"reason": portfolio["reason"]} if portfolio.get("reason") else {}),
        "exposure": portfolio.get("exposure", {}),
        "multiples": [
            {
                "id": b["id"],
                "legs": [
                    {
                        "fixture_id": component.jogo(p),
                        "market": p.get("market_name"),
                        "market_type": p.get("market_type"),
                        "line": p.get("value_label"),
                        "odd": p.get("odd"),
                        "probability": p.get("taxa_real"),
                        "probability_calibrated": p.get("probabilidade_calibrada"),
                        "component_score": p.get("component_score"),
                        "sample_quality": p.get("sample_quality"),
                        "risk": p.get("risco"),
                        "projection_margin": p.get("projection_margin"),
                    }
                    for p in b["pernas"]
                ],
                "odd_total": b["odd_total"],
                "probability": b["probabilidade"],
                "fair_odd": b["fair_odd"],
                "edge": b["edge"],
                "EV": b["ev"],
                "score": b["score"],
                "score_liquido": b.get("score_liquido"),
                "faixa": b["faixa"],
                "risk": b["risco"],
                "correlation": b["correlacao"]["nivel"],
                "diversification": b["diversificacao"]["score"],
                "overlap": (b.get("overlap") or {}).get("score", 0.0),
                "bet_house": b.get("casa"),
                "decision": b.get("decision", "PICK"),
            }
            for b in portfolio.get("multiples", [])
        ],
    }


def _reuso_permitido(bilhete: dict, reuso: dict, config: cfg.MultiplaConfig) -> bool:
    """Reuso e' excecao: so' perna excepcional, so' uma segunda vez."""
    for perna in bilhete["pernas"]:
        chave = _chave_da_perna(perna)
        ja = reuso.get(chave, 0)
        if not ja:
            continue
        if ja >= cfg.MAX_REUSO_EXCEPCIONAL:
            return False
        if perna["component_score"] < cfg.SCORE_PARA_REUSO_EXCEPCIONAL:
            return False
    return True
