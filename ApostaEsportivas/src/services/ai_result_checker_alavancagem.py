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

    def _check_pick(self, fixture_id, market, line, odd, cur) -> str | None:
        """
        Avalia um pick individual. Retorna 'GREEN', 'RED' ou None (sem dados ainda).
        Para alavancagem, tratamos HALF-WIN/HALF-LOSS como RED (precisa acertar certo).
        """
        stats = self._checker.get_fixture_result(fixture_id, cur)
        if not stats:
            return None

        op, val = self._checker.parse_line(line)
        mt      = self._checker.detect_market_type(market)
        side    = self._checker.detect_side(market)

        if mt == "goals":
            stat_val = (
                stats["home_goals"]  if side == "home" else
                stats["away_goals"]  if side == "away" else
                stats["total_goals"]
            )
            result, _ = self._checker.evaluate_asian(stat_val, val, op)

        elif mt == "corners":
            stat_val = (
                stats["home_corners"]  if side == "home" else
                stats["away_corners"]  if side == "away" else
                stats["total_corners"]
            )
            result, _ = self._checker.evaluate_asian(stat_val, val, op)

        elif mt == "cards":
            if "amarelo" in market.lower() or "yellow" in market.lower():
                stat_val = (
                    stats["home_yellow"] if side == "home" else
                    stats["away_yellow"] if side == "away" else
                    stats["total_yellow"]
                )
            else:
                stat_val = (
                    stats["home_cards"] if side == "home" else
                    stats["away_cards"] if side == "away" else
                    stats["total_cards"]
                )
            result, _ = self._checker.evaluate_asian(stat_val, val, op)

        elif mt == "btts":
            if op == "yes":
                result = (
                    "GREEN" if stats["home_goals"] > 0 and stats["away_goals"] > 0
                    else "RED"
                )
            else:
                result = (
                    "GREEN" if stats["home_goals"] == 0 or stats["away_goals"] == 0
                    else "RED"
                )
        else:
            result = "RED"

        # Normaliza HALF-WIN / HALF-LOSS / PUSH → RED (alavancagem precisa de acerto pleno)
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
                   fixture_id_2, market_2, line_2, odd_2,
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
             fid1, mkt1, ln1, odd1,
             fid2, mkt2, ln2, odd2,
             odd_combined, stake) = row

            stake        = Decimal(str(stake))
            odd_combined = Decimal(str(odd_combined))

            # --- Pick 1 ---
            r1 = self._check_pick(fid1, mkt1, ln1, float(odd1), cur)
            if r1 is None:
                print(f"[CHECKER-ALAVANCAGEM] id={pk_id}: sem stats para fixture_id_1={fid1} — aguardando.")
                continue

            # --- Pick 2 (somente combinação) ---
            r2 = None
            if tipo == "combinacao" and fid2 is not None:
                r2 = self._check_pick(fid2, mkt2, ln2, float(odd2), cur)
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
                profit       = stake * (odd_combined - Decimal("1"))
                bankroll_after = stake + profit
            else:
                profit        = -stake
                bankroll_after = Decimal("0")  # serie zerada → próxima usa BANKROLL_INIT

            print(
                f"[CHECKER-ALAVANCAGEM] id={pk_id} ({tipo}) | "
                f"P1={r1} P2={r2} → {final_result} | "
                f"Stake: R${float(stake):.2f} | "
                f"Profit: R${float(profit):.2f} | "
                f"Bankroll após: R${float(bankroll_after):.2f}"
            )

            cur.execute("""
                UPDATE picks_alavancagem
                SET result        = %s,
                    profit        = %s,
                    bankroll_after = %s,
                    checked_at    = NOW()
                WHERE id = %s
            """, (final_result, profit, bankroll_after, pk_id))

            processed += 1

        conn.commit()
        cur.close()
        conn.close()

        print(f"[CHECKER-ALAVANCAGEM] Finalizado. Processados: {processed}")
        return processed
