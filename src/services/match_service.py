from database.db_connection import get_connection
from datetime import datetime


def ensure_match_exists(fixture_id, league, home_team, away_team, match_datetime):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (id, match_datetime, status, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    ''', (
        fixture_id, datetime.utcfromtimestamp(match_datetime), 'scheduled', datetime.utcnow()
    ))
    conn.commit()
    cursor.close()
    conn.close()
