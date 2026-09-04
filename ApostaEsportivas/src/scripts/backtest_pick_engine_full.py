"""
backtest_pick_engine_full.py · Roda o motor deterministico (services.pick_engine)
de ponta a ponta -- mesma sequencia de chamadas de engine_pipelines/*.py,
incluindo Data Validation Engine, calibracao bayesiana, Poisson e Smart Safe
Line -- contra fixtures JA ENCERRADOS no DEV, com o historico de cada time
truncado ANTES da data daquele fixture (MatchStatsService.*_matches_full/
get_last_n_all_competitions(before_date=...), evita vazar resultado futuro
no calculo). Diferente de backtest_pick_engine.py (que so valida a formula
de taxa isolada via stats_model.weighted_rate), este chama
pick_engine.orchestrator.analyze_fixture_markets() de verdade.

Compara contra:
  1. O resultado real do jogo (match_statistics, ja coletado -- grading
     imediato, sem esperar dia nenhum).
  2. O que a IA realmente escolheu e como se saiu nesses MESMOS fixtures no
     passado -- leitura so-leitura em PROD via ai/_homologation_common.py,
     resultado ja gravado (result/profit), zero chamada de IA nova.

Cobre os 4 tipos de pick (VIP, Free/Dica, Multipla, Alavancagem) -- Multipla/
Alavancagem reusam o mesmo algoritmo guloso de combinacao de
engine_pipelines/multipla_pipeline.py e alavancagem_pipeline.py, mas
agrupando fixtures processados por match_date historico em vez de
CURRENT_DATE. Simplificacoes assumidas (ver aviso impresso no relatorio):
nao restringe Alavancagem a WC_LEAGUE_ID (senao a amostra historica fica
proxima de zero) e nao exclui pares ja usados em VIP/Free do mesmo dia
(used_pairs) -- ambas mudariam pouco o resultado agregado e adicionam
complexidade que nao ajuda a responder "o motor funciona".

NUNCA escreve em nenhuma tabela de picks (nem DEV nem PROD) -- so leitura +
agregacao em memoria, mesmo padrao dry-run de ai/vip_engine_shadow.py.

Pre-requisito: rodar scripts/copy_prod_history_to_dev.py antes (garante
match_statistics/league_standings/odds_values atualizados no DEV).

Uso:
  python src/scripts/backtest_pick_engine_full.py [--limit N]
"""
import os
import sys
import argparse
import itertools
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from dotenv import load_dotenv, find_dotenv
_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

# ONDE ESTE BACKTEST LE (2026-08-13)
# ----------------------------------
# Padrao continua DEV. `--prod` passa a ler PRODUCAO, e a razao de existir e'
# que o DEV nao sustenta a medicao: em 13/08 ele tinha 1309 jogos encerrados e
# odds de 3 fixtures, sem interseccao nenhuma -- o backtest processava ZERO
# partida. Alem disso `league_standings` tem ~130 linhas la, entao a ponderacao
# por forca do adversario mal aparece, e o backfill de historico por time nunca
# rodou no DEV.
#
# Ler PROD e' seguro porque este script nao escreve nada la: a unica escrita do
# arquivo inteiro e' `INSERT INTO backtest_runs` (tabela de metrica, que nenhuma
# outra parte do sistema le), e ela fica atras de --gravar. Nao ha chamada de
# IA, nao ha escrita em tabela de pick, nao ha decision_log.
#
# O que --prod CUSTA e' leitura no banco que atende o site: uma passada por
# fixture encerrado com odds, varias consultas cada. Rodar em horario de jogo
# nao e' boa ideia.
#
# A env e' resolvida ANTES dos imports de servico de proposito: MatchStatsService
# e companhia chamam get_connection() sem env explicito e leem DB_ENV na hora da
# conexao (mesmo truque de ai/vip_engine_shadow.py). Por isso a leitura de
# sys.argv aqui, crua, em vez de esperar o argparse la embaixo.
MODO_PROD = "--prod" in sys.argv
_AMBIENTE = "prod" if MODO_PROD else "dev"
_SUFIXO = "_PROD" if MODO_PROD else "_DEV"

for _key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    _val = os.getenv(f"{_key}{_SUFIXO}")
    if _val:
        os.environ[_key] = _val
os.environ["DB_ENV"] = _AMBIENTE

if MODO_PROD:
    print("=" * 70)
    print("[BACKTEST] LENDO PRODUCAO. Somente leitura -- nada e' gravado sem --gravar.")
    print("[BACKTEST] Evite rodar em horario de jogo: sao muitas consultas no")
    print("[BACKTEST] mesmo banco que atende o site.")
    print("=" * 70)

from utils.db_utils import get_connection
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.ai_result_checker_service import AIResultCheckerService
from services.pick_engine import (
    analyze_fixture_markets, rank_market_candidates, DEFAULT_CONFIG, DICA_CONFIG,
)
from services.pick_engine.calibration import get_market_calibration
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import metrics as pe_metrics
from ai._homologation_common import fetch_ai_legs

MULTIPLA_ODD_MIN, MULTIPLA_ODD_MAX = 2.00, 3.00
ALAV_ODD_MIN, ALAV_ODD_MAX = 1.45, 1.55
ALAV_LEG_ODD_MIN, ALAV_LEG_ODD_MAX = 1.05, 1.65
MAX_CANDIDATES_FOR_COMBO = 12


###############################################################################
# Carga de dados (DEV) e execucao do motor por fixture
###############################################################################
def _load_history(match_stats, team_id, season, league_id, before_date):
    # uses_all_competitions_history, nao is_national_team_league: o segundo e'
    # so' metade da regra desde 2026-08-01, quando copa de clube passou a usar
    # o mesmo caminho. O backtest media um motor que producao nao roda -- toda
    # fixture de Libertadores/Copa do Brasil entrava aqui com historico travado
    # na competicao, enquanto os pipelines liam multi-competicao.
    if cp.uses_all_competitions_history(league_id):
        return match_stats.get_last_n_all_competitions(team_id, before_date=before_date)
    return match_stats.get_all_matches_full(team_id, season, league_id, before_date=before_date)


def _build_signals(last10_home, last10_away, home_team_id, away_team_id, league_id, reference_date):
    """reference_date e' obrigatorio aqui (diferente dos pipelines de
    producao, que deixam implicito = hoje): build_context()/rest_days()
    default pra date.today() quando omitido, o que pra um fixture historico
    calcularia 'dias de descanso' contra a data de HOJE em vez da data do
    jogo -- viés silencioso, sem erro."""
    profile_home = tpm.build_profile(last10_home, home_team_id)
    profile_away = tpm.build_profile(last10_away, away_team_id)
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, home_team_id, away_team_id, None, None, league_id,
        reference_date=reference_date,
    )
    team_strength_data = ts.compare_team_strength(profile_home, profile_away)
    return context_data, matchup, team_strength_data


