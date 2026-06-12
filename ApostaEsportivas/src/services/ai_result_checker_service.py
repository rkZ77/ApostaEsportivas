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

        # Cartões (antes de "corner" para evitar falso positivo em "red card")
        if any(w in name for w in ["cart", "card", "amarelo", "yellow", "vermelho"]):
            return "cards"

        # Escanteios / Cantos
        if any(w in name for w in ["canto", "escanteio", "corner", " esc"]):
            return "corners"

        # Gols
        if any(w in name for w in ["gol", "goal"]):
            return "goals"

        # BTTS
        if any(w in name for w in ["btts", "ambas marcam", "ambas as equipes", "ambas"]):
            return "btts"

        # Resultado / 1X2
        if any(w in name for w in ["resultado", "1x2", "vencedor", "moneyline"]):
            return "result_1x2"

        # Dupla chance
        if any(w in name for w in ["dupla chance", "double chance"]):
            return "double_chance"

        # Handicap asiático / europeu
        if any(w in name for w in ["handicap", "handi", "h.a.", " ha "]):
            return "handicap"

        return "unknown"

    ##########################################################################
    # DETECTA LADO (CASA / VISITANTE / TOTAL)
    # home_team / away_team: nomes dos times para matching por nome
    ##########################################################################
    def detect_side(self, market_name, home_team=None, away_team=None):
        name = market_name.lower()

        if any(w in name for w in ["casa", "home", "mandante"]):
            return "home"
        if any(w in name for w in ["visitante", "away", "fora", "visita"]):
            return "away"

        # Tenta detectar pelo nome do time
        if home_team and home_team.lower() in name:
            return "home"
        if away_team and away_team.lower() in name:
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
            low  = line - Decimal("0.25")
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
    # RESULTADO 1X2
    ##########################################################################
    def evaluate_result_1x2(self, stats, raw_line):
        """Avalia resultado final. raw_line: '1', 'X', '2', 'casa', 'empate', 'visitante'."""
        ln = (raw_line or "").lower().strip()

        home_g = stats["home_goals"]
        away_g = stats["away_goals"]

        if home_g > away_g:
            actual = "1"
        elif home_g == away_g:
            actual = "x"
        else:
            actual = "2"

        if ln in ("1", "casa", "mandante", "home"):
            pred = "1"
        elif ln in ("x", "empate", "draw", "e"):
            pred = "x"
        elif ln in ("2", "visitante", "away", "fora"):
            pred = "2"
        else:
            return ("RED", Decimal("-1"))

        if pred == actual:
            return ("GREEN", Decimal("1"))
        return ("RED", Decimal("-1"))

    ##########################################################################
    # DUPLA CHANCE
    ##########################################################################
    def evaluate_double_chance(self, stats, raw_line):
        """Avalia dupla chance. raw_line: '1X', '12', 'X2' etc."""
        ln = (raw_line or "").lower().replace(" ", "").replace("ou", "").strip()

        home_g = stats["home_goals"]
        away_g = stats["away_goals"]

        if home_g > away_g:
            actual = "1"
        elif home_g == away_g:
            actual = "x"
        else:
            actual = "2"

        combos = {
            "1x": {"1", "x"}, "x1": {"1", "x"},
            "12": {"1", "2"}, "21": {"1", "2"},
            "x2": {"x", "2"}, "2x": {"x", "2"},
            # formas extensas
            "casaouempate": {"1", "x"},
            "casaouvisitante": {"1", "2"},
            "empateouvisitante": {"x", "2"},
        }

        for key, valid in combos.items():
            if key in ln:
                win = actual in valid
                return ("GREEN", Decimal("1")) if win else ("RED", Decimal("-1"))

        return ("RED", Decimal("-1"))

    ##########################################################################
    # HANDICAP ASIÁTICO (resultado)
    # market_name ex: "Handicap Asiático Casa -1.5", line ex: "-1.5"
    ##########################################################################
    def evaluate_handicap(self, stats, raw_line, side):
        """Handicap asiático aplicado ao resultado (gols)."""
        try:
            handicap = Decimal(str(raw_line).replace(",", ".").strip())
        except Exception:
            return ("RED", Decimal("-1"))

        home_g = Decimal(str(stats["home_goals"]))
        away_g = Decimal(str(stats["away_goals"]))

        if side == "home":
            adj_home = home_g + handicap
            if adj_home > away_g:
                return ("GREEN", Decimal("1"))
            elif adj_home == away_g:
                return ("PUSH", Decimal("0"))
            else:
                return ("RED", Decimal("-1"))
        else:
            adj_away = away_g + handicap
            if adj_away > home_g:
                return ("GREEN", Decimal("1"))
            elif adj_away == home_g:
                return ("PUSH", Decimal("0"))
            else:
                return ("RED", Decimal("-1"))

    ##########################################################################
    # RESOLVE STAT_VAL + RESULTADO para mercados over/under
    ##########################################################################
    def _resolve_overunder(self, stats, mt, side):
        """Retorna o valor estatístico correto para o mercado e lado."""
        if mt == "goals":
            return (
                stats["home_goals"]  if side == "home" else
                stats["away_goals"]  if side == "away" else
                stats["total_goals"]
            )
        if mt == "corners":
            return (
                stats["home_corners"]  if side == "home" else
                stats["away_corners"]  if side == "away" else
                stats["total_corners"]
            )
        if mt == "cards":
            return (
                stats["home_cards"] if side == "home" else
                stats["away_cards"] if side == "away" else
                stats["total_cards"]
            )
        return None

    ##########################################################################
    # AVALIA UM PICK COMPLETO
    # Aceita nome dos times para detect_side funcionar com times no nome do mercado
    ##########################################################################
    def evaluate_pick(self, market, line, odd, stats, home_team=None, away_team=None):
        """
        Avalia um pick individual. Retorna (result_str, factor, profit_str).
        result_str: GREEN / RED / PUSH / HALF-WIN / HALF-LOSS
        factor:     Decimal usado em calculate_profit
        """
        mt   = self.detect_market_type(market)
        side = self.detect_side(market, home_team, away_team)
        op, val = self.parse_line(line)

        if mt in ("goals", "corners"):
            stat_val = self._resolve_overunder(stats, mt, side)
            result, factor = self.evaluate_asian(stat_val, val, op)

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
            result, factor = self.evaluate_asian(stat_val, val, op)

        elif mt == "btts":
            if op == "yes":
                win = stats["home_goals"] > 0 and stats["away_goals"] > 0
            else:
                win = stats["home_goals"] == 0 or stats["away_goals"] == 0
            result, factor = ("GREEN", Decimal("1")) if win else ("RED", Decimal("-1"))

        elif mt == "result_1x2":
            result, factor = self.evaluate_result_1x2(stats, line)

        elif mt == "double_chance":
            result, factor = self.evaluate_double_chance(stats, line)

        elif mt == "handicap":
            result, factor = self.evaluate_handicap(stats, line, side)

        else:
            result, factor = ("RED", Decimal("-1"))

        return result, factor

    ##########################################################################
    # CALCULA PROFIT
    ##########################################################################
    def calculate_profit(self, factor, stake, stake_pct, odd):

        stake     = Decimal(str(stake))
        stake_pct = Decimal(str(stake_pct))
        odd       = Decimal(str(odd))

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
    # EXECUÇÃO PRINCIPAL (picks_vip)
    ##########################################################################
    def check_all_results(self):

        print(f"[CHECKER] Processando tabela: {self.table}")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute(f"""
            SELECT id, fixture_id, market, line, odd, stake, stake_pct,
                   home_team_name, away_team_name
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

        for (sid, fixture_id, market, line, odd, stake, stake_pct,
             home_team, away_team) in rows:

            stake     = Decimal(str(stake))     if stake     is not None else Decimal("1")
            stake_pct = Decimal(str(stake_pct)) if stake_pct is not None else Decimal("0")
            odd       = Decimal(str(odd))

            stats = self.get_fixture_result(fixture_id, cur)
            if not stats:
                print(f"[CHECKER] Sem stats para fixture_id={fixture_id} (id={sid}) — aguardando sync.")
                continue

            result, factor = self.evaluate_pick(market, line, float(odd), stats,
                                                home_team, away_team)

            profit, _ = self.calculate_profit(factor, stake, stake_pct, odd)

            mt   = self.detect_market_type(market)
            side = self.detect_side(market, home_team, away_team)
            side_label = {"home": "CASA", "away": "VISIT", "total": "TOTAL"}.get(side, "TOTAL")
            print(f"[{sid}] {market} | {mt} | {side_label} | {result}")

            try:
                cur.execute(f"""
                    UPDATE {self.table}
                    SET result = %s,
                        profit = %s
                    WHERE id = %s;
                """, (result, profit, sid))
                conn.commit()
            except Exception as e:
                print(f"[CHECKER] Erro ao salvar id={sid}: {e} — reconectando...")
                try: conn.rollback()
                except Exception: pass
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(f"""
                    UPDATE {self.table}
                    SET result = %s,
                        profit = %s
                    WHERE id = %s;
                """, (result, profit, sid))
                conn.commit()

            processed += 1

        cur.close()
        conn.close()

        print(f"[CHECKER] Finalizado. Processados: {processed}")

        return processed
