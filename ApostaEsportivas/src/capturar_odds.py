import time
from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from collectors.odds_collector_service import OddsCollectorService, prune_odds_snapshots


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

        # SO' o dia corrente. A janela era CURRENT_DATE + 2 dias, mas nenhum
        # consumidor le' odd de jogo futuro: os quatro pipelines do motor
        # filtram `match_datetime::date = CURRENT_DATE` (ver
        # engine_pipelines/*.py). Como o run() da TRUNCATE em odds_values antes
        # de coletar, a odd de D+1/D+2 era apagada no dia seguinte sem nunca ter
        # sido lida -- e recoletada. Cada jogo tinha as odds baixadas em 3 dias
        # seguidos, 2 requisicoes por vez (Bet365 + Betano): 6 requisicoes onde
        # 2 bastam.
        cur.execute(f"""
            SELECT fixture_id
            FROM fixtures
            WHERE status IN ('NS', 'TBD')
              AND match_datetime::date = {HOJE_BR}
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
    def cleanup_all_odds(self, truncar: bool = True):
        """TRUNCATE nas tres tabelas de cotacao ANTES de recoletar.

        `odds_snapshots` NAO entra aqui de proposito: ela e' append-only e
        existe justamente pra sobreviver a esta limpeza. O TRUNCATE com CASCADE
        e' seguro pra ela porque nao ha chave estrangeira ligando as duas -- se
        alguem adicionar uma no futuro, o historico de preco desaparece toda
        madrugada e o CLV volta a ficar vazio sem nenhum aviso.

        `truncar=False` roda so' a retencao dos retratos e deixa as cotacoes
        onde estao. E' o caminho do dia sem jogo pre-jogo pra coletar -- ver o
        comentario em run(), que e' onde essa decisao e' tomada.
        """
        start = time.perf_counter()

        conn = get_connection()
        cur = conn.cursor()

        if truncar:
            print("[ODDS] Limpando TODAS as odds do banco...")
            cur.execute("""
                TRUNCATE odds_values,
                         odds_markets,
                         odds_bookmakers
                RESTART IDENTITY CASCADE;
            """)

        # Retencao dos retratos: uma vez por execucao, nao por fixture. Roda
        # nos dois caminhos -- e' limpeza de historico, nao depende de haver
        # coleta hoje.
        removidos = prune_odds_snapshots(cur)
        if removidos:
            print(f"[ODDS] {removidos} retrato(s) antigo(s) de cotacao removido(s).")

        conn.commit()
        cur.close()
        conn.close()

        end = time.perf_counter()

        print(f"[TIMER] Cleanup levou {end - start:.4f}s")
        if truncar:
            print("[ODDS] Banco limpo com TRUNCATE.")

    # ----------------------------------------------------------------------
    # COLETAR ODDS
    # ----------------------------------------------------------------------
    def collect_odds(self, fixtures=None):

        # A lista pode vir pronta do run(), que precisa consultar ANTES de
        # decidir se trunca. Sem isso seriam duas queries iguais por rodada.
        if fixtures is None:
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

            # ---------------- SAVE (com retry em deadlock) ----------------
            save_start = time.perf_counter()
            for attempt in range(1, 4):
                try:
                    self.odds_collector.save_odds(fixture_id, bookmakers)
                    break
                except Exception as e:
                    if "deadlock" in str(e).lower() and attempt < 3:
                        print(f"[ODDS] Deadlock · tentativa {attempt}/3, aguardando 3s...")
                        time.sleep(3)
                    else:
                        print(f"[ODDS] Erro ao salvar fixture {fixture_id}: {e}")
                        break
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

        # 1️⃣ Descobre o que ha pra coletar ANTES de limpar qualquer coisa.
        #
        # A ordem era TRUNCATE-e-depois-coletar, incondicional (2026-08-11).
        # Num dia em que a coleta nao tinha nada a fazer -- todos os jogos de
        # hoje ja comecaram, entao nenhum esta mais em NS/TBD -- o TRUNCATE
        # apagava as cotacoes que estavam la e a coleta repunha ZERO. O efeito
        # nao era "rodei o pipeline a toa": era `odds_values` vazia, e os seis
        # geradores logo depois (VIP, free, multipla, alavancagem, faltas,
        # goleiros) ficando sem insumo e nao gerando NADA. Rodar o pipeline
        # fora de hora destruia o dia em vez de so' nao adiantar -- e como
        # cada etapa e' isolada e "termina OK", nada no log dizia isso.
        fixtures = self.get_pre_match_fixtures()

        if not fixtures:
            print("[ODDS] Nenhum jogo pré-jogo (NS/TBD) hoje em Brasília.")
            print("[ODDS] As cotações atuais ficam como estão · SEM truncar.")
            self.cleanup_all_odds(truncar=False)
            print(f"\n[TIMER] EXECUÇÃO TOTAL: {time.perf_counter() - global_start:.4f}s")
            print("=========== FINALIZADO ===========\n")
            return

        # 2️⃣ Limpa banco rápido
        self.cleanup_all_odds()

        # 3️⃣ Coleta odds
        self.collect_odds(fixtures)

        global_time = time.perf_counter() - global_start

        print(f"\n[TIMER] EXECUÇÃO TOTAL: {global_time:.4f}s")
        print("=========== FINALIZADO ===========\n")


if __name__ == "__main__":
    OddsMain().run()
