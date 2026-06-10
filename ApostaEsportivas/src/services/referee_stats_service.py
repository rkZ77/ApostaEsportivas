import psycopg2.extras
from utils.db_utils import get_connection


class RefereeStatsService:

    def get_stats(self, referee: str, season: int) -> dict | None:
        """Retorna médias pré-calculadas do árbitro na temporada, ou None se não houver dados."""
        if not referee:
            return None

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                r.referee_id,
                r.name        AS referee,
                rs.season,
                rs.games,
                rs.avg_yellow,
                rs.avg_red,
                rs.avg_fouls,
                rs.avg_corners,
                rs.avg_goals,
                rs.max_yellow,
                rs.min_yellow
            FROM referee_stats rs
            JOIN referees r ON r.referee_id = rs.referee_id
            WHERE r.name = %s
              AND rs.season = %s
        """, (referee, season))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return dict(row)
