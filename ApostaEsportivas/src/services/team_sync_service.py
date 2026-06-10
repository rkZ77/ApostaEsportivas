import os
import psycopg2
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_SSLMODE = os.getenv("DB_SSLMODE")

HEADERS = {"x-apisports-key": API_KEY}


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )


# ================================================================
# Carrega ligas da tabela leagues
# ================================================================
def load_leagues_from_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT league_id, name, season FROM leagues;")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    leagues = {}
    for league_id, name, season in rows:
        leagues[league_id] = {
            "name": name,
            "season": season
        }

    return leagues


class TeamSyncService:

    def __init__(self):
        self.conn = None
        self.cur = None

    def _open_db(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()

    def _close_db(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    # -----------------------------------------------------------------
    # Obter season mais recente (caso não exista no banco)
    # -----------------------------------------------------------------
    def _get_latest_season(self, league_id):
        url = "https://v3.football.api-sports.io/leagues"
        params = {"id": league_id}

        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()

        response = r.json().get("response", [])
        if not response:
            return None

        seasons = response[0]["seasons"]
        return seasons[-1]["year"]

    # -----------------------------------------------------------------
    # Buscar times da API (agora respeitando season do banco)
    # -----------------------------------------------------------------
    def _fetch_teams(self, league_id, season):
        print(f"[INFO] Buscando times | Liga {league_id} | Season {season}")

        url = "https://v3.football.api-sports.io/teams"
        params = {"league": league_id, "season": season}

        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()

        teams_data = r.json().get("response", [])
        print(f"[INFO] {len(teams_data)} times encontrados")

        teams = []
        for t in teams_data:
            team = t.get("team")
            if not team:
                continue

            teams.append({
                "team_id": team["id"],
                "name": team["name"],
                "country": team["country"],
                "league_id": league_id,
                "season": season,
            })

        return teams

    # -----------------------------------------------------------------
    # SALVAR TIMES
    # -----------------------------------------------------------------
    def _save_team(self, t):
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
            VALUES (%s,%s,%s,%s,%s,NOW(),NOW())
            ON CONFLICT (team_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                country = EXCLUDED.country,
                league_id = EXCLUDED.league_id,
                season = EXCLUDED.season,
                last_updated = NOW();
        """, (
            t["team_id"],
            t["name"],
            t["country"],
            t["league_id"],
            t["season"]
        ))

    # -----------------------------------------------------------------
    # PROCESSO PRINCIPAL
    # -----------------------------------------------------------------
    def sync_all_teams(self):
        print("[TEAMS] Sincronizando times…")
        self._open_db()

        leagues = load_leagues_from_db()
        print(f"[INFO] {len(leagues)} ligas carregadas do banco.")

        for league_id, info in leagues.items():
            season = info["season"]

            teams = self._fetch_teams(league_id, season)

            if not teams:
                print(f"[WARN] Nenhum time retornado para liga {league_id}")
                continue

            for t in teams:
                self._save_team(t)

            self.conn.commit()
            print(f"[OK] Liga {league_id} ({info['name']}) sincronizada\n")

        self._close_db()
        print("[FINALIZADO] Times sincronizados com sucesso.")
