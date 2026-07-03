import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Garante output em tempo real mesmo quando não há terminal interativo
os.environ.setdefault("PYTHONUNBUFFERED", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from utils.db_utils import get_connection


class DataCollectorMain:

    def __init__(self):
        self.status_sync = None
        self.team_sync = None
        self.fixture_collector = None
        self.standings_collector = None
        self.match_stats = None
        self.team_aggregator = None
        self.wc_teams = []

    def _get_status_sync(self):
        if self.status_sync is None:
            from collectors.fixture_status_sync_service import FixtureStatusSyncService
            self.status_sync = FixtureStatusSyncService()
        return self.status_sync

    def _get_team_sync(self):
        if self.team_sync is None:
            from collectors.team_statistics_sync_service import LeagueTeamsSyncService
            self.team_sync = LeagueTeamsSyncService()
        return self.team_sync

    def _get_fixture_collector(self):
        if self.fixture_collector is None:
            from collectors.fixture_collector_service import FixtureCollectorService
            self.fixture_collector = FixtureCollectorService()
        return self.fixture_collector

    def _get_standings_collector(self):
        if self.standings_collector is None:
            from collectors.standings_collector_service import StandingsCollectorService
            self.standings_collector = StandingsCollectorService()
        return self.standings_collector

    def _get_match_stats(self):
        if self.match_stats is None:
            from collectors.match_statistics_sync_service import MatchStatisticsSyncService
            self.match_stats = MatchStatisticsSyncService()
        return self.match_stats

    def _get_team_aggregator(self):
        if self.team_aggregator is None:
            from services.team_stats_aggregator_service import TeamStatsAggregatorService
            self.team_aggregator = TeamStatsAggregatorService()
        return self.team_aggregator

    # ---------------------------------------------------------
    # RESET — apaga todos os dados de temporada (mantém leagues)
    # ---------------------------------------------------------

    def run_reset(self):
        print("\n[RESET] Apagando todos os dados de temporada...")
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            TRUNCATE TABLE
                match_statistics,
                team_statistics,
                teams,
                fixtures,
                league_standings,
                league_analysis,
                referee_stats,
                referees,
                historical_stats,
                picks_vip,
                picks_vip,
                picks_multiplas,
                picks_free,
                odds_values,
                odds_markets,
                odds_bookmakers,
                bet_recommendations
            RESTART IDENTITY CASCADE;
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[RESET] Dados limpos. Execute run_all() para popular a nova liga.\n")

    # ---------------------------------------------------------
    # STAGES
    # ---------------------------------------------------------

    def run_stage_0(self):
        print("[STAGE 0] Atualizando status dos fixtures...")
        self._get_status_sync().process_all_fixtures()

    def run_stage_1(self):
        print("[STAGE 1] Sincronizando times por liga...")
        self._get_team_sync().sync_league_teams()

    def run_stage_2(self):
        print("[STAGE 2] Coletando fixtures...")
        fixture_collector = self._get_fixture_collector()
        fixtures = fixture_collector.collect_fixtures_today_br()
        fixture_collector.save_fixtures(fixtures)

    def run_stage_3(self):
        print("[STAGE 3] Atualizando classificação das ligas...")
        self._get_standings_collector().process_all()

    def run_stage_4(self, mode="fast", days=3, collect_wc_friendlies=True, wc_mode="fast"):
        print("[STAGE 4] Estatísticas de jogos finalizados...")

        service = self._get_match_stats()

        if mode == "full":
            print("[MODE] FULL - temporada inteira")
            service.sync_all_finished_fixtures(use_date_filter=False)

        elif mode == "custom":
            print(f"[MODE] CUSTOM - últimos {days} dias")
            service.sync_all_finished_fixtures(use_date_filter=True, days=days)

        else:
            print("[MODE] FAST - últimos 3 dias")
            service.sync_all_finished_fixtures()

        self.wc_teams = self._collect_world_cup_friendlies(wc_mode=wc_mode) if collect_wc_friendlies else []

    def _collect_world_cup_friendlies(self, season=2026, wc_mode="fast"):
        """
        Coleta jogos recentes das seleções da Copa do Mundo.
          wc_mode="fast" → padrão diário  (15 jogos por seleção)
          wc_mode="full" → nova copa      (30 jogos por seleção)
        """
        WC_LIMITS = {"fast": 15, "full": 30}
        limit = WC_LIMITS.get(wc_mode, 15)

        from collectors.world_cup_friendlies_collector import WorldCupFriendliesCollector
        print(f"\n[STAGE 4] Copa {season} | wc_mode={wc_mode} | {limit} jogos/seleção...")
        collector = WorldCupFriendliesCollector()
        teams = collector.collect_world_cup_friendlies(season=season, limit=limit)
        return teams if teams else []

    def _get_wc_teams_from_db(self, season=2026) -> list:
        """Busca times da Copa do Mundo direto da tabela teams (league_id=1)."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT team_id FROM teams WHERE league_id = 1 AND season = %s", (season,))
        teams = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return teams

    def run_stage_5(self, mode="recent", days=3, wc_last_n=15):
        print("[STAGE 5] Calculando médias agregadas...")
        aggregator = self._get_team_aggregator()

        if mode == "full":
            aggregator.update_full_season_statistics()
        else:
            aggregator.update_recent_teams_statistics(days=days)

        # Seleções da Copa: sempre busca da tabela teams (independe do Stage 4)
        # Usa últimos N jogos misturando amistosos + Copa do Mundo
        wc_teams = getattr(self, 'wc_teams', None) or self._get_wc_teams_from_db()

        if wc_teams:
            print(f"\n[STAGE 5] Médias das {len(wc_teams)} seleções da Copa (últimos {wc_last_n} jogos)...")
            for team_id in wc_teams:
                aggregator.process_national_team(
                    team_id=team_id,
                    season=2026,
                    last_n=wc_last_n
                )
            print(f"[STAGE 5] Seleções da Copa atualizadas!\n")
        else:
            print("[STAGE 5] Nenhuma seleção da Copa encontrada na tabela teams.\n")
    

    # ---------------------------------------------------------
    # PIPELINE
    # ---------------------------------------------------------

    def run_new_league(self):
        print("\n========== NOVA LIGA — RESET + COLETA COMPLETA ==========\n")
        self.run_reset()
        self.run_all()

    def run_all(self):
        print("\n========== DATA COLLECTOR ==========\n")

        self.run_stage_0()
        self.run_stage_1()
        self.run_stage_2()
        self.run_stage_3()

        # ---------------------------------------------------------
        # Ligas de clube — escolhe um:
        #self.run_stage_4(mode="fast")                # padrão diário
        #self.run_stage_4(mode="full")               # liga nova (temporada inteira)
        self.run_stage_4(mode="custom", days=7)     # personalizado

        # Copa do Mundo — adiciona wc_mode:
        # wc_mode="fast"  → padrão (15 jogos/seleção)  ← default acima
        # wc_mode="full"  → nova copa (30 jogos/seleção, primeira vez)
        #self.run_stage_4(mode="fast", wc_mode="full")   # só copa nova
        #self.run_stage_4(mode="full", wc_mode="full")   # liga nova + copa nova
        # ---------------------------------------------------------

        self.run_stage_5()

        print("\n========== DATA COLLECTOR FINALIZADO ==========\n")


# ---------------------------------------------------------
# EXECUÇÃO
# ---------------------------------------------------------

if __name__ == "__main__":
    collector = DataCollectorMain()

    if len(sys.argv) == 1:
        collector.run_all()
    else:
        stage = sys.argv[1]

        if stage == "0":
            collector.run_stage_0()

        elif stage == "1":
            collector.run_stage_1()

        elif stage == "2":
            collector.run_stage_2()

        elif stage == "3":
            collector.run_stage_3()

        elif stage == "4":
            # Ex: python atualizar_jogos.py 4 fast
            #     python atualizar_jogos.py 4 full
            #     python atualizar_jogos.py 4 custom 7
            #     python atualizar_jogos.py 4 fast wc_full   ← copa nova
            mode    = sys.argv[2] if len(sys.argv) > 2 else "fast"
            wc_mode = "full" if (len(sys.argv) > 3 and sys.argv[3] == "wc_full") else "fast"

            if mode == "full":
                collector.run_stage_4(mode="full", wc_mode=wc_mode)

            elif mode == "custom":
                days = int(sys.argv[3]) if (len(sys.argv) > 3 and sys.argv[3] != "wc_full") else 3
                collector.run_stage_4(mode="custom", days=days, wc_mode=wc_mode)

            else:
                collector.run_stage_4(mode="fast", wc_mode=wc_mode)

        elif stage == "5":
            # Ex: python atualizar_jogos.py 5
            #     python atualizar_jogos.py 5 full
            #     python atualizar_jogos.py 5 recent 3 15   <- wc_last_n=15
            mode      = sys.argv[2] if len(sys.argv) > 2 else "recent"
            days      = int(sys.argv[3]) if len(sys.argv) > 3 else 3
            wc_last_n = int(sys.argv[4]) if len(sys.argv) > 4 else 15
            collector.run_stage_5(mode=mode, days=days, wc_last_n=wc_last_n)

        elif stage == "reset":
            collector.run_reset()

        elif stage == "new_league":
            collector.run_new_league()

        else:
            print("Stage inválido. Use 0,1,2,3,4,5,reset,new_league")