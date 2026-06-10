from utils.db_utils import get_connection
import re
from decimal import Decimal


_ALLOWED_CHECKER_TABLES = frozenset({"picks_vip", "picks_free", "picks_alavancagem"})


class AIResultCheckerService:

    def __init__(self, table_name="picks_vip"):
        if table_name not in _ALLOWED_CHECKER_TABLES:
            raise ValueError(f"Tabela não permitida: {table_name!r}. Use: {_ALLOWED_CHECKER_TABLES}")
        self.table = table_name

    ##########################################################################
    # BUSCA ESTATÍSTICAS
    ##########################################################################
    def get_fixture_result(self, fixture_id, cur):

        cur.execute("""
            SELECT
                home_goals,
                away_goals,
                total_goals,
                home_corners,
                away_corners,
                total_corners,
                home_yellow_cards,
                away_yellow_cards,
                home_red_cards,
                away_red_cards
            FROM match_statistics
            WHERE fixture_id = %s
            LIMIT 1;
        """, (fixture_id,))

        row = cur.fetchone()

        if not row:
            return None

        return {
            "home_goals":    row[0],
            "away_goals":    row[1],
            "total_goals":   row[2],
            "home_corners":  row[3],
            "away_corners":  row[4],
            "total_corners": row[5],
            "home_yellow":   row[6],
            "away_yellow":   row[7],
            "home_red":      row[8],
            "away_red":      row[9],
            "home_cards":    row[6] + row[8],
            "away_cards":    row[7] + row[9],
            "total_cards":   (row[6] + row[8]) + (row[7] + row[9]),
            "total_yellow":  row[6] + row[7],
            "total_red":     row[8] + row[9],
        }

    ##########################################################################
    # PARSE DE LINHA
    ##########################################################################
    def parse_line(self, line):
        if not line:
            return None, None

        ln = line.lower().strip()
        ln = ln.replace("acima de", "over")
        ln = ln.replace("mais de", "over")
        ln = ln.replace("abaixo de", "under")
        ln = ln.replace("menos de", "under")

        if ln in ["yes", "sim"]:
            return "yes", None
        if ln in ["no", "nao", "não"]:
            return "no", None

        nums = re.findall(r"[+-]?\d+(?:\.\d+)?", ln.replace(",", "."))
        num_val = Decimal(nums[0]) if nums else None

        if "over" in ln:
            return "over", num_val
        if "under" in ln:
            return "under", num_val

        return None, num_val

    ##########################################################################
    # DETECTA MERCADO
    ##########################################################################
    def detect_market_type(self, market_name):
        name = market_name.lower()

        if "cart" in name:
            return "cards"
        if "esc" in name or "corner" in name:
            return "corners"
        if "gol" in name or "goal" in name:
            return "goals"
        if "btts" in name or "ambas" in name:
            return "btts"

        return "unknown"

    ##########################################################################
    # DETECTA LADO (CASA / VISITANTE / TOTAL)
    ##########################################################################
    def detect_side(self, market_name):
        name = market_name.lower()
        if any(w in name for w in ["casa", "home", "mandante"]):
            return "home"
        if any(w in name for w in ["visitante", "away", "fora"]):
            return "away"
        return "total"

    ##########################################################################
    # ENGINE ASIÁTICA
    ##########################################################################
    def evaluate_asian(self, value, line, op):

        value = Decimal(value)
        line = Decimal(line)

        if line % 1 == 0:
            if op == "over":
                if value > line:
                    return ("GREEN", Decimal("1"))
                elif value == line:
                    return ("PUSH", Decimal("0"))
                else:
                    return ("RED", Decimal("-1"))
            else:
                if value < line:
                    return ("GREEN", Decimal("1"))
                elif value == line:
                    return ("PUSH", Decimal("0"))
                else:
                    return ("RED", Decimal("-1"))

        if line % 1 == Decimal("0.5"):
            if op == "over":
                return ("GREEN", Decimal("1")) if value > line else ("RED", Decimal("-1"))
            else:
                return ("GREEN", Decimal("1")) if value < line else ("RED", Decimal("-1"))

        if line % 1 in [Decimal("0.25"), Decimal("0.75")]:
            low = line - Decimal("0.25")
            high = line + Decimal("0.25")

            if op == "over":
                if value > high:
                    return ("GREEN", Decimal("1"))
                elif value == high:
                    return ("HALF-WIN", Decimal("0.5"))
                elif value == low:
                    return ("HALF-LOSS", Decimal("-0.5"))
                else:
                    return ("RED", Decimal("-1"))
            else:
                if value < low:
                    return ("GREEN", Decimal("1"))
                elif value == low:
                    return ("HALF-WIN", Decimal("0.5"))
                elif value == high:
                    return ("HALF-LOSS", Decimal("-0.5"))
                else:
                    return ("RED", Decimal("-1"))

        return ("RED", Decimal("-1"))

    ##########################################################################
    # CALCULA PROFIT (AGORA COM STAKE_PCT)
    ##########################################################################
    def calculate_profit(self, factor, stake, stake_pct, odd):

        stake = Decimal(str(stake))
        stake_pct = Decimal(str(stake_pct))
        odd = Decimal(str(odd))

        if factor == Decimal("1"):
            return (
                stake * (odd - Decimal("1")),
                stake_pct * (odd - Decimal("1"))
            )

        if factor == Decimal("0.5"):
            return (
                (stake * (odd - Decimal("1"))) / Decimal("2"),
                (stake_pct * (odd - Decimal("1"))) / Decimal("2")
            )

        if factor == Decimal("0"):
            return Decimal("0"), Decimal("0")

        if factor == Decimal("-0.5"):
            return (
                -stake / Decimal("2"),
                -stake_pct / Decimal("2")
            )

        return -stake, -stake_pct

    ##########################################################################
    # EXECUÇÃO PRINCIPAL
    ##########################################################################
    def check_all_results(self):

        print(f"[CHECKER] Processando tabela: {self.table}")

        conn = get_connection()
        cur = conn.cursor()

        cur.execute(f"""
            SELECT id, fixture_id, market, line, odd, stake, stake_pct
            FROM {self.table}
            WHERE result IS NULL;
        """)

        rows = cur.fetchall()

        if not rows:
            print("[CHECKER] Nada pendente.")
            cur.close()
            conn.close()
            return 0

        processed = 0

        for (sid, fixture_id, market, line, odd, stake, stake_pct) in rows:

            stake = Decimal(str(stake))
            stake_pct = Decimal(str(stake_pct))
            odd = Decimal(str(odd))

            stats = self.get_fixture_result(fixture_id, cur)
            if not stats:
                print(f"[CHECKER] Sem stats para fixture_id={fixture_id} (id={sid}) — aguardando sync.")
                continue

            op, val = self.parse_line(line)
            mt   = self.detect_market_type(market)
            side = self.detect_side(market)

            if mt == "goals":
                stat_val = (
                    stats["home_goals"]  if side == "home" else
                    stats["away_goals"]  if side == "away" else
                    stats["total_goals"]
                )
                result, factor = self.evaluate_asian(stat_val, val, op)

            elif mt == "corners":
                stat_val = (
                    stats["home_corners"]  if side == "home" else
                    stats["away_corners"]  if side == "away" else
                    stats["total_corners"]
                )
                result, factor = self.evaluate_asian(stat_val, val, op)

            elif mt == "cards":
                # Amarelos específicos vs total de cartões
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
                result, factor = self.evaluate_asian(stat_val, val, op)

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
                result, factor = ("RED", Decimal("-1"))

            # 🔥 AGORA CORRETO
            profit, profit_pct = self.calculate_profit(factor, stake, stake_pct, odd)

            side_label = {"home": "CASA", "away": "VISIT", "total": "TOTAL"}.get(side, "TOTAL")
            print(f"[{sid}] {market} | {side_label} | {result}")

            cur.execute(f"""
                UPDATE {self.table}
                SET result = %s,
                    profit = %s,
                    profit_pct = %s,
                    checked_at = NOW()
                WHERE id = %s;
            """, (result, profit, profit_pct, sid))

            processed += 1

        conn.commit()
        cur.close()
        conn.close()

        print(f"[CHECKER] Finalizado. Processados: {processed}")

        return processed