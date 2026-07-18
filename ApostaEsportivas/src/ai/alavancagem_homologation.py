"""Homologacao do motor de picks (services/pick_engine) pra Alavancagem --
fase de validacao antes de promover o motor pra producao (ver plano).
Mesmo padrao de vip_engine_shadow.py: roda inteiramente contra DEV
(DB_ENV=dev), so-leitura, nunca escreve em picks_alavancagem; a
comparacao com o combo real da IA (secao 6) abre uma conexao PROD
separada e so-leitura, sob demanda, via ai/_homologation_common.py.

Reimplementa localmente a busca de fixtures da Copa (mesmo motivo de nao
importar ai/alavancagem_pipeline.py -- instancia Anthropic() no nivel de
modulo), espelhando engine_pipelines/alavancagem_pipeline.py::
_gather_leg_candidates + _find_combo -- mesmo algoritmo guloso: so
fixtures da Copa (WC_LEAGUE_ID=1), filtro extra de odd individual
(1.05-1.65) DEPOIS do motor ja ter escolhido a perna (3a camada de
rejeicao, especifica desta pipeline), pernas podem ser do mesmo fixture
ou de fixtures diferentes, tenta simples -> dupla -> tripla ate bater
[1.45, 1.55] de odd combinada, rejeita combo com todas as pernas do
mesmo market_type.

Uso:
    python -m ai.alavancagem_homologation
"""
import os
import itertools

for _key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    _dev_val = os.getenv(f"{_key}_DEV")
    if _dev_val:
        os.environ[_key] = _dev_val
os.environ["DB_ENV"] = "dev"

from datetime import datetime
from utils.db_utils import get_connection
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.pick_engine import (
    analyze_fixture_markets, rank_all_candidates_debug, select_final_picks_debug,
)
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import homologation as homolog
from ai._homologation_common import append_jsonl, fetch_ai_pick_for_fixture, fetch_ai_legs

WC_LEAGUE_ID = 1
ODD_COMBINED_MIN = 1.45
ODD_COMBINED_MAX = 1.55
ODD_INDIVIDUAL_MIN = 1.05
ODD_INDIVIDUAL_MAX = 1.65
MAX_FIXTURES = 15
MAX_CANDIDATES_FOR_COMBO = 12

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "alavancagem_homologation.jsonl")


def _wc_fixtures_with_odds(cur) -> list:
    cur.execute("""
        SELECT DISTINCT f.fixture_id, f.home_team_id, f.away_team_id,
               f.home_team, f.away_team, f.season, f.match_datetime, f.league_id, f.round
        FROM fixtures f
        INNER JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE f.league_id = %s
          AND f.match_datetime::date = CURRENT_DATE
          AND f.status = 'NS'
          AND ov.odd_value BETWEEN %s AND %s
        ORDER BY f.match_datetime
        LIMIT %s
    """, (WC_LEAGUE_ID, ODD_INDIVIDUAL_MIN, ODD_INDIVIDUAL_MAX, MAX_FIXTURES))
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    if cp.is_national_team_league(league_id):
        return match_stats.get_last_n_all_competitions(team_id)
    return match_stats.get_all_matches_full(team_id, season, league_id)


def _fetch_latest_ai_combo(table: str) -> list:
    all_legs = fetch_ai_legs(table)
    if not all_legs:
        return []
    latest_id = max(all_legs, key=lambda leg: leg.get("created_at") or "")["source_id"]
    return [leg for leg in all_legs if leg["source_id"] == latest_id]


