"""
backtest_pick_math.py · Valida a formula de taxa_ponderada (pick_math_service)
contra resultados reais ja registrados em picks_vip, ANTES de conectar o
modulo em qualquer pipeline ao vivo.

Uso:
  python src/scripts/backtest_pick_math.py

Escopo (Fase 1 do plano "Calculo deterministico para taxa/confidence/EV"):
  Só reconstroi mercados "Gols Mais/Menos" (Total Gols Over/Under), que sao
  os mais faceis de reconstruir sem ambiguidade de contexto casa/fora.
  Nao elimina 100% do lookahead bias (league_standings usado para
  opponent_rank e a foto mais recente da tabela, nao a posicao na data do
  jogo) mas os jogos historicos usados para calcular taxa sao sempre
  anteriores a data do pick.
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

_LINE_RE = re.compile(r'(Over|Under|Mais|Menos)\s*([\d.]+)', re.IGNORECASE)


def _parse_direction_line(raw_line: str):
    if not raw_line:
        return None
    m = _LINE_RE.search(raw_line)
    if not m:
        return None
    direction = "over" if m.group(1).lower() in ("over", "mais") else "under"
    return direction, float(m.group(2))


def _fetch_goals_picks(cur):
    # league_id/season vem de match_statistics (fixture_id ali e PK), nao da
    # tabela fixtures (que so guarda a fila de jogos futuros, quase vazia).
    cur.execute("""
        SELECT
            p.fixture_id, p.match_date, p.home_team_id, p.away_team_id,
            p.line, p.confidence, p.probability, p.result,
            ms.league_id, ms.season
        FROM picks_vip p
        JOIN match_statistics ms ON ms.fixture_id = p.fixture_id
        WHERE p.result IN ('GREEN', 'RED')
          AND p.market_type = 'goals'
        ORDER BY p.match_date DESC
    """)
    return cur.fetchall()


def _matches_before(cur, team_id, league_id, season, before_date, is_home):
    team_col = "home_team_id" if is_home else "away_team_id"
    opp_col = "away_team_id" if is_home else "home_team_id"
    cur.execute(f"""
        SELECT
            ms.match_date, ms.total_goals,
            ls.rank AS opponent_rank
        FROM match_statistics ms
        LEFT JOIN league_standings ls
            ON ls.team_id = ms.{opp_col}
           AND ls.league_id = ms.league_id
           AND ls.season = ms.season
        WHERE ms.{team_col} = %s
          AND ms.league_id = %s
          AND ms.season = %s
          AND ms.match_date < %s
        ORDER BY ms.match_date DESC
        LIMIT 15
    """, (team_id, league_id, season, before_date))
    return cur.fetchall()


def run():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    picks = _fetch_goals_picks(cur)
    print(f"[BACKTEST] {len(picks)} picks de gols (GREEN/RED) encontrados em picks_vip.\n")

    buckets = {"<60%": [], "60-70%": [], "70-80%": [], "80%+": [], "sem_amostra": []}
    skipped_no_parse = 0

    for p in picks:
        parsed = _parse_direction_line(p["line"])
        if not parsed:
            skipped_no_parse += 1
            continue
        direction, line_val = parsed

        home_hist = _matches_before(cur, p["home_team_id"], p["league_id"], p["season"], p["match_date"], is_home=True)
        away_hist = _matches_before(cur, p["away_team_id"], p["league_id"], p["season"], p["match_date"], is_home=False)

        def hit_fn(m):
            over = 1 if (m["total_goals"] or 0) > line_val else 0
            return over if direction == "over" else 1 - over

        home_rate = weighted_rate(home_hist, hit_fn, reference_date=p["match_date"])
        away_rate = weighted_rate(away_hist, hit_fn, reference_date=p["match_date"])

        n = home_rate["amostra"] + away_rate["amostra"]
        if n == 0:
            buckets["sem_amostra"].append(p)
            continue

        taxa_vals = [t for t in (home_rate["taxa_ponderada"], away_rate["taxa_ponderada"]) if t is not None]
        taxa_real = sum(taxa_vals) / len(taxa_vals)

        bucket = "<60%" if taxa_real < 0.60 else "60-70%" if taxa_real < 0.70 else "70-80%" if taxa_real < 0.80 else "80%+"
        buckets[bucket].append({"pick": p, "taxa_real": taxa_real})

    cur.close()
    conn.close()

    print(f"[BACKTEST] {skipped_no_parse} picks ignorados (line nao reconhecida como Over/Under).\n")
    print(f"{'Bucket taxa_real (Python)':<28}{'N':>6}{'Hit rate real (GREEN%)':>26}")
    for label in ("<60%", "60-70%", "70-80%", "80%+"):
        entries = buckets[label]
        n = len(entries)
        if n == 0:
            print(f"{label:<28}{n:>6}{'·':>26}")
            continue
        greens = sum(1 for e in entries if e["pick"]["result"] == "GREEN")
        print(f"{label:<28}{n:>6}{greens / n * 100:>25.1f}%")

    sem_amostra = len(buckets["sem_amostra"])
    print(f"\n{'sem historico suficiente':<28}{sem_amostra:>6}")
    print(
        "\nLeitura: se o hit rate real crescer junto com o bucket de taxa_real "
        "(60-70% < 70-80% < 80%+), a formula esta calibrada na direcao certa. "
        "Se for achatado ou invertido, os pesos (temporal_decay_weight / "
        "opponent_weight) precisam de ajuste antes de ir pra Fase 2."
    )


if __name__ == "__main__":
    run()
