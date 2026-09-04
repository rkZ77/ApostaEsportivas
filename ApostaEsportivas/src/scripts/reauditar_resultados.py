"""Reauditoria de resultados: reconfere TODO pick ja' resolvido e corrige o
que nao bate com a estatistica oficial.

Existe porque nenhum dos dois caminhos de resolucao olha pra tras: o job em
lote (atualizar_resultados_sugestoes.py) e o caminho ao vivo
(website/backend/routers/live.py::resolve_all_pending) so' processam pick com
`result IS NULL`. Uma vez gravado -- certo ou errado -- o resultado nunca era
reconferido, e um pick liquidado a partir de estatistica ausente ficava
errado pra sempre.

Nao existe correcao manual aqui: a reauditoria chama o MESMO motor de
liquidacao que o resto do sistema (services/settlement.py, via
AIResultCheckerService). Se este script muda um resultado, e' porque o motor
corrigido discorda do que estava gravado.

Uso:
    python scripts/reauditar_resultados.py              # so' relatorio
    python scripts/reauditar_resultados.py --apply      # relatorio + correcao
    python scripts/reauditar_resultados.py --sem-coleta # nao chama a API

Por padrao roda a coleta de estatistica antes (sync_pending_fixtures com
include_resolved=True): sem a folha certa no banco, reconferir nao serve pra
nada. `--sem-coleta` pula essa etapa quando a cota da API-Football importa
mais do que a atualidade do dado.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import settlement
from services.ai_result_checker_service import AIResultCheckerService
from utils.db_utils import get_connection


# tabela -> (coluna do time da casa, coluna do time visitante)
_TABELAS_SIMPLES = {
    "picks_vip":      ("home_team_name", "away_team_name"),
    "picks_free":     ("home_team", "away_team"),
    "picks_faltas":   ("home_team", "away_team"),
}


def _divergencia(atual, calculado) -> bool:
    """So' e' divergencia quando o motor tem um veredito DIFERENTE. Motor sem
    veredito (None) nao apaga um resultado ja' gravado -- pode ser mercado
    que este checker nao cobre, e nesse caso quem sabe e' o caminho ao vivo."""
    return calculado is not None and calculado != atual


def _auditar_simples(cur, checker, tabela, home_col, away_col):
    cur.execute(f"""
        SELECT id, fixture_id, market, market_type, line, odd, result, profit,
               {home_col}, {away_col}, match_date
        FROM {tabela}
        WHERE result IS NOT NULL
        ORDER BY id
    """)
    achados = []
    for (pid, fixture_id, market, market_type, line, odd, result, profit,
         home, away, match_date) in cur.fetchall():
        stats = checker.get_fixture_result(fixture_id, cur) if fixture_id else None
        if not stats:
            achados.append({
                "tabela": tabela, "id": pid, "fixture_id": fixture_id,
                "market": market, "line": line, "odd": odd,
                "atual": result, "calculado": None, "profit_atual": profit,
                "profit_novo": None, "match_date": match_date,
                "motivo": "sem folha de estatistica no banco",
                "corrigivel": False,
            })
            continue

        calculado, factor = checker.evaluate_pick(
            market, line, float(odd or 1), stats, home, away, market_type=market_type)
        profit_novo = checker.calculate_profit(factor, odd) if calculado else None

        if _divergencia(result, calculado) or (
                calculado is not None and profit_novo is not None
                and profit is not None and abs(float(profit_novo) - float(profit)) > 0.005):
            achados.append({
                "tabela": tabela, "id": pid, "fixture_id": fixture_id,
                "market": market, "line": line, "odd": odd,
                "atual": result, "calculado": calculado,
                "profit_atual": profit, "profit_novo": profit_novo,
                "match_date": match_date,
                "motivo": ("resultado diverge" if _divergencia(result, calculado)
                           else "profit diverge"),
                "corrigivel": True,
            })
        elif calculado is None:
            achados.append({
                "tabela": tabela, "id": pid, "fixture_id": fixture_id,
                "market": market, "line": line, "odd": odd,
                "atual": result, "calculado": None, "profit_atual": profit,
                "profit_novo": None, "match_date": match_date,
                "motivo": "mercado/linha nao coberto por este checker",
                "corrigivel": False,
            })
    return achados


