import os
import requests
from dotenv import load_dotenv, find_dotenv

from utils.db_utils import get_connection

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no ambiente")

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}


# ================================================================
# Carrega ligas da tabela leagues
# ================================================================
def load_leagues_from_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT league_id, season FROM leagues;")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [{"league_id": r[0], "season": r[1]} for r in rows]


# ================================================================
# Serviço de sincronização de times
# ================================================================
class LeagueTeamsSyncService:

    def __init__(self):
        self.conn = None
        self.cur = None

    def _open(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()

    def _close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    # ---------------------------------------------------------
    # Busca times da API por liga
    # ---------------------------------------------------------
    def _fetch_teams_from_api(self, league_id, season):
        url = f"{BASE_URL}/teams"

        params = {
            "league": league_id,
            "season": season
        }

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=15
            )
            response.raise_for_status()
        except Exception as e:
            print(f"[ERRO] Falha API | League {league_id}: {e}")
            return []

        data = response.json().get("response", [])

        teams = []
        for item in data:
            team = item.get("team", {})

            teams.append({
                "team_id": team.get("id"),
                "name": team.get("name"),
                "country": team.get("country"),
                "league_id": league_id,
                "season": season
            })

        return teams

    # ---------------------------------------------------------
    # Insert ou Update (Upsert real)
    # ---------------------------------------------------------
    def _upsert_team(self, team):
        self.cur.execute("""
            INSERT INTO teams (
                team_id,
                name,
                country,
                league_id,
                season,
                created_at,
                last_updated
            )
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (team_id, league_id, season)
            DO UPDATE SET
                name = EXCLUDED.name,
                country = EXCLUDED.country,
                last_updated = NOW();
        """, (
            team["team_id"],
            team["name"],
            team["country"],
            team["league_id"],
            team["season"]
        ))

    # ---------------------------------------------------------
    # Processo principal
    # ---------------------------------------------------------
    def sync_league_teams(self):
        print("[TEAMS] Iniciando sincronização...")

        self._open()

        leagues = load_leagues_from_db()

        if not leagues:
            print("[WARN] Nenhuma liga encontrada na tabela leagues.")
            self._close()
            return

        for league in leagues:
            league_id = league["league_id"]
            season = league["season"]

            print(f"[TEAMS] Liga {league_id} | Season {season}")

            api_teams = self._fetch_teams_from_api(league_id, season)

            if not api_teams:
                print("[WARN] Nenhum time retornado pela API.")
                continue

            for team in api_teams:
                self._upsert_team(team)

            self.conn.commit()
            print(f"[OK] {len(api_teams)} times processados.")

        self._close()

        # Conta total de times no banco após sync
        conn2 = get_connection()
        cur2 = conn2.cursor()
        cur2.execute("SELECT COUNT(*) FROM teams;")
        total = cur2.fetchone()[0]
        cur2.close()
        conn2.close()

        print(f"[TEAMS] Finalizado. Total de times no banco: {total}")
