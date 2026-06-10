from utils.db_utils import get_connection


class MatchStatsServiceMedia:

    def __init__(self):
        self.db = get_connection

    ##########################################################################
    # BUSCA TODOS OS JOGOS FINALIZADOS (FT) DO TIME NA TEMPORADA
    ##########################################################################
    def get_team_games_stats_in_season(self, team_id, league_id, season):

        conn = self.db()
        cur = conn.cursor()

        query = """
            SELECT *
            FROM match_statistics
            WHERE league_id = %s
              AND season = %s
              AND status = 'FT'
              AND (home_team_id = %s OR away_team_id = %s)
        """

        cur.execute(query, (league_id, season, team_id, team_id))

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    ##########################################################################
    # BUSCA ÚLTIMOS N JOGOS DA SELEÇÃO (QUALQUER COMPETIÇÃO)
    ##########################################################################
    def get_national_team_last_n_games(self, team_id, last_n=10):
        """Últimos N jogos finalizados de uma seleção, independente de liga/temporada."""
        conn = self.db()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM match_statistics
            WHERE status = 'FT'
              AND (home_team_id = %s OR away_team_id = %s)
            ORDER BY match_date DESC
            LIMIT %s
        """, (team_id, team_id, last_n))

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    ##########################################################################
    # LÓGICA DE AGREGAÇÃO COMPARTILHADA
    ##########################################################################
    def _aggregate_games(self, games, team_id):
        """Agrega lista de jogos em médias HOME/AWAY. Usado por ambos os métodos."""

        def base_totals():
            return {
                "goals_for": 0, "goals_against": 0,
                "corners_for": 0, "corners_against": 0,
                "yellow_for": 0, "yellow_against": 0,
                "red_for": 0, "red_against": 0,
                "shots_on_for": 0, "shots_on_against": 0,
                "shots_off_for": 0, "shots_off_against": 0,
                "total_shots_for": 0, "total_shots_against": 0,
                "blocked_for": 0, "blocked_against": 0,
                "saves_for": 0, "saves_against": 0,
                "fouls_for": 0, "fouls_against": 0,
                "offsides_for": 0, "offsides_against": 0,
                "possession_for": 0, "possession_against": 0,
                "passes_for": 0, "passes_against": 0,
                "passes_accuracy_for": 0, "passes_accuracy_against": 0,
                "count": 0
            }

        home = base_totals()
        away = base_totals()

        for g in games:

            if g["home_team_id"] == team_id:
                target = home
                prefix_for = "home"
                prefix_against = "away"
            else:
                target = away
                prefix_for = "away"
                prefix_against = "home"

            target["goals_for"] += g.get(f"{prefix_for}_goals") or 0
            target["goals_against"] += g.get(f"{prefix_against}_goals") or 0
            target["corners_for"] += g.get(f"{prefix_for}_corners") or 0
            target["corners_against"] += g.get(f"{prefix_against}_corners") or 0
            target["yellow_for"] += g.get(f"{prefix_for}_yellow_cards") or 0
            target["yellow_against"] += g.get(f"{prefix_against}_yellow_cards") or 0
            target["red_for"] += g.get(f"{prefix_for}_red_cards") or 0
            target["red_against"] += g.get(f"{prefix_against}_red_cards") or 0
            target["shots_on_for"] += g.get(f"{prefix_for}_shots_on") or 0
            target["shots_on_against"] += g.get(f"{prefix_against}_shots_on") or 0
            target["shots_off_for"] += g.get(f"{prefix_for}_shots_off") or 0
            target["shots_off_against"] += g.get(f"{prefix_against}_shots_off") or 0
            target["total_shots_for"] += g.get(f"{prefix_for}_total_shots") or 0
            target["total_shots_against"] += g.get(f"{prefix_against}_total_shots") or 0
            target["blocked_for"] += g.get(f"{prefix_for}_blocked_shots") or 0
            target["blocked_against"] += g.get(f"{prefix_against}_blocked_shots") or 0
            target["saves_for"] += g.get(f"{prefix_for}_goalkeeper_saves") or 0
            target["saves_against"] += g.get(f"{prefix_against}_goalkeeper_saves") or 0
            target["fouls_for"] += g.get(f"{prefix_for}_fouls") or 0
            target["fouls_against"] += g.get(f"{prefix_against}_fouls") or 0
            target["offsides_for"] += g.get(f"{prefix_for}_offsides") or 0
            target["offsides_against"] += g.get(f"{prefix_against}_offsides") or 0
            target["possession_for"] += g.get(f"{prefix_for}_possession") or 0
            target["possession_against"] += g.get(f"{prefix_against}_possession") or 0
            target["passes_for"] += g.get(f"{prefix_for}_passes") or 0
            target["passes_against"] += g.get(f"{prefix_against}_passes") or 0
            target["passes_accuracy_for"] += g.get(f"{prefix_for}_passes_accuracy") or 0
            target["passes_accuracy_against"] += g.get(f"{prefix_against}_passes_accuracy") or 0
            target["count"] += 1

        def build_avg(totals, context_type):
            count = totals["count"]
            if count == 0:
                return None
            result = {}
            for k, v in totals.items():
                if k != "count":
                    result[f"avg_{k}"] = round(v / count, 2)
            result["avg_total_goals"] = round((totals["goals_for"] + totals["goals_against"]) / count, 2)
            result["avg_total_corners"] = round((totals["corners_for"] + totals["corners_against"]) / count, 2)
            result["avg_total_yellow"] = round((totals["yellow_for"] + totals["yellow_against"]) / count, 2)
            result["avg_total_red"] = round((totals["red_for"] + totals["red_against"]) / count, 2)
            result["games_count"] = count
            result["context_type"] = context_type
            return result

        results = []
        home_avg = build_avg(home, "HOME")
        if home_avg:
            results.append(home_avg)
        away_avg = build_avg(away, "AWAY")
        if away_avg:
            results.append(away_avg)

        return results

    ##########################################################################
    # CALCULA MÉDIAS COMPLETAS SEPARADAS POR HOME / AWAY
    ##########################################################################
    def calculate_team_season_averages(self, team_id, league_id, season):

        games = self.get_team_games_stats_in_season(team_id, league_id, season)

        if not games:
            return []

        return self._aggregate_games(games, team_id)

    ##########################################################################
    # CALCULA MÉDIAS DAS SELEÇÕES — ÚLTIMOS N JOGOS (AMISTOSOS + COPA)
    ##########################################################################
    def calculate_national_team_averages(self, team_id, last_n=10):
        """Médias dos últimos N jogos da seleção, misturando amistosos e Copa do Mundo."""
        games = self.get_national_team_last_n_games(team_id, last_n)

        if not games:
            return []

        return self._aggregate_games(games, team_id)
