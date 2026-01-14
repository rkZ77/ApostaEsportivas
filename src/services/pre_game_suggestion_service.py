from database.db_connection import get_connection
from datetime import datetime


def save_pre_game_suggestion(fixture_id, league, home_team, away_team, market, side, match_datetime):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bet_recommendations
        (match_id, market, team_side, line, odd, probability, expected_value, recommendation, created_at)
        VALUES (%s, %s, %s, %s, NULL, NULL, NULL, %s, %s)
        ON CONFLICT (match_id, market, team_side, line) DO NOTHING
    ''', (
        fixture_id, market, side, 0.0, 'PENDING', datetime.utcfromtimestamp(
            match_datetime)
    ))
    conn.commit()
    cursor.close()
    conn.close()
