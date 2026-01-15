import os
import psycopg2
import requests
from datetime import datetime

API_KEY = os.getenv("API_FOOTBALL_KEY")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "apostas")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

API_URL = "https://v3.football.api-sports.io/fixtures"
HEADERS = {"x-apisports-key": API_KEY}

# Mercado fixo: GOLS TOTAL Over 2.5
GOALS_LINE = 2.5


def get_pending_recommendations():
    print("[DEBUG] DB_HOST:", repr(DB_HOST), type(DB_HOST))
    print("[DEBUG] DB_PORT:", repr(DB_PORT), type(DB_PORT))
    print("[DEBUG] DB_NAME:", repr(DB_NAME), type(DB_NAME))
    print("[DEBUG] DB_USER:", repr(DB_USER), type(DB_USER))
    print("[DEBUG] DB_PASS:", repr(DB_PASS), type(DB_PASS))
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()
    cur.execute("""
    SELECT id, fixture_id, market, line
    FROM bet_recommendations
    WHERE status = 'PENDING'
      AND market = 'GOLS'
      AND line = %s
""", (GOALS_LINE,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_fixture_goals(fixture_id):
    params = {"id": fixture_id}
    response = requests.get(API_URL, headers=HEADERS, params=params)
    response.raise_for_status()
    data = response.json()
    resp = data.get("response", [])
    if not resp:
        return None
    fixture = resp[0]
    status = fixture["fixture"]["status"]["short"]
    if status not in ["FT", "AET", "PEN"]:
        return None  # Ignore unfinished games
    home_goals = fixture["goals"]["home"]
    away_goals = fixture["goals"]["away"]
    if home_goals is None or away_goals is None:
        return None
    return home_goals + away_goals


def evaluate_recommendations():
    recs = get_pending_recommendations()
    greens = 0
    reds = 0
    evaluated = 0
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()
    for rec_id, fixture_id, market, line in recs:
        total_goals = get_fixture_goals(fixture_id)
        if total_goals is None:
            continue
        status = "GREEN" if total_goals > line else "RED"
        cur.execute("""
            UPDATE recommendations SET status = %s, evaluated_at = %s WHERE id = %s
        """, (status, datetime.now(), rec_id))
        evaluated += 1
        if status == "GREEN":
            greens += 1
        else:
            reds += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"[INFO] Sugestões avaliadas: {evaluated}")
    print(f"[INFO] Greens: {greens} | Reds: {reds}")


if __name__ == "__main__":
    evaluate_recommendations()