def _resultados_das_pernas(cur, checker, pernas):
    """[(resultado, odd)] de cada perna, ou None se alguma nao resolve."""
    saida = []
    for perna in pernas:
        stats = checker.get_fixture_result(perna["fixture_id"], cur) if perna.get("fixture_id") else None
        if not stats:
            return None
        resultado, _ = checker.evaluate_pick(
            perna.get("market") or "", perna.get("line") or "",
            float(perna.get("odd") or 1), stats,
            perna.get("home_team"), perna.get("away_team"),
            market_type=perna.get("market_type"))
        if resultado is None:
            return None
        saida.append((resultado, perna.get("odd")))
    return saida


def _auditar_multiplas(cur, checker):
    cur.execute("""
        SELECT id, games, total_odd, result, profit, match_date
        FROM picks_multiplas WHERE result IS NOT NULL ORDER BY id
    """)
    achados = []
    for pid, games_raw, total_odd, result, profit, match_date in cur.fetchall():
        games = json.loads(games_raw) if isinstance(games_raw, str) else games_raw
        if not isinstance(games, list) or not games:
            continue
        pernas = [{
            "fixture_id": g.get("fixture_id"),
            "market": g.get("market"), "market_type": g.get("market_type"),
            "line": g.get("line"), "odd": g.get("odd"),
            "home_team": g.get("home_team") or g.get("home"),
            "away_team": g.get("away_team") or g.get("away"),
        } for g in games]

        resolvidas = _resultados_das_pernas(cur, checker, pernas)
        if resolvidas is None:
            achados.append({
                "tabela": "picks_multiplas", "id": pid, "fixture_id": None,
                "market": f"{len(pernas)} pernas", "line": "", "odd": total_odd,
                "atual": result, "calculado": None, "profit_atual": profit,
                "profit_novo": None, "match_date": match_date,
                "motivo": "alguma perna sem folha/mercado nao coberto",
                "corrigivel": False,
            })
            continue

        calculado, profit_novo, _odd_efetiva = settlement.combine_legs(
            [r for r, _ in resolvidas], [o for _, o in resolvidas], total_odd)
        if _divergencia(result, calculado):
            achados.append({
                "tabela": "picks_multiplas", "id": pid, "fixture_id": None,
                "market": " + ".join(f"{p['market']} {p['line']}" for p in pernas),
                "line": "", "odd": total_odd,
                "atual": result, "calculado": calculado,
                "profit_atual": profit, "profit_novo": profit_novo,
                "match_date": match_date,
                "pernas": [r for r, _ in resolvidas],
                "motivo": "resultado combinado diverge",
                "corrigivel": True,
            })
    return achados


def _auditar_alavancagem(cur, checker):
    cur.execute("""
        SELECT id, odd_combined, result, profit, match_date,
               fixture_id_1, market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
               fixture_id_2, market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
               fixture_id_3, market_3, market_type_3, line_3, odd_3, home_team_3, away_team_3
        FROM picks_alavancagem WHERE result IS NOT NULL ORDER BY id
    """)
    achados = []
    for row in cur.fetchall():
        pid, odd_combined, result, profit, match_date = row[0:5]
        pernas = []
        for offset in (5, 12, 19):
            fid, market, market_type, line, odd, home, away = row[offset:offset + 7]
            if fid is None:
                continue
            pernas.append({"fixture_id": fid, "market": market, "market_type": market_type,
                           "line": line, "odd": odd, "home_team": home, "away_team": away})
        if not pernas:
            continue

        resolvidas = _resultados_das_pernas(cur, checker, pernas)
        if resolvidas is None:
            achados.append({
                "tabela": "picks_alavancagem", "id": pid, "fixture_id": None,
                "market": f"{len(pernas)} pernas", "line": "", "odd": odd_combined,
                "atual": result, "calculado": None, "profit_atual": profit,
                "profit_novo": None, "match_date": match_date,
                "motivo": "alguma perna sem folha/mercado nao coberto",
                "corrigivel": False,
            })
            continue

        calculado, profit_novo, _odd_efetiva = settlement.combine_legs(
            [r for r, _ in resolvidas], [o for _, o in resolvidas], odd_combined)
        if _divergencia(result, calculado):
            achados.append({
                "tabela": "picks_alavancagem", "id": pid, "fixture_id": None,
                "market": " + ".join(f"{p['market']} {p['line']}" for p in pernas),
                "line": "", "odd": odd_combined,
                "atual": result, "calculado": calculado,
                "profit_atual": profit, "profit_novo": profit_novo,
                "match_date": match_date,
                "pernas": [r for r, _ in resolvidas],
                "motivo": "resultado combinado diverge",
                "corrigivel": True,
            })
    return achados


