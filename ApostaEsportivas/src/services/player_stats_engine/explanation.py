"""Justificativa do Player Stats -- a partir dos numeros que decidiram.

Mesma regra do Pick Boost: nenhum numero novo nasce aqui. A IA pode explicar
por cima depois; o calculo e a conclusao sao do motor estatistico.
"""
from __future__ import annotations


def _n(v, casas=2) -> str:
    return "n/d" if v is None else f"{float(v):.{casas}f}".replace(".", ",")


def _pct(v) -> str:
    return "n/d" if v is None else f"{float(v) * 100:.1f}%"


def resumo_estruturado(c: dict) -> list:
    """Os indicadores do candidato, rotulados pra tela."""
    metodo = c["metodo"]
    jogador = c["jogador"]
    analise = c["analise"]
    serie = c.get("serie") or []

    itens = [
        {"rotulo": "Linha", "valor": c["rotulo_linha"],
         "detalhe": f"{metodo.label} · {jogador['player_name']} ({jogador['team_name']})"},
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
         "detalhe": f"Binomial Negativa · dispersão {_n(analise.get('phi'))}"},
        {"rotulo": "Odd justa x oferecida",
         "valor": f"{_n(analise.get('fair_odd'))} x {_n(analise.get('odd'))}",
         "detalhe": f"margem {_pct(analise.get('edge'))} · EV {_pct(analise.get('ev'))}"},
        {"rotulo": "Score", "valor": _n(c.get("pick_score"), 3),
         "detalhe": "probabilidade, segurança da odd, amostra e margem"},
    ]
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
            "valor": " · ".join(str(int(v)) for v in serie[:10]),
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
