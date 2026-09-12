"""Justificativa do Player Stats -- a partir dos numeros que decidiram.

Mesma regra do Pick Boost: nenhum numero novo nasce aqui. A IA pode explicar
por cima depois; o calculo e a conclusao sao do motor estatistico.
"""
from __future__ import annotations


def _n(v, casas=2) -> str:
    return "n/d" if v is None else f"{float(v):.{casas}f}".replace(".", ",")


def _pct(v) -> str:
    return "n/d" if v is None else f"{float(v) * 100:.1f}%"


def _risco(v) -> str:
    """LOW/MEDIUM/HIGH em português. O rótulo é do apostador, a chave é do motor."""
    return {"LOW": "baixo", "MEDIUM": "médio", "HIGH": "alto"}.get(v, "não medido")


def resumo_estruturado(c: dict) -> list:
    """Os indicadores do candidato, rotulados pra tela."""
    metodo = c["metodo"]
    jogador = c["jogador"]
    analise = c["analise"]
    serie = c.get("serie") or []

    itens = [
        {"rotulo": "Linha", "valor": c["rotulo_linha"],
         "detalhe": f"{metodo.label}, {jogador['player_name']} ({jogador['team_name']})"},
        {"rotulo": "Média recente",
         "valor": _n(analise.get("esperado_bruto")),
         "detalhe": f"{analise.get('amostra')} atuações de titular"},
        {"rotulo": "Valor esperado no jogo",
         "valor": _n(analise.get("esperado")),
         "detalhe": ("ajustado pelo volume do adversário"
                     if analise.get("ajuste_adversario") else "sem ajuste de adversário")},
        {"rotulo": "Frequência histórica",
         "valor": _pct(c.get("frequencia")),
         "detalhe": f"{c.get('acertos')} de {analise.get('amostra')} atuações "
                    f"bateram a linha"},
        {"rotulo": "Probabilidade do modelo", "valor": _pct(analise.get("probability")),
         "detalhe": (f"Binomial Negativa, dispersão {_n(analise.get('phi'))}"
                     + (f", com desconto de {_pct(analise.get('abatimento'))} "
                        f"sobre {_pct(analise.get('probability_modelo'))}"
                        if analise.get("abatimento") else ""))},
        {"rotulo": "Odd justa x oferecida",
         "valor": f"{_n(analise.get('fair_odd'))} x {_n(analise.get('odd'))}",
         "detalhe": f"margem {_pct(analise.get('edge'))}, EV {_pct(analise.get('ev'))}"},
        {"rotulo": "Score", "valor": _n(c.get("pick_score"), 3),
         "detalhe": "probabilidade, segurança da odd, amostra e margem"},
    ]
    # AS CAMADAS DA V2 (2026-09-11) entram na tela pela mesma porta que todo o
    # resto: sem numero novo. Cada item aqui e' um numero que JA' decidiu o
    # pick -- se ele nao aparece, a tela mostra uma conclusao que o apostador
    # nao consegue conferir, que e' o caso que a aba Motor existe pra evitar.
    minutos = c.get("minutos") or {}
    if minutos.get("esperados"):
        itens.append({
            "rotulo": "Minutos esperados",
            "valor": f"{minutos['esperados']:.0f}",
            "detalhe": (f"média de {_n(minutos.get('da_amostra'), 0)} nas atuações "
                        f"lidas, risco de minutos {_risco(minutos.get('risco'))}"),
        })
    if analise.get("amostra_no_mando"):
        itens.append({
            "rotulo": "No mando de hoje",
            "valor": _n(analise.get("esperado_no_mando")),
            "detalhe": f"{analise.get('amostra_no_mando')} atuações, com peso de "
                       f"{_pct(analise.get('peso_do_mando'))} na projeção",
        })
    ajuste = c.get("adversario_ajuste") or {}
    if ajuste.get("disponivel"):
        itens.append({
            "rotulo": "Setor do adversário",
            "valor": f"{_n(ajuste.get('media'))} por jogo",
            "detalhe": f"a liga concede {_n(ajuste.get('baseline'))}, "
                       f"o que ajusta a projeção em "
                       f"{(float(ajuste.get('ajuste') or 1) - 1) * 100:+.1f}%",
        })
    margem = c.get("margem") or {}
    if margem.get("absoluta") is not None:
        itens.append({
            "rotulo": "Margem sobre a linha",
            "valor": f"{margem['absoluta']:+.2f}".replace(".", ","),
            "detalhe": f"{(margem.get('relativa') or 0) * 100:+.0f}% acima da linha",
        })
    disp = c.get("dispersao") or {}
    if disp.get("cv") is not None:
        itens.append({
            "rotulo": "Regularidade",
            "valor": f"CV {_n(disp.get('cv'))}",
            "detalhe": f"mediana {_n(disp.get('mediana'))}, entre "
                       f"{_n(disp.get('minimo'), 0)} e {_n(disp.get('maximo'), 0)}",
        })
    qualidade = c.get("data_quality") or {}
    if qualidade.get("score") is not None:
        itens.append({
            "rotulo": "Qualidade dos dados",
            "valor": f"{qualidade['score']:.0f}/100",
            "detalhe": f"amostra, minutos, titularidade, recência e adversário "
                       f"({qualidade.get('classificacao')})",
        })
    for achado in (c.get("contradicoes") or []):
        itens.append({
            "rotulo": "Ponto de atenção",
            "valor": achado["texto"],
            "detalhe": f"contradição {achado['severidade'].lower()}",
        })
    if c.get("adversario"):
        adv = c["adversario"]
        itens.append({
            "rotulo": "Volume do adversário",
            "valor": _n(adv.get("media")),
            "detalhe": f"{adv.get('amostra')} jogos no mando de hoje",
        })
    if serie:
        itens.append({
            "rotulo": "Últimas atuações",
            "valor": ", ".join(str(int(v)) for v in serie[:10]),
            "detalhe": "da mais recente para a mais antiga",
        })
    return itens


def frase(c: dict) -> str:
    """Texto corrido pro campo `reasoning` do pick."""
    metodo, jogador = c["metodo"], c["jogador"]
    analise = c["analise"]
    partes = [
        f"{jogador['player_name']} ({jogador['team_name']}) registra "
        f"{_n(analise.get('esperado_bruto'))} {metodo.label.lower()} por jogo em "
        f"{analise.get('amostra')} atuações de titular."
    ]
    if c.get("adversario") and c["adversario"].get("media") is not None:
        partes.append(
            f"O adversário de hoje produz {_n(c['adversario']['media'])} por jogo "
            f"nesse mando ({c['adversario'].get('amostra')} jogos), o que leva a "
            f"expectativa para {_n(analise.get('esperado'))}."
        )
    minutos = c.get("minutos") or {}
    if minutos.get("esperados") and (minutos.get("fator") or 1.0) < 1.0:
        partes.append(
            f"A expectativa de {minutos['esperados']:.0f} minutos hoje é menor que a "
            f"das atuações que formaram essa média, e a projeção foi reduzida por isso."
        )
    ajuste = c.get("adversario_ajuste") or {}
    if ajuste.get("disponivel") and ajuste.get("ajuste") not in (None, 1.0):
        direcao = "acima" if float(ajuste["ajuste"]) > 1 else "abaixo"
        partes.append(
            f"O adversário concede {_n(ajuste.get('media'))} por jogo neste mando, "
            f"{direcao} da média da liga ({_n(ajuste.get('baseline'))})."
        )
    if c.get("frequencia") is not None:
        partes.append(
            f"A linha foi batida em {c.get('acertos')} das {analise.get('amostra')} "
            f"atuações ({_pct(c.get('frequencia'))})."
        )
    partes.append(
        f"Probabilidade de {c['rotulo_linha'].lower()}: {_pct(analise.get('probability'))} "
        f"(odd justa {_n(analise.get('fair_odd'))} contra {_n(analise.get('odd'))} "
        f"oferecida, margem de {_pct(analise.get('edge'))})."
    )
    return " ".join(partes)
