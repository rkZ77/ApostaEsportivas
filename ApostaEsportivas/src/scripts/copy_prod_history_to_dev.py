"""
copy_prod_history_to_dev.py · Copia (somente leitura no PROD, somente
insercao aditiva no DEV) o historico necessario para rodar backtests do
motor deterministico: match_statistics, league_standings, picks_vip e
odds_values (fixtures ja encerrados apenas, pra nao copiar a tabela toda).

NUNCA escreve no PROD. NUNCA apaga/atualiza nada no DEV · so insere linhas
que ainda nao existem (ON CONFLICT DO NOTHING / dedup manual).

Uso:
  python src/scripts/copy_prod_history_to_dev.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import psycopg2.extras
from utils.db_utils import get_connection

MATCH_STATS_COLS = [
    "fixture_id", "league_id", "season", "home_team_id", "away_team_id",
    "home_goals", "away_goals", "total_goals",
    "home_corners", "away_corners", "total_corners",
    "home_yellow_cards", "away_yellow_cards", "total_yellow_cards",
    "home_red_cards", "away_red_cards", "total_red_cards",
    "status", "match_date",
    "home_shots_on", "away_shots_on", "home_shots_off", "away_shots_off",
    "home_total_shots", "away_total_shots",
    "home_blocked_shots", "away_blocked_shots",
    "home_goalkeeper_saves", "away_goalkeeper_saves",
    "home_fouls", "away_fouls", "home_offsides", "away_offsides",
    "home_possession", "away_possession", "home_passes", "away_passes",
    "home_passes_accuracy", "away_passes_accuracy",
    "referee", "home_goals_ht", "away_goals_ht",
]

LEAGUE_STANDINGS_COLS = [
    "league_id", "league_name", "country", "season", "group_name",
    "team_id", "team_name", "team_logo", "rank", "points", "goals_diff",
    "form", "status", "description", "played", "win", "draw", "lose",
    "goals_for", "goals_against", "home_played", "home_win", "home_draw",
    "home_lose", "home_goals_for", "home_goals_against", "away_played",
    "away_win", "away_draw", "away_lose", "away_goals_for",
    "away_goals_against", "api_last_update", "created_at", "updated_at",
]

PICKS_VIP_COLS = [
    "fixture_id", "match_date", "home_team_id", "away_team_id",
    "home_team_name", "away_team_name", "market", "line", "odd",
    "bet_house", "market_type", "market_id", "confidence", "stake",
    "stake_pct", "ev", "reasoning", "result", "profit", "created_at",
    "probability",
]

ODDS_VALUES_COLS = [
    "market_row_id", "value_name", "odd_value",
    "fixture_id", "league_id", "season", "match_datetime",
    "home_team_id", "home_team", "away_team_id", "away_team",
    "bookmaker_id", "bookmaker_name",
    "market_id", "market_name",
    "market_type", "side_team",
    "team_id", "team_name",
    "line_value", "market_pt",
    "created_at", "updated_at",
]


def _copy_table(prod_cur, dev_cur, table, cols, select_sql, conflict_col=None):
    prod_cur.execute(select_sql)
    rows = prod_cur.fetchall()
    if not rows:
        print(f"[COPY] {table}: 0 linhas no PROD para copiar.")
        return

    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    conflict_clause = f"ON CONFLICT ({conflict_col}) DO NOTHING" if conflict_col else ""

    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) {conflict_clause}"

    inserted = 0
    for r in rows:
        dev_cur.execute(sql, [r[c] for c in cols])
        inserted += dev_cur.rowcount
    print(f"[COPY] {table}: {len(rows)} lidas no PROD, {inserted} inseridas no DEV (resto ja existia).")


def _copy_league_standings(prod_cur, dev_cur):
    prod_cur.execute(f"SELECT {', '.join(LEAGUE_STANDINGS_COLS)} FROM league_standings")
    rows = prod_cur.fetchall()

    dev_cur.execute("SELECT league_id, team_id, season FROM league_standings")
    existing = {(r["league_id"], r["team_id"], r["season"]) for r in dev_cur.fetchall()}

    col_list = ", ".join(LEAGUE_STANDINGS_COLS)
    placeholders = ", ".join(["%s"] * len(LEAGUE_STANDINGS_COLS))
    sql = f"INSERT INTO league_standings ({col_list}) VALUES ({placeholders})"

    inserted = 0
    for r in rows:
        key = (r["league_id"], r["team_id"], r["season"])
        if key in existing:
            continue
        dev_cur.execute(sql, [r[c] for c in LEAGUE_STANDINGS_COLS])
        existing.add(key)
        inserted += 1
    print(f"[COPY] league_standings: {len(rows)} lidas no PROD, {inserted} inseridas no DEV (resto ja existia).")


def run():
    prod_conn = get_connection(env="prod")
    dev_conn = get_connection(env="dev")
    prod_cur = prod_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    dev_cur = dev_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        _copy_table(
            prod_cur, dev_cur, "match_statistics", MATCH_STATS_COLS,
            f"SELECT {', '.join(MATCH_STATS_COLS)} FROM match_statistics",
            conflict_col="fixture_id",
        )
        _copy_league_standings(prod_cur, dev_cur)
        _copy_table(
            prod_cur, dev_cur, "picks_vip", PICKS_VIP_COLS,
            f"SELECT {', '.join(PICKS_VIP_COLS)} FROM picks_vip WHERE result IN ('GREEN','RED')",
            conflict_col="fixture_id",
        )
        # So fixtures ja encerrados (com match_statistics) -- evita copiar
        # odds de fixtures NS/futuros, que mudam ate o jogo comecar e nao
        # servem pro backtest (que so olha pro passado).
        _copy_table(
            prod_cur, dev_cur, "odds_values", ODDS_VALUES_COLS,
            f"SELECT {', '.join(ODDS_VALUES_COLS)} FROM odds_values "
            f"WHERE fixture_id IN (SELECT fixture_id FROM match_statistics)",
            conflict_col="market_row_id, value_name",
        )
        dev_conn.commit()
        print("[COPY] Commit no DEV concluido. PROD nao foi alterado (somente leitura).")
    except Exception:
        dev_conn.rollback()
        raise
    finally:
        prod_cur.close()
        dev_cur.close()
        prod_conn.close()
        dev_conn.close()


if __name__ == "__main__":
    run()
