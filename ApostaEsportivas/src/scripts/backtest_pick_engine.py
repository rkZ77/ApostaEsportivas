"""
backtest_pick_engine.py · Generaliza backtest_pick_math.py (que so cobria
gols via picks_vip) para TODAS as pernas resolvidas historicamente nas 4
tabelas (picks_vip, picks_free, picks_multiplas, picks_alavancagem) e nas
familias goals/corners/cards/btts (as unicas que a IA historicamente
escolheu -- os 10 mercados novos da Fase 5 nunca foram apostados de
verdade, entao nao ha "gabarito" real pra validar eles ainda).

Cada perna e resolvida de forma INDEPENDENTE via AIResultCheckerService
(ja testado, le direto de match_statistics) -- pra multiplas/alavancagem
isso da o resultado de CADA perna, nao so o resultado combinado da
aposta inteira (uma multipla RED pode ter 1 perna GREEN e 1 RED).

Uso:
  DB_ENV=dev python src/scripts/backtest_pick_engine.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import psycopg2.extras
from utils.db_utils import get_connection
from services.pick_engine.stats_model import weighted_rate
from services.ai_result_checker_service import AIResultCheckerService
from services.pick_legs_extractor import fetch_all_legs, fixture_context as _fixture_context

_LINE_RE = re.compile(r'(Over|Under|Mais|Menos)\s*([\d.]+)', re.IGNORECASE)

_FAMILY_FIELD = {
    "goals": "total_goals",
    "corners": "total_corners",
    "cards": "total_yellow_cards",
}


def _parse_direction_line(raw_line: str):
    if not raw_line:
        return None
    m = _LINE_RE.search(raw_line)
    if m:
        direction = "over" if m.group(1).lower() in ("over", "mais") else "under"
        return direction, float(m.group(2))
    ln = raw_line.strip().lower()
    if ln in ("yes", "sim", "no", "não", "nao"):
        return ("yes" if ln in ("yes", "sim") else "no"), None
    return None


def _matches_before(cur, team_id, league_id, season, before_date, is_home, family):
    field = _FAMILY_FIELD.get(family)
    team_col = "home_team_id" if is_home else "away_team_id"
    opp_col = "away_team_id" if is_home else "home_team_id"
    select_stat = field if field else "home_goals, away_goals"
    cur.execute(f"""
        SELECT ms.match_date, {select_stat}, ls.rank AS opponent_rank
        FROM match_statistics ms
        LEFT JOIN league_standings ls
            ON ls.team_id = ms.{opp_col} AND ls.league_id = ms.league_id AND ls.season = ms.season
        WHERE ms.{team_col} = %s AND ms.league_id = %s AND ms.season = %s AND ms.match_date < %s
        ORDER BY ms.match_date DESC LIMIT 15
    """, (team_id, league_id, season, before_date))
    cols = ["match_date"] + (["stat"] if field else ["home_goals", "away_goals"]) + ["opponent_rank"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _compute_taxa_real(cur, leg, ctx):
    family = leg["market_type"]
    parsed = _parse_direction_line(leg["line"])
    if not parsed:
        return None
    direction, line_val = parsed

    home_hist = _matches_before(cur, ctx["home_team_id"], ctx["league_id"], ctx["season"], leg["match_date"], True, family)
    away_hist = _matches_before(cur, ctx["away_team_id"], ctx["league_id"], ctx["season"], leg["match_date"], False, family)

    if family == "btts":
        want_yes = direction == "yes"

        def hit_fn(m):
            occurred = (m.get("home_goals") or 0) > 0 and (m.get("away_goals") or 0) > 0
            return 1 if occurred == want_yes else 0
    else:
        if line_val is None:
            return None
        is_over = direction == "over"

        def hit_fn(m):
            over = 1 if (m.get("stat") or 0) > line_val else 0
            return over if is_over else 1 - over

    home_rate = weighted_rate(home_hist, hit_fn, reference_date=leg["match_date"])
    away_rate = weighted_rate(away_hist, hit_fn, reference_date=leg["match_date"])
    n = home_rate["amostra"] + away_rate["amostra"]
    if n == 0:
        return None
    vals = [t for t in (home_rate["taxa_ponderada"], away_rate["taxa_ponderada"]) if t is not None]
    return sum(vals) / len(vals), n


def run():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    plain_cur = conn.cursor()  # AIResultCheckerService espera cursor posicional
    checker = AIResultCheckerService()

    all_legs = [
        leg for leg in fetch_all_legs(cur)
        if leg.get("market_type") in ("goals", "corners", "cards", "btts") and leg.get("fixture_id")
    ]
    print(f"[BACKTEST] {len(all_legs)} pernas encontradas (4 tabelas, goals/corners/cards/btts, resolvidas ou não).\n")

    buckets = {fam: {"<60%": [], "60-70%": [], "70-80%": [], "80%+": []} for fam in ("goals", "corners", "cards", "btts")}
    skipped_no_context = skipped_no_parse = skipped_no_result = 0

    for leg in all_legs:
        ctx = _fixture_context(plain_cur, leg["fixture_id"])
        if not ctx or not ctx["home_team_id"] or not ctx["away_team_id"]:
            skipped_no_context += 1
            continue

        computed = _compute_taxa_real(plain_cur, leg, ctx)
        if not computed:
            skipped_no_parse += 1
            continue
        taxa_real, amostra = computed

        stats = checker.get_fixture_result(leg["fixture_id"], plain_cur)
        if not stats:
            skipped_no_result += 1
            continue
        real_result, _ = checker.evaluate_pick(leg["market"], leg["line"], leg["odd"] or 1.5, stats)
        if real_result not in ("GREEN", "RED"):
            skipped_no_result += 1
            continue

        bucket = "<60%" if taxa_real < 0.60 else "60-70%" if taxa_real < 0.70 else "70-80%" if taxa_real < 0.80 else "80%+"
        buckets[leg["market_type"]][bucket].append(real_result)

    cur.close(); plain_cur.close(); conn.close()

    print(f"[BACKTEST] {skipped_no_context} pernas sem contexto (fixture nao encontrado em match_statistics).")
    print(f"[BACKTEST] {skipped_no_parse} pernas sem parsing de linha reconhecido ou sem amostra historica.")
    print(f"[BACKTEST] {skipped_no_result} pernas sem resultado real determinavel (mercado nao suportado pelo checker).\n")

    for family in ("goals", "corners", "cards", "btts"):
        print(f"=== {family.upper()} ===")
        print(f"{'Bucket taxa_real (motor)':<28}{'N':>6}{'Hit rate real (GREEN%)':>26}")
        for label in ("<60%", "60-70%", "70-80%", "80%+"):
            results = buckets[family][label]
            n = len(results)
            if n == 0:
                print(f"{label:<28}{n:>6}{'·':>26}")
                continue
            greens = sum(1 for r in results if r == "GREEN")
            print(f"{label:<28}{n:>6}{greens / n * 100:>25.1f}%")
        print()

    print(
        "Leitura: se o hit rate real crescer junto com o bucket de taxa_real "
        "em cada familia, a formula esta calibrada na direcao certa. Buckets "
        "com poucas pernas (N<15 ou assim) tem margem de erro grande -- nao "
        "tirar conclusao forte so com eles."
    )


if __name__ == "__main__":
    run()
