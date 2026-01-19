import os
import psycopg2
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY")
API_URL = "https://v3.football.api-sports.io/fixtures"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"


class PostGameEvaluationService:

    def __init__(self):
        self.headers = {"x-apisports-key": API_KEY}

    # ---------------------------------------
    # PEGAR RESULTADOS FINAIS DO JOGO
    # ---------------------------------------
    def get_fixture_result(self, fixture_id):
        params = {"id": fixture_id}
        r = requests.get(API_URL, headers=self.headers, params=params)
        r.raise_for_status()

        data = r.json().get("response", [])
        if not data:
            return None

        fixture = data[0]

        status = fixture["fixture"]["status"]["short"]

        if status not in ["FT", "AET", "PEN"]:
            return None  # jogo não finalizado, pular

        result = {
            "home_goals": fixture["goals"]["home"],
            "away_goals": fixture["goals"]["away"],
            "total_goals": fixture["goals"]["home"] + fixture["goals"]["away"],
            "home_corners": fixture["statistics"][0]["statistics"][7]["value"] if fixture["statistics"] else None,
            "away_corners": fixture["statistics"][1]["statistics"][7]["value"] if fixture["statistics"] else None,
            "home_cards": fixture["statistics"][0]["statistics"][6]["value"] if fixture["statistics"] else None,
            "away_cards": fixture["statistics"][1]["statistics"][6]["value"] if fixture["statistics"] else None,
        }

        return result

    # ---------------------------------------
    # LER TODAS AS APOSTAS PENDENTES
    # ---------------------------------------
    def get_pending_recommendations(self):
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        cur.execute("""
            SELECT id, match_id, market, team_side, line, odd
            FROM bet_recommendations
            WHERE recommendation = 'PENDING'
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return rows

    # ---------------------------------------
    # AVALIAÇÃO DA APOSTA
    # ---------------------------------------
    def evaluate_bet(self, market, side, line, result):
        """
        Lógica:
        - totals → total_goals > line
        - corners_totals → total_corners > line
        - cards_totals → total_cards > line
        """

        if market == "totals":
            total = result["total_goals"]

        elif market == "corners_totals":
            total = (result["home_corners"] or 0) + \
                (result["away_corners"] or 0)

        elif market == "cards_totals":
            total = (result["home_cards"] or 0) + (result["away_cards"] or 0)

        else:
            return None  # mercado não suportado ainda

        if side == "Over":
            return "GREEN" if total > line else "RED"

        if side == "Under":
            return "GREEN" if total < line else "RED"

        return None

    # ---------------------------------------
    # ATUALIZAR NO BANCO
    # ---------------------------------------
    def update_recommendation(self, rec_id, status):
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        cur.execute("""
            UPDATE bet_recommendations
            SET recommendation = %s,
                evaluated_at = %s
            WHERE id = %s
        """, (status, datetime.utcnow(), rec_id))

        conn.commit()
        cur.close()
        conn.close()

    # ---------------------------------------
    # PIPELINE PRINCIPAL
    # ---------------------------------------
    def run(self):
        print("\n--- Pós-Jogo: Avaliação iniciada ---")

        pending = self.get_pending_recommendations()

        if not pending:
            print("[INFO] Não há apostas pendentes para avaliar.")
            return

        print(f"[INFO] Avaliando {len(pending)} recomendações pendentes")

        for rec_id, match_id, market, side, line, odd in pending:

            print(
                f"\n[PROCESSANDO] Rec {rec_id} | Fixture {match_id} | {market} {side} {line}")

            result = self.get_fixture_result(match_id)
            if not result:
                print("[SKIP] Jogo ainda não terminou ou não encontrado")
                continue

            status = self.evaluate_bet(market, side, line, result)

            if not status:
                print("[ERRO] Mercado não suportado:", market)
                continue

            self.update_recommendation(rec_id, status)

            print(f"[OK] Rec {rec_id} ⇒ {status}")

        print("\n--- Pós-Jogo Finalizado ---")


if __name__ == "__main__":
    service = PostGameEvaluationService()
    service.run()
