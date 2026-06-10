from utils.db_utils import get_connection
from decimal import Decimal
from services.ai_result_checker_service import AIResultCheckerService


class AIResultCheckerFree:
    """Checker para picks_free (Pick do Dia). Sem stake/stake_pct — profit em unidades."""

    def __init__(self):
        self._engine = AIResultCheckerService()

    def check_all_results(self):
        print("[CHECKER-FREE] Processando picks_free pendentes...")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute("""
            SELECT id, fixture_id, market, line, odd
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

        for (pk_id, fixture_id, market, line, odd) in rows:
            odd = Decimal(str(odd))

            stats = self._engine.get_fixture_result(fixture_id, cur)
            if not stats:
                print(f"[CHECKER-FREE] id={pk_id}: sem stats para fixture_id={fixture_id} — aguardando.")
                continue

            op, val = self._engine.parse_line(line)
            mt       = self._engine.detect_market_type(market)
            side     = self._engine.detect_side(market)

            if mt == "goals":
                stat_val = (
                    stats["home_goals"]  if side == "home" else
                    stats["away_goals"]  if side == "away" else
                    stats["total_goals"]
                )
                result, factor = self._engine.evaluate_asian(stat_val, val, op)

            elif mt == "corners":
                stat_val = (
                    stats["home_corners"]  if side == "home" else
                    stats["away_corners"]  if side == "away" else
                    stats["total_corners"]
                )
                result, factor = self._engine.evaluate_asian(stat_val, val, op)

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
                result, factor = self._engine.evaluate_asian(stat_val, val, op)

            elif mt == "btts":
                if op == "yes":
                    result, factor = (
                        ("GREEN", Decimal("1"))
                        if stats["home_goals"] > 0 and stats["away_goals"] > 0
                        else ("RED", Decimal("-1"))
                    )
                else:
                    result, factor = (
                        ("GREEN", Decimal("1"))
                        if stats["home_goals"] == 0 or stats["away_goals"] == 0
                        else ("RED", Decimal("-1"))
                    )
            else:
                result, factor = "RED", Decimal("-1")

            # Profit em unidades (stake = 1u)
            profit, _ = self._engine.calculate_profit(factor, Decimal("1"), Decimal("1"), odd)

            print(f"[CHECKER-FREE] id={pk_id} | {market} {line} | {result} | profit={float(profit):.2f}u")

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