def _finished_fixtures_with_odds(cur, limit=None):
    """Fixtures encerrados no DEV com match_statistics + pelo menos uma odd
    capturada (odds so sao copiadas pra fixtures ja em match_statistics,
    ver copy_prod_history_to_dev.py)."""
    sql = """
        SELECT DISTINCT ms.fixture_id, ms.league_id, ms.season,
               ms.home_team_id, ms.away_team_id, ms.match_date
        FROM match_statistics ms
        WHERE ms.status = 'FT'
          AND EXISTS (SELECT 1 FROM odds_values ov WHERE ov.fixture_id = ms.fixture_id)
        ORDER BY ms.match_date ASC
    """
    if limit:
        sql += " LIMIT %s"
        cur.execute(sql, (limit,))
    else:
        cur.execute(sql)
    cols = ["fixture_id", "league_id", "season", "home_team_id", "away_team_id", "match_date"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _grade(checker, stats, pick):
    if not pick:
        return None
    result, factor = checker.evaluate_pick(pick["market_name"], pick["value_label"], pick["odd"], stats)
    if result is None:
        return None
    profit = checker.calculate_profit(factor, pick["odd"])
    return {"result": result, "profit": float(profit)}


def _process_fixture(fx, match_stats, odds_service, checker, calibration_snapshot, dev_cur,
                      ai_vip_by_fixture, ai_free_by_fixture):
    fixture_id = fx["fixture_id"]
    structured_odds = odds_service.load_odds_structured(fixture_id)
    if not structured_odds:
        return None

    last10_home = _load_history(match_stats, fx["home_team_id"], fx["season"], fx["league_id"], fx["match_date"])
    last10_away = _load_history(match_stats, fx["away_team_id"], fx["season"], fx["league_id"], fx["match_date"])
    if not last10_home or not last10_away:
        return None

    hist_home_val = dv.validate_history(last10_home)
    hist_away_val = dv.validate_history(last10_away)
    if not hist_home_val["passed"] or not hist_away_val["passed"]:
        return None

    context_data, matchup, team_strength_data = _build_signals(
        last10_home, last10_away, fx["home_team_id"], fx["away_team_id"], fx["league_id"],
        reference_date=fx["match_date"],
    )
    coverage_val = dv.validate_coverage(
        structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
        context_data=context_data,
    )
    quality = dv.data_quality_score({"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val)

    stats = checker.get_fixture_result(fixture_id, dev_cur)
    if not stats:
        return None

    # VIP/Multipla/Alavancagem usam DEFAULT_CONFIG; Free/Dica usa DICA_CONFIG
    # (confidence minimo mais alto) -- roda os dois porque config afeta o
    # calculo do candidato (nao so o filtro final), mesma logica de producao.
    default_candidates = analyze_fixture_markets(
        structured_odds, last10_home, last10_away, reference_date=fx["match_date"],
        config=DEFAULT_CONFIG, calibration_data=calibration_snapshot,
        context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
        data_quality_score=quality["score"],
    )
    default_picks = rank_market_candidates(default_candidates, config=DEFAULT_CONFIG)
    for p in default_picks:
        p["_grade"] = _grade(checker, stats, p)
        p["_fixture"] = fx

    dica_candidates = analyze_fixture_markets(
        structured_odds, last10_home, last10_away, reference_date=fx["match_date"],
        config=DICA_CONFIG, calibration_data=calibration_snapshot,
        context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
        data_quality_score=quality["score"],
    )
    dica_picks = rank_market_candidates(dica_candidates, config=DICA_CONFIG)
    for p in dica_picks:
        p["_grade"] = _grade(checker, stats, p)

    vip_pick = next((p for p in default_picks if p.get("is_best_pick")), default_picks[0] if default_picks else None)
    dica_pick = next((p for p in dica_picks if p.get("is_best_pick")), dica_picks[0] if dica_picks else None)

    return {
        "fixture": fx,
        "vip_pick": vip_pick,
        "dica_pick": dica_pick,
        "leg_pool": default_picks,
        "ai_vip": ai_vip_by_fixture.get(fixture_id),
        "ai_free": ai_free_by_fixture.get(fixture_id),
    }


def _index_by_fixture(legs):
    """Mais recente por fixture_id, mesmo criterio de
    ai/_homologation_common.py::fetch_ai_pick_for_fixture -- mas indexado
    uma vez so, em memoria, em vez de re-escanear a tabela inteira do PROD
    a cada fixture (o que _fetch_ai_pick_for_fixture faria se chamado num
    loop de centenas de fixtures historicos)."""
    idx = {}
    for leg in legs:
        fid = leg.get("fixture_id")
        if fid is None:
            continue
        existing = idx.get(fid)
        if existing is None or (leg.get("created_at") or "") > (existing.get("created_at") or ""):
            idx[fid] = leg
    return idx


###############################################################################
# Simulacao de combos (Multipla/Alavancagem) por dia historico
###############################################################################
def _find_combo(legs, odd_min, odd_max, same_fixture_allowed, score_key):
    pool = sorted(legs, key=lambda p: p[score_key], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]
    sizes = (1, 2, 3) if same_fixture_allowed else (2, 3)
    for combo_size in sizes:
        best = None
        for combo in itertools.combinations(pool, combo_size):
            if not same_fixture_allowed:
                fids = {p["_fixture"]["fixture_id"] for p in combo}
                if len(fids) != combo_size:
                    continue
            else:
                market_types = {p["market_type"] for p in combo}
                if combo_size > 1 and len(market_types) == 1:
                    continue
            odd_total = 1.0
            for p in combo:
                odd_total *= p["odd"]
            odd_total = round(odd_total, 4)
            if not (odd_min <= odd_total <= odd_max):
                continue
            score = round(sum(p[score_key] for p in combo) / len(combo), 4)
            if best is None or score > best[1]:
                best = (combo, score, odd_total)
        if best:
            return best
    return None


def _ai_combo_summary(table):
    """Desempenho real e completo da IA nessa tabela (todo o periodo com
    resultado, nao necessariamente os mesmos dias do backtest -- so leitura
    em PROD)."""
    conn = get_connection(env="prod")
    cur = conn.cursor()
    cur.execute(f"SELECT result, profit FROM {table} WHERE result IN ('GREEN','RED')")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    n = len(rows)
    if n == 0:
        return 0, None, None
    greens = sum(1 for r in rows if r[0] == "GREEN")
    profits = [float(r[1]) for r in rows if r[1] is not None]
    roi = sum(profits) / len(profits) if profits else None
    return n, greens / n, roi


def _report_combo(results, label, odd_min, odd_max, same_fixture_allowed, score_key,
                   ai_table, leg_odd_range=None):
    by_date = defaultdict(list)
    for r in results:
        for p in r["leg_pool"]:
            if not (p.get("_grade") and p["_grade"]["result"] in ("GREEN", "RED")):
                continue
            if leg_odd_range and not (leg_odd_range[0] <= p["odd"] <= leg_odd_range[1]):
                continue
            by_date[r["fixture"]["match_date"]].append(p)

    combo_rows = []
    for legs in by_date.values():
        found = _find_combo(legs, odd_min, odd_max, same_fixture_allowed, score_key)
        if not found:
            continue
        combo, _score, odd_total = found
        combo_green = all(p["_grade"]["result"] == "GREEN" for p in combo)
        profit = (odd_total - 1) if combo_green else -1.0
        combo_rows.append({"result": "GREEN" if combo_green else "RED", "profit": profit})

    n_e, hit_e, roi_e = _hit_roi(combo_rows)
    n_a, hit_a, roi_a = _ai_combo_summary(ai_table)

    print(f"=== {label} ===")
    print(f"Motor (simulado, dias historicos com combo formado): "
          f"N={n_e} | Hit={_fmt_pct(hit_e)} | ROI medio={_fmt_pct(roi_e, signed=True)} por combo (1u)")
    print(f"IA (historico real completo, {ai_table}): "
          f"N={n_a} | Hit={_fmt_pct(hit_a)} | ROI medio={_fmt_pct(roi_a, signed=True)} por combo (1u)")
    print()


###############################################################################
# Relatorio VIP / Free (comparacao fixture-a-fixture)
###############################################################################
def _hit_roi(rows):
    n = len(rows)
    if n == 0:
        return 0, None, None
    greens = sum(1 for r in rows if r["result"] == "GREEN")
    profits = [r["profit"] for r in rows if r.get("profit") is not None]
    roi = sum(profits) / len(profits) if profits else None
    return n, greens / n, roi


def _fmt_pct(value, signed=False):
    if value is None:
        return "·"
    return f"{value*100:+.1f}%" if signed else f"{value*100:.1f}%"


def _report_vip_free(results):
    buckets_engine = defaultdict(lambda: defaultdict(list))
    buckets_ai = defaultdict(lambda: defaultdict(list))

    for r in results:
        if r["vip_pick"] and r["vip_pick"].get("_grade") and r["vip_pick"]["_grade"]["result"] in ("GREEN", "RED"):
            buckets_engine["VIP"][r["vip_pick"]["market_type"]].append(r["vip_pick"]["_grade"])
        ai_vip = r["ai_vip"]
        if ai_vip and ai_vip.get("result") in ("GREEN", "RED"):
            buckets_ai["VIP"][ai_vip.get("market_type") or "unknown"].append({
                "result": ai_vip["result"],
                "profit": float(ai_vip["profit"]) if ai_vip.get("profit") is not None else None,
            })

        if r["dica_pick"] and r["dica_pick"].get("_grade") and r["dica_pick"]["_grade"]["result"] in ("GREEN", "RED"):
            buckets_engine["FREE"][r["dica_pick"]["market_type"]].append(r["dica_pick"]["_grade"])
        ai_free = r["ai_free"]
        if ai_free and ai_free.get("result") in ("GREEN", "RED"):
            buckets_ai["FREE"][ai_free.get("market_type") or "unknown"].append({
                "result": ai_free["result"],
                "profit": float(ai_free["profit"]) if ai_free.get("profit") is not None else None,
            })

    for tipo in ("VIP", "FREE"):
        print(f"=== {tipo}: MOTOR vs IA (mesmos fixtures, resultado real) ===")
        print(f"{'Mercado':<12}{'N motor':>9}{'Hit motor':>12}{'ROI motor':>12}   {'N IA':>7}{'Hit IA':>10}{'ROI IA':>10}")
        all_mts = set(buckets_engine[tipo]) | set(buckets_ai[tipo])
        for mt in sorted(all_mts):
            n_e, hit_e, roi_e = _hit_roi(buckets_engine[tipo].get(mt, []))
            n_a, hit_a, roi_a = _hit_roi(buckets_ai[tipo].get(mt, []))
            print(f"{mt:<12}{n_e:>9}{_fmt_pct(hit_e):>12}{_fmt_pct(roi_e, signed=True):>12}   "
                  f"{n_a:>7}{_fmt_pct(hit_a):>10}{_fmt_pct(roi_a, signed=True):>10}")
        print()


###############################################################################
# Fase 1.7 do plano de implementacao (2026-07-25): grava Brier/LogLoss/ECE
# desta rodada em backtest_runs, pra virar gate de regressao comparavel
# entre execucoes -- antes disso, cada rodada de backtest so existia como
# print no terminal, sem historico pra comparar "essa mudanca em config.py
# melhorou ou piorou" de forma objetiva.
###############################################################################
def _collect_grade_pairs(results: list) -> list:
    pairs = []
    for r in results:
        for pick in (r["vip_pick"], r["dica_pick"]):
            if not pick or not pick.get("_grade"):
                continue
            if pick["_grade"]["result"] not in ("GREEN", "RED"):
                continue
            pairs.append({"confidence": pick["confidence"], "result": pick["_grade"]["result"]})
    return pairs


def _git_commit_sha() -> str | None:
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _store_backtest_run(results: list, run_label: str, config_snapshot: dict) -> None:
    import json as _json

    pairs = _collect_grade_pairs(results)
    brier = pe_metrics.brier_score(pairs)
    ll = pe_metrics.log_loss(pairs)
    curve = pe_metrics.reliability_curve(pairs)
    ece = pe_metrics.expected_calibration_error(curve)

    all_profits = [
        float(pick["_grade"]["profit"])
        for r in results for pick in (r["vip_pick"], r["dica_pick"])
        if pick and pick.get("_grade") and pick["_grade"]["result"] in ("GREEN", "RED")
    ]
    roi = round(sum(all_profits) / len(all_profits), 4) if all_profits else None

    dates = [r["fixture"]["match_date"] for r in results if r.get("fixture")]
    date_start, date_end = (min(dates), max(dates)) if dates else (None, None)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO backtest_runs
        (run_label, commit_sha, date_range_start, date_range_end, config_snapshot,
         brier_score, log_loss, ece, roi, n_picks)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        run_label, _git_commit_sha(), date_start, date_end, _json.dumps(config_snapshot, default=str),
        brier["score"] if brier else None, ll["score"] if ll else None, ece, roi,
        brier["n"] if brier else 0,
    ))
    conn.commit()
    cur.close()
    conn.close()

    print(f"\n[BACKTEST_RUNS] {run_label}: n={brier['n'] if brier else 0} "
          f"Brier={brier['score'] if brier else '·'} LogLoss={ll['score'] if ll else '·'} "
          f"ECE={ece} ROI={_fmt_pct(roi, signed=True) if roi is not None else '·'} -- gravado em backtest_runs.")


###############################################################################
# Execucao principal
###############################################################################
def run(limit=None, gravar=True, snapshots=False, minutos_antes=0):
    match_stats = MatchStatsService()
    if snapshots:
        from services.odds_snapshot_service import SnapshotOddsService
        odds_service = SnapshotOddsService(minutos_antes=minutos_antes)
    else:
        odds_service = OddsService()
    checker = AIResultCheckerService()
    calibration_snapshot = get_market_calibration()

    print("[BACKTEST] Indexando picks reais da IA em PROD (so-leitura, uma vez)...")
    ai_vip_by_fixture = _index_by_fixture(fetch_ai_legs("picks_vip"))
    ai_free_by_fixture = _index_by_fixture(fetch_ai_legs("picks_free"))

    dev_conn = get_connection()
    dev_cur = dev_conn.cursor()
    if snapshots:
        fixtures = odds_service.fixtures_com_snapshot(limit=limit)
        print(f"[BACKTEST] {len(fixtures)} fixture(s) encerrado(s) com cotacao pre-jogo "
              f"arquivada em odds_snapshots ({_AMBIENTE.upper()}).\n")
    else:
        fixtures = _finished_fixtures_with_odds(dev_cur, limit=limit)
        print(f"[BACKTEST] {len(fixtures)} fixture(s) encerrado(s) com odds em "
              f"odds_values ({_AMBIENTE.upper()}).\n")

    results = []
    skipped = 0
    for fx in fixtures:
        try:
            r = _process_fixture(
                fx, match_stats, odds_service, checker, calibration_snapshot, dev_cur,
                ai_vip_by_fixture, ai_free_by_fixture,
            )
        except Exception as e:
            print(f"[BACKTEST] Erro no fixture {fx['fixture_id']}, pulando: {e}")
            skipped += 1
            continue
        if r is None:
            skipped += 1
            continue
        results.append(r)
        vip = r["vip_pick"]
        vip_label = f"{vip['market_name']} {vip['value_label']} ({(vip.get('_grade') or {}).get('result', '?')})" if vip else "sem pick"
        ai = r["ai_vip"]
        ai_label = f"{ai['market']} {ai['line']} ({ai['result']})" if ai else "sem pick IA"
        print(f"[BACKTEST] Fixture {fx['fixture_id']} ({fx['match_date']}): MOTOR={vip_label} | IA={ai_label}")

    dev_cur.close()
    dev_conn.close()

    print(f"\n[BACKTEST] {len(results)}/{len(fixtures)} fixture(s) processado(s) pelo motor "
          f"({skipped} pulado(s) por falta de odds/historico/dado suficiente).\n")

    _report_vip_free(results)
    if gravar:
        _store_backtest_run(results, run_label=f"full_backtest_{_AMBIENTE}", config_snapshot={"DEFAULT_CONFIG": DEFAULT_CONFIG.__dict__, "DICA_CONFIG": DICA_CONFIG.__dict__})
    else:
        print("\n[BACKTEST_RUNS] nada gravado (rodada so'-leitura). Use --gravar pra registrar.")
    _report_combo(
        results, "MULTIPLA (odd_total 2.00-3.00, fixtures diferentes)",
        MULTIPLA_ODD_MIN, MULTIPLA_ODD_MAX, same_fixture_allowed=False, score_key="final_score",
        ai_table="picks_multiplas",
    )
    _report_combo(
        results, "ALAVANCAGEM (odd_combined 1.45-1.55, pode ser mesmo fixture)",
        ALAV_ODD_MIN, ALAV_ODD_MAX, same_fixture_allowed=True, score_key="confidence",
        ai_table="picks_alavancagem", leg_odd_range=(ALAV_LEG_ODD_MIN, ALAV_LEG_ODD_MAX),
    )

    print(
        "Leitura: 'Motor' e 100% simulado (nunca gravado, sem gasto de IA). 'IA' e o "
        "desempenho REAL ja registrado no passado. Buckets com N pequeno (<15 ou assim) "
        "tem margem de erro grande -- nao tirar conclusao forte so com eles. Multipla/"
        "Alavancagem aqui NAO restringem por liga nem excluem pares ja usados em VIP/Free "
        "do mesmo dia (simplificacoes do backtest, producao tem essas regras) -- ver "
        "docstring do arquivo."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="limita a quantidade de fixtures processados (teste rapido)")
    parser.add_argument("--prod", action="store_true",
                         help="le PRODUCAO em vez do DEV (somente leitura; ver o "
                              "comentario no topo do arquivo)")
    parser.add_argument("--gravar", action="store_true",
                         help="grava a linha de metrica em backtest_runs. Em DEV e' o "
                              "padrao historico; em --prod exige este flag explicito")
    parser.add_argument("--snapshots", action="store_true",
                         help="le a cotacao de odds_snapshots (arquivo append-only) em vez "
                              "de odds_values, que so' guarda a odd de agora. E' o unico "
                              "jeito de haver jogo encerrado COM odd -- ver "
                              "services/odds_snapshot_service.py")
    parser.add_argument("--minutos-antes", type=int, default=0,
                         help="usa a ultima cotacao pelo menos N minutos antes do apito "
                              "(0 = a mais proxima do jogo, que e' o preco real de quem "
                              "apostou em cima da hora)")
    args = parser.parse_args()
    # Em DEV grava como sempre gravou. Em PROD, so' com pedido explicito: uma
    # rodada de medicao nao pode escrever em producao por descuido de quem
    # digitou o comando.
    run(limit=args.limit, gravar=args.gravar or not MODO_PROD,
        snapshots=args.snapshots, minutos_antes=args.minutos_antes)
