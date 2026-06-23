import time
from utils.db_utils import get_connection
from collectors.odds_collector_service import OddsCollectorService


class OddsMain:

    def __init__(self):
        self.odds_collector = OddsCollectorService()

    # ----------------------------------------------------------------------
    # FIXTURES PRE-MATCH (NS/TBD)
    # ----------------------------------------------------------------------
    def get_pre_match_fixtures(self):

        start = time.perf_counter()

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT fixture_id
            FROM fixtures
            WHERE status IN ('NS', 'TBD')
              AND match_datetime::date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '2 days'
        """)

        fixtures = [row[0] for row in cur.fetchall()]

        cur.close()
        conn.close()

        end = time.perf_counter()
        print(f"[TIMER] Buscar fixtures levou {end - start:.4f}s")

        return fixtures

    # ----------------------------------------------------------------------
    # LIMPAR TODAS AS ODDS (ULTRA RÁPIDO)
    # ----------------------------------------------------------------------
    def cleanup_all_odds(self):

        start = time.perf_counter()

        conn = get_connection()
        cur = conn.cursor()

        print("[ODDS] Limpando TODAS as odds do banco...")

        cur.execute("""
            TRUNCATE odds_values,
                     odds_markets,
                     odds_bookmakers
            RESTART IDENTITY CASCADE;
        """)

        conn.commit()
        cur.close()
        conn.close()

        end = time.perf_counter()

        print(f"[TIMER] Cleanup levou {end - start:.4f}s")
        print("[ODDS] Banco limpo com TRUNCATE.")

    # ----------------------------------------------------------------------
    # COLETAR ODDS
    # ----------------------------------------------------------------------
    def collect_odds(self):

        fixtures = self.get_pre_match_fixtures()
        print(f"[ODDS] Fixtures NS/TBD encontrados: {len(fixtures)}")

        total_start = time.perf_counter()

        for index, fixture_id in enumerate(fixtures, start=1):

            print(
                f"\n[ODDS] ({index}/{len(fixtures)}) Processando fixture {fixture_id}")

            fixture_start = time.perf_counter()

            # ---------------- API ----------------
            api_start = time.perf_counter()
            data = self.odds_collector.fetch_odds_by_fixture(fixture_id)
            api_time = time.perf_counter() - api_start
            print(f"[TIMER] API levou {api_time:.4f}s")

            if not data:
                print("[ODDS] Nenhuma odd encontrada.")
                continue

            bookmakers = data.get("bookmakers", [])
            if not bookmakers:
                print("[ODDS] Sem bookmakers.")
                continue

            # ---------------- SAVE ----------------
            save_start = time.perf_counter()
            self.odds_collector.save_odds(fixture_id, bookmakers)
            save_time = time.perf_counter() - save_start
            print(f"[TIMER] Save DB levou {save_time:.4f}s")

            fixture_time = time.perf_counter() - fixture_start
            print(f"[TIMER] TOTAL fixture {fixture_id}: {fixture_time:.4f}s")

        total_time = time.perf_counter() - total_start

        print(f"\n[TIMER] TOTAL GERAL coleta: {total_time:.4f}s")
        print("[ODDS] Coleta concluída.")

    # ----------------------------------------------------------------------
    # EXECUÇÃO FINAL
    # ----------------------------------------------------------------------
    def run(self):

        print("\n=========== COLETOR DE ODDS ===========")

        global_start = time.perf_counter()

        # 1️⃣ Limpa banco rápido
        self.cleanup_all_odds()

        # 2️⃣ Coleta odds
        self.collect_odds()

        global_time = time.perf_counter() - global_start

        print(f"\n[TIMER] EXECUÇÃO TOTAL: {global_time:.4f}s")
        print("=========== FINALIZADO ===========\n")


if __name__ == "__main__":
    OddsMain().run()
