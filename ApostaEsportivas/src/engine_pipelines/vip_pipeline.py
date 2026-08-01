"""VIP via motor deterministico (pick_engine) -- unico gerador de picks_vip
desde 2026-07-17 (decisao do usuario de cortar IA em producao tambem, nao
so em dev). Espelha gerar_sugestao_vip.py + ai_suggestions_service.py na
estrutura de dados salva em picks_vip, mas sem IA: mercado/linha/confidence/
EV/probability vem do pick_engine, reasoning vem de pick_engine.explain()."""
import json

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.standings_service import StandingsService
from services.referee_stats_service import RefereeStatsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain, homologation
from services.pick_engine.ai_review import review_gate
from services.pick_engine.staking import calculate_stake
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from engine_pipelines.decision_log import log_decision



def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    # Fase 1.6 (2026-07-25): jogos anteriores a uma mudanca estrutural
    # marcada (troca de tecnico/elenco relevante) nao entram no historico --
    # ver teams.structural_change_date / MatchStatsService.get_structural_change_date.
    since_date = match_stats.get_structural_change_date(team_id)
    if cp.is_national_team_league(league_id):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since_date)
    return match_stats.get_all_matches_full(team_id, season, league_id, since_date=since_date)


def _build_signals(last10_home, last10_away, home_team_id, away_team_id, league_id, round_str=None):
    """Contexto + perfil/matchup/team_strength (sem noticias -- exigiria
    chamada HTTP por fixture, fora de escopo nesta primeira versao)."""
    profile_home = tpm.build_profile(last10_home, home_team_id)
    profile_away = tpm.build_profile(last10_away, away_team_id)
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, home_team_id, away_team_id,
        None, None, league_id, round_str=round_str,
    )
    team_strength_data = ts.compare_team_strength(profile_home, profile_away)
    return context_data, matchup, team_strength_data


def _save_pick(cur, fixture: dict, pick: dict, data_quality_score: float | None) -> bool:
    stake_pct, stake_units = calculate_stake(
        confidence=pick["confidence"], odd=pick["odd"], ev=pick["ev"], pick_type="vip",
    )
    reasoning = explain(pick)
    # Retrato do candidato no momento da escolha (variancia/model-fit/edge/
    # confidence) -- usado depois por services/pick_engine/red_analysis.py
    # pra distinguir, se este pick der RED, erro real de evento imprevisivel
    # antes de contar contra a calibracao (services/pick_engine/calibration.py).
    engine_debug_data = homologation.build_score_breakdown_section(pick, data_quality_score)
    engine_debug_data["ai_review"] = pick.get("ai_review")
    engine_debug = json.dumps(
        engine_debug_data,
        default=str, ensure_ascii=False,
    )

    cur.execute("""
        INSERT INTO picks_vip (
            fixture_id, match_date,
            home_team_id, away_team_id,
            home_team_name, away_team_name,
            market, line, odd, bet_house,
            market_type, market_id,
            confidence, ev, probability, reasoning,
            stake_pct, stake_units, engine_debug,
            created_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT (fixture_id) DO NOTHING
    """, (
        fixture["fixture_id"], fixture["match_datetime"].date(),
        fixture["home_team_id"], fixture["away_team_id"],
        fixture["home_team"], fixture["away_team"],
        pick["market_name"], pick["value_label"], pick["odd"], pick["best_bookmaker"],
        pick["market_type"], pick["market_id"],
        pick["confidence"], pick["ev"], pick["taxa_real"], reasoning,
        stake_pct, stake_units, engine_debug,
    ))
    return cur.rowcount > 0


def run_vip_engine():
    fixtures_service = FixturesService()
    match_stats = MatchStatsService()
    odds_service = OddsService()
    referee_service = RefereeStatsService()

    fixtures = fixtures_service.get_ns_without_suggestions()
    if not fixtures:
        print("[VIP_ENGINE] Nenhum fixture pendente.")
        return

    print(f"[VIP_ENGINE] Processando {len(fixtures)} fixtures (motor deterministico)...")

    conn = get_connection()
    cur = conn.cursor()
    saved = 0

    for fixture in fixtures:
        try:
            structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
            if not structured_odds:
                continue

            last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
            last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
            if not last10_home or not last10_away:
                continue

            # Data Validation Engine -- roda ANTES de qualquer analise de
            # mercado; historico insuficiente de qualquer time aborta a
            # fixture inteira (mesmo padrao ja validado em vip_engine_shadow.py).
            hist_home_val = dv.validate_history(last10_home)
            hist_away_val = dv.validate_history(last10_away)
            if not hist_home_val["passed"] or not hist_away_val["passed"]:
                continue

            context_data, matchup, team_strength_data = _build_signals(
                last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], round_str=fixture.get("round"),
            )
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
                context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
                referee_stats=referee_stats, league_stats=league_stats,
                league_id=fixture["league_id"], data_quality_score=quality["score"],
            )
            picks = rank_market_candidates(candidates)
            log_decision("VIP_ENGINE", fixture, candidates, picks, matchup=matchup, context_data=context_data)
            if not picks:
                continue

            best = next((p for p in picks if p.get("is_best_pick")), picks[0])
            best = {**best, "data_quality_score": quality["score"]}
            reviewed = review_gate("vip").apply([best], "vip", fixture)
            if not reviewed:
                continue
            best = reviewed[0]
            if _save_pick(cur, fixture, best, quality["score"]):
                conn.commit()
                saved += 1
                print(f"[VIP_ENGINE] Fixture {fixture['fixture_id']}: "
                      f"{best['market_name']} {best['value_label']} @ {best['odd']} "
                      f"(confidence={best['confidence']*100:.0f}%, ev={best['ev']*100:+.1f}%)")
            else:
                conn.rollback()

        except Exception as e:
            conn.rollback()
            print(f"[VIP_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            continue

    cur.close()
    conn.close()
    print(f"[VIP_ENGINE] {saved} picks salvos.")


if __name__ == "__main__":
    run_vip_engine()
