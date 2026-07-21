"""
Verifica resultados da tabela picks_bingo.
- Cada jogo (games[i]) e' GREEN somente se TODAS as pernas do seu
  sub-combo (games[i]['legs']) acertarem; qualquer perna RED/HALF/PUSH
  vira o jogo inteiro RED.
- O bingo inteiro so e' GREEN se TODOS os jogos forem GREEN.
- Profit em unidades (stake real calculado pelo frontend via Kelly/bankroll
  do usuario, mesmo padrao ja adotado em picks_alavancagem).
"""

import json
from decimal import Decimal

from utils.db_utils import get_connection
from services.ai_result_checker_service import AIResultCheckerService


class AIResultCheckerBingo:

    def __init__(self):
        self._engine = AIResultCheckerService()

    ##########################################################################
    # AVALIA UMA PERNA (fixture_id/home_team/away_team vem do JOGO pai --
    # a perna em si so guarda market/line/odd)
    # Retorna 'GREEN', 'RED' ou None (stats ainda nao disponiveis)
    ##########################################################################
    def _evaluate_leg(self, leg, fixture_id, home_team, away_team, cur):
        stats = self._engine.get_fixture_result(fixture_id, cur)
        if not stats:
            return None  # jogo ainda sem resultado -- nao validar

        result, _ = self._engine.evaluate_pick(
            leg.get("market", ""), leg.get("line", ""), float(leg.get("odd") or 1.0),
            stats, home_team, away_team,
        )

        if result is None:
            return None  # dados ausentes -> perna ainda pendente
        # Sub-combo exige acerto pleno -- HALF/PUSH viram RED
        if result not in ("GREEN", "RED"):
            return "RED"
        return result

    ##########################################################################
    # MAIN · so valida um bingo quando TODOS os jogos tiverem stats
    ##########################################################################
    def check_all_results(self):
        print("[CHECKER-BINGO] Processando picks pendentes...")

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, games, odd_final
            FROM picks_bingo
            WHERE result IS NULL
        """)
        rows = cur.fetchall()

        if not rows:
            print("[CHECKER-BINGO] Nada pendente.")
            cur.close()
            conn.close()
            return 0

        processed = 0

        for pk_id, games_json, odd_final in rows:
            games = games_json if isinstance(games_json, list) else json.loads(games_json)

            game_results = []
            games_updated = False

            for game in games:
                fixture_id = game.get("fixture_id")
                home_team = game.get("home_team")
                away_team = game.get("away_team")
                legs = game.get("legs", [])

                leg_results = []
                for leg in legs:
                    existing = leg.get("result")
                    if existing in ("GREEN", "RED"):
                        leg_results.append(existing)
                        continue
                    r = self._evaluate_leg(leg, fixture_id, home_team, away_team, cur)
                    if r is None:
                        leg_results.append(None)
                    else:
                        leg["result"] = r
                        leg_results.append(r)
                        games_updated = True

                if any(r is None for r in leg_results):
                    game_results.append(None)
                    continue

                game_result = "GREEN" if all(r == "GREEN" for r in leg_results) else "RED"
                if game.get("result") != game_result:
                    game["result"] = game_result
                    games_updated = True
                game_results.append(game_result)

            pending = any(r is None for r in game_results)

            if pending:
                # Salva resultados parciais (pernas e jogos) para exibir no frontend
                if games_updated:
                    try:
                        cur.execute("""
                            UPDATE picks_bingo
                            SET games = %s
                            WHERE id = %s;
                        """, (json.dumps(games), pk_id))
                        conn.commit()
                    except Exception as e:
                        print(f"[CHECKER-BINGO] Erro ao salvar parcial id={pk_id}: {e}")
                        try: conn.rollback()
                        except Exception: pass
                faltando = sum(1 for r in game_results if r is None)
                print(f"[CHECKER-BINGO] id={pk_id}: aguardando resultado de {faltando} jogo(s).")
                continue

            final_result = "GREEN" if all(r == "GREEN" for r in game_results) else "RED"

            # Garante consistencia: se overall GREEN, todos os jogos/pernas ficam GREEN
            if final_result == "GREEN":
                for game in games:
                    game["result"] = "GREEN"
                    for leg in game.get("legs", []):
                        leg["result"] = "GREEN"

            odd_final_dec = Decimal(str(odd_final))
            profit = (odd_final_dec - Decimal("1")) if final_result == "GREEN" else Decimal("-1")

            print(f"[CHECKER-BINGO] id={pk_id} | {final_result} | jogos={game_results}")

            try:
                cur.execute("""
                    UPDATE picks_bingo
                    SET result = %s,
                        profit = %s,
                        games  = %s,
                        checked_at = NOW()
                    WHERE id = %s;
                """, (final_result, profit, json.dumps(games), pk_id))
                conn.commit()
            except Exception as e:
                print(f"[CHECKER-BINGO] Erro ao salvar id={pk_id}: {e} · reconectando...")
                try: conn.rollback()
                except Exception: pass
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE picks_bingo
                    SET result = %s,
                        profit = %s,
                        games  = %s,
                        checked_at = NOW()
                    WHERE id = %s;
                """, (final_result, profit, json.dumps(games), pk_id))
                conn.commit()

            processed += 1

        cur.close()
        conn.close()

        print(f"[CHECKER-BINGO] Finalizado. Processados: {processed}")
        return processed


if __name__ == "__main__":
    AIResultCheckerBingo().check_all_results()
