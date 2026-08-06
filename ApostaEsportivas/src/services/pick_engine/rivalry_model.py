"""Rivalidade MEDIDA, nao listada.

O CASO QUE ORIGINOU ESTE MODULO
-------------------------------
"Under cartoes" aprovado num Fluminense x Vasco, jogo de volta valendo
classificacao. O motor tinha taxa historica boa pra Under porque a media dos
15 jogos de cada time e' de campeonato normal -- e nada no calculo sabia que
aquele jogo especifico nao era um jogo normal.

POR QUE NAO UMA LISTA DE CLASSICOS
----------------------------------
A tentacao e' cadastrar pares de times e marcar "classico = sim". Isso e'
fragil e nao escala: exige manutencao manual, nao cobre liga nova, nao
distingue classico quente de classico morno, e nao diz QUANTO ajustar. Pior:
seria uma constante escolhida no lugar de uma quantidade medivel.

Aqui a rivalidade e' estimada do proprio historico. Se Flu x Vasco produz 7,2
cartoes por confronto enquanto os dois times promediam 4,3 nos demais jogos, o
excesso de +2,9 nao e' opiniao sobre rivalidade -- e' o que aconteceu nos
confrontos anteriores. Um par de times sem histerese nenhuma mede excesso zero
e nao sofre ajuste, sem ninguem precisar decidir se "conta como classico".

O dado vem de MatchStatsService.get_h2h_matches(), que le `match_statistics`
-- a mesma tabela de sempre. Nao ha coletor novo nem chamada de API.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao decide pick. Devolve um excesso medido e a amostra que o sustenta; quem
usa (referee_model.game_intensity e o gate de cartoes) decide o peso.
"""
from __future__ import annotations

from services.pick_engine.stats_model import _cards_points

# Amostra minima de confrontos diretos pra o excesso ser levado a serio. Com
# menos de 4 encontros, a diferenca entre o H2H e a linha de base e' quase
# toda ruido -- e' o mesmo criterio de bom senso ja' aplicado ao arbitro
# (cards_referee_min_games), calibrado pra baixo porque confronto direto e'
# ainda mais raro que jogo de arbitro.
MIN_CONFRONTOS = 4

# Excesso de pontos de cartao (amarelo=1, vermelho=2) a partir do qual o
# confronto e' considerado de tensao acima do normal. 1.5 ponto equivale a um
# amarelo e meio a mais que o esperado pelos dois times -- diferenca que
# aparece no resultado de um Under 5.5, nao no ruido.
EXCESSO_RELEVANTE = 1.5

# Teto do excesso considerado, pra um unico confronto atipico (expulsao dupla,
# briga generalizada) nao dominar a estimativa inteira.
EXCESSO_MAX = 4.0


def _media_cartoes(jogos: list) -> float | None:
    """Pontos de cartao por jogo (amarelo=1, vermelho=2) -- mesma convencao de
    _cards_points e da graduacao real do resultado."""
    if not jogos:
        return None
    return sum(_cards_points(j, "total") for j in jogos) / len(jogos)


def rivalry_signal(h2h_matches: list, baseline_cartoes: float | None) -> dict:
    """Excesso disciplinar medido nos confrontos diretos.

    `h2h_matches`: saida de MatchStatsService.get_h2h_matches().
    `baseline_cartoes`: pontos de cartao por jogo esperados pra estes dois
    times fora do confronto -- normalmente
    stats_model.expected_value_convergence(...)['expected_value'] da familia
    cards, que ja' cruza feitos e cedidos.

    Sempre devolve os numeros brutos junto do rotulo, nunca so' o rotulo --
    mesma convencao de context_model e referee_model.
    """
    n = len(h2h_matches or [])
    media_h2h = _media_cartoes(h2h_matches)

    if n < MIN_CONFRONTOS or media_h2h is None or baseline_cartoes is None:
        return {
            "confiavel": False,
            "confrontos": n,
            "media_h2h": round(media_h2h, 2) if media_h2h is not None else None,
            "baseline": baseline_cartoes,
            "excesso": None,
            "label": "desconhecido",
        }

    excesso = max(min(media_h2h - float(baseline_cartoes), EXCESSO_MAX), -EXCESSO_MAX)
    if excesso >= EXCESSO_RELEVANTE:
        label = "rivalidade_alta"
    elif excesso <= -EXCESSO_RELEVANTE:
        label = "confronto_frio"
    else:
        label = "normal"

    return {
        "confiavel": True,
        "confrontos": n,
        "media_h2h": round(media_h2h, 2),
        "baseline": round(float(baseline_cartoes), 2),
        "excesso": round(excesso, 2),
        "label": label,
    }


def intensity_delta(sinal: dict | None) -> float:
    """Quanto o excesso de H2H desloca o score de intensidade de jogo (0-1).

    Proporcional ao excesso medido e limitado a +-0.20, pra a rivalidade
    reforcar o sinal sem poder sozinha decidir a elegibilidade de um mercado.
    Sem amostra confiavel devolve 0 -- ausencia de dado nunca vira evidencia
    de calma.
    """
    if not sinal or not sinal.get("confiavel") or sinal.get("excesso") is None:
        return 0.0
    return round(max(min(sinal["excesso"] / EXCESSO_MAX * 0.20, 0.20), -0.20), 4)
