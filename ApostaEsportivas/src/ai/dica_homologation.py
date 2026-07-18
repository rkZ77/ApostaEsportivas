"""Homologacao do motor de picks (services/pick_engine) pra Dica do Dia
(Free) -- fase de validacao antes de promover o motor pra producao (ver
plano). Mesmo padrao de vip_engine_shadow.py: roda inteiramente contra
DEV (DB_ENV=dev), so-leitura, nunca escreve em picks_free; a comparacao
com o pick real da IA (secao 6) abre uma conexao PROD separada e
so-leitura, sob demanda, via ai/_homologation_common.py.

Reimplementa localmente a selecao de fixtures/faixa de odd (nao importa
de ai/dica_do_dia_pipeline.py -- esse modulo instancia Anthropic() no
nivel de modulo, import indevido custaria uma inicializacao de client sem
necessidade), espelhando engine_pipelines/dica_pipeline.py::
_fixtures_with_odds_in_range -- mesma faixa de odd (1.30-1.80), mesma
prioridade de liga, mesmo limite de 3 fixtures/dia -- mas gera um
registro de homologacao POR FIXTURE avaliado (nao so o vencedor final),
pra a homologacao mostrar a decisao completa, nao so o resultado.

Uso:
    python -m ai.dica_homologation
"""
import os

for _key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    _dev_val = os.getenv(f"{_key}_DEV")
    if _dev_val:
        os.environ[_key] = _dev_val
os.environ["DB_ENV"] = "dev"

from utils.db_utils import get_connection
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.pick_engine import (
    analyze_fixture_markets, rank_all_candidates_debug, select_final_picks_debug,
)
from services.pick_engine.config import DICA_CONFIG
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import homologation as homolog
from ai._homologation_common import append_jsonl, fetch_ai_pick_for_fixture

ODD_MIN = 1.30
ODD_MAX = 1.80
MAX_FIXTURES = 3

_LEAGUE_PRIORITY = {
    1: 1, 2: 2, 3: 3, 848: 4, 39: 5, 140: 6, 135: 7, 78: 8,
    61: 9, 94: 10, 88: 11, 13: 12, 11: 13, 71: 14, 72: 15,
}

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "dica_homologation.jsonl")


def _fixtures_with_odds_in_range(cur) -> list:
    """Mesma query de engine_pipelines/dica_pipeline.py::_fixtures_with_odds_in_range,
    reimplementada aqui pra nao acoplar (mesmo motivo do arquivo original)."""
    cur.execute("""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.status, f.round
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE DATE(f.match_datetime) = CURRENT_DATE
          AND f.status IN ('NS', 'TBD', 'LIVE')
          AND ov.odd_value BETWEEN %s AND %s
    """, (ODD_MIN, ODD_MAX))
    cols = [d.name for d in cur.description]
    fixtures = [dict(zip(cols, row)) for row in cur.fetchall()]
    fixtures.sort(key=lambda f: (_LEAGUE_PRIORITY.get(f["league_id"], 99), f["match_datetime"]))
    return fixtures[:MAX_FIXTURES]


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    if cp.is_national_team_league(league_id):
        return match_stats.get_last_n_all_competitions(team_id)
    return match_stats.get_all_matches_full(team_id, season, league_id)


def _process_fixture(fixture: dict, match_stats: MatchStatsService, odds_service: OddsService) -> dict | None:
    fixture_id = fixture["fixture_id"]
    structured_odds = odds_service.load_odds_structured(fixture_id)
    if not structured_odds:
        print(f"[DICA_HOMOLOG] Fixture {fixture_id}: sem odds estruturadas, pulando.")
        return None

    last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
    last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])

    hist_home_val = dv.validate_history(last10_home)
    hist_away_val = dv.validate_history(last10_away)
    if not hist_home_val["passed"] or not hist_away_val["passed"]:
        print(f"[DICA_HOMOLOG] Fixture {fixture_id}: historico insuficiente, pulando.")
        return None

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
        config=DICA_CONFIG, context_data=context_data, matchup_data=matchup,
        team_strength_data=team_strength_data, data_quality_score=quality["score"], debug=True,
    )
    eligible, discarded = rank_all_candidates_debug(debug_out["candidates"], config=DICA_CONFIG)
    picked, excluded = select_final_picks_debug(eligible)
    engine_best = next((p for p in picked if p.get("is_best_pick")), None)

    market_report = homolog.build_market_report(
        picked, excluded, discarded, debug_out["eliminated_markets"], debug_out["entries_dropped"],
        data_quality_score=quality["score"],
    )
    ai_pick = fetch_ai_pick_for_fixture(fixture_id, "picks_free")
    comparison = homolog.build_comparison_section(engine_best, ai_pick)

    record = homolog.build_homologation_record(
        "Free",
        {"fixture_id": fixture_id, "home_team": fixture["home_team"], "away_team": fixture["away_team"],
         "league_id": fixture["league_id"]},
        market_report, comparison, data_quality_score=quality["score"],
    )

    eng_label = (
        f"{engine_best['market_name']} {engine_best['value_label']} @ {engine_best['odd']} "
        f"(conf={engine_best['confidence']*100:.0f}%)" if engine_best else "sem candidato aprovado"
    )
    ai_label = f"{ai_pick['market']} {ai_pick['line']} @ {ai_pick['odd']}" if ai_pick else "sem pick da IA em PROD"
    print(f"[DICA_HOMOLOG] Fixture {fixture_id} ({fixture['home_team']} x {fixture['away_team']}): "
          f"IA={ai_label} | MOTOR={eng_label}")
    return record


def run_homologation():
    conn = get_connection()
    cur = conn.cursor()
    fixtures = _fixtures_with_odds_in_range(cur)
    cur.close()
    conn.close()

    print(f"[DICA_HOMOLOG] {len(fixtures)} fixture(s) candidatos (odd {ODD_MIN}-{ODD_MAX}) em DEV.")

    match_stats = MatchStatsService()
    odds_service = OddsService()
    logged = 0
    for fixture in fixtures:
        try:
            record = _process_fixture(fixture, match_stats, odds_service)
        except Exception as e:
            print(f"[DICA_HOMOLOG] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            continue
        if record:
            append_jsonl(_LOG_PATH, record)
            logged += 1

    print(f"[DICA_HOMOLOG] {logged} registro(s) gravado(s) em {os.path.abspath(_LOG_PATH)}")


if __name__ == "__main__":
    run_homologation()
