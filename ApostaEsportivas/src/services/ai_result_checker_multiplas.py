from utils.db_utils import get_connection
from services.ai_result_checker_service import AIResultCheckerService
from services import settlement
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
        """Resultado real da perna -- GREEN/RED/PUSH/HALF-*, sem achatar.

        Antes qualquer coisa que nao fosse GREEN/RED virava RED aqui, o que
        matava o bilhete inteiro por causa de uma perna ANULADA (PUSH). Quem
        sabe combinar as pernas e' settlement.combine_legs(), e ele precisa do
        resultado verdadeiro de cada uma pra fazer a conta certa."""
        fixture_id = leg.get("fixture_id")
        market     = leg.get("market", "")
        line       = leg.get("line", "")
        odd        = leg.get("odd", 1.0)
        home_team  = leg.get("home_team") or leg.get("home")
        away_team  = leg.get("away_team") or leg.get("away")

        stats = self._engine.get_fixture_result(fixture_id, cur)
        if not stats:
            return None  # jogo ainda sem resultado · não validar

        result, _factor = self._engine.evaluate_pick(
            market, line, float(odd), stats, home_team, away_team,
            market_type=leg.get("market_type"),
        )
        return result  # None = perna ainda pendente

    ##########################################################################
    # MAIN · só valida quando TODOS os jogos tiverem stats
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
            leg_odds = []
            games_updated = False

            for leg in games:
                leg_odds.append(leg.get("odd"))
                # Reutiliza resultado já anotado de uma passagem anterior
                existing = leg.get("result")
                if existing in settlement.RESULT_LABELS:
                    leg_results.append(existing)
                    continue

                r = self.evaluate_leg(leg, cur)
                if r is None:
                    fid = leg.get("fixture_id", "?")
                    print(f"[CHECKER MULTIPLAS] id={mid}: sem stats para fixture_id={fid} · aguardando.")
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

            final_result, profit, odd_efetiva = settlement.combine_legs(
                leg_results, leg_odds, total_odd)
            if final_result is None:
                print(f"[CHECKER MULTIPLAS] id={mid}: nao foi possivel combinar as "
                      f"pernas ({leg_results}) - segue pendente.")
                continue

            print(f"[CHECKER MULTIPLAS] id={mid} | {final_result} | legs={leg_results} | "
                  f"odd efetiva={odd_efetiva} | profit={profit}")

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
                print(f"[CHECKER MULTIPLAS] Erro ao salvar id={mid}: {e} · reconectando...")
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
