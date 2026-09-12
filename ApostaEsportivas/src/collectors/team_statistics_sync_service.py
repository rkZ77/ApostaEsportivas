import os
from dotenv import load_dotenv, find_dotenv

from utils.db_utils import get_connection
from utils.api_client import buscar

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no ambiente")

BASE_URL = "https://v3.football.api-sports.io"


# ================================================================
# Carrega ligas da tabela leagues
# ================================================================
def load_leagues_from_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT league_id, season FROM leagues WHERE COALESCE(ativa, TRUE);")
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
        """Times da liga. LEVANTA em falha -- nao devolve lista vazia.

        Aqui o `return []` do `except` custava mais caro que na maioria dos
        coletores, e de um jeito que nao aparecia neste arquivo: a tabela
        `teams` e' o FILTRO do coletor de fixtures
        (`FixtureCollectorService._get_all_team_ids`), que so' aceita jogo com
        pelo menos um time cadastrado. Uma liga que falhasse aqui saia do
        radar inteiro -- sem time cadastrado, nenhum jogo dela vira fixture,
        nenhuma odd e' coletada, nenhum pick existe. E o log dizia
        "[ERRO] Falha API" numa linha e seguia para a proxima liga.
        """
        data = buscar(
            "teams",
            {"league": league_id, "season": season},
            origem="coletor_times",
        )

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
    def sync_league_teams(self, apenas_liga=None):
        """Sincroniza os times das ligas cadastradas.

        `apenas_liga` limita a UMA liga -- e' o que a coleta de liga nova usa
        (1 requisicao em vez de uma por liga cadastrada). Sem times cadastrados
        nenhum jogo da liga e' salvo: FixtureCollectorService filtra por
        `SELECT team_id FROM teams`, e foi assim que a Sul-Americana ficou
        cadastrada e sem coletar nada ate' 2026-08-11.
        """
        print("[TEAMS] Iniciando sincronização...")

        self._open()

        leagues = load_leagues_from_db()
        if apenas_liga is not None:
            leagues = [l for l in leagues if l["league_id"] == apenas_liga]
            if not leagues:
                print(f"[WARN] Liga {apenas_liga} nao esta cadastrada em `leagues`.")
                self._close()
                return

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
