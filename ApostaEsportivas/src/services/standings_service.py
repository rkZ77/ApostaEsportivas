from utils.db_utils import get_connection


class StandingsService:

    def get_team_standing(self, team_id, league_id, season):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""

        SELECT
            rank,
            points,
            goals_diff,
            form,
            played,
            win,
            draw,
            lose
        FROM league_standings
        WHERE team_id = %s
        AND league_id = %s
        AND season = %s

        """, (team_id, league_id, season))

        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return None

        return {
            "rank": row[0],
            "points": row[1],
            "goal_diff": row[2],
            "form": row[3],
            "played": row[4],
            "wins": row[5],
            "draws": row[6],
            "losses": row[7]
        }