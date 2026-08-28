from services.team_stats_reader import TeamStatsReader
from services.match_stats_service_media import MatchStatsServiceMedia


class TeamStatsAggregatorService:

    def __init__(self):
        self.reader = TeamStatsReader()
        self.match_stats = MatchStatsServiceMedia()

    ##########################################################################
    # Processa UM time
    ##########################################################################
    def process_single_team(self, team_id, league_id, season):

        print(
            f"-> Processando | Team {team_id} | Liga {league_id} | Season {season}")

        stats_list = self.match_stats.calculate_team_season_averages(
            team_id=team_id,
            league_id=league_id,
            season=season
        )

        if not stats_list:
            print("   ✖ Nenhum jogo FT encontrado\n")
            return

        for stats in stats_list:

            self.reader.upsert_team_statistics(
                team_id=team_id,
                league_id=league_id,
                season=season,
                stats=stats
            )

            print(
                f"   ✔ Salvo | {stats['context_type']} | Jogos: {stats['games_count']}"
            )

        print()

    ##########################################################################
    # Atualiza só times com fixtures recentes (padrão do pipeline)
    ##########################################################################
    def update_recent_teams_statistics(self, days=3):

        print(
            f"\n[TeamStatsAggregatorService] Atualizando times com fixtures dos últimos {days} dias...\n")

        teams = self.reader.get_teams_with_recent_fixtures(days=days)

        if not teams:
            print("[TeamStatsAggregatorService] Nenhum time com fixtures recentes.\n")
            return

        total = len(teams)
        processed = 0

        for t in teams:

            self.process_single_team(
                team_id=t["team_id"],
                league_id=t["league_id"],
                season=t["season"]
            )

            processed += 1
            print(f"Progresso: {processed}/{total}\n")

        print("\n[TeamStatsAggregatorService] Finalizado.\n")

    ##########################################################################
    # Atualiza SÓ o que ficou desatualizado (2026-08-27)
    ##########################################################################
    def update_stale_teams_statistics(self, limite: int = 0, progresso=None) -> dict:
        """Recalcula a média só dos times cuja partida é mais nova que a média.

        É o meio-termo que faltava entre reprocessar a temporada inteira
        (`update_full_season_statistics`, que APAGA a tabela) e reprocessar todo
        time que jogou nos últimos dias (`update_recent_teams_statistics`, que
        refaz a conta de quem não mudou). Ver a docstring de
        `TeamStatsReader.get_teams_with_stale_statistics`.

        `progresso(feitos, total)` é chamado a cada time · o /admin usa pra
        mostrar a barra sem precisar ler o stdout.

        Não custa requisição de API nenhuma: tudo sai do banco.
        """
        alvos = self.reader.get_teams_with_stale_statistics(limite=limite)
        total = len(alvos)
        print(f"\n[TeamStatsAggregatorService] {total} time(s) com média desatualizada.\n")

        feitos, falhas = 0, 0
        for t in alvos:
            try:
                self.process_single_team(
                    team_id=t["team_id"], league_id=t["league_id"], season=t["season"])
            except Exception as e:
                # Um time que falha não pode derrubar o lote · a média dele
                # continua velha e ele volta na próxima passada, porque o
                # critério é o estado do banco e não uma lista guardada.
                falhas += 1
                print(f"   ✖ Falha no time {t['team_id']}: {e}")
            feitos += 1
            if progresso:
                progresso(feitos, total)

        print(f"\n[TeamStatsAggregatorService] {feitos - falhas} de {total} atualizados.\n")
        return {"total": total, "feitos": feitos, "falhas": falhas}

    ##########################################################################
    # Processa seleção nacional · últimos N jogos (amistosos + Copa)
    ##########################################################################
    def process_national_team(self, team_id, season=2026, last_n=10):

        print(f"-> Seleção | Team {team_id} | Copa {season} | Últimos {last_n} jogos")

        stats_list = self.match_stats.calculate_national_team_averages(
            team_id=team_id,
            last_n=last_n
        )

        if not stats_list:
            print("   ✖ Nenhum jogo encontrado\n")
            return

        for stats in stats_list:

            self.reader.upsert_team_statistics(
                team_id=team_id,
                league_id=1,  # Copa do Mundo
                season=season,
                stats=stats
            )

            print(f"   ✔ Salvo | {stats['context_type']} | Jogos: {stats['games_count']}")

        print()

    ##########################################################################
    # Reprocessa TODOS os times (rebuild completo)
    ##########################################################################
    def update_full_season_statistics(self):

        print(
            "\n[TeamStatsAggregatorService] Reprocessando temporada completa...\n")

        self.reader.delete_all_team_statistics()

        teams = self.reader.get_all_teams()

        total = len(teams)
        processed = 0

        for t in teams:

            self.process_single_team(
                team_id=t["team_id"],
                league_id=t["league_id"],
                season=t["season"]
            )

            processed += 1
            print(f"Progresso: {processed}/{total}\n")

        print("\n[TeamStatsAggregatorService] Finalizado.\n")
