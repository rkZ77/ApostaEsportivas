import os
import psycopg2
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida")

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"

HEADERS = {"x-apisports-key": API_KEY}

FIXTURES_URL = "https://v3.football.api-sports.io/fixtures"
STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"

LEAGUES = [
    {"league_id": 39, "season": 2025},
    {"league_id": 140, "season": 2025},
    {"league_id": 78, "season": 2025},
    {"league_id": 475, "season": 2026},
]


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )


def get_finished_fixtures(league_id, season):
    params = {
        "league": league_id,
        "season": season,
        "status": "FT"
    }
    r = requests.get(FIXTURES_URL, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()["response"]


def get_fixture_statistics(fixture_id):
    params = {"fixture": fixture_id}
    r = requests.get(STATS_URL, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()["response"]


def extract_stat(stats, stat_name):
    for s in stats:
        if s["type"] == stat_name:
            return s["value"] or 0
    return 0


def sync_match_statistics():
    conn = get_connection()
    cur = conn.cursor()

    total_saved = 0

    for league in LEAGUES:
        league_id = league["league_id"]
        season = league["season"]

        print(f"[INFO] Buscando jogos finalizados - Liga {league_id}")

        fixtures = get_finished_fixtures(league_id, season)

        for f in fixtures:
            fixture = f["fixture"]
            teams = f["teams"]
            goals = f["goals"]

            fixture_id = fixture["id"]
            status = fixture["status"]["short"]

            if status not in ["FT", "AET", "PEN"]:
                continue

            home_team_id = teams["home"]["id"]
            away_team_id = teams["away"]["id"]

            if not home_team_id or not away_team_id:
                continue

            stats = get_fixture_statistics(fixture_id)
            if not stats or len(stats) < 2:
                continue

            home_stats = stats[0]["statistics"]
            away_stats = stats[1]["statistics"]

            home_corners = extract_stat(home_stats, "Corner Kicks")
            away_corners = extract_stat(away_stats, "Corner Kicks")

            home_yellow = extract_stat(home_stats, "Yellow Cards")
            away_yellow = extract_stat(away_stats, "Yellow Cards")

            home_red = extract_stat(home_stats, "Red Cards")
            away_red = extract_stat(away_stats, "Red Cards")

            cur.execute("""
                INSERT INTO match_statistics (
                    fixture_id, league_id, season,
                    home_team_id, away_team_id,
                    home_goals, away_goals, total_goals,
                    home_corners, away_corners, total_corners,
                    home_yellow_cards, away_yellow_cards, total_yellow_cards,
                    home_red_cards, away_red_cards, total_red_cards,
                    status, match_date, last_updated
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (fixture_id) DO NOTHING
            """, (
                fixture_id,
                league_id,
                season,
                home_team_id,
                away_team_id,
                goals["home"] or 0,
                goals["away"] or 0,
                (goals["home"] or 0) + (goals["away"] or 0),
                home_corners,
                away_corners,
                home_corners + away_corners,
                home_yellow,
                away_yellow,
                home_yellow + away_yellow,
                home_red,
                away_red,
                home_red + away_red,
                status,
                datetime.fromisoformat(fixture["date"].replace("Z", ""))
            ))

            total_saved += 1

        conn.commit()
        print(f"[OK] Liga {league_id} sincronizada")

    cur.close()
    conn.close()

    print(f"[FINALIZADO] Estatísticas de partidas salvas: {total_saved}")


if __name__ == "__main__":
    sync_match_statistics()
