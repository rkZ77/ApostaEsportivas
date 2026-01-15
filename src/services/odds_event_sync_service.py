import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"
DB_HOST = "localhost"

SPORT_KEY = "soccer_epl"
EVENTS_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/events"

def get_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST
    )

def sync_odds_events():
    params = {
        "apiKey": API_KEY,
        "regions": "eu"
    }

    r = requests.get(EVENTS_URL, params=params)
    r.raise_for_status()
    events = r.json()

    conn = get_connection()
    cur = conn.cursor()

    for e in events:
        cur.execute("""
            INSERT INTO odds_events
            (fixture_id, sport_key, odds_event_id, commence_time, home_team, away_team)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (fixture_id) DO NOTHING
        """, (
            None,  # será associado depois
            SPORT_KEY,
            e["id"],
            e["commence_time"],
            e["home_team"],
            e["away_team"]
        ))

    conn.commit()
    cur.close()
    conn.close()

    print("[OK] Odds events sincronizados")
