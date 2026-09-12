import os
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from utils.db_utils import get_connection
from dotenv import load_dotenv, find_dotenv
from utils.api_client import buscar, ApiFootballError, ApiQuotaEsgotada

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")

FINALIZED_STATUSES = {
    "FT", "AET", "PEN", "CANC", "PST", "ABD", "WO"
}

TZ_BR = ZoneInfo("America/Sao_Paulo")


def _para_br_naive(dt_str: str) -> datetime:
    """ISO da API (UTC) -> datetime ingenuo em horario de Brasilia.

    Este service gravava `fixture["date"]` CRU em fixtures.match_datetime,
    enquanto o fixture_collector_service grava a mesma coluna convertida pra
    Brasilia (convert_utc_to_br_naive). Duas convencoes na mesma coluna: o
    valor final dependia de qual dos dois rodou por ultimo, e o horario do
    jogo aparecia 3 horas adiantado sempre que o status sync tinha rodado
    depois. Agora os dois gravam BR.
    """
    dt = datetime.fromisoformat((dt_str or "").replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_BR).replace(tzinfo=None)


class FixtureStatusSyncService:

    def __init__(self):
        pass

    def fetch_fixture_status(self, fixture_id):
        """Status do jogo, ou None quando a API nao conhece esse fixture.

        `buscar` levanta em falha, entao `None` volta a significar uma coisa
        so'. Importa aqui porque o status errado nao fica parado: fixture que
        nao atualiza pra FT continua entrando nas consultas de jogo pendente,
        e fixture que nao atualiza pra PST/CANC segue elegivel a pick.
        """
        response = buscar(
            "fixtures", {"id": fixture_id}, origem="coletor_status")
        if not response:
            return None

        fixture = response[0]["fixture"]

        return {
            "status": fixture["status"]["short"],
            "match_datetime": _para_br_naive(fixture["date"]),
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
                response = buscar(
                    "fixtures",
                    {"ids": "-".join(str(f) for f in lote)},
                    origem="coletor_status",
                )
            except ApiQuotaEsgotada:
                # Os lotes seguintes so' produziriam a mesma recusa.
                print(f"[STATUS] Cota esgotada; {len(ids) - i} fixture(s) "
                      f"ficaram sem checagem de status nesta rodada.")
                break
            except ApiFootballError as e:
                # Lote que falha continua sendo pulado (um lote ruim nao pode
                # travar a sincronizacao inteira), mas agora o `except` pega
                # SO' falha de API -- antes era `except Exception`, que engolia
                # junto o KeyError de um payload em formato inesperado e fazia
                # defeito de parsing parecer instabilidade de rede.
                print(f"[STATUS] Erro no lote {lote}: {e}")
                continue

            for item in response:
                fixture = item.get("fixture") or {}
                fid = fixture.get("id")
                if fid is None:
                    continue
                out[fid] = {
                    "status": fixture["status"]["short"],
                    "match_datetime": _para_br_naive(fixture["date"]),
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