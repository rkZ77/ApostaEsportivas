"""VIP via motor deterministico (pick_engine) -- unico gerador de picks_vip
desde 2026-07-17 (decisao do usuario de cortar IA em producao tambem, nao
so em dev). Espelha gerar_sugestao_vip.py + ai_suggestions_service.py na
estrutura de dados salva em picks_vip, mas sem IA: mercado/linha/confidence/
EV/probability vem do pick_engine, reasoning vem de pick_engine.explain()."""
import json
import textwrap
import traceback

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.team_stats_service import TeamStatsService
from services.standings_service import StandingsService
from services.referee_stats_service import RefereeStatsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain, homologation
from services.pick_engine.ai_review import review_gate
from services.pick_engine.config import VIP_CONFIG
from services.pick_engine.staking import calculate_stake
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import context_gate
from services.pick_engine import stats_model
from services.pick_engine import competition_rules_store
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_run, log_skip,
)
from services.engine_audit import amostra, auditar



def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    # Fase 1.6 (2026-07-25): jogos anteriores a uma mudanca estrutural
    # marcada (troca de tecnico/elenco relevante) nao entram no historico --
    # ver teams.structural_change_date / MatchStatsService.get_structural_change_date.
    since_date = match_stats.get_structural_change_date(team_id)
    # Copa de clube usa o mesmo caminho que selecao desde 2026-08-01:
    # a competicao nao acumula jogo suficiente pra sustentar analise
    # sozinha (ver competition_profile.uses_all_competitions_history).
    if cp.uses_all_competitions_history(league_id):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since_date)
    return match_stats.get_all_matches_full(team_id, season, league_id, since_date=since_date)


def _build_signals(last10_home, last10_away, home_team_id, away_team_id, league_id,
                    round_str=None, standing_home=None, standing_away=None,
                    league_table=None):
    """Contexto + perfil/matchup/team_strength (sem noticias -- exigiria
    chamada HTTP por fixture, fora de escopo nesta primeira versao).

    standing_home/standing_away (StandingsService.get_team_standing) passaram
    a ser preenchidos em 2026-08-05. Antes TODOS os pipelines chamavam
    build_context com None nos dois lugares, o que fazia context_model.
    table_pressure() devolver sempre label='desconhecido' e derrubava, em
    silencio, tres coisas que ja estavam implementadas: o termo de pressao de
    tabela no context_score, o componente de pressao no referee_model.
    game_intensity (que decide se cartoes e' mercado elegivel) e a checagem de
    fase (context_score so' suprime o bonus em mata-mata -- sem o bonus, a
    classificacao de round_phase nao mudava nada). A tabela league_standings
    ja' era coletada e o StandingsService ja' existia; so' ninguem ligava os
    dois."""
    profile_home = tpm.build_profile(last10_home, home_team_id)
    profile_away = tpm.build_profile(last10_away, away_team_id)
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, home_team_id, away_team_id,
        standing_home, standing_away, league_id, round_str=round_str,
        league_table=league_table,
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
    # A AMOSTRA (2026-08-27): quais jogos o motor leu, ate' 10 por time, com o
    # contexto do confronto (classico, jogo de volta, placar da ida). Puramente
    # ADITIVO -- nenhum calculo le esta chave; ela existe pra o "Entenda esta
    # analise" poder mostrar a amostra que DECIDIU, em vez de reconsultar o
    # banco e arriscar exibir um recorte diferente (que e' o que acontecia em
    # jogo de copa, onde o motor le todas as competicoes e a tela lia so' a
    # liga). Ver services/engine_audit/amostra.py.
    if pick.get("amostra"):
        engine_debug_data["amostra"] = pick["amostra"]
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


# AUDITORIA (2026-08-27). Duas linhas, e nenhuma no corpo da funcao: o Pre
# Live esta' congelado. O decorador abre a execucao (run_id, contagens,
# status) e o decision_log carimba esse run_id sozinho nas linhas que ja'
# gravava -- ver services/engine_audit/audit.py::auditar.
@auditar("PRE_LIVE", "vip")
def run_vip_engine():
    fixtures_service = FixturesService()
    match_stats = MatchStatsService()
    odds_service = OddsService()
    team_stats_service = TeamStatsService()
    referee_service = RefereeStatsService()
    standings_service = StandingsService()

    fixtures = fixtures_service.get_ns_without_suggestions()
    if not fixtures:
        print("[VIP_ENGINE] Nenhum fixture pendente.")
        return

    print(f"[VIP_ENGINE] Processando {len(fixtures)} fixtures (motor deterministico)...")

    conn = get_connection()
    cur = conn.cursor()
    # Regulamento de mata-mata das competicoes nao cadastradas a mao, do
    # banco pra memoria, UMA vez por rodada. Sem isto o motor devolve
    # DESCONHECIDO pro formato dessas competicoes, que e' o comportamento
    # de antes -- nada quebra, so' se sabe menos.
    competition_rules_store.carregar(cur)
    saved = 0

    for fixture in fixtures:
        try:
            structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
            if not structured_odds:
                log_skip("VIP_ENGINE", fixture, MOTIVO_SEM_ODDS)
                continue

            last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
            last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
            if not last10_home or not last10_away:
                log_skip("VIP_ENGINE", fixture, MOTIVO_SEM_HISTORICO)
                continue

            # Data Validation Engine -- roda ANTES de qualquer analise de
            # mercado; historico insuficiente de qualquer time aborta a
            # fixture inteira (mesmo padrao ja validado em vip_engine_shadow.py).
            hist_home_val = dv.validate_history(last10_home)
            hist_away_val = dv.validate_history(last10_away)
            if not hist_home_val["passed"] or not hist_away_val["passed"]:
                log_skip("VIP_ENGINE", fixture, MOTIVO_HISTORICO_REPROVADO)
                continue

            standing_home, standing_away = standings_service.get_for_fixture(
                fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], fixture["season"])
            # A tabela INTEIRA, nao so' as duas linhas: e' o que permite medir
            # distancia ate a fronteira que importa (ver competitive_pressure).
            league_table = standings_service.get_league_table(
                fixture["league_id"], fixture["season"])
            context_data, matchup, team_strength_data = _build_signals(
                last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], round_str=fixture.get("round"),
                standing_home=standing_home, standing_away=standing_away,
                league_table=league_table,
            )
            referee_stats = referee_service.get_stats(fixture.get("referee"), fixture["season"])
            league_stats = referee_service.get_league_stats(fixture["league_id"], fixture["season"])
            league_baseline = team_stats_service.get_league_baseline(
                fixture["league_id"], fixture["season"])

            coverage_val = dv.validate_coverage(
                structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
                standings_home=standing_home, standings_away=standing_away,
                referee_stats=referee_stats, context_data=context_data,
            )
            integrity_val, outlier_info = dv.aggregate_fixture_quality_checks(
                last10_home, last10_away,
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"])
            quality = dv.data_quality_score(
                {"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val,
                integrity_validation=integrity_val, outlier_info=outlier_info,
            )

            team_stats_home, team_stats_away = team_stats_service.get_for_fixture(
                fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], fixture["season"])

            # Contexto da partida: mata-mata, ida/volta, placar da ida,
            # agregado e rivalidade medida no confronto direto. Alimenta o
            # context_gate, que barra Under contradizendo o que o jogo vai ser.
            conv_cartoes = stats_model.expected_value_convergence(
                last10_home, last10_away, "cards", "total",
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
                league_baseline=league_baseline,
            )
            match_context = context_gate.build_for_fixture(
                match_stats, fixture, conv_cartoes, league_table=league_table)

            # Lista que o motor preenche com TODA linha e TODA familia que ele
            # viu, inclusive as que morreram antes de virar candidato. Vai
            # inteira pro log de decisao -- e' o que faz a tela do admin
            # mostrar o mercado que perdeu, e nao so' o que venceu.
            rastro: list = []
            candidates = analyze_fixture_markets(
                structured_odds, last10_home, last10_away,
                context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
                referee_stats=referee_stats, league_stats=league_stats,
                league_id=fixture["league_id"], data_quality_score=quality["score"],
                match_context=match_context,
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
            config=VIP_CONFIG,
            rastro=rastro,
            )
            picks = rank_market_candidates(candidates, config=VIP_CONFIG)
            log_decision("VIP_ENGINE", fixture, candidates, picks, matchup=matchup,
                          context_data=context_data, rastro=rastro)
            if not picks:
                continue

            best = next((p for p in picks if p.get("is_best_pick")), picks[0])
            best = {**best, "data_quality_score": quality["score"],
                    "amostra": amostra.build(
                        home_team_id=fixture["home_team_id"],
                        away_team_id=fixture["away_team_id"],
                        historico_home=last10_home, historico_away=last10_away,
                        home_team=fixture.get("home_team"),
                        away_team=fixture.get("away_team"),
                        match_context=match_context)}
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
            # Stack trace completo: sem ele, "pulou 8 fixtures" nao diz
            # ONDE quebrou -- e o caminho de gravacao mudou em 2026-08-01.
            print(f"[VIP_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue

    cur.close()
    conn.close()
    print(f"[VIP_ENGINE] {saved} picks salvos.")


if __name__ == "__main__":
    run_vip_engine()
