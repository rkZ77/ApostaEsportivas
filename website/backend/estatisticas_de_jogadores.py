"""Desarme, interceptacao, duelo, drible e passe decisivo POR TIME (15/10/2026,
pedido do usuario: "coloca tudo que tiver de estatistica no site").

A folha do JOGO da API-Football nao traz esses numeros; a folha dos JOGADORES
traz, e a coleta ja' grava em `player_match_stats`. Aqui eles sao somados por
time e por jogo · nenhuma chamada a API.

So' conta o time que tem folha de verdade no jogo: MIN_JOGADORES com minuto
em campo. A coleta escreve zero no contador de quem jogou e nao fez o lance
(ver _ZERO_QUANDO_HA_FOLHA no coletor), mas jogo com 3 jogadores coletados
daria um time com 2 desarmes · numero inventado pela metade.

Tiro de meta, lateral e "ataque perigoso" NAO existem no provedor (nem na
folha do jogo nem na do jogador).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: (coluna em player_match_stats, chave, rotulo)
ITENS = (
    ("tackles_total",    "desarmes",         "Desarmes"),
    ("interceptions",    "interceptacoes",   "Interceptações"),
    ("duels_won",        "duelos_ganhos",    "Duelos ganhos"),
    ("dribbles_success", "dribles_certos",   "Dribles certos"),
    ("passes_key",       "passes_decisivos", "Passes decisivos"),
)
CHAVES = tuple(chave for _, chave, _ in ITENS)
MIN_JOGADORES = 11


def _sql() -> str:
    somas = ", ".join(f"SUM({col}) AS {chave}" for col, chave, _ in ITENS)
    return f"""
        SELECT fixture_id, team_id, {somas}, COUNT(*) AS jogadores
          FROM player_match_stats
         WHERE fixture_id = ANY(%s) AND minutes > 0
         GROUP BY fixture_id, team_id
        HAVING COUNT(*) >= {MIN_JOGADORES}
    """


def por_jogo(cur, fixture_ids: list) -> dict:
    """{fixture_id: {team_id: {chave: valor}}}. Tabela ausente ou banco
    recusando: {} · o resto da tela segue sem esses numeros."""
    ids = [int(f) for f in fixture_ids if f is not None]
    if not ids:
        return {}
    try:
        cur.execute(_sql(), (ids,))
        linhas = cur.fetchall()
    except Exception:
        cur.connection.rollback()
        logger.warning("[JOGADORES] soma por time indisponivel", exc_info=True)
        return {}
    saida: dict = {}
    for r in linhas:
        if r.get("fixture_id") is None or r.get("team_id") is None:
            continue
        valores = {chave: int(r[chave]) for chave in CHAVES if r.get(chave) is not None}
        saida.setdefault(int(r["fixture_id"]), {})[int(r["team_id"])] = valores
    return saida


def medias_da_liga(por_fixture: dict) -> dict:
    """{chave: {"media", "jogos"}}: os dois times somados, por jogo, so' nos
    jogos em que OS DOIS tem folha."""
    acc: dict = {}
    for times in por_fixture.values():
        if len(times) != 2:
            continue
        a, b = times.values()
        for chave in CHAVES:
            if chave in a and chave in b:
                s = acc.setdefault(chave, [0, 0])
                s[0] += a[chave] + b[chave]
                s[1] += 1
    return {k: {"media": round(s / n, 2), "jogos": n} for k, (s, n) in acc.items() if n}
