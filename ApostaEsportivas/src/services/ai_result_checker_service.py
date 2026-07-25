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
                home_goals, away_goals, total_goals,
                home_corners, away_corners, total_corners,
                home_yellow_cards, away_yellow_cards,
                home_red_cards, away_red_cards,
                home_goals_ht, away_goals_ht,
                status,
                home_offsides, away_offsides
            FROM match_statistics
            WHERE fixture_id = %s
            LIMIT 1;
        """, (fixture_id,))

        row = cur.fetchone()

        if not row:
            return None

        hy, hr = (row[6] or 0), (row[8] or 0)
        ay, ar = (row[7] or 0), (row[9] or 0)
        hg_ht  = row[10]
        ag_ht  = row[11]
        h_off, a_off = row[13], row[14]

        return {
            "home_goals":    row[0] or 0,
            "away_goals":    row[1] or 0,
            "total_goals":   row[2] or 0,
            "home_corners":  row[3] or 0,
            "away_corners":  row[4] or 0,
            "total_corners": row[5] or 0,
            "home_yellow":   hy,
            "away_yellow":   ay,
            "home_red":      hr,
            "away_red":      ar,
            # cartao vermelho vale 2 pontos (mesma convencao usada pra
            # calcular a taxa historica em stats_model._cards_points --
            # gradear com uma regra e prever com outra deixaria a
            # confidence do pick sem relacao com o que de fato decide o
            # resultado real. "home_yellow"/"away_yellow"/"total_yellow"
            # acima continuam contagem pura, pros mercados so' de amarelo).
            "home_cards":    hy + 2 * hr,
            "away_cards":    ay + 2 * ar,
            "status":        row[12],
            "total_cards":   hy + 2 * hr + ay + 2 * ar,
            "total_yellow":  hy + ay,
            "total_red":     hr + ar,
            "home_goals_ht": hg_ht,
            "away_goals_ht": ag_ht,
            "total_goals_ht": (hg_ht or 0) + (ag_ht or 0) if hg_ht is not None else None,
            "home_offsides": h_off or 0,
            "away_offsides": a_off or 0,
            "total_offsides": (h_off or 0) + (a_off or 0),
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
    # DETECTA SE É MERCADO DE 1° TEMPO
    ##########################################################################
    @staticmethod
    def _is_first_half(market_name: str) -> bool:
        n = market_name.lower()
        return any(k in n for k in [
            "1° tempo", "1º tempo", "primeiro tempo",
            "1st half", "first half", "halftime", "half time",
            "ht -", "- ht", "(ht)", "[ht]",
        ])

    ##########################################################################
    # DETECTA MERCADO
    # Retorna tipo base (sem sufixo _ht); use _is_first_half() separado.
    ##########################################################################
    def detect_market_type(self, market_name):
        name = market_name.lower()

        # Remove qualificadores de tempo para não confundir keywords
        for strip in ["1° tempo", "1º tempo", "primeiro tempo", "1st half",
                      "first half", "halftime", "half time", "2° tempo", "2º tempo"]:
            name = name.replace(strip, "")

        # Cartões (antes de corner para evitar "red card")
        if any(w in name for w in ["cart", "card", "amarelo", "yellow", "vermelho"]):
            return "cards"

        # Escanteios
        if any(w in name for w in ["canto", "escanteio", "corner", " esc", "asian handicap corner"]):
            return "corners"

        # BTTS
        if any(w in name for w in ["btts", "ambas marcam", "ambas as equipes", "ambas", "both teams"]):
            return "btts"

        # Gols
        if any(w in name for w in ["gol", "goal", "total de gol"]):
            return "goals"

        # Impedimentos (achado rodando o motor deterministico contra jogos
        # reais: o motor sugere esse mercado -- pick_engine.classify_market()
        # ja suporta -- mas nada aqui sabia resolver o resultado real, o pick
        # ficava pra sempre com result=NULL)
        if any(w in name for w in ["impediment", "offside"]):
            return "offsides"

        # Dupla Chance  (1X / X2 / 12 / "Casa ou Empate" etc.)
        dc_kws = ["dupla chance", "double chance",
                  "casa ou empate", "empate ou casa", "empate ou visit",
                  "visit ou empate", "casa ou visit", "visit ou casa",
                  "1x2x", "1x ", "x2 ", " 1x", " x2", "(1x)", "(x2)", "(12)"]
        if any(w in name for w in dc_kws):
            return "double_chance"

        # Classificação (mata-mata) · quem avança de fase (90min + prorrogação + pênaltis)
        if any(w in name for w in ["classificaç", "classificacao", "to qualify", "qualify", "passagem de fase"]):
            return "to_qualify"

        # Resultado / 1X2
        if any(w in name for w in ["resultado", "1x2", "vencedor", "moneyline",
                                    "match winner", "full time result"]):
            return "result_1x2"

        # Handicap asiático / europeu
        if any(w in name for w in ["handicap", "handi", "h.a.", " ha "]):
            return "handicap"

        # Over/Under genérico → trata como gols se nada mais encaixou
        if any(w in name for w in ["over", "under", "acima", "abaixo", "mais de", "menos de"]):
            return "goals"

        return "unknown"

    ##########################################################################
    # DETECTA LADO (CASA / VISITANTE / TOTAL)
    ##########################################################################
    def detect_side(self, market_name, home_team=None, away_team=None):
        name = market_name.lower()

        if any(w in name for w in ["casa", "home", "mandante"]):
            return "home"
        if any(w in name for w in ["visitante", "away", "fora", "visita"]):
            return "away"

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
    # RESULTADO 1X2  (aceita também variantes de dupla chance na linha)
    ##########################################################################
    def evaluate_result_1x2(self, hg, ag, raw_line, market=""):
        """hg/ag: gols casa/fora. raw_line: '1', 'X', '2', '1X', 'Casa ou Empate', etc."""
        ln  = (raw_line or "").lower().replace(" ", "").replace("ou", "").strip()
        mkt = (market or "").lower()

        if hg > ag:   actual = "1"
        elif hg == ag: actual = "x"
        else:          actual = "2"

        # Dupla chance dentro do evaluate_result_1x2. As chaves "home/away" etc
        # cobrem o value_name cru que a API-Football devolve pro mercado Double
        # Chance ("Home/Away", "Home/Draw", "Draw/Away") -- achado rodando o
        # motor deterministico contra jogos reais: esse pick nunca resolvia
        # GREEN/RED porque so' as variantes PT-BR/compactas existiam aqui.
        combos = {
            "1x": {"1", "x"}, "x1": {"1", "x"},
            "12": {"1", "2"}, "21": {"1", "2"},
            "x2": {"x", "2"}, "2x": {"x", "2"},
            "casaempate": {"1", "x"}, "empatevisitante": {"x", "2"},
            "casavisitante": {"1", "2"},
            "home/away": {"1", "2"}, "away/home": {"1", "2"},
            "home/draw": {"1", "x"}, "draw/home": {"1", "x"},
            "draw/away": {"x", "2"}, "away/draw": {"x", "2"},
        }
        for key, valid in combos.items():
            if key in ln or key in mkt.replace(" ", ""):
                return ("GREEN", Decimal("1")) if actual in valid else ("RED", Decimal("-1"))

        # Resultado simples
        if ln in ("1", "casa", "mandante", "home"):
            pred = "1"
        elif ln in ("x", "empate", "draw", "e"):
            pred = "x"
        elif ln in ("2", "visitante", "away", "fora"):
            pred = "2"
        else:
            return (None, Decimal("0"))  # linha não reconhecida → não resolve

        return ("GREEN", Decimal("1")) if pred == actual else ("RED", Decimal("-1"))

    ##########################################################################
    # DUPLA CHANCE
    ##########################################################################
    def evaluate_double_chance(self, hg, ag, raw_line, market=""):
        return self.evaluate_result_1x2(hg, ag, raw_line, market)

    ##########################################################################
    # HANDICAP ASIÁTICO (resultado)
    ##########################################################################
    def evaluate_handicap(self, hg, ag, raw_line, val, side, home_team=None, away_team=None):
        """Handicap Asiatico (linha inteira/meia/quarto-de-bola).

        Bug real encontrado com pick em producao (Handicap Asiatico, linha
        "Home +0.25"): a linha inteira era jogada direto no Decimal(), o
        parse estourava excecao e a pick caia sempre em RED, mercado nenhum
        resolvido de fato -- corrigido usando o `val` ja extraido em
        parse_line() (so o numero) em vez de reparsear o texto cru aqui.

        O lado (casa/fora) normalmente vem embutido no proprio texto da
        linha ("Home +0.25"), nao no nome do mercado -- extrai daqui, com o
        `side` de detect_side(market, ...) so como ultimo fallback (usado
        pelas chamadas de handicap de escanteios/gols, onde raw_line e so o
        numero sem indicacao de lado).

        Tambem cobre quarto-de-bola (.25/.75), que a versao anterior nao
        suportava: divide em duas metades de meia-bola e combina os dois
        resultados em HALF-WIN/HALF-LOSS quando aplicavel.
        """
        if val is None:
            return (None, Decimal("0"))
        handicap = val

        raw_lower = str(raw_line or "").lower()
        resolved_side = side
        if any(k in raw_lower for k in ("home", "casa", "mandante")):
            resolved_side = "home"
        elif any(k in raw_lower for k in ("away", "visitante", "fora", "visita")):
            resolved_side = "away"
        elif home_team and home_team.lower() in raw_lower:
            resolved_side = "home"
        elif away_team and away_team.lower() in raw_lower:
            resolved_side = "away"

        home_g = Decimal(str(hg))
        away_g = Decimal(str(ag))

        def _straight(h):
            if resolved_side == "away":
                adj, opp = away_g + h, home_g
            else:
                adj, opp = home_g + h, away_g
            if adj > opp:   return Decimal("1")
            if adj == opp:  return Decimal("0")
            return Decimal("-1")

        quarters = handicap * 4
        if quarters == quarters.to_integral_value() and int(quarters) % 2 != 0:
            half_a = (quarters - 1) / 4
            half_b = (quarters + 1) / 4
            factor = (_straight(half_a) + _straight(half_b)) / 2
        else:
            factor = _straight(handicap)

        result = {
            Decimal("1"): "GREEN", Decimal("0.5"): "HALF-WIN", Decimal("0"): "PUSH",
            Decimal("-0.5"): "HALF-LOSS", Decimal("-1"): "RED",
        }[factor]
        return (result, factor)

    ##########################################################################
    # RESOLVE STAT_VAL para mercados over/under
    ##########################################################################
    def _resolve_overunder(self, stats, mt, side, is_ht=False):
        if mt == "goals":
            if is_ht:
                hg = stats.get("home_goals_ht")
                ag = stats.get("away_goals_ht")
                if hg is None or ag is None:
                    return None  # dados de 1° tempo ainda não disponíveis
                return hg if side == "home" else ag if side == "away" else hg + ag
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
        if mt == "offsides":
            return (
                stats["home_offsides"] if side == "home" else
                stats["away_offsides"] if side == "away" else
                stats["total_offsides"]
            )
        return None

    ##########################################################################
    # AVALIA UM PICK COMPLETO
    # Retorna (None, Decimal("0")) quando não é possível determinar o resultado.
    ##########################################################################
    def evaluate_pick(self, market, line, odd, stats, home_team=None, away_team=None):
        mt     = self.detect_market_type(market)
        is_ht  = self._is_first_half(market)
        side   = self.detect_side(market, home_team, away_team)
        op, val = self.parse_line(line)

        # Mercados de over/under (gols totais/escanteios/cartões) são
        # liquidados pelas casas com base no TEMPO NORMAL (90min) -- mas
        # /fixtures/statistics da API-Football devolve o jogo inteiro
        # (incluindo prorrogação/pênaltis) sem separar por período. Sem
        # como recalcular o número certo, anula (PUSH) em vez de arriscar
        # um RED/GREEN errado. Mercados de 1° tempo não são afetados (HT é
        # sempre tempo normal, por definição).
        if mt in ("goals", "corners", "cards", "offsides") and not is_ht and stats.get("status") in ("AET", "PEN"):
            return ("PUSH", Decimal("0"))

        # Seleciona gols corretos (1° tempo ou jogo completo)
        if is_ht:
            hg = stats.get("home_goals_ht")
            ag = stats.get("away_goals_ht")
            if hg is None or ag is None:
                return (None, Decimal("0"))  # aguardando dados de HT
        else:
            hg = stats["home_goals"]
            ag = stats["away_goals"]

        if mt in ("goals", "corners"):
            stat_val = self._resolve_overunder(stats, mt, side, is_ht)
            if stat_val is None or val is None:
                return (None, Decimal("0"))
            if op in ("over", "under"):
                result, factor = self.evaluate_asian(stat_val, val, op)
            else:
                # Asian handicap sem over/under (ex: "Corners Asian Handicap Away -5.5")
                if mt == "corners":
                    result, factor = self.evaluate_handicap(
                        stats["home_corners"], stats["away_corners"], str(val), val, side,
                        home_team, away_team
                    )
                else:
                    result, factor = self.evaluate_handicap(hg, ag, str(val), val, side, home_team, away_team)

        elif mt == "cards":
            if val is None:
                return (None, Decimal("0"))
            is_yellow = any(k in market.lower() for k in ["amarelo", "yellow"])
            if side == "home":
                stat_val = stats["home_yellow"] if is_yellow else stats["home_cards"]
            elif side == "away":
                stat_val = stats["away_yellow"] if is_yellow else stats["away_cards"]
            else:
                stat_val = stats["total_yellow"] if is_yellow else stats["total_cards"]
            result, factor = self.evaluate_asian(stat_val, val, op)

        elif mt == "offsides":
            stat_val = self._resolve_overunder(stats, mt, side, is_ht)
            if stat_val is None or val is None:
                return (None, Decimal("0"))
            result, factor = self.evaluate_asian(stat_val, val, op)

        elif mt == "btts":
            both = hg > 0 and ag > 0
            if op in ("yes", None) and line and "sim" in (line or "").lower():
                result, factor = ("GREEN", Decimal("1")) if both else ("RED", Decimal("-1"))
            elif op == "no" or (line and any(k in (line or "").lower() for k in ["no", "não", "nao"])):
                result, factor = ("RED", Decimal("-1")) if both else ("GREEN", Decimal("1"))
            else:
                return (None, Decimal("0"))  # linha BTTS não reconhecida → não resolve

        elif mt == "to_qualify":
            # Lado vem do campo line ("Casa"/"Visitante"/"Home"/"Away"), não do nome do mercado.
            # Se o placar (90min+prorrogação) está empatado, o jogo foi decidido nos pênaltis ·
            # essa informação não é capturada em match_statistics hoje, então não arriscamos
            # um GREEN/RED errado e deixamos pendente para conferência manual.
            side_line = (str(line) or "").strip().lower()
            if hg == ag:
                return (None, Decimal("0"))
            if side_line in ("casa", "home", "mandante"):
                result, factor = ("GREEN", Decimal("1")) if hg > ag else ("RED", Decimal("-1"))
            elif side_line in ("visitante", "away", "fora"):
                result, factor = ("GREEN", Decimal("1")) if ag > hg else ("RED", Decimal("-1"))
            else:
                return (None, Decimal("0"))

        elif mt in ("result_1x2", "double_chance"):
            result, factor = self.evaluate_result_1x2(hg, ag, line, market)

        elif mt == "handicap":
            result, factor = self.evaluate_handicap(hg, ag, line, val, side, home_team, away_team)

        else:
            return (None, Decimal("0"))  # mercado desconhecido → não resolve

        return result, factor

    ##########################################################################
    # CALCULA PROFIT
    ##########################################################################
    def calculate_profit(self, factor, odd):
        """Calcula lucro por 1 unidade apostada. Stake real é calculado por usuário via Kelly."""
        odd = Decimal(str(odd))
        if factor == Decimal("1"):    return odd - Decimal("1")
        if factor == Decimal("0.5"):  return (odd - Decimal("1")) / Decimal("2")
        if factor == Decimal("0"):    return Decimal("0")
        if factor == Decimal("-0.5"): return Decimal("-0.5")
        return Decimal("-1")

    ##########################################################################
    # EXECUÇÃO PRINCIPAL (picks_vip)
    ##########################################################################
    def check_all_results(self):

        print(f"[CHECKER] Processando tabela: {self.table}")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute(f"""
            SELECT id, fixture_id, market, line, odd,
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

        for (sid, fixture_id, market, line, odd,
             home_team, away_team) in rows:

            odd = Decimal(str(odd))

            stats = self.get_fixture_result(fixture_id, cur)
            if not stats:
                print(f"[CHECKER] Sem stats para fixture_id={fixture_id} (id={sid}) · aguardando sync.")
                continue

            result, factor = self.evaluate_pick(market, line, float(odd), stats,
                                                home_team, away_team)

            if result is None:
                print(f"[CHECKER] id={sid}: mercado nao reconhecido ou dados HT ausentes - pulando.")
                continue

            profit = self.calculate_profit(factor, odd)

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
                print(f"[CHECKER] Erro ao salvar id={sid}: {e} · reconectando...")
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
