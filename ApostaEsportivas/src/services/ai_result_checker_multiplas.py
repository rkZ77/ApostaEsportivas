from utils.db_utils import get_connection
from decimal import Decimal
import json
import re


_ALLOWED_MULTIPLAS_TABLES = frozenset({"picks_multiplas"})


class AIMultiplasCheckerService:

    def __init__(self, table_name="picks_multiplas"):
        if table_name not in _ALLOWED_MULTIPLAS_TABLES:
            raise ValueError(f"Tabela não permitida: {table_name!r}. Use: {_ALLOWED_MULTIPLAS_TABLES}")
        self.table = table_name

    ##########################################################################
    # BUSCA STATS
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
            "home_goals": row[0],
            "away_goals": row[1],
            "total_goals": row[2],
            "home_corners": row[3],
            "away_corners": row[4],
            "total_corners": row[5],
            "home_cards": row[6] + row[8],
            "away_cards": row[7] + row[9],
            "total_cards": (row[6] + row[8]) + (row[7] + row[9]),
        }

    ##########################################################################
    # PARSE
    ##########################################################################
    def parse_line(self, line):

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
    # ASIAN SIMPLIFICADO
    ##########################################################################
    def evaluate_asian(self, value, line, op):

        value = Decimal(value)
        line = Decimal(line)

        if line % 1 == 0:
            if op == "over":
                if value > line:
                    return "GREEN"
                elif value == line:
                    return "PUSH"
                else:
                    return "RED"
            else:
                if value < line:
                    return "GREEN"
                elif value == line:
                    return "PUSH"
                else:
                    return "RED"

        if line % 1 == Decimal("0.5"):
            if op == "over":
                return "GREEN" if value > line else "RED"
            else:
                return "GREEN" if value < line else "RED"

        if line % 1 in [Decimal("0.25"), Decimal("0.75")]:
            low = line - Decimal("0.25")
            high = line + Decimal("0.25")

            if op == "over":
                if value > high:
                    return "GREEN"
                elif value in [low, high]:
                    return "HALF"
                else:
                    return "RED"
            else:
                if value < low:
                    return "GREEN"
                elif value in [low, high]:
                    return "HALF"
                else:
                    return "RED"

        return "RED"

    ##########################################################################
    # AVALIA UMA LEG
    ##########################################################################
    def evaluate_leg(self, leg, cur):

        stats = self.get_fixture_result(leg["fixture_id"], cur)
        if not stats:
            print(f"[CHECKER MULTIPLAS] Sem stats para fixture_id={leg['fixture_id']} — leg pulada como RED.")
            return "RED"

        op, val = self.parse_line(leg["line"])
        mt = self.detect_market_type(leg["market"])

        if mt == "goals":
            return self.evaluate_asian(stats["total_goals"], val, op)

        elif mt == "corners":
            return self.evaluate_asian(stats["total_corners"], val, op)

        elif mt == "cards":
            return self.evaluate_asian(stats["total_cards"], val, op)

        elif mt == "btts":
            if op == "yes":
                return "GREEN" if (stats["home_goals"] > 0 and stats["away_goals"] > 0) else "RED"
            else:
                return "GREEN" if (stats["home_goals"] == 0 or stats["away_goals"] == 0) else "RED"

        return "RED"

    ##########################################################################
    # MAIN
    ##########################################################################
    def check_all_results(self):

        print(f"[CHECKER MULTIPLAS] Processando tabela: {self.table}")

        conn = get_connection()
        cur = conn.cursor()

        cur.execute(f"""
            SELECT id, games, stake, stake_pct, total_odd
            FROM {self.table}
            WHERE result IS NULL;
        """)

        rows = cur.fetchall()

        if not rows:
            print("[CHECKER MULTIPLAS] Nada pendente.")
            cur.close()
            conn.close()
            return 0

        processed = 0

        for mid, games_json, stake, stake_pct, total_odd in rows:

            # 🔥 TRATA JSON (string ou já lista)
            if isinstance(games_json, str):
                games = json.loads(games_json)
            else:
                games = games_json

            final_result = "GREEN"

            for leg in games:
                result = self.evaluate_leg(leg, cur)

                if result == "RED":
                    final_result = "RED"
                    break

            stake = Decimal(str(stake))
            stake_pct = Decimal(str(stake_pct))
            total_odd = Decimal(str(total_odd))

            # 🔥 PROFIT CORRETO (BASEADO NA BANCA)
            if final_result == "RED":
                profit = -stake
                profit_pct = -stake_pct
            else:
                profit = stake * (total_odd - Decimal("1"))
                profit_pct = stake_pct * (total_odd - Decimal("1"))

            print(f"{mid} - {final_result}")

            cur.execute(f"""
                UPDATE {self.table}
                SET result = %s,
                    profit = %s,
                    profit_pct = %s
                WHERE id = %s;
            """, (final_result, profit, profit_pct, mid))

            processed += 1

        conn.commit()
        cur.close()
        conn.close()

        print(f"[CHECKER MULTIPLAS] Finalizado. Processados: {processed}")

        return processed