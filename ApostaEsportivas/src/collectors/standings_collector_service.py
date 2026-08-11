import os
import requests
from dotenv import load_dotenv, find_dotenv
from psycopg2.extras import execute_batch
from utils.db_utils import get_connection

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")

HEADERS = {
    "x-apisports-key": API_KEY
}


class StandingsCollectorService:

    def __init__(self):
        self.url = "https://v3.football.api-sports.io/standings"

    # ----------------------------------------------------------
    # LIMPAR TABELA
    # ----------------------------------------------------------
    def truncate_table(self):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("TRUNCATE TABLE league_standings")

        conn.commit()

        cur.close()
        conn.close()

        print("[STANDINGS] Tabela limpa.")

    # ----------------------------------------------------------
    # BUSCAR LIGAS
    # ----------------------------------------------------------
    def get_leagues(self):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
        SELECT league_id, season
        FROM leagues
        WHERE COALESCE(ativa, TRUE)
        """)

        leagues = cur.fetchall()

        cur.close()
        conn.close()

        return leagues

    # ----------------------------------------------------------
    # FETCH API
    # ----------------------------------------------------------
    def fetch_standings(self, league_id, season):

        r = requests.get(
            self.url,
            headers=HEADERS,
            params={
                "league": league_id,
                "season": season
            },
            timeout=20
        )

        r.raise_for_status()

        data = r.json().get("response", [])

        if not data:
            return None

        return data[0]["league"]

    # ----------------------------------------------------------
    # SALVAR
    # ----------------------------------------------------------
    def save_standings(self, league_data):

        league_id = league_data["id"]
        league_name = league_data["name"]
        country = league_data["country"]
        season = league_data["season"]

        # standings é lista de grupos · Copa do Mundo tem 12 grupos (A-L),
        # ligas comuns têm 1. Itera por todos os grupos.
        all_groups = league_data["standings"]

        conn = get_connection()
        cur = conn.cursor()

        rows = []

        for group in all_groups:
            for team in group:
                rows.append((
                    league_id,
                    league_name,
                    country,
                    season,
                    team["group"],
                    team["team"]["id"],
                    team["team"]["name"],
                    team["team"]["logo"],
                    team["rank"],
                    team["points"],
                    team["goalsDiff"],
                    team["form"],
                    team["status"],
                    team["description"],
                    team["all"]["played"],
                    team["all"]["win"],
                    team["all"]["draw"],
                    team["all"]["lose"],
                    team["all"]["goals"]["for"],
                    team["all"]["goals"]["against"],
                    team["home"]["played"],
                    team["home"]["win"],
                    team["home"]["draw"],
                    team["home"]["lose"],
                    team["home"]["goals"]["for"],
                    team["home"]["goals"]["against"],
                    team["away"]["played"],
                    team["away"]["win"],
                    team["away"]["draw"],
                    team["away"]["lose"],
                    team["away"]["goals"]["for"],
                    team["away"]["goals"]["against"],
                    team["update"]
                ))

        execute_batch(cur, """

        INSERT INTO league_standings (

            league_id,
            league_name,
            country,
            season,
            group_name,

            team_id,
            team_name,
            team_logo,

            rank,
            points,
            goals_diff,

            form,
            status,
            description,

            played,
            win,
            draw,
            lose,

            goals_for,
            goals_against,

            home_played,
            home_win,
            home_draw,
            home_lose,
            home_goals_for,
            home_goals_against,

            away_played,
            away_win,
            away_draw,
            away_lose,
            away_goals_for,
            away_goals_against,

            api_last_update,

            created_at,
            updated_at

        )

        VALUES (

            %s,%s,%s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,
            %s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,
            %s,
            NOW(),NOW()

        )

        """, rows)

        conn.commit()

        cur.close()
        conn.close()

        print(f"[STANDINGS] Liga {league_id} inserida.")

    # ----------------------------------------------------------
    # PROCESSAR TODAS AS LIGAS
    # ----------------------------------------------------------
    def process_all(self):

        # limpa tabela antes de carregar
        self.truncate_table()

        leagues = self.get_leagues()

        print(f"Ligas encontradas: {len(leagues)}")

        for league_id, season in leagues:

            try:

                league_data = self.fetch_standings(league_id, season)

                if league_data:
                    self.save_standings(league_data)

            except Exception as e:

                print(f"Erro liga {league_id}: {e}")