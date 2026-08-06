"""
Verifica resultados da tabela picks_alavancagem.
- GREEN somente se TODOS os picks acertarem
- RED se qualquer pick falhar
- Profit em unidades (stake real calculado pelo frontend via Kelly/bankroll do usuário)
"""

from utils.db_utils import get_connection
from services import settlement
from services.ai_result_checker_service import AIResultCheckerService


class AIResultCheckerAlavancagem:

    def __init__(self):
        self._checker = AIResultCheckerService()

    def _check_pick(self, fixture_id, market, line, odd, cur,
                    home_team=None, away_team=None, market_type=None) -> str | None:
        """Resultado real da perna (GREEN/RED/PUSH/HALF-*), ou None sem dados.

        Nao achata mais PUSH/HALF em RED: uma perna anulada nao pode derrubar
        um bilhete que ainda paga. A combinacao e' feita em
        settlement.combine_legs(), que recalcula a odd do bilhete."""
        stats = self._checker.get_fixture_result(fixture_id, cur)
        if not stats:
            return None

        result, _ = self._checker.evaluate_pick(
            market, line, float(odd), stats, home_team, away_team,
            market_type=market_type,
        )
        return result

    def check_all_results(self):
        print("[CHECKER-ALAVANCAGEM] Processando picks pendentes...")

        conn = get_connection()
        cur  = conn.cursor()

        # Le as TRES pernas. Antes so' lia 1 e 2, e so' checava a 2 quando
        # tipo == 'combinacao' -- valor que o pipeline nunca grava (ele usa
        # 'simples'/'dupla'/'tripla', ver _TIPO_POR_TAMANHO em
        # engine_pipelines/alavancagem_pipeline.py). Resultado: toda 'dupla'
        # caia no ramo de perna unica e era graduada so' pela perna 1, mas
        # paga com odd_combined -- GREEN indevido e profit inflado sempre que
        # a perna 2 perdesse. Havia 3 duplas assim em producao (ids 21, 25 e
        # 31). A perna 3 nunca foi lida por ninguem.
        cur.execute("""
            SELECT id, tipo,
                   fixture_id_1, market_1, line_1, odd_1,
                   home_team_1, away_team_1,
                   fixture_id_2, market_2, line_2, odd_2,
                   home_team_2, away_team_2,
                   fixture_id_3, market_3, line_3, odd_3,
                   home_team_3, away_team_3,
                   odd_combined
            FROM picks_alavancagem
            WHERE result IS NULL
        """)
        rows = cur.fetchall()

        if not rows:
            print("[CHECKER-ALAVANCAGEM] Nada pendente.")
            cur.close()
            conn.close()
            return 0

        processed = 0

        for row in rows:
            (pk_id, tipo,
             fid1, mkt1, ln1, odd1, home1, away1,
             fid2, mkt2, ln2, odd2, home2, away2,
             fid3, mkt3, ln3, odd3, home3, away3,
             odd_combined) = row

            # Quem manda e' a presenca da perna no banco, nao o texto de
            # `tipo`: qualquer perna gravada TEM que ser conferida, seja o
            # rotulo 'dupla', 'tripla' ou 'combinacao'. Amarrar isso a um
            # valor especifico de `tipo` foi exatamente o que deixou as
            # duplas passarem sem checar a perna 2.
            pernas = [
                (i, fid, mkt, ln, odd, home, away)
                for i, (fid, mkt, ln, odd, home, away) in enumerate(
                    ((fid1, mkt1, ln1, odd1, home1, away1),
                     (fid2, mkt2, ln2, odd2, home2, away2),
                     (fid3, mkt3, ln3, odd3, home3, away3)), start=1)
                if fid is not None
            ]
            if not pernas:
                print(f"[CHECKER-ALAVANCAGEM] id={pk_id}: sem nenhuma perna gravada · pulando.")
                continue

            resultados = {}
            odds_pernas = {}
            aguardando = False
            for i, fid, mkt, ln, odd, home, away in pernas:
                r = self._check_pick(fid, mkt, ln, float(odd or 1), cur, home, away)
                if r is None:
                    print(f"[CHECKER-ALAVANCAGEM] id={pk_id}: sem stats para fixture_id_{i}={fid} · aguardando.")
                    aguardando = True
                    break
                resultados[i] = r
                odds_pernas[i] = odd
            if aguardando:
                continue

            ordem = sorted(resultados)
            final_result, profit, odd_efetiva = settlement.combine_legs(
                [resultados[i] for i in ordem],
                [odds_pernas[i] for i in ordem],
                odd_combined,
            )
            if final_result is None:
                print(f"[CHECKER-ALAVANCAGEM] id={pk_id}: nao foi possivel combinar "
                      f"as pernas ({resultados}) · segue pendente.")
                continue

            detalhe = " ".join(f"P{i}={resultados[i]}" for i in ordem)
            print(
                f"[CHECKER-ALAVANCAGEM] id={pk_id} ({tipo}) | "
                f"{detalhe} -> {final_result} | odd efetiva={odd_efetiva} | "
                f"profit={float(profit):.2f}u"
            )

            cur.execute("""
                UPDATE picks_alavancagem
                SET result     = %s,
                    profit     = %s,
                    checked_at = NOW()
                WHERE id = %s
            """, (final_result, profit, pk_id))

            processed += 1

        conn.commit()
        cur.close()
        conn.close()

        print(f"[CHECKER-ALAVANCAGEM] Finalizado. Processados: {processed}")
        return processed
