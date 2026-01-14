from collectors.api_football_collector import ApiFootballCollector
from database.db_connection import get_connection


class HistoryIngestionService:
    def __init__(self, league_id=475, season=2026):
        self.collector = ApiFootballCollector()
        self.league_id = league_id
        self.season = season

    def ingest_finished_matches(self):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            finished_matches = self.collector.get_fixtures()
            for match in finished_matches:
                # Supondo que match['status'] == 'finished' para jogos encerrados
                if match.get('status') != 'finished':
                    continue
                fixture_id = match['match_id']
                home_team = match['homeTeam']
                away_team = match['awayTeam']
                match_date = match['startTimestamp']
                status = match.get('status')
                # Times
                for team in [home_team, away_team]:
                    cursor.execute(
                        'INSERT INTO teams (name) VALUES (%s) ON CONFLICT (name) DO NOTHING',
                        (team['name'],))
                # Match
                cursor.execute(
                    'SELECT id FROM teams WHERE name=%s', (home_team['name'],))
                home_team_id = cursor.fetchone()[0]
                cursor.execute(
                    'SELECT id FROM teams WHERE name=%s', (away_team['name'],))
                away_team_id = cursor.fetchone()[0]
                cursor.execute('INSERT INTO matches (match_id, home_team_id, away_team_id, match_date, status) VALUES (%s, %s, %s, to_timestamp(%s), %s) ON CONFLICT (match_id) DO NOTHING',
                               (fixture_id, home_team_id, away_team_id, match_date, status))
                cursor.execute(
                    'SELECT id FROM matches WHERE match_id=%s', (fixture_id,))
                match_id = cursor.fetchone()[0]
                # Estatísticas
                stats = self.collector.get_fixture_statistics(fixture_id)
                for team, is_home in [(home_team, True), (away_team, False)]:
                    team_db_id = home_team_id if is_home else away_team_id
                    goals_for = stats.get('home', {}).get(
                        'Goals') if is_home else stats.get('away', {}).get('Goals')
                    goals_against = stats.get('away', {}).get(
                        'Goals') if is_home else stats.get('home', {}).get('Goals')
                    corners = stats.get('home', {}).get(
                        'Corner Kicks', 0) if is_home else stats.get('away', {}).get('Corner Kicks', 0)
                    cards = (
                        stats.get('home', {}).get('Yellow Cards', 0) +
                        stats.get('home', {}).get('Red Cards', 0)
                        if is_home else
                        stats.get('away', {}).get('Yellow Cards', 0) +
                        stats.get('away', {}).get('Red Cards', 0)
                    )
                    cursor.execute('INSERT INTO match_statistics (match_id, team_id, goals_for, goals_against, corners, cards) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (match_id, team_id) DO NOTHING',
                                   (match_id, team_db_id, goals_for, goals_against, corners, cards))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
