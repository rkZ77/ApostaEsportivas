"""Dica do Dia via motor deterministico (pick_engine) -- so roda quando
DB_ENV=dev. Reimplementa localmente a selecao de fixtures/checagem de
"ja rodou hoje" (nao importa de ai/dica_do_dia_pipeline.py -- esse modulo
instancia Anthropic() no nivel de modulo, import indevido custaria uma
inicializacao de client sem necessidade e acopla este pipeline ao de IA)."""
import os

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
from services.odds_service import OddsService
from ai.ai_suggestions_service import AISuggestionsService  # so o staticmethod calculate_stake
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain
from services.pick_engine.config import DICA_CONFIG
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx

WC_LEAGUE_ID = 1
ODD_MIN = 1.30
ODD_MAX = 1.80
MAX_FIXTURES = 3

_LEAGUE_PRIORITY = {
    1: 1, 2: 2, 3: 3, 848: 4, 39: 5, 140: 6, 135: 7, 78: 8,
    61: 9, 94: 10, 88: 11, 13: 12, 11: 13, 71: 14, 72: 15,
}


def _require_dev():
    if os.getenv("DB_ENV", "").lower() != "dev":
        raise RuntimeError(
            "run_dica_engine() so pode rodar com DB_ENV=dev -- producao continua com IA.")


def _has_today_dica(cur) -> bool:
    cur.execute("SELECT COUNT(*) FROM picks_free WHERE match_date = CURRENT_DATE")
    return cur.fetchone()[0] >= 1


def _fixtures_with_odds_in_range(cur) -> list:
    """Mesma query de ai/dica_do_dia_pipeline.py::get_fixtures_with_odds_in_range,
    reimplementada aqui para nao acoplar a esse modulo (que instancia
    Anthropic() no import)."""
    cur.execute("""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.status
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE DATE(f.match_datetime) = CURRENT_DATE
          AND f.status IN ('NS', 'TBD', 'LIVE')
          AND ov.odd_value BETWEEN %s AND %s
    """, (ODD_MIN, ODD_MAX))

    rows = cur.fetchall()
    fixtures = [
        {
            "fixture_id": r[0], "league_id": r[1], "season": r[2],
            "home_team_id": r[3], "away_team_id": r[4],
            "home_team": r[5], "away_team": r[6],
            "match_datetime": r[7], "status": r[8],
        }
        for r in rows
    ]
    fixtures.sort(key=lambda f: (_LEAGUE_PRIORITY.get(f["league_id"], 99), f["match_datetime"]))
    return fixtures[:MAX_FIXTURES]


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    if league_id in NATIONAL_TEAM_LEAGUE_IDS:
        return match_stats.get_last_n_all_competitions(team_id)
    return match_stats.get_all_matches_full(team_id, season, league_id)


def _best_candidate_across_fixtures(fixtures: list) -> tuple | None:
    """Roda o motor pra cada fixture candidato e devolve (fixture, pick) do
    maior Score Final entre os que passam DICA_CONFIG (confidence>=0.72),
    ou None se nenhum passar."""
    match_stats = MatchStatsService()
    odds_service = OddsService()

    best_fixture, best_pick = None, None

    for fixture in fixtures:
        structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
        if not structured_odds:
            continue

        last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
        last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
        if not last10_home or not last10_away:
            continue

        profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
        profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
        matchup = tpm.compare_matchup(profile_home, profile_away)
        context_data = ctx.build_context(
            last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
            None, None, fixture["league_id"],
        )

        candidates = analyze_fixture_markets(
            structured_odds, last10_home, last10_away,
            config=DICA_CONFIG, context_data=context_data, matchup_data=matchup,
        )
        picks = rank_market_candidates(candidates, config=DICA_CONFIG)
        if not picks:
            continue

        pick = next((p for p in picks if p.get("is_best_pick")), picks[0])
        if best_pick is None or pick["final_score"] > best_pick["final_score"]:
            best_fixture, best_pick = fixture, pick

    if best_pick is None:
        return None
    return best_fixture, best_pick


def _save_pick(cur, fixture: dict, pick: dict):
    stake_pct, stake_units = AISuggestionsService.calculate_stake(
        confidence=pick["confidence"], odd=pick["odd"], ev=pick["ev"], max_units=5,
    )
    reasoning = explain(pick)

    cur.execute("""
        INSERT INTO picks_free
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id,
             league_id, league_name, market, market_type, line, odd, bet_house,
             market_id, confidence, prob_real, edge, reasoning,
             stake_pct, stake_units)
        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date) DO UPDATE SET
            fixture_id   = EXCLUDED.fixture_id,
            home_team    = EXCLUDED.home_team,
            away_team    = EXCLUDED.away_team,
            home_team_id = EXCLUDED.home_team_id,
            away_team_id = EXCLUDED.away_team_id,
            league_id    = EXCLUDED.league_id,
            league_name  = EXCLUDED.league_name,
            market       = EXCLUDED.market,
            market_type  = EXCLUDED.market_type,
            line         = EXCLUDED.line,
            odd          = EXCLUDED.odd,
            bet_house    = EXCLUDED.bet_house,
            market_id    = EXCLUDED.market_id,
            confidence   = EXCLUDED.confidence,
            prob_real    = EXCLUDED.prob_real,
            edge         = EXCLUDED.edge,
            reasoning    = EXCLUDED.reasoning,
            stake_pct    = EXCLUDED.stake_pct,
            stake_units  = EXCLUDED.stake_units
    """, (
        fixture["fixture_id"], fixture["home_team"], fixture["away_team"],
        fixture["home_team_id"], fixture["away_team_id"],
        fixture["league_id"], None,
        pick["market_name"], pick["market_type"], pick["value_label"], pick["odd"], pick["best_bookmaker"],
        pick["market_id"], pick["confidence"], pick["taxa_real"], pick["edge"], reasoning,
        stake_pct, stake_units,
    ))


def run_dica_engine():
    _require_dev()

    conn = get_connection()
    cur = conn.cursor()

    if _has_today_dica(cur):
        print("[DICA_ENGINE] Já existe pick de hoje.")
        cur.close()
        conn.close()
        return

    fixtures = _fixtures_with_odds_in_range(cur)
    if not fixtures:
        print("[DICA_ENGINE] Nenhum fixture com odd na faixa hoje.")
        cur.close()
        conn.close()
        return

    print(f"[DICA_ENGINE] Avaliando {len(fixtures)} fixtures (DEV, motor deterministico)...")

    result = _best_candidate_across_fixtures(fixtures)
    if not result:
        print("[DICA_ENGINE] Nenhum candidato passou nos critérios mínimos (DICA_CONFIG).")
        cur.close()
        conn.close()
        return

    fixture, pick = result
    _save_pick(cur, fixture, pick)
    conn.commit()
    cur.close()
    conn.close()

    print(f"[DICA_ENGINE] Salvo: fixture {fixture['fixture_id']} — "
          f"{pick['market_name']} {pick['value_label']} @ {pick['odd']} "
          f"(confidence={pick['confidence']*100:.0f}%, ev={pick['ev']*100:+.1f}%)")


if __name__ == "__main__":
    run_dica_engine()
