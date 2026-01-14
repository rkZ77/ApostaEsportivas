from database.db_connection import get_connection


class HistoricalStatsService:
    def __init__(self):
        pass

    def get_team_stats(self, team_id, n_games=10):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT ms.goals_for, ms.goals_against, ms.corners, ms.cards FROM match_statistics ms
                         JOIN matches m ON ms.match_id = m.id
                         WHERE ms.team_id=%s AND m.status='finished'
                         ORDER BY ms.id DESC LIMIT %s''', (team_id, n_games))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        if not rows:
            return {
                'avg_goals_for': 0.0,
                'avg_goals_against': 0.0,
                'avg_corners': 0.0,
                'avg_cards': 0.0
            }
        n = len(rows)
        return {
            'avg_goals_for': sum(r[0] for r in rows) / n,
            'avg_goals_against': sum(r[1] for r in rows) / n,
            'avg_corners': sum(r[2] for r in rows) / n,
            'avg_cards': sum(r[3] for r in rows) / n
        }