def _process_fixture(fixture: dict, match_stats: MatchStatsService, odds_service: OddsService,
                      debug_by_fixture: dict, legs_out: list) -> None:
    fixture_id = fixture["fixture_id"]
    structured_odds = odds_service.load_odds_structured(fixture_id)
    if not structured_odds:
        print(f"[ALAVANCAGEM_HOMOLOG] Fixture {fixture_id}: sem odds estruturadas, pulando.")
        return

    last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
    last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])

    hist_home_val = dv.validate_history(last10_home)
    hist_away_val = dv.validate_history(last10_away)
    if not hist_home_val["passed"] or not hist_away_val["passed"]:
        print(f"[ALAVANCAGEM_HOMOLOG] Fixture {fixture_id}: historico insuficiente, pulando.")
        return

    profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
    profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
        None, None, fixture["league_id"], round_str=fixture.get("round"),
    )
    team_strength_data = ts.compare_team_strength(profile_home, profile_away)

    coverage_val = dv.validate_coverage(
        structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
        context_data=context_data,
    )
    quality = dv.data_quality_score({"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val)

    debug_out = analyze_fixture_markets(
        structured_odds, last10_home, last10_away,
        context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
        data_quality_score=quality["score"], debug=True,
    )
    debug_by_fixture[fixture_id] = debug_out
    eligible, discarded = rank_all_candidates_debug(debug_out["candidates"])
    picked, excluded = select_final_picks_debug(eligible)

    market_report = homolog.build_market_report(
        picked, excluded, discarded, debug_out["eliminated_markets"], debug_out["entries_dropped"],
        data_quality_score=quality["score"],
    )
    ai_pick = fetch_ai_pick_for_fixture(fixture_id, "picks_alavancagem")
    engine_best = next((p for p in picked if p.get("is_best_pick")), None)
    comparison = homolog.build_comparison_section(engine_best, ai_pick)
    record = homolog.build_homologation_record(
        "Alavancagem",
        {"fixture_id": fixture_id, "home_team": fixture["home_team"], "away_team": fixture["away_team"],
         "league_id": fixture["league_id"]},
        market_report, comparison, data_quality_score=quality["score"],
    )
    append_jsonl(_LOG_PATH, record)

    for p in picked:
        # Filtro extra pos-motor (3a camada de rejeicao, especifica desta
        # pipeline -- ver docstring do modulo): so entram no pool de combo
        # pernas com odd individual na faixa exigida.
        if not (ODD_INDIVIDUAL_MIN <= p["odd"] <= ODD_INDIVIDUAL_MAX):
            continue
        p["_fixture"] = fixture
        legs_out.append(p)


def _find_combo(legs: list):
    pool = sorted(legs, key=lambda p: p["final_score"], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]
    for combo_size in (1, 2, 3):
        best = None
        for combo in itertools.combinations(pool, combo_size):
            market_types = {p["market_type"] for p in combo}
            if combo_size > 1 and len(market_types) == 1:
                continue
            odd_combined = round(1.0, 4)
            for p in combo:
                odd_combined *= p["odd"]
            odd_combined = round(odd_combined, 4)
            if not (ODD_COMBINED_MIN <= odd_combined <= ODD_COMBINED_MAX):
                continue
            confidence_media = round(sum(p["confidence"] for p in combo) / len(combo), 4)
            if best is None or confidence_media > best[1]:
                best = (combo, confidence_media, odd_combined)
        if best:
            return best
    return None


def run_homologation():
    conn = get_connection()
    cur = conn.cursor()
    fixtures = _wc_fixtures_with_odds(cur)
    cur.close()
    conn.close()

    print(f"[ALAVANCAGEM_HOMOLOG] {len(fixtures)} fixture(s) da Copa com odd na faixa individual em DEV.")

    match_stats = MatchStatsService()
    odds_service = OddsService()
    debug_by_fixture, legs = {}, []
    for fixture in fixtures:
        try:
            _process_fixture(fixture, match_stats, odds_service, debug_by_fixture, legs)
        except Exception as e:
            print(f"[ALAVANCAGEM_HOMOLOG] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            continue

    result = _find_combo(legs)
    old_combo = _fetch_latest_ai_combo("picks_alavancagem")
    engine_combo = list(result[0]) if result else []
    comparison = homolog.build_combo_comparison_section(engine_combo, old_combo, debug_by_fixture)

    combo_record = {
        "record_type": "combo",
        "pick_type": "Alavancagem",
        "logged_at": datetime.now().isoformat(),
        "combo_encontrado": result is not None,
        "confidence_media": result[1] if result else None,
        "odd_combined": result[2] if result else None,
        "pernas": [
            {"fixture_id": p["_fixture"]["fixture_id"], "market_type": p["market_type"], "value_label": p["value_label"]}
            for p in engine_combo
        ],
        "comparacao_ia": comparison,
    }
    append_jsonl(_LOG_PATH, combo_record)

    if result:
        combo, confidence_media, odd_combined = result
        pernas = " + ".join(f"{p['_fixture']['home_team']} x {p['_fixture']['away_team']} ({p['market_name']} {p['value_label']})" for p in combo)
        print(f"[ALAVANCAGEM_HOMOLOG] Combo: {pernas} | odd_combined={odd_combined} | confidence_media={confidence_media}")
    else:
        print("[ALAVANCAGEM_HOMOLOG] Nenhuma combinacao bateu a faixa de odd combinada.")
    print(f"[ALAVANCAGEM_HOMOLOG] registros gravados em {os.path.abspath(_LOG_PATH)}")


if __name__ == "__main__":
    run_homologation()
