"""Extrai pernas individuais das 4 tabelas de picks (picks_vip/picks_free
sao 1 linha = 1 perna; picks_multiplas/picks_alavancagem tem 2-3 pernas
por linha, em formatos diferentes -- JSON array vs colunas _1/_2/_3).
Usado por scripts/backtest_pick_engine.py e services/picks_ledger_sync_service.py
-- extraido pra um lugar so em vez de duplicar a logica de achatamento."""
import json


def fetch_vip_free_legs(cur, table: str) -> list:
    """cur precisa ser RealDictCursor. table = 'picks_vip' ou 'picks_free'.
    picks_vip guarda nome do time em home_team_name/away_team_name;
    picks_free guarda em home_team/away_team -- colunas diferentes."""
    team_cols = ("home_team_name AS home_team, away_team_name AS away_team"
                 if table == "picks_vip" else "home_team, away_team")
    cur.execute(f"""
        SELECT id, fixture_id, match_date, home_team_id, away_team_id,
               {team_cols}, market, market_type, line, odd, bet_house,
               confidence, {"probability" if table == "picks_vip" else "prob_real AS probability"},
               {"ev" if table == "picks_vip" else "edge AS ev"},
               reasoning, stake_pct, stake_units, result, profit, created_at
        FROM {table}
        WHERE fixture_id IS NOT NULL
    """)
    legs = []
    for row in cur.fetchall():
        d = dict(row)
        d["source_table"] = table
        d["source_id"] = d.pop("id")
        # leg_number=1 (nao None) -- NULL nao e deduplicado por UNIQUE
        # constraint no Postgres (NULL != NULL), quebraria idempotencia
        # do upsert em picks_ledger.
        d["leg_number"] = 1
        legs.append(d)
    return legs


def fetch_multiplas_legs(cur) -> list:
    """cur precisa ser RealDictCursor."""
    cur.execute("SELECT id, games, match_date, created_at FROM picks_multiplas")
    legs = []
    for row in cur.fetchall():
        games_raw = row["games"]
        games = games_raw if isinstance(games_raw, list) else json.loads(games_raw)
        for i, g in enumerate(games, start=1):
            if not g.get("fixture_id"):
                continue
            legs.append({
                "source_table": "picks_multiplas", "source_id": row["id"], "leg_number": i,
                "fixture_id": g["fixture_id"], "match_date": row["match_date"],
                "home_team_id": g.get("home_team_id"), "away_team_id": g.get("away_team_id"),
                "home_team": g.get("home_team"), "away_team": g.get("away_team"),
                "market": g.get("market", ""), "market_type": g.get("market_type"),
                "line": g.get("line", ""), "odd": g.get("odd"), "bet_house": g.get("bet_house"),
                "confidence": g.get("confidence"), "probability": g.get("prob_real"),
                "ev": None, "reasoning": None, "stake_pct": None, "stake_units": None,
                "result": g.get("result"), "profit": None, "created_at": row["created_at"],
            })
    return legs


def fetch_alavancagem_legs(cur) -> list:
    """cur precisa ser RealDictCursor."""
    cur.execute("""
        SELECT id, match_date, created_at,
               fixture_id_1, home_team_1, away_team_1, market_1, market_type_1, line_1, odd_1,
               bet_house_1, confidence_1, prob_real_1, reasoning_1,
               fixture_id_2, home_team_2, away_team_2, market_2, market_type_2, line_2, odd_2,
               bet_house_2, confidence_2, prob_real_2, reasoning_2,
               fixture_id_3, home_team_3, away_team_3, market_3, market_type_3, line_3, odd_3,
               bet_house_3, confidence_3, prob_real_3, reasoning_3
        FROM picks_alavancagem
    """)
    legs = []
    for row in cur.fetchall():
        for i in (1, 2, 3):
            fid = row[f"fixture_id_{i}"]
            if not fid:
                continue
            legs.append({
                "source_table": "picks_alavancagem", "source_id": row["id"], "leg_number": i,
                "fixture_id": fid, "match_date": row["match_date"],
                "home_team_id": None, "away_team_id": None,
                "home_team": row[f"home_team_{i}"], "away_team": row[f"away_team_{i}"],
                "market": row[f"market_{i}"] or "", "market_type": row[f"market_type_{i}"],
                "line": row[f"line_{i}"] or "", "odd": row[f"odd_{i}"], "bet_house": row[f"bet_house_{i}"],
                "confidence": row[f"confidence_{i}"], "probability": row[f"prob_real_{i}"],
                "ev": None, "reasoning": row[f"reasoning_{i}"], "stake_pct": None, "stake_units": None,
                "result": None, "profit": None, "created_at": row["created_at"],
            })
    return legs


def fetch_all_legs(cur) -> list:
    """Todas as pernas de todas as tabelas de picks, achatadas.
    cur precisa ser RealDictCursor."""
    legs = []
    legs += fetch_vip_free_legs(cur, "picks_vip")
    legs += fetch_vip_free_legs(cur, "picks_free")
    # picks_faltas e picks_goleiros usam exatamente as mesmas colunas de
    # picks_free (home_team/away_team, prob_real, edge), entao reusam o mesmo
    # extractor -- os condicionais la' dentro so' distinguem picks_vip.
    # try/except porque instancia sem a migracao das tabelas novas nao pode
    # deixar de sincronizar o ledger inteiro.
    for tabela in ("picks_faltas", "picks_goleiros"):
        try:
            legs += fetch_vip_free_legs(cur, tabela)
        except Exception:
            cur.connection.rollback()
    legs += fetch_multiplas_legs(cur)
    legs += fetch_alavancagem_legs(cur)
    return legs


def fixture_context(cur, fixture_id: int):
    """home_team_id/away_team_id/league_id/season direto de match_statistics
    (fonte unica de verdade -- ignora o que estiver denormalizado nas
    tabelas de picks, que pode faltar pra multiplas/alavancagem).
    cur pode ser cursor comum (posicional) ou RealDictCursor."""
    cur.execute("""
        SELECT home_team_id, away_team_id, league_id, season
        FROM match_statistics WHERE fixture_id = %s LIMIT 1
    """, (fixture_id,))
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {"home_team_id": row[0], "away_team_id": row[1], "league_id": row[2], "season": row[3]}
