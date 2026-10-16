"""O árbitro da partida, no Raio-X (16/10/2026, pedido do usuário: "quem é o
árbitro, quantos jogos apitou na temporada, média de faltas, cartões, VAR, e
filtrar só os jogos que ele apitou do time da casa e do visitante").

Tudo do banco, nenhuma chamada a API:
  - os jogos dele: `match_statistics.referee`, pela CHAVE do nome (arbitro.py:
    "Raphael Claus" e "Raphael Claus, Brazil" sao a mesma pessoa);
  - VAR e pênalti: `match_events` (coletor de eventos). Só existe nos jogos
    com evento coletado, e a média diz em quantos.

Recortes: a temporada dele em TODAS as competições (árbitro apita liga e
copa), a mesma só nesta liga, e os jogos dele com cada um dos dois times em
qualquer temporada · encontro de árbitro com time é raro, e só a temporada
daria um ou dois jogos.
"""
from __future__ import annotations

import logging

from arbitro import chave_do_arbitro, sql_chave

logger = logging.getLogger(__name__)

FINALIZADOS = ("FT", "AET", "PEN")
#: Jogos com um dos times, em qualquer temporada.
MAX_COM_TIME = 20
#: Jogos da temporada que vão pra lista da tela (a média usa todos).
MAX_LISTA = 40

#: Detalhe do evento de VAR na API -> português.
VAR_PT = {
    "goal cancelled": "Gol anulado",
    "goal disallowed - offside": "Gol anulado (impedimento)",
    "goal disallowed - foul": "Gol anulado (falta)",
    "goal disallowed - handball": "Gol anulado (mão)",
    "goal confirmed": "Gol confirmado",
    "penalty confirmed": "Pênalti confirmado",
    "penalty cancelled": "Pênalti cancelado",
    "card upgrade": "Cartão revisto",
    "card reviewed": "Cartão revisto",
}


def var_em_portugues(detalhe: str | None) -> str:
    d = (detalhe or "").strip()
    return VAR_PT.get(d.lower(), d or "Revisão do VAR")


def _jogos(cur, chave: str, onde: str, params: tuple, limite: int) -> list[dict]:
    cur.execute(f"""
        SELECT ms.fixture_id, ms.match_date, ms.league_id, ms.season,
               ms.home_team_id, ms.away_team_id,
               (SELECT t.name FROM teams t WHERE t.team_id = ms.home_team_id LIMIT 1) AS home_team,
               (SELECT t.name FROM teams t WHERE t.team_id = ms.away_team_id LIMIT 1) AS away_team,
               ms.home_goals, ms.away_goals,
               ms.home_yellow_cards, ms.away_yellow_cards, ms.home_red_cards, ms.away_red_cards,
               ms.home_fouls, ms.away_fouls, ms.events_checked_at IS NOT NULL AS tem_eventos
          FROM match_statistics ms
         WHERE {sql_chave('ms.referee')} = %s AND ms.status IN ('FT','AET','PEN') {onde}
         ORDER BY ms.match_date DESC
         LIMIT %s
    """, (chave, *params, limite))
    return [dict(r) for r in cur.fetchall()]


def _eventos(cur, fixture_ids: list) -> dict:
    """{fixture_id: {"var": [...], "penaltis": n}} dos jogos com evento."""
    if not fixture_ids:
        return {}
    try:
        cur.execute("""
            SELECT fixture_id, minuto, team_id, tipo, detalhe
              FROM match_events
             WHERE fixture_id = ANY(%s)
               AND (lower(tipo) = 'var'
                    OR (lower(tipo) = 'goal' AND detalhe ILIKE '%%penalty%%'))
             ORDER BY fixture_id, seq
        """, (list(fixture_ids),))
        linhas = cur.fetchall()
    except Exception:
        cur.connection.rollback()
        logger.warning("[ARBITRO] eventos indisponiveis", exc_info=True)
        return {}
    saida: dict = {}
    for r in linhas:
        e = saida.setdefault(r["fixture_id"], {"var": [], "penaltis": 0})
        if (r["tipo"] or "").lower() == "var":
            e["var"].append({"minuto": r["minuto"], "team_id": r["team_id"],
                             "lance": var_em_portugues(r["detalhe"])})
        else:
            e["penaltis"] += 1          # convertido ou perdido: foi marcado
    return saida


def _media(valores: list) -> dict | None:
    v = [x for x in valores if x is not None]
    return {"media": round(sum(v) / len(v), 2), "jogos": len(v)} if v else None


def _pct(jogos: list, cond) -> int | None:
    return round(100 * sum(1 for j in jogos if cond(j)) / len(jogos)) if jogos else None


def _soma(j, a, b):
    return None if j.get(a) is None or j.get(b) is None else j[a] + j[b]


