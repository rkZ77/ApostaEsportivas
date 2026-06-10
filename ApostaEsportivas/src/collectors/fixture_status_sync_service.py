import os
import requests
from datetime import datetime, date
from utils.db_utils import get_connection
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"x-apisports-key": API_KEY}
API_URL = "https://v3.football.api-sports.io/fixtures"

FINALIZED_STATUSES = {
    "FT", "AET", "PEN", "CANC", "PST", "ABD", "WO"
}


class FixtureStatusSyncService:

    def __init__(self):
        pass

    def fetch_fixture_status(self, fixture_id):
        r = requests.get(API_URL, headers=HEADERS, params={
                         "id": fixture_id}, timeout=20)
        r.raise_for_status()

        response = r.json().get("response", [])
        if not response:
            return None

        fixture = response[0]["fixture"]

        return {
            "status": fixture["status"]["short"],
            "match_datetime": fixture["date"],
            "referee": fixture.get("referee"),
        }

    def update_fixture_status(self, fixture_id, data):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE fixtures
            SET
                status = %s,
                match_datetime = %s,
                referee = %s,
                last_updated = NOW()
            WHERE fixture_id = %s
        """, (
            data["status"],
            data["match_datetime"],
            data["referee"],
            fixture_id
        ))

        conn.commit()
        cur.close()
        conn.close()

    def delete_fixture(self, fixture_id):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM fixtures WHERE fixture_id = %s",
                    (fixture_id,))

        conn.commit()
        cur.close()
        conn.close()

        print(f"[DELETE] Fixture {fixture_id} removido do banco.")

    def process_all_fixtures(self):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT fixture_id, status, match_datetime FROM fixtures")
        fixture_rows = cur.fetchall()

        cur.close()
        conn.close()

        print(f"[STATUS] Encontrados {len(fixture_rows)} fixtures...")

        for fixture_id, status, match_datetime in fixture_rows:

            # 1️⃣ JÁ FINALIZADOS NO BANCO → DELETAR DIRETO, SEM CHAMAR API
            if status in FINALIZED_STATUSES:
                self.delete_fixture(fixture_id)
                continue

            # 2️⃣ NÃO FINALIZADOS → ATUALIZAR VIA API
            updated = self.fetch_fixture_status(fixture_id)

            if not updated:
                print(f"[STATUS] Fixture {fixture_id} não encontrado na API.")
                continue

            # 3️⃣ INDEPENDENTE DO STATUS → SEMPRE ATUALIZA (FT será deletado na próxima rodada)
            self.update_fixture_status(fixture_id, updated)
            print(f"[STATUS] Atualizado fixture {fixture_id} → {updated['status']}")

        print("[STATUS] Processamento concluído.")