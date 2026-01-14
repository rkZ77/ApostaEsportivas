from database.db_connection import get_connection
from datetime import datetime


def save_recommendation(match_id, market, team_side, line, odd, probability, expected_value, recommendation):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bet_recommendations
        (match_id, market, team_side, line, odd, probability, expected_value, recommendation, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id, market, team_side, line) DO NOTHING
    ''', (
        match_id, market, team_side, line, odd, probability, expected_value, recommendation, datetime.now()
    ))
    conn.commit()
    cursor.close()
    conn.close()
