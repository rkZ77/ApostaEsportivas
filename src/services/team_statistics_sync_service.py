import os
import psycopg2
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida")

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"

API_URL = "https://v3.football.api-sports.io/teams/statistics"
HEADERS = {"x-apisports-key": API_KEY}


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_team_statistics(team_id, league_id, season):
    r = requests.get(
        API_URL,
        headers=HEADERS,
        params={"team": team_id, "league": league_id, "season": season}
    )
    r.raise_for_status()
    return r.json().get("response", {})


def sync_team_statistics():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, league_id, season
        FROM teams
    """)
    teams = cur.fetchall()

    print(f"[INFO] Sincronizando estatísticas de {len(teams)} times")

    for team_id, league_id, season in teams:
        try:
            stats = fetch_team_statistics(team_id, league_id, season)
            if not stats:
                print(f"[WARN] Sem estatísticas para time {team_id}")
                continue

            fixtures = stats.get("fixtures", {})
            goals = stats.get("goals", {})
            cards = stats.get("cards", {})

            goals_for_total = safe_int(
                goals.get("for", {}).get("total", {}).get("total")
            )
            goals_against_total = safe_int(
                goals.get("against", {}).get("total", {}).get("total")
            )

            avg_goals_for = safe_float(
                goals.get("for", {}).get("average", {}).get("total")
            )
            avg_goals_against = safe_float(
                goals.get("against", {}).get("average", {}).get("total")
            )

            home_avg_goals_for = safe_float(
                goals.get("for", {}).get("average", {}).get("home")
            )
            away_avg_goals_for = safe_float(
                goals.get("for", {}).get("average", {}).get("away")
            )

            yellow_avg = safe_float(
                cards.get("yellow", {}).get("average")
            )
            red_avg = safe_float(
                cards.get("red", {}).get("average")
            )

            matches_played = safe_int(
                fixtures.get("played", {}).get("total")
            )

            cur.execute("""
                INSERT INTO team_season_statistics (
                    team_id, league_id, season,
                    matches_played,
                    goals_for, goals_against,
                    avg_goals_for, avg_goals_against,
                    home_avg_goals_for, away_avg_goals_for,
                    avg_yellow_cards, avg_red_cards,
                    last_updated
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (team_id, league_id, season)
                DO UPDATE SET
                    matches_played = EXCLUDED.matches_played,
                    goals_for = EXCLUDED.goals_for,
                    goals_against = EXCLUDED.goals_against,
                    avg_goals_for = EXCLUDED.avg_goals_for,
                    avg_goals_against = EXCLUDED.avg_goals_against,
                    home_avg_goals_for = EXCLUDED.home_avg_goals_for,
                    away_avg_goals_for = EXCLUDED.away_avg_goals_for,
                    avg_yellow_cards = EXCLUDED.avg_yellow_cards,
                    avg_red_cards = EXCLUDED.avg_red_cards,
                    last_updated = NOW()
            """, (
                team_id,
                league_id,
                season,
                matches_played,
                goals_for_total,
                goals_against_total,
                avg_goals_for,
                avg_goals_against,
                home_avg_goals_for,
                away_avg_goals_for,
                yellow_avg,
                red_avg,
                datetime.utcnow()
            ))

            print(f"[OK] Time {team_id} sincronizado")

        except Exception as e:
            print(f"[ERRO] Time {team_id}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    print("[FINALIZADO] Estatísticas sincronizadas")


if __name__ == "__main__":
    sync_team_statistics()