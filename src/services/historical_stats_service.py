from database.db_connection import get_connection


class HistoricalStatsService:
    def __init__(self):
        pass

    def get_team_stats(self, team_id):
        """
        Consulta estatísticas históricas para um time.
        Retorna médias para últimos 5, 10, 15 jogos (total, mandante, visitante).
        """
        conn = get_connection()
        cursor = conn.cursor()
        result = {}
        for n_games in [5, 10, 15]:
            result[f'last_{n_games}'] = self._get_stats_for_last_n_games(
                cursor, team_id, n_games)
        cursor.close()
        conn.close()
        return result

    def _get_stats_for_last_n_games(self, cursor, team_id, n_games):
        # Busca todos os jogos finalizados do time, ordenados por data desc
        cursor.execute('''
            SELECT ms.goals_for, ms.goals_against, ms.corners, ms.cards, m.home_team_id, m.away_team_id, m.id, m.match_datetime
            FROM match_statistics ms
            JOIN matches m ON ms.match_id = m.id
            WHERE ms.team_id=%s AND m.status='finished'
            ORDER BY m.match_datetime DESC
            LIMIT %s
        ''', (team_id, n_games))
        rows = cursor.fetchall()
        # total
        total = self._calc_stats(rows)
        # mandante
        home_rows = [r for r in rows if r[4] == team_id]
        home = self._calc_stats(home_rows)
        # visitante
        away_rows = [r for r in rows if r[5] == team_id]
        away = self._calc_stats(away_rows)
        return {'total': total, 'home': home, 'away': away}

    def _calc_stats(self, rows):
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
