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
