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
        self.history_backfill = None
        # (self.wc_teams removido junto com a coleta de amistosos da Copa)

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

    def _get_history_backfill(self):
        if self.history_backfill is None:
            from collectors.team_history_backfill_service import TeamHistoryBackfillService
            self.history_backfill = TeamHistoryBackfillService()
        return self.history_backfill

    # ---------------------------------------------------------
    # RESET · apaga todos os dados de temporada (mantém leagues)
    # ---------------------------------------------------------

    def run_reset(self):
        """Limpa dados de COLETA. NUNCA toca em pick.

        REGRA DO USUARIO (2026-08-01): historico de pick nao se apaga, nunca.
        Ate aqui as tabelas de pick estavam nesta lista -- entao
        `python atualizar_jogos.py new_league`, o comando obvio pra cadastrar
        liga nova, apagava picks_vip/picks_free/picks_multiplas. Com CASCADE,
        levava junto picks_ledger e user_followed_picks.

        A lista tinha ainda dois defeitos que reforcam que ninguem revisava
        isso: picks_vip aparecia DUAS vezes e picks_alavancagem nao aparecia
        -- os mesmos dois erros ja corrigidos uma vez antes e perdidos num
        revert.

        Coleta se recupera rodando o collector de novo; pick resolvido nao
        volta, e ele e' a base de calibracao do motor (ai_performance_service
        faz JOIN em match_statistics pra derivar hit-rate real). Se algum dia
        precisar mesmo zerar pick, que seja um comando separado e explicito,
        nao efeito colateral de "cadastrar liga nova".
        """
        print("\n[RESET] Apagando dados de coleta (picks preservados)...")
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

    # A coleta de amistosos das selecoes da Copa foi REMOVIDA em 2026-08-01.
    # Toda rodada diaria buscava 15 jogos recentes de cada uma das 48
    # selecoes, com uma chamada de estatistica por jogo: 48 x 16 = ~768
    # requisicoes/dia pra alimentar competicao encerrada. Com a cota da
    # API-Football estourada por isso, a coleta de jogos e de ODDS das ligas
    # ATIVAS parava de rodar -- o motor ficava sem o insumo do produto real.
    # A liga 1 continua em `leagues` e os 104 jogos ja coletados continuam
    # em match_statistics: 77% do ledger de picks depende deles pra
    # calibracao (ai_performance_service faz JOIN ali).
    def run_stage_4(self, mode="fast", days=3):
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


    def run_stage_5(self, mode="recent", days=3):
        print("[STAGE 5] Calculando medias agregadas...")
        aggregator = self._get_team_aggregator()
        if mode == "full":
            aggregator.update_full_season_statistics()
        else:
            aggregator.update_recent_teams_statistics(days=days)

    # POR QUE ISTO NAO E' A COLETA DE AMISTOSOS DA COPA DE NOVO
    # ---------------------------------------------------------
    # A semelhanca e' real: os dois pedem "ultimos 15 jogos deste time" e uma
    # folha de estatistica por jogo. O que estourou a cota naquela vez foi o
    # gatilho, nao o formato -- ela rodava para as 48 selecoes TODO DIA, tivesse
    # ou nao dado faltando, ~768 requisicoes diarias.
    #
    # Aqui o gatilho e' a carencia medida: so' entra o time que joga HOJE e tem
    # menos de MIN_JOGOS_PADRAO jogos no banco, e o jogo ja gravado e' pulado
    # pelo mesmo filtro do Stage 4. Dia sem time carente custa ZERO requisicao
    # (nem a listagem e' pedida), e o teto corta a rodada antes de a coleta de
    # odds ficar sem cota.
    def run_stage_6(self):
        print("[STAGE 6] Historico por time (quem esta abaixo do minimo)...")
        self._get_history_backfill().run()


    # ---------------------------------------------------------
    # PIPELINE
    # ---------------------------------------------------------

    def run_league(self, league_id: int, com_historico: bool = True):
        """Coleta COMPLETA de UMA liga, sem tocar no resto do banco.

        E' o que `new_league` deveria ter sido. Aquele comando faz TRUNCATE em
        match_statistics/teams/fixtures/standings e recoleta tudo: perde a base
        historica inteira (que sustenta a calibracao do motor) e gasta uma
        montanha de requisicao pra recuperar o que ja' existia. Aqui e' upsert,
        escopado na liga pedida.

        A ordem nao e' opcional. FixtureCollectorService filtra por
        `SELECT team_id FROM teams`, entao liga sem time cadastrado nao coleta
        jogo nenhum, por mais que a API tenha -- foi exatamente o estado da
        Sul-Americana em 2026-08-11: cadastrada em `leagues`, 56 times na API,
        zero no banco, zero jogos.

        Custo em requisicao: 1 (times) + 1 por data da janela (jogos) + 1 por
        jogo ja finalizado da temporada (estatistica). O ultimo termo e' o que
        pesa, e e' o que da' base pro motor analisar a liga.

        `com_historico=False` pula exatamente esse termo. Serve pra liga cuja
        temporada ainda nao comecou: nao ha jogo finalizado pra buscar, entao a
        varredura so' gastaria a listagem e voltaria de maos vazias. Quem marca
        isso e' o admin no cadastro (leagues.temporada_iniciada).
        """
        print(f"\n========== COLETA DA LIGA {league_id} ==========\n")
        print("[1/4] Times da liga...")
        self._get_team_sync().sync_league_teams(apenas_liga=league_id)

        print("[2/4] Jogos da janela...")
        self.run_stage_2()

        if com_historico:
            print("[3/4] Estatistica dos jogos ja finalizados (temporada inteira)...")
            self._get_match_stats().sync_all_finished_fixtures(
                use_date_filter=False, apenas_liga=league_id)

            print("[4/4] Medias agregadas por time...")
            self.run_stage_5(mode="full")
        else:
            print("[3/4] Temporada marcada como NAO INICIADA, pulando o historico.")
            print("[4/4] Nada pra agregar sem jogo finalizado.")

        print(f"\n========== LIGA {league_id} COLETADA ==========\n")

    def run_new_league(self):
        print("\n========== NOVA LIGA · RESET + COLETA COMPLETA ==========\n")
        self.run_reset()
        self.run_all(mode="full")

    def run_all(self, mode=None, days=None):
        """
        mode/days podem ser passados explicitamente (ex: run_new_league)
        ou controlados via variável de ambiente, pra permitir um backfill pontual
        sem editar este arquivo (e sem risco de esquecer o "full" ligado depois):
          ATUALIZAR_JOGOS_MODE=custom (padrão, diário) → últimos ATUALIZAR_JOGOS_DAYS dias (7)
          ATUALIZAR_JOGOS_MODE=fast                    → últimos 3 dias (default do serviço)
          ATUALIZAR_JOGOS_MODE=full                    → temporada inteira (liga nova)

        Ex. backfill pontual sem editar código:
          ATUALIZAR_JOGOS_MODE=full python atualizar_jogos.py
        """
        print("\n========== DATA COLLECTOR ==========\n")

        self.run_stage_0()
        self.run_stage_1()
        self.run_stage_2()
        self.run_stage_3()

        mode = mode or os.getenv("ATUALIZAR_JOGOS_MODE", "custom")
        days = days if days is not None else int(os.getenv("ATUALIZAR_JOGOS_DAYS", "7"))

        self.run_stage_4(mode=mode, days=days)
        # ANTES do 5 de proposito: o agregador le match_statistics, entao o
        # jogo que o backfill acabou de gravar so' entra em team_statistics
        # (e no modelo Poisson que le dali) se ja estiver no banco quando ele
        # rodar. Invertendo a ordem, o dado ficaria um dia atrasado.
        self.run_stage_6()
        self.run_stage_5(mode="full" if mode == "full" else "recent", days=days)

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
            mode    = sys.argv[2] if len(sys.argv) > 2 else "fast"

            if mode == "full":
                collector.run_stage_4(mode="full")

            elif mode == "custom":
                days = int(sys.argv[3]) if (len(sys.argv) > 3 and True) else 3
                collector.run_stage_4(mode="custom", days=days)

            else:
                collector.run_stage_4(mode="fast")

        elif stage == "5":
            # Ex: python atualizar_jogos.py 5
            #     python atualizar_jogos.py 5 full
            mode      = sys.argv[2] if len(sys.argv) > 2 else "recent"
            days      = int(sys.argv[3]) if len(sys.argv) > 3 else 3
            collector.run_stage_5(mode=mode, days=days)

        elif stage == "6":
            # Ex: python atualizar_jogos.py 6
            #     python atualizar_jogos.py 6 10 60   (min_jogos, teto de requisicoes)
            from collectors.team_history_backfill_service import (
                TeamHistoryBackfillService, MIN_JOGOS_PADRAO, TETO_REQUISICOES_PADRAO,
            )
            min_jogos = int(sys.argv[2]) if len(sys.argv) > 2 else MIN_JOGOS_PADRAO
            teto = int(sys.argv[3]) if len(sys.argv) > 3 else TETO_REQUISICOES_PADRAO
            TeamHistoryBackfillService(min_jogos=min_jogos, teto_requisicoes=teto).run()

        elif stage == "liga":
            # Ex: python atualizar_jogos.py liga 11
            # Coleta completa de UMA liga, sem TRUNCATE. E' o que o botao
            # "Coletar" do /admin dispara.
            # Ex: python atualizar_jogos.py liga 11
            #     python atualizar_jogos.py liga 11 leve   (sem o historico)
            if len(sys.argv) < 3:
                print("Uso: python atualizar_jogos.py liga <league_id> [leve]")
                sys.exit(2)
            leve = len(sys.argv) > 3 and sys.argv[3] == "leve"
            collector.run_league(int(sys.argv[2]), com_historico=not leve)

        elif stage == "reset":
            collector.run_reset()

        elif stage == "new_league":
            collector.run_new_league()

        else:
            print("Stage inválido. Use 0,1,2,3,4,5,6,liga <id>,reset,new_league")