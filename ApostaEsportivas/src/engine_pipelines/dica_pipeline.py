"""Dica do Dia via motor deterministico (pick_engine) -- unico gerador de
picks_free desde 2026-07-17 (decisao do usuario de cortar IA em producao
tambem, nao so em dev). Reimplementa localmente a selecao de fixtures/
checagem de "ja rodou hoje" (nao importa de ai/dica_do_dia_pipeline.py --
esse modulo instancia Anthropic() no nivel de modulo, import indevido
custaria uma inicializacao de client sem necessidade e acopla este
pipeline ao de IA)."""
import json

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain, homologation
from services.pick_engine.ai_review import review_gate
from services.pick_engine.config import DICA_CONFIG
from services.pick_engine.staking import calculate_stake
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import ranking
from services.referee_stats_service import RefereeStatsService
from engine_pipelines.decision_log import log_decision


WC_LEAGUE_ID = 1
ODD_MIN = 1.39
ODD_MAX = 1.90
MAX_FIXTURES = 3

_LEAGUE_PRIORITY = {
    1: 1, 2: 2, 3: 3, 848: 4, 39: 5, 140: 6, 135: 7, 78: 8,
    61: 9, 94: 10, 88: 11, 13: 12, 11: 13, 71: 14, 72: 15,
}


def _has_today_dica(cur) -> bool:
    cur.execute("SELECT COUNT(*) FROM picks_free WHERE match_date = CURRENT_DATE")
    return cur.fetchone()[0] >= 1


def _today_vip_used_market_groups(cur) -> set:
    """Grupos de correlacao (ranking.correlation_group) de todo market_type
    ja usado em QUALQUER picks_vip hoje -- bloqueio GLOBAL, nao so no mesmo
    fixture: a Free (Dica do Dia) roda DEPOIS do VIP em cmd_tudo() (ver
    main.py), entao nao pode repetir pro assinante gratuito o mesmo mercado
    que ja saiu como VIP no dia, em jogo nenhum (decisao explicita do
    usuario -- antes so bloqueava (fixture_id, market_type) igual, deixando
    o mesmo mercado repetir livremente em outro jogo). correlation_group()
    agrupa "cards"/"handicap_cards" etc. como a mesma familia, pra nao
    driblar o bloqueio so trocando a estrutura da aposta sobre o mesmo dado
    bruto. Multipla/Alavancagem rodam DEPOIS da Free e mantem a regra
    propria (fixture+mercado, contra VIP e Free) -- fora de escopo aqui."""
    cur.execute("SELECT market_type FROM picks_vip WHERE match_date = CURRENT_DATE")
    return {ranking.correlation_group(r[0]) for r in cur.fetchall() if r[0]}


