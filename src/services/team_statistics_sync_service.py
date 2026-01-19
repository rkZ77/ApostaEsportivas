import os
import psycopg2
import requests

API_KEY = os.getenv("API_FOOTBALL_KEY")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "football_stats")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "Pereira2310!")

ALLOWED_LEAGUES = {
    39,  # Premier League
    71,  # Brasileirão A
    103,  # Paulista
    140,  # La Liga
    78,  # Bundesliga
}


class TeamStatisticsSyncService:

    def __init__(self):
        if not API_KEY:
            raise RuntimeError("API_FOOTBALL_KEY não definida")
        self.base_url = "https://v3.football.api-sports.io"

    def _connect(self):
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )

    def _load_unique_teams(self):
        conn = self._connect()
        cur = conn.cursor()

        cur.execute("""
            SELECT DISTINCT home_id FROM fixtures
            WHERE league_id = ANY(%s)
            UNION
            SELECT DISTINCT away_id FROM fixtures
            WHERE league_id = ANY(%s)
        """, (list(ALLOWED_LEAGUES), list(ALLOWED_LEAGUES)))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [r[0] for r in rows if r[0] is not None]

    def fetch_team_stats(self, team_id):
        url = f"{self.base_url}/teams/statistics"
        headers = {"x-apisports-key": API_KEY}
        params = {
            "team": team_id,
            "season": 2025,
        }

        r = requests.get(url, headers=headers, params=params)

        if r.status_code != 200:
            return None

        data = r.json()["response"]

        return {
            "team_id": team_id,
            "avg_goals_for": data["goals"]["for"]["average"]["total"],
            "avg_goals_against": data["goals"]["against"]["average"]["total"],
            "avg_corners": data.get("corners", {}).get("for", 0),
            "avg_cards": data.get("cards", {}).get("yellow", {}).get("average", 0),
        }

    def save_team_stats(self, stats):
        conn = self._connect()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO team_statistics (
                team_id,
                avg_goals_for,
                avg_goals_against,
                avg_corners,
                avg_cards
            )
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (team_id)
            DO UPDATE SET
                avg_goals_for     = EXCLUDED.avg_goals_for,
                avg_goals_against = EXCLUDED.avg_goals_against,
                avg_corners       = EXCLUDED.avg_corners,
                avg_cards         = EXCLUDED.avg_cards
        """, (
            stats["team_id"],
            stats["avg_goals_for"],
            stats["avg_goals_against"],
            stats["avg_corners"],
            stats["avg_cards"]
        ))

        conn.commit()
        cur.close()
        conn.close()

    def sync(self):
        teams = self._load_unique_teams()
        print(f"[STATS] Encontrados {len(teams)} times para atualizar.")

        for team_id in teams:
            stats = self.fetch_team_stats(team_id)
            if stats:
                self.save_team_stats(stats)
                print(f"[STATS] Atualizado team {team_id}")
            else:
                print(f"[WARN] Time {team_id} sem estatísticas")
