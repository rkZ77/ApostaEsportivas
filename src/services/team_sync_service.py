import os
import requests
import psycopg2
from psycopg2.extras import execute_values

API_KEY = os.getenv("API_FOOTBALL_KEY")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "apostas")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

LEAGUES = {
    "Premier League": 39,
    "La Liga": 140,
    "Bundesliga": 78,
    "Paulistão A1": 475
}

API_URL = "https://v3.football.api-sports.io/teams"
HEADERS = {"x-apisports-key": API_KEY}


def get_teams_by_league(league_id):
    params = {"league": league_id, "season": "2025"}
    response = requests.get(API_URL, headers=HEADERS, params=params)
    response.raise_for_status()
    data = response.json()
    return [
        {
            "team_id": team["team"]["id"],
            "team_name": team["team"]["name"],
            "league_id": league_id
        }
        for team in data.get("response", [])
    ]


def insert_teams(teams):
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    cur = conn.cursor()
    sql = """
        INSERT INTO teams (team_id, team_name, league_id)
        VALUES %s
        ON CONFLICT (team_id) DO NOTHING;
    """
    values = [(t["team_id"], t["team_name"], t["league_id"]) for t in teams]
    execute_values(cur, sql, values)
    conn.commit()
    cur.close()
    conn.close()


def main():
    for league_name, league_id in LEAGUES.items():
        teams = get_teams_by_league(league_id)
        print(f"[INFO] Times encontrados na liga {league_name}: {len(teams)}")
        # Check which teams are new before insert
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT team_id FROM teams WHERE league_id = %s", (league_id,))
        existing_ids = set(row[0] for row in cur.fetchall())
        new_teams = [t for t in teams if t["team_id"] not in existing_ids]
        print(f"[INFO] Times novos inseridos: {len(new_teams)}")
        cur.close()
        conn.close()
        if new_teams:
            insert_teams(new_teams)


if __name__ == "__main__":
    main()
