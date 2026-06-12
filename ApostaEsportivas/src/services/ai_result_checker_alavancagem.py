"""
Verifica resultados da tabela picks_alavancagem.
- Alavancagem pode ter 1 ou 2 picks (tipo 'simples' ou 'combinacao')
- GREEN somente se TODOS os picks acertarem
- RED se qualquer pick falhar
- Atualiza: result, profit, bankroll_after
"""

from utils.db_utils import get_connection
from decimal import Decimal
from services.ai_result_checker_service import AIResultCheckerService


class AIResultCheckerAlavancagem:

    def __init__(self):
        self._checker = AIResultCheckerService()

    def _check_pick(self, fixture_id, market, line, odd, cur,
                    home_team=None, away_team=None) -> str | None:
        """
        Avalia um pick individual. Retorna 'GREEN', 'RED' ou None (sem dados ainda).
        Para alavancagem, tratamos HALF-WIN/HALF-LOSS/PUSH como RED.
        """
        stats = self._checker.get_fixture_result(fixture_id, cur)
        if not stats:
            return None

        result, _ = self._checker.evaluate_pick(
            market, line, float(odd), stats, home_team, away_team
        )

        # Alavancagem precisa de acerto pleno
        if result not in ("GREEN", "RED"):
            result = "RED"

        return result

    def check_all_results(self):
        print("[CHECKER-ALAVANCAGEM] Processando picks pendentes...")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute("""
            SELECT id, tipo,
                   fixture_id_1, market_1, line_1, odd_1,
                   home_team_1, away_team_1,
                   fixture_id_2, market_2, line_2, odd_2,
                   home_team_2, away_team_2,
                   odd_combined, stake
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
             odd_combined, stake) = row

            stake        = Decimal(str(stake))
            odd_combined = Decimal(str(odd_combined))

            # --- Pick 1 ---
            r1 = self._check_pick(fid1, mkt1, ln1, float(odd1), cur, home1, away1)
            if r1 is None:
                print(f"[CHECKER-ALAVANCAGEM] id={pk_id}: sem stats para fixture_id_1={fid1} — aguardando.")
                continue

            # --- Pick 2 (somente combinação) ---
            r2 = None
            if tipo == "combinacao" and fid2 is not None:
                r2 = self._check_pick(fid2, mkt2, ln2, float(odd2), cur, home2, away2)
                if r2 is None:
                    print(f"[CHECKER-ALAVANCAGEM] id={pk_id}: sem stats para fixture_id_2={fid2} — aguardando.")
                    continue

            # --- Resultado final ---
            if tipo == "combinacao":
                final_result = "GREEN" if r1 == "GREEN" and r2 == "GREEN" else "RED"
            else:
                final_result = r1

            # --- Profit e bankroll ---
            if final_result == "GREEN":
                profit         = stake * (odd_combined - Decimal("1"))
                bankroll_after = stake + profit
            else:
                profit         = -stake
                bankroll_after = Decimal("0")  # série zerada

            print(
                f"[CHECKER-ALAVANCAGEM] id={pk_id} ({tipo}) | "
                f"P1={r1} P2={r2} → {final_result} | "
                f"Stake: R${float(stake):.2f} | "
                f"Profit: R${float(profit):.2f} | "
                f"Bankroll após: R${float(bankroll_after):.2f}"
            )

            cur.execute("""
                UPDATE picks_alavancagem
                SET result         = %s,
                    profit         = %s,
                    bankroll_after = %s,
                    checked_at     = NOW()
                WHERE id = %s
            """, (final_result, profit, bankroll_after, pk_id))

            processed += 1

        conn.commit()
        cur.close()
        conn.close()

        print(f"[CHECKER-ALAVANCAGEM] Finalizado. Processados: {processed}")
        return processed
