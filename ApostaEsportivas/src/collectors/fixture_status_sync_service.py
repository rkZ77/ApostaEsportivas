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

    # Limite da API-Football pro parametro `ids`: 20 fixtures por chamada.
    BULK_SIZE = 20

    def fetch_statuses_bulk(self, fixture_ids):
        """Status de ate 20 fixtures por requisicao, via /fixtures?ids=1-2-3.

        Substitui o /fixtures?id=X um-a-um: com 80 fixtures na tabela eram 80
        requisicoes por rodada, agora sao 4. Mesmo recurso que routers/live.py
        ja usava em _fetch_fixtures_bulk.

        Devolve {fixture_id: dados}. Fixture que a API nao retornar simplesmente
        nao aparece no dict -- o chamador trata como "nao encontrado", igual ao
        None do fetch_fixture_status.
        """
        out = {}
        ids = list(fixture_ids)

        for i in range(0, len(ids), self.BULK_SIZE):
            lote = ids[i:i + self.BULK_SIZE]
            try:
                r = requests.get(
                    API_URL, headers=HEADERS,
                    params={"ids": "-".join(str(f) for f in lote)}, timeout=20,
                )
                r.raise_for_status()
                response = r.json().get("response", [])
            except Exception as e:
                print(f"[STATUS] Erro no lote {lote}: {e}")
                continue

            for item in response:
                fixture = item.get("fixture") or {}
                fid = fixture.get("id")
                if fid is None:
                    continue
                out[fid] = {
                    "status": fixture["status"]["short"],
                    "match_datetime": fixture["date"],
                    "referee": fixture.get("referee"),
                }

        return out

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
        self.delete_fixtures([fixture_id])

    def delete_fixtures(self, fixture_ids):
        """Deleta em uma query só. Era uma conexão nova por fixture."""
        if not fixture_ids:
            return

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM fixtures WHERE fixture_id = ANY(%s)",
                    (list(fixture_ids),))

        conn.commit()
        cur.close()
        conn.close()

        print(f"[DELETE] {len(fixture_ids)} fixture(s) removido(s) do banco.")

    def process_all_fixtures(self):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT fixture_id, status, match_datetime FROM fixtures")
        fixture_rows = cur.fetchall()

        cur.close()
        conn.close()

        print(f"[STATUS] Encontrados {len(fixture_rows)} fixtures...")

        # 1️⃣ JÁ FINALIZADOS NO BANCO → DELETAR DIRETO, SEM CHAMAR API
        ja_finalizados = [fid for fid, status, _ in fixture_rows
                          if status in FINALIZED_STATUSES]
        if ja_finalizados:
            self.delete_fixtures(ja_finalizados)

        # 2️⃣ NÃO FINALIZADOS → ATUALIZAR VIA API, EM LOTE
        # Era uma requisição por fixture (/fixtures?id=X). Com a tabela cheia
        # (todos os jogos NS das 7 ligas) isso sozinho passava de 60 requisições
        # por rodada do pipeline. Em lote de 20 vira 3 ou 4.
        pendentes = [fid for fid, status, _ in fixture_rows
                     if status not in FINALIZED_STATUSES]
        if not pendentes:
            print("[STATUS] Processamento concluído.")
            return

        atualizados = self.fetch_statuses_bulk(pendentes)

        a_deletar = []
        for fixture_id in pendentes:
            updated = atualizados.get(fixture_id)

            if not updated:
                print(f"[STATUS] Fixture {fixture_id} não encontrado na API.")
                continue

            # 3️⃣ SE JÁ FINALIZOU → DELETA DIRETO; SENÃO ATUALIZA
            if updated["status"] in FINALIZED_STATUSES:
                a_deletar.append(fixture_id)
            else:
                self.update_fixture_status(fixture_id, updated)
                print(f"[STATUS] Atualizado fixture {fixture_id} → {updated['status']}")

        if a_deletar:
            self.delete_fixtures(a_deletar)

        print("[STATUS] Processamento concluído.")