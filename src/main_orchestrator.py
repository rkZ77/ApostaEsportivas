import datetime
import psycopg2
import requests
from dotenv import load_dotenv
import os

from src.services.pre_game_suggestion_service import PreGameSuggestionService
from src.services.post_game_evaluation_service import PostGameEvaluationService

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"x-apisports-key": API_KEY}

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"


class MainOrchestrator:

    def __init__(self):
        self.pre_game = PreGameSuggestionService()
        self.post_game = PostGameEvaluationService()

    # ---------------------------------------------------------------------
    # ETAPA 1 — CARREGAR PARTIDAS DO DIA
    # ---------------------------------------------------------------------
    def get_today_fixtures(self):
        today = datetime.datetime.utcnow().date()

        params = {
            "date": today.strftime("%Y-%m-%d")
        }

        url = "https://v3.football.api-sports.io/fixtures"

        print(f"\n[FIXTURES] Buscando jogos do dia... {today}")

        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()

        data = r.json().get("response", [])

        fixtures = []
        for f in data:
            fixtures.append({
                "fixture_id": f["fixture"]["id"],
                "league_id": f["league"]["id"],
                "home_team": f["teams"]["home"]["name"],
                "away_team": f["teams"]["away"]["name"],
                "match_datetime": f["fixture"]["timestamp"]
            })

        print(f"[FIXTURES] Encontrados {len(fixtures)} jogos para hoje.")

        return fixtures

    # ---------------------------------------------------------------------
    # ETAPA 2 — EXECUTAR PRÉ-JOGO
    # ---------------------------------------------------------------------
    def run_pre_game(self):
        fixtures = self.get_today_fixtures()

        if not fixtures:
            print("[PRE-JOGO] Nenhum jogo encontrado. Encerrando etapa.")
            return

        print("\n========== ETAPA 2: PRÉ-JOGO ==========")

        for fx in fixtures:
            self.pre_game.generate_pre_game(fx)

        print("========== PRÉ-JOGO FINALIZADO ==========\n")

    # ---------------------------------------------------------------------
    # ETAPA 3 — EXECUTAR PÓS-JOGO
    # ---------------------------------------------------------------------
    def run_post_game(self):
        print("\n========== ETAPA 3: PÓS-JOGO ==========")
        self.post_game.run()
        print("========== PÓS-JOGO FINALIZADO ==========\n")

    # ---------------------------------------------------------------------
    # ETAPA 4 — GERAR MÉTRICAS SIMPLES
    # ---------------------------------------------------------------------
    def run_metrics(self):

        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE recommendation = 'GREEN'),
                COUNT(*) FILTER (WHERE recommendation = 'RED')
            FROM bet_recommendations
        """)

        greens, reds = cur.fetchone()

        cur.close()
        conn.close()

        total = greens + reds if greens + reds > 0 else 1
        accuracy = greens / total * 100

        print("\n========== ETAPA 4: MÉTRICAS ==========")
        print(f"Greens: {greens}")
        print(f"Reds: {reds}")
        print(f"Taxa de acerto: {accuracy:.2f}%")
        print("========== MÉTRICAS FINALIZADAS ==========\n")

    # ---------------------------------------------------------------------
    # EXECUTAR TUDO
    # ---------------------------------------------------------------------
    def run_all(self):
        print("\n========== ORCHESTRATOR INICIADO ==========")

        self.run_pre_game()
        self.run_post_game()
        self.run_metrics()

        print("========== ORCHESTRATOR FINALIZADO ==========\n")


if __name__ == "__main__":
    orchestrator = MainOrchestrator()
    orchestrator.run_all()
