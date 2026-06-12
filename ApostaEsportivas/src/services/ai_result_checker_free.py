from utils.db_utils import get_connection
from decimal import Decimal
from services.ai_result_checker_service import AIResultCheckerService


class AIResultCheckerFree:
    """Checker para picks_free (Pick do Dia). Profit em unidades (stake = 1u)."""

    def __init__(self):
        self._engine = AIResultCheckerService()

    def check_all_results(self):
        print("[CHECKER-FREE] Processando picks_free pendentes...")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute("""
            SELECT id, fixture_id, market, line, odd, home_team, away_team
            FROM picks_free
            WHERE result IS NULL
        """)
        rows = cur.fetchall()

        if not rows:
            print("[CHECKER-FREE] Nada pendente.")
            cur.close()
            conn.close()
            return 0

        processed = 0

        for (pk_id, fixture_id, market, line, odd, home_team, away_team) in rows:
            odd = Decimal(str(odd))

            stats = self._engine.get_fixture_result(fixture_id, cur)
            if not stats:
                print(f"[CHECKER-FREE] id={pk_id}: sem stats para fixture_id={fixture_id} — aguardando.")
                continue

            result, factor = self._engine.evaluate_pick(
                market, line, float(odd), stats, home_team, away_team
            )

            # Profit em unidades (stake = 1u)
            profit, _ = self._engine.calculate_profit(factor, Decimal("1"), Decimal("1"), odd)

            mt   = self._engine.detect_market_type(market)
            side = self._engine.detect_side(market, home_team, away_team)
            print(f"[CHECKER-FREE] id={pk_id} | {market} | {mt} | {side} | {result} | profit={float(profit):.2f}u")

            cur.execute("""
                UPDATE picks_free
                SET result = %s,
                    profit = %s
                WHERE id = %s
            """, (result, profit, pk_id))

            processed += 1

        conn.commit()
        cur.close()
        conn.close()

        print(f"[CHECKER-FREE] Finalizado. Processados: {processed}")
        return processed
