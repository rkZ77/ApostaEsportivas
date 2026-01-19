import os
import requests
import psycopg2
from dotenv import load_dotenv
from datetime import date

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")

if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no ambiente")

BASE_URL = "https://v3.football.api-sports.io"

# Ligas suportadas no projeto
ALLOWED_LEAGUES = {
    39,    # Premier League
    71,    # Brasileirão Série A
    475,   # Paulistão A
    140,   # La Liga
    78     # Bundesliga
}

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "football_stats")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "Pereira2310!")


class FixtureCollectorService:
    def __init__(self):
        self.base_url = BASE_URL
        self.headers = {"x-apisports-key": API_KEY}

    def get_fixtures_by_date(self, target_date: date):
        print(f"[FIXTURES] Buscando jogos {target_date}")

        url = f"{self.base_url}/fixtures"
        params = {"date": str(target_date)}

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        data = response.json()
        fixtures_normalized = []

        for fx in data.get("response", []):
            league_id = fx["league"]["id"]

            # Filtra apenas ligas relevantes
            if league_id not in ALLOWED_LEAGUES:
                continue

            status = fx["fixture"]["status"]["short"]

            # Apenas jogos não finalizados
            if status not in ("NS", "TBD"):
                continue

            fixtures_normalized.append({
                "fixture_id": fx["fixture"]["id"],
                "league_id": league_id,
                "home_team": fx["teams"]["home"]["name"],
                "away_team": fx["teams"]["away"]["name"],
                "match_datetime": fx["fixture"]["timestamp"]
            })

        print(
            f"[FIXTURES] {len(fixtures_normalized)} jogos válidos na data {target_date}")
        return fixtures_normalized

    def save_fixtures(self, fixtures: list):
        """
        Salva fixtures no banco evitando duplicação (fixture_id UNIQUE)
        """
        if not fixtures:
            print("[FIXTURES] Nenhum fixture para salvar.")
            return

        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        for fx in fixtures:
            cur.execute("""
                INSERT INTO fixtures (
                    fixture_id, league_id, home_team, away_team, match_datetime
                ) VALUES (%s, %s, %s, %s, to_timestamp(%s))
                ON CONFLICT (fixture_id) DO NOTHING
            """, (
                fx["fixture_id"],
                fx["league_id"],
                fx["home_team"],
                fx["away_team"],
                fx["match_datetime"]
            ))

        conn.commit()
        cur.close()
        conn.close()

        print(f"[FIXTURES] {len(fixtures)} fixtures salvos no banco.")
