"""Confronto direto pela API quando o banco nao tem (12/10/2026, pedido do usuario).

O Raio-X le' o confronto de `match_statistics`, que so' tem os jogos que a
coleta trouxe · Atalanta x Venezia mostrava "ainda nao se enfrentaram" com
anos de historico entre os dois. Quando o banco volta vazio, UMA consulta a
`fixtures/headtohead` por par de times, guardada em `h2h_api_cache` por 30 dias
(par vazio tambem: dois times que nunca se enfrentaram nao custam de novo).

A API so' traz o placar, sem escanteio e cartao: esses ficam nulos e a tela
mostra traco. Cota acima de 90% no dia: nao consulta, e o Raio-X segue como
antes · confronto e' informacao boa de ter, nao pode disputar com liquidacao.
"""
from __future__ import annotations

import json
import logging
import os

import requests

import api_quota

logger = logging.getLogger(__name__)

API_URL = "https://v3.football.api-sports.io/fixtures/headtohead"
VALIDADE_DIAS = 30
TETO_DA_COTA_PCT = 90
_ENCERRADOS = ("FT", "AET", "PEN")

#: Criada em migrations.py · aqui so' pra ficar perto de quem le'.
DDL = """
    CREATE TABLE IF NOT EXISTS h2h_api_cache (
        time_a        INTEGER NOT NULL,
        time_b        INTEGER NOT NULL,
        jogos         JSONB NOT NULL DEFAULT '[]',
        consultado_em TIMESTAMP NOT NULL DEFAULT NOW(),
        PRIMARY KEY (time_a, time_b)
    )
"""


def _par(a: int, b: int) -> tuple[int, int]:
    """A ordem do mando nao muda o confronto: uma linha por par."""
    return (a, b) if a < b else (b, a)


def jogos_da_resposta(resposta: list, limite: int) -> list[dict]:
    """Itens de /fixtures/headtohead -> o formato do `h2h` do Raio-X."""
    jogos = []
    for item in resposta or []:
        fx, times, gols = item.get("fixture") or {}, item.get("teams") or {}, item.get("goals") or {}
        if ((fx.get("status") or {}).get("short")) not in _ENCERRADOS:
            continue
        if gols.get("home") is None or gols.get("away") is None:
            continue
        jogos.append({
            "data": (fx.get("date") or "")[:19] or None,
            # Pro filtro "so' esta competicao" da aba Confronto (14/10/2026).
            # Cache gravado antes disso vem sem: conta so' em "todas".
            "league_id": (item.get("league") or {}).get("id"),
            "home_team_id": (times.get("home") or {}).get("id"),
            "away_team_id": (times.get("away") or {}).get("id"),
            "home_goals": gols["home"], "away_goals": gols["away"],
            "escanteios": None, "amarelos": None,
        })
    jogos.sort(key=lambda j: j["data"] or "", reverse=True)
    return jogos[:limite]


def _cota_permite() -> bool:
    pct = api_quota.estado_atual().get("pct_usado")
    return pct is None or pct < TETO_DA_COTA_PCT


def confronto(cur, home_id: int, away_id: int, limite: int = 8) -> list[dict] | None:
    """Os jogos entre os dois, do cache ou da API. None = nao deu pra saber."""
    a, b = _par(home_id, away_id)
    try:
        cur.execute("""
            SELECT jogos FROM h2h_api_cache
             WHERE time_a = %s AND time_b = %s
               AND consultado_em > NOW() - make_interval(days => %s)
        """, (a, b, VALIDADE_DIAS))
        linha = cur.fetchone()
        if linha:
            jogos = linha["jogos"]
            return (json.loads(jogos) if isinstance(jogos, str) else jogos)[:limite]
    except Exception:
        cur.connection.rollback()
        logger.warning("[H2H API] cache indisponivel", exc_info=True)
        return None

    chave = os.getenv("API_FOOTBALL_KEY", "")
    if not chave or not _cota_permite():
        return None
    try:
        r = requests.get(API_URL, headers={"x-apisports-key": chave},
                         params={"h2h": f"{a}-{b}", "last": 20}, timeout=10)
        api_quota.registrar(r.headers, origem="raio-x h2h")
        if r.status_code != 200:
            return None
        payload = r.json() or {}
        if isinstance(payload.get("errors"), dict) and payload["errors"]:
            # Recusa (limite, chave): nao grava · vazio aqui nao e' "nunca jogaram".
            logger.warning("[H2H API] %s-%s recusado: %s", a, b, payload["errors"])
            return None
        jogos = jogos_da_resposta(payload.get("response") or [], 20)
    except Exception as e:
        logger.warning("[H2H API] %s-%s: %s", a, b, e)
        return None
    try:
        cur.execute("""
            INSERT INTO h2h_api_cache (time_a, time_b, jogos, consultado_em)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (time_a, time_b) DO UPDATE
               SET jogos = EXCLUDED.jogos, consultado_em = NOW()
        """, (a, b, json.dumps(jogos)))
        cur.connection.commit()
    except Exception:
        cur.connection.rollback()
        logger.warning("[H2H API] nao gravou %s-%s", a, b, exc_info=True)
    return jogos[:limite]