def resumo(jogos: list[dict]) -> dict:
    """Os números de uma lista de jogos dele. Média só sobre quem tem o dado."""
    com_eventos = [j for j in jogos if j.get("tem_eventos")]
    placar = [j for j in jogos if j.get("home_goals") is not None and j.get("away_goals") is not None]
    amarelos = [_soma(j, "home_yellow_cards", "away_yellow_cards") for j in jogos]
    vermelhos = [_soma(j, "home_red_cards", "away_red_cards") for j in jogos]
    pontos = [None if a is None or v is None else a + 2 * v for a, v in zip(amarelos, vermelhos)]
    return {
        "jogos": len(jogos),
        "faltas": _media([_soma(j, "home_fouls", "away_fouls") for j in jogos]),
        "amarelos": _media(amarelos),
        "vermelhos": _media(vermelhos),
        # Amarelo + 2 x vermelho: a conta que o motor usa pra pick de cartão.
        "pontos_de_cartao": _media(pontos),
        "amarelos_mandante": _media([j.get("home_yellow_cards") for j in jogos]),
        "amarelos_visitante": _media([j.get("away_yellow_cards") for j in jogos]),
        "pct_mais_de_3_5_amarelos": _pct([a for a in amarelos if a is not None], lambda a: a > 3.5),
        "pct_mais_de_4_5_amarelos": _pct([a for a in amarelos if a is not None], lambda a: a > 4.5),
        "penaltis": _media([j.get("penaltis", 0) for j in com_eventos]),
        "var": _media([len(j.get("var") or []) for j in com_eventos]),
        "pct_mandante_vence": _pct(placar, lambda j: j["home_goals"] > j["away_goals"]),
        "pct_empate": _pct(placar, lambda j: j["home_goals"] == j["away_goals"]),
        "pct_visitante_vence": _pct(placar, lambda j: j["home_goals"] < j["away_goals"]),
    }


def _linha_da_tela(j: dict) -> dict:
    return {
        "fixture_id": j["fixture_id"],
        "data": j["match_date"].isoformat()[:10] if hasattr(j["match_date"], "isoformat") else str(j["match_date"])[:10],
        "league_id": j["league_id"],
        "home_team_id": j["home_team_id"], "away_team_id": j["away_team_id"],
        "home_team": j.get("home_team"), "away_team": j.get("away_team"),
        "home_goals": j.get("home_goals"), "away_goals": j.get("away_goals"),
        "amarelos": _soma(j, "home_yellow_cards", "away_yellow_cards"),
        "vermelhos": _soma(j, "home_red_cards", "away_red_cards"),
        "faltas": _soma(j, "home_fouls", "away_fouls"),
        "home_amarelos": j.get("home_yellow_cards"), "away_amarelos": j.get("away_yellow_cards"),
        "penaltis": j.get("penaltis") if j.get("tem_eventos") else None,
        "var": j.get("var") if j.get("tem_eventos") else None,
    }


def _com_eventos(cur, jogos: list[dict]) -> list[dict]:
    ev = _eventos(cur, [j["fixture_id"] for j in jogos if j.get("tem_eventos")])
    for j in jogos:
        e = ev.get(j["fixture_id"]) or {}
        j["var"] = e.get("var", [])
        j["penaltis"] = e.get("penaltis", 0)
    return jogos


def arbitro_do_jogo(cur, fixture_id: int) -> dict:
    cur.execute("""
        SELECT f.referee, f.league_id, f.season, f.home_team_id, f.away_team_id,
               f.home_team, f.away_team,
               (SELECT ms.referee FROM match_statistics ms WHERE ms.fixture_id = f.fixture_id LIMIT 1) AS referee_ms
          FROM fixtures f WHERE f.fixture_id = %s
    """, (fixture_id,))
    fix = cur.fetchone()
    if not fix:
        return {"status": "sem_jogo"}
    nome = fix["referee"] or fix["referee_ms"]
    chave = chave_do_arbitro(nome)
    if not chave:
        # A escala costuma sair 1 ou 2 dias antes do jogo.
        return {"status": "sem_arbitro"}

    temporada = _com_eventos(cur, _jogos(cur, chave, "AND ms.season = %s", (fix["season"],), 500))
    com_casa = _com_eventos(cur, _jogos(
        cur, chave, "AND (ms.home_team_id = %s OR ms.away_team_id = %s)",
        (fix["home_team_id"], fix["home_team_id"]), MAX_COM_TIME))
    com_fora = _com_eventos(cur, _jogos(
        cur, chave, "AND (ms.home_team_id = %s OR ms.away_team_id = %s)",
        (fix["away_team_id"], fix["away_team_id"]), MAX_COM_TIME))
    nesta_liga = [j for j in temporada if j["league_id"] == fix["league_id"]]

    def bloco(jogos, limite=MAX_LISTA):
        return {"resumo": resumo(jogos), "jogos": [_linha_da_tela(j) for j in jogos[:limite]]}

    return {
        "status": "ok",
        "nome": nome.split(",", 1)[0].strip(),
        "temporada": fix["season"],
        "league_id": fix["league_id"],
        "temporada_toda": bloco(temporada),
        "nesta_liga": bloco(nesta_liga),
        "com_mandante": {"team_id": fix["home_team_id"], **bloco(com_casa)},
        "com_visitante": {"team_id": fix["away_team_id"], **bloco(com_fora)},
    }