def _fixtures_with_odds_in_range(cur) -> list:
    """Mesma query de ai/dica_do_dia_pipeline.py::get_fixtures_with_odds_in_range,
    reimplementada aqui para nao acoplar a esse modulo (que instancia
    Anthropic() no import)."""
    cur.execute("""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.status, f.round, f.referee
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
            "match_datetime": r[7], "status": r[8], "round": r[9],
            "referee": r[10],
        }
        for r in rows
    ]
    fixtures.sort(key=lambda f: (_LEAGUE_PRIORITY.get(f["league_id"], 99), f["match_datetime"]))
    return fixtures[:MAX_FIXTURES]


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    # Fase 1.6 (2026-07-25): jogos anteriores a uma mudanca estrutural
    # marcada (troca de tecnico/elenco relevante) nao entram no historico --
    # ver teams.structural_change_date / MatchStatsService.get_structural_change_date.
    since_date = match_stats.get_structural_change_date(team_id)
    if cp.is_national_team_league(league_id):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since_date)
    return match_stats.get_all_matches_full(team_id, season, league_id, since_date=since_date)


def _best_candidate_across_fixtures(fixtures: list, used_groups: set) -> tuple | None:
    """Roda o motor pra cada fixture candidato e devolve (fixture, pick,
    data_quality_score) do maior Score Final entre os que passam DICA_CONFIG
    (confidence>=0.72), ou None se nenhum passar. Pula candidatos cujo grupo
    de correlacao de market_type ja saiu em QUALQUER picks_vip hoje
    (used_groups, bloqueio global -- ver _today_vip_used_market_groups)."""
    match_stats = MatchStatsService()
    odds_service = OddsService()
    referee_service = RefereeStatsService()

    best_fixture, best_pick, best_quality = None, None, None

    for fixture in fixtures:
        structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
        if not structured_odds:
            continue

        last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
        last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
        if not last10_home or not last10_away:
            continue

        hist_home_val = dv.validate_history(last10_home)
        hist_away_val = dv.validate_history(last10_away)
        if not hist_home_val["passed"] or not hist_away_val["passed"]:
            continue

        profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
        profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
        matchup = tpm.compare_matchup(profile_home, profile_away)
        context_data = ctx.build_context(
            last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
            None, None, fixture["league_id"], round_str=fixture.get("round"),
        )
        team_strength_data = ts.compare_team_strength(profile_home, profile_away)
        referee_stats = referee_service.get_stats(fixture.get("referee"), fixture["season"])
        league_stats = referee_service.get_league_stats(fixture["league_id"], fixture["season"])

        coverage_val = dv.validate_coverage(
            structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
            referee_stats=referee_stats, context_data=context_data,
        )
        integrity_val, outlier_info = dv.aggregate_fixture_quality_checks(last10_home, last10_away)
        quality = dv.data_quality_score(
            {"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val,
            integrity_validation=integrity_val, outlier_info=outlier_info,
        )

        candidates = analyze_fixture_markets(
            structured_odds, last10_home, last10_away,
            config=DICA_CONFIG, context_data=context_data, matchup_data=matchup,
            team_strength_data=team_strength_data, referee_stats=referee_stats,
            league_stats=league_stats,
            league_id=fixture["league_id"], data_quality_score=quality["score"],
        )
        picks = rank_market_candidates(candidates, config=DICA_CONFIG)
        log_decision("DICA_ENGINE", fixture, candidates, picks, matchup=matchup, context_data=context_data)
        picks = [p for p in picks if ranking.correlation_group(p["market_type"]) not in used_groups]
        if not picks:
            continue

        pick = next((p for p in picks if p.get("is_best_pick")), picks[0])
        if best_pick is None or pick["final_score"] > best_pick["final_score"]:
            best_fixture, best_pick, best_quality = fixture, {**pick, "data_quality_score": quality["score"]}, quality["score"]

    if best_pick is None:
        return None
    return best_fixture, best_pick, best_quality


def _save_pick(cur, fixture: dict, pick: dict, data_quality_score: float | None):
    stake_pct, stake_units = calculate_stake(
        confidence=pick["confidence"], odd=pick["odd"], ev=pick["ev"], pick_type="free",
    )
    reasoning = explain(pick)
    # Retrato do candidato no momento da escolha -- mesma logica de
    # engine_pipelines/vip_pipeline.py::_save_pick, usado depois por
    # services/pick_engine/red_analysis.py + calibration.py.
    engine_debug_data = homologation.build_score_breakdown_section(pick, data_quality_score)
    engine_debug_data["ai_review"] = pick.get("ai_review")
    engine_debug = json.dumps(
        engine_debug_data,
        default=str, ensure_ascii=False,
    )

    cur.execute("""
        INSERT INTO picks_free
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id,
             league_id, league_name, market, market_type, line, odd, bet_house,
             market_id, confidence, prob_real, edge, reasoning,
             stake_pct, stake_units, engine_debug)
        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            stake_units  = EXCLUDED.stake_units,
            engine_debug = EXCLUDED.engine_debug
    """, (
        fixture["fixture_id"], fixture["home_team"], fixture["away_team"],
        fixture["home_team_id"], fixture["away_team_id"],
        fixture["league_id"], None,
        pick["market_name"], pick["market_type"], pick["value_label"], pick["odd"], pick["best_bookmaker"],
        pick["market_id"], pick["confidence"], pick["taxa_real"], pick["edge"], reasoning,
        stake_pct, stake_units, engine_debug,
    ))


def run_dica_engine():
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

    print(f"[DICA_ENGINE] Avaliando {len(fixtures)} fixtures (motor deterministico)...")

    used_groups = _today_vip_used_market_groups(cur)
    if used_groups:
        print(f"[DICA_ENGINE] {len(used_groups)} grupo(s) de mercado ja usados no VIP hoje (bloqueio global) · bloqueados")

    result = _best_candidate_across_fixtures(fixtures, used_groups)
    if not result:
        print("[DICA_ENGINE] Nenhum candidato passou nos critérios mínimos (DICA_CONFIG).")
        cur.close()
        conn.close()
        return

    fixture, pick, quality_score = result
    reviewed = review_gate("dica").apply([pick], "dica", fixture)
    if not reviewed:
        print("[DICA_ENGINE] Pick vetado pela revisao de IA.")
        cur.close()
        conn.close()
        return
    pick = reviewed[0]
    _save_pick(cur, fixture, pick, quality_score)
    conn.commit()
    cur.close()
    conn.close()

    print(f"[DICA_ENGINE] Salvo: fixture {fixture['fixture_id']} · "
          f"{pick['market_name']} {pick['value_label']} @ {pick['odd']} "
          f"(confidence={pick['confidence']*100:.0f}%, ev={pick['ev']*100:+.1f}%)")


if __name__ == "__main__":
    run_dica_engine()