def _aplicar(conn, cur, achados):
    """Grava as correcoes. `user_followed_picks` acompanha, senao o painel do
    usuario continuaria mostrando o resultado antigo."""
    tipo_por_tabela = {"picks_vip": "vip", "picks_free": "free",
                       "picks_multiplas": "multipla", "picks_alavancagem": "alavancagem",
                       "picks_faltas": "faltas", "picks_goleiros": "goleiros"}
    aplicados = 0
    for a in achados:
        if not a.get("corrigivel"):
            continue
        cur.execute(
            f"UPDATE {a['tabela']} SET result = %s, profit = %s WHERE id = %s",
            (a["calculado"], a["profit_novo"], a["id"]))
        cur.execute(
            "UPDATE user_followed_picks SET result = %s WHERE pick_id = %s AND pick_type = %s",
            (a["calculado"], a["id"], tipo_por_tabela[a["tabela"]]))
        aplicados += 1
    conn.commit()
    return aplicados


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="grava as correcoes (sem isso, so' relata)")
    parser.add_argument("--sem-coleta", action="store_true",
                        help="nao chama a API-Football pra completar as folhas")
    args = parser.parse_args()

    if not args.sem_coleta:
        print("=== Coletando/completando folhas de estatistica ===")
        from collectors.match_statistics_sync_service import MatchStatisticsSyncService
        MatchStatisticsSyncService().sync_pending_fixtures(include_resolved=True)

    conn = get_connection()
    cur = conn.cursor()
    checker = AIResultCheckerService()

    achados = []
    total = 0
    for tabela, (home_col, away_col) in _TABELAS_SIMPLES.items():
        try:
            cur.execute(f"SELECT count(*) FROM {tabela} WHERE result IS NOT NULL")
            total += cur.fetchone()[0]
            achados += _auditar_simples(cur, checker, tabela, home_col, away_col)
        except Exception as e:
            print(f"[REAUDITORIA] {tabela} indisponivel: {e}")
            conn.rollback()

    for nome, fn in (("picks_multiplas", _auditar_multiplas),
                     ("picks_alavancagem", _auditar_alavancagem)):
        try:
            cur.execute(f"SELECT count(*) FROM {nome} WHERE result IS NOT NULL")
            total += cur.fetchone()[0]
            achados += fn(cur, checker)
        except Exception as e:
            print(f"[REAUDITORIA] {nome} indisponivel: {e}")
            conn.rollback()

    divergentes = [a for a in achados if a.get("corrigivel")]
    nao_cobertos = [a for a in achados if not a.get("corrigivel")]

    print(f"\n=== REAUDITORIA · {total} picks resolvidos ===")
    print(f"    divergentes (corrigiveis): {len(divergentes)}")
    print(f"    nao conferiveis por aqui : {len(nao_cobertos)}")

    if divergentes:
        print("\n--- DIVERGENCIAS ---")
        for a in divergentes:
            print(f"  {a['tabela']}#{a['id']} ({a['match_date']}) {a['market']} {a['line']} @ {a['odd']}")
            print(f"      gravado={a['atual']} (profit {a['profit_atual']}) -> "
                  f"correto={a['calculado']} (profit {a['profit_novo']}) · {a['motivo']}")
            if a.get("pernas"):
                print(f"      pernas={a['pernas']}")

    if nao_cobertos:
        print("\n--- NAO CONFERIVEIS (folha ausente ou mercado fora deste checker) ---")
        for a in nao_cobertos:
            print(f"  {a['tabela']}#{a['id']} ({a['match_date']}) fixture={a['fixture_id']} "
                  f"{a['market']} {a['line']} · gravado={a['atual']} · {a['motivo']}")

    if args.apply and divergentes:
        aplicados = _aplicar(conn, cur, divergentes)
        print(f"\n[REAUDITORIA] {aplicados} registro(s) corrigido(s).")
        try:
            from services.picks_ledger_sync_service import sync as sync_ledger
            sync_ledger()
        except Exception as e:
            print(f"[REAUDITORIA] Aviso: picks_ledger nao sincronizado: {e}")
    elif divergentes:
        print("\n[REAUDITORIA] Nada gravado (rode com --apply pra corrigir).")

    cur.close()
    conn.close()
    return len(divergentes)


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
