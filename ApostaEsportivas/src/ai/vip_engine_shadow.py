"""Homologacao do motor de picks (services/pick_engine) para o VIP -- fase
de validacao antes de promover o motor pra producao (ver plano). Roda
inteiramente contra o banco DEV (DB_ENV=dev, mesmo ambiente de
engine_pipelines/*.py) -- nunca escreve em picks_vip nem em nenhuma outra
tabela de picks, so acrescenta linhas a
`ApostaEsportivas/logs/vip_engine_shadow.jsonl`. A unica leitura em PROD e'
so-leitura, sob demanda, via ai/_homologation_common.py::fetch_ai_pick_for_fixture
-- busca o pick real que a IA ja salvou pro mesmo fixture_id (os fixtures
de teste em DEV sao copias de fixtures reais do PROD com o mesmo id, via
copy_prod_history_to_dev.py), sem gerar pick novo (custaria orcamento de
API que o usuario esta evitando agora).

Cada registro do log tem as 6 secoes da homologacao: mercados avaliados,
motivo de descarte por camada, todas as linhas comparadas dentro do
mercado vencedor, composicao completa do score, explicabilidade, e
comparacao com o pick real da IA (quando existir em PROD pra esse
fixture_id -- None vira status explicito "sem_comparacao_disponivel",
nunca erro).

Uso:
    python -m ai.vip_engine_shadow
"""
import os

for _key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    _dev_val = os.getenv(f"{_key}_DEV")
    if _dev_val:
        os.environ[_key] = _dev_val
os.environ["DB_ENV"] = "dev"

from utils.db_utils import get_connection
from utils.paths import log_path
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
from ai._homologation_common import append_jsonl, fetch_ai_pick_for_fixture

_LOG_PATH = log_path("vip_engine_shadow.jsonl")


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    if cp.is_national_team_league(league_id):
        return match_stats.get_last_n_all_competitions(team_id)
    return match_stats.get_all_matches_full(team_id, season, league_id)


def _build_signals(last10_home, last10_away, home_team_id, away_team_id, league_id, round_str=None):
    profile_home = tpm.build_profile(last10_home, home_team_id)
    profile_away = tpm.build_profile(last10_away, away_team_id)
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, home_team_id, away_team_id,
        None, None, league_id, round_str=round_str,
    )
    team_strength_data = ts.compare_team_strength(profile_home, profile_away)
    return context_data, matchup, team_strength_data


def _fetch_ns_fixtures(cur) -> list:
    """Todos os fixtures NS em DEV (independente de ja ter pick_vip salvo
    -- homologacao reanalisa o mesmo fixture ao longo dos dias conforme
    odds/historico mudam, diferente de um pipeline que so processa uma
    vez). Mesmas colunas de fixtures_service.py, incluindo round
    (Prioridade 4)."""
    cur.execute("""
        SELECT fixture_id, league_id, season, home_team_id, away_team_id,
               home_team, away_team, match_datetime, round
        FROM fixtures
        WHERE status = 'NS'
        ORDER BY match_datetime ASC;
    """)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _process_fixture(
    fixture_id, league_id, season, home_team_id, away_team_id,
    home_team_name, away_team_name, match_date,
    match_stats: MatchStatsService, odds_service: OddsService, round_str=None,
) -> dict | None:
    """Roda o motor em modo debug pra 1 fixture e monta o registro de
    homologacao (secoes 1-6). Retorna None se nao houver dado suficiente
    (odds ou historico) pra analisar -- so acontece ANTES de qualquer
    analise de mercado, entao nao ha nada de "descarte de mercado" a
    reportar (a fixture inteira fica de fora, nao um mercado isolado)."""
    structured_odds = odds_service.load_odds_structured(fixture_id)
    if not structured_odds:
        print(f"[VIP_SHADOW] Fixture {fixture_id}: sem odds estruturadas, pulando.")
        return None

    last10_home = _load_history(match_stats, home_team_id, season, league_id)
    last10_away = _load_history(match_stats, away_team_id, season, league_id)

    hist_home_val = dv.validate_history(last10_home)
    hist_away_val = dv.validate_history(last10_away)
    if not hist_home_val["passed"] or not hist_away_val["passed"]:
        print(f"[VIP_SHADOW] Fixture {fixture_id}: historico insuficiente "
              f"(casa={hist_home_val['amostra']}j, fora={hist_away_val['amostra']}j), pulando.")
        return None

    context_data, matchup, team_strength_data = _build_signals(
        last10_home, last10_away, home_team_id, away_team_id, league_id, round_str=round_str,
    )

    coverage_val = dv.validate_coverage(
        structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
        context_data=context_data,
    )
    quality = dv.data_quality_score(
        {"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val,
    )

    debug_out = analyze_fixture_markets(
        structured_odds, last10_home, last10_away,
        context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
        data_quality_score=quality["score"], debug=True,
    )
    eligible, discarded = rank_all_candidates_debug(debug_out["candidates"])
    picked, excluded = select_final_picks_debug(eligible)
    engine_best = next((p for p in picked if p.get("is_best_pick")), None)

    market_report = homolog.build_market_report(
        picked, excluded, discarded, debug_out["eliminated_markets"], debug_out["entries_dropped"],
        data_quality_score=quality["score"],
    )
    ai_pick = fetch_ai_pick_for_fixture(fixture_id, "picks_vip")
    comparison = homolog.build_comparison_section(engine_best, ai_pick)

    record = homolog.build_homologation_record(
        "VIP",
        {"fixture_id": fixture_id, "home_team": home_team_name, "away_team": away_team_name, "league_id": league_id},
        market_report, comparison, data_quality_score=quality["score"],
    )
    record["match_datetime"] = match_date.isoformat() if match_date else None

    ai_label = (
        f"{ai_pick['market']} {ai_pick['line']} @ {ai_pick['odd']}" if ai_pick else "sem pick da IA em PROD"
    )
    eng_label = (
        f"{engine_best['market_name']} {engine_best['value_label']} @ {engine_best['odd']} "
        f"(conf={engine_best['confidence']*100:.0f}%)"
        if engine_best else "sem candidato aprovado"
    )
    print(f"[VIP_SHADOW] Fixture {fixture_id} ({home_team_name} x {away_team_name}): "
          f"IA={ai_label} | MOTOR={eng_label}")

    return record


def run_shadow():
    match_stats = MatchStatsService()
    odds_service = OddsService()

    conn = get_connection()  # DB_ENV=dev ja setado no import deste modulo
    cur = conn.cursor()
    ns_fixtures = _fetch_ns_fixtures(cur)
    cur.close()
    conn.close()

    print(f"[VIP_SHADOW] {len(ns_fixtures)} fixture(s) NS em DEV.")

    logged = 0
    for fx in ns_fixtures:
        try:
            record = _process_fixture(
                fx["fixture_id"], fx["league_id"], fx["season"],
                fx["home_team_id"], fx["away_team_id"],
                fx["home_team"], fx["away_team"], fx.get("match_datetime"),
                match_stats, odds_service, round_str=fx.get("round"),
            )
        except Exception as e:
            print(f"[VIP_SHADOW] Erro no fixture {fx['fixture_id']}, pulando: {e}")
            continue
        if record:
            append_jsonl(_LOG_PATH, record)
            logged += 1

    print(f"[VIP_SHADOW] {logged} registro(s) gravado(s) em {os.path.abspath(_LOG_PATH)}")


if __name__ == "__main__":
    run_shadow()
