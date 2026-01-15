import psycopg2

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"


class HistoricalStatsService:

    def _get_connection(self):
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )

    def get_team_stats(self, team_id):
        conn = self._get_connection()
        cur = conn.cursor()

        result = {}
        for n in [5, 10, 15]:
            result[f"last_{n}"] = self._get_last_n_stats(cur, team_id, n)

        cur.close()
        conn.close()
        return result

    def _get_last_n_stats(self, cur, team_id, limit):
        cur.execute("""
            SELECT
                CASE
                    WHEN home_team_id = %s THEN home_goals
                    ELSE away_goals
                END AS goals_for,

                CASE
                    WHEN home_team_id = %s THEN away_goals
                    ELSE home_goals
                END AS goals_against,

                CASE
                    WHEN home_team_id = %s THEN home_corners
                    ELSE away_corners
                END AS corners,

                CASE
                    WHEN home_team_id = %s THEN home_yellow_cards + home_red_cards
                    ELSE away_yellow_cards + away_red_cards
                END AS cards,

                home_team_id,
                away_team_id
            FROM match_statistics
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND status = 'FT'
            ORDER BY match_date DESC
            LIMIT %s
        """, (
            team_id, team_id, team_id, team_id,
            team_id, team_id, limit
        ))

        rows = cur.fetchall()

        return {
            "total": self._calc(rows),
            "home": self._calc([r for r in rows if r[4] == team_id]),
            "away": self._calc([r for r in rows if r[5] == team_id])
        }

    def _calc(self, rows):
        if not rows:
            return {
                "avg_goals_for": 0.0,
                "avg_goals_against": 0.0,
                "avg_corners": 0.0,
                "avg_cards": 0.0
            }

        n = len(rows)
        return {
            "avg_goals_for": sum(r[0] for r in rows) / n,
            "avg_goals_against": sum(r[1] for r in rows) / n,
            "avg_corners": sum(r[2] for r in rows) / n,
            "avg_cards": sum(r[3] for r in rows) / n
        }


# ===== TESTE LOCAL =====
if __name__ == "__main__":
    service = HistoricalStatsService()
    TEST_TEAM_ID = 7848  # exemplo: Manchester United
    stats = service.get_team_stats(TEST_TEAM_ID)
    print(stats)
