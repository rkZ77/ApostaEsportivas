from utils.db_utils import get_connection
from services.ai_result_checker_service import AIResultCheckerService
from decimal import Decimal
import json


_ALLOWED_MULTIPLAS_TABLES = frozenset({"picks_multiplas"})


class AIMultiplasCheckerService:

    def __init__(self, table_name="picks_multiplas"):
        if table_name not in _ALLOWED_MULTIPLAS_TABLES:
            raise ValueError(f"Tabela não permitida: {table_name!r}. Use: {_ALLOWED_MULTIPLAS_TABLES}")
        self.table = table_name
        self._engine = AIResultCheckerService()

    ##########################################################################
    # AVALIA UMA LEG
    # Retorna 'GREEN', 'RED' ou None (stats ainda não disponíveis)
    ##########################################################################
    def evaluate_leg(self, leg, cur):
        fixture_id = leg.get("fixture_id")
        market     = leg.get("market", "")
        line       = leg.get("line", "")
        odd        = leg.get("odd", 1.0)
        home_team  = leg.get("home_team")
        away_team  = leg.get("away_team")

        stats = self._engine.get_fixture_result(fixture_id, cur)
        if not stats:
            return None  # jogo ainda sem resultado — não validar

        result, factor = self._engine.evaluate_pick(
            market, line, float(odd), stats, home_team, away_team
        )

        # Múltipla exige acerto pleno — HALF e PUSH viram RED
        if result not in ("GREEN", "RED"):
            return "RED"
        return result

    ##########################################################################
    # MAIN — só valida quando TODOS os jogos tiverem stats
    ##########################################################################
    def check_all_results(self):

        print(f"[CHECKER MULTIPLAS] Processando tabela: {self.table}")

        conn = get_connection()
        cur  = conn.cursor()

        cur.execute(f"""
            SELECT id, games, total_odd
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

        for mid, games_json, total_odd in rows:

            if isinstance(games_json, str):
                games = json.loads(games_json)
            else:
                games = games_json

            leg_results = []
            games_updated = False

            for leg in games:
                # Reutiliza resultado já anotado de uma passagem anterior
                existing = leg.get("result")
                if existing in ("GREEN", "RED"):
                    leg_results.append(existing)
                    continue

                r = self.evaluate_leg(leg, cur)
                if r is None:
                    fid = leg.get("fixture_id", "?")
                    print(f"[CHECKER MULTIPLAS] id={mid}: sem stats para fixture_id={fid} — aguardando.")
                    leg_results.append(None)
                else:
                    leg["result"] = r  # anota resultado parcial na perna
                    leg_results.append(r)
                    games_updated = True

            pending = any(r is None for r in leg_results)

            if pending:
                # Salva resultados parciais nas pernas para exibir no frontend
                if games_updated:
                    try:
                        cur.execute(f"""
                            UPDATE {self.table}
                            SET games = %s
                            WHERE id = %s;
                        """, (json.dumps(games), mid))
                        conn.commit()
                    except Exception as e:
                        print(f"[CHECKER MULTIPLAS] Erro ao salvar parcial id={mid}: {e}")
                        try: conn.rollback()
                        except Exception: pass
                continue

            final_result = "GREEN" if all(r == "GREEN" for r in leg_results) else "RED"

            total_odd = Decimal(str(total_odd))

            # Profit por 1 unidade
            if final_result == "RED":
                profit = Decimal("-1")
            else:
                profit = total_odd - Decimal("1")

            print(f"[CHECKER MULTIPLAS] id={mid} | {final_result} | legs={leg_results}")

            try:
                cur.execute(f"""
                    UPDATE {self.table}
                    SET result = %s,
                        profit = %s,
                        games  = %s
                    WHERE id = %s;
                """, (final_result, profit, json.dumps(games), mid))
                conn.commit()
            except Exception as e:
                print(f"[CHECKER MULTIPLAS] Erro ao salvar id={mid}: {e} — reconectando...")
                try: conn.rollback()
                except Exception: pass
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(f"""
                    UPDATE {self.table}
                    SET result = %s,
                        profit = %s,
                        games  = %s
                    WHERE id = %s;
                """, (final_result, profit, json.dumps(games), mid))
                conn.commit()

            processed += 1

        cur.close()
        conn.close()

        print(f"[CHECKER MULTIPLAS] Finalizado. Processados: {processed}")
        return processed
