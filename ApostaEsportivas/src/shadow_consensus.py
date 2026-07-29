"""Modo sombra (Fase 3 do motor de picks): roda o pick_engine para os
mesmos fixtures que ja tem pick salvo pela IA hoje (picks_vip/picks_free),
e registra as duas saidas lado a lado em logs/shadow_consensus.jsonl.

NUNCA escreve em picks_vip/picks_free/picks_alavancagem -- so leitura
dessas tabelas e escrita no arquivo de log. Cada fixture roda isolado em
try/except: uma falha nao derruba os demais nem quem chamou este script.

picks_alavancagem fica fora por ora (schema multi-perna fixture_id_1/2/3,
nao mapeia 1:1 pra um unico fixture como picks_vip/picks_free).

Uso: python main.py shadow  (ou "python shadow_consensus.py" direto)
"""
import sys
import os
import json
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
from services.odds_service import OddsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates
from services.pick_engine import consensus

from utils.paths import LOGS_DIR as LOG_DIR, log_path

LOG_PATH = log_path("shadow_consensus.jsonl")


def _today_ai_picks(cur) -> list:
    """Le os picks de hoje de picks_vip e picks_free (fixture_id unico)."""
    picks = []

    cur.execute("""
        SELECT fixture_id, market_type, market, line, confidence, ev, probability
        FROM picks_vip
        WHERE match_date = CURRENT_DATE
    """)
    for row in cur.fetchall():
        picks.append({
            "source": "picks_vip",
            "fixture_id": row[0], "market_type": row[1], "market": row[2],
            "line": row[3], "confidence": row[4], "ev": row[5], "probability": row[6],
        })

    cur.execute("""
        SELECT fixture_id, market_type, market, line, confidence, prob_real
        FROM picks_free
        WHERE match_date = CURRENT_DATE
    """)
    for row in cur.fetchall():
        picks.append({
            "source": "picks_free",
            "fixture_id": row[0], "market_type": row[1], "market": row[2],
            "line": row[3], "confidence": row[4], "ev": None, "probability": row[5],
        })

    return picks


def _run_engine_for_fixture(fixture_id: int):
    """Roda o pick_engine (sem contexto/perfil/noticias por ora -- so o que
    ja da pra montar com dados que ja temos aqui sem duplicar todo o
    pipeline) e devolve os picks rankeados, ou [] se faltar dado."""
    fixtures_service = FixturesService()
    match_stats = MatchStatsService()
    odds_service = OddsService()

    fixture = fixtures_service.get_fixture_by_id(fixture_id)
    if not fixture:
        return []

    structured_odds = odds_service.load_odds_structured(fixture_id)
    if not structured_odds:
        return []

    # Selecoes precisam cruzar todas as competicoes (Copa + Eliminatorias +
    # Amistosos) -- so jogos da liga/temporada atual (ex: so a Copa) da
    # amostra pequena demais. Mesmo criterio ja usado no resto do projeto
    # (match_stats_service.NATIONAL_TEAM_LEAGUE_IDS).
    if fixture["league_id"] in NATIONAL_TEAM_LEAGUE_IDS:
        last10_home = match_stats.get_last_n_all_competitions(fixture["home_team_id"])
        last10_away = match_stats.get_last_n_all_competitions(fixture["away_team_id"])
    else:
        last10_home = match_stats.get_all_matches_full(
            fixture["home_team_id"], fixture["season"], fixture["league_id"])
        last10_away = match_stats.get_all_matches_full(
            fixture["away_team_id"], fixture["season"], fixture["league_id"])

    candidates = analyze_fixture_markets(structured_odds, last10_home, last10_away)
    return rank_market_candidates(candidates)


def run_shadow_comparison():
    os.makedirs(LOG_DIR, exist_ok=True)
    conn = get_connection()
    cur = conn.cursor()

    ai_picks = _today_ai_picks(cur)
    cur.close()
    conn.close()

    if not ai_picks:
        print("[SHADOW] Nenhum pick de IA salvo hoje ainda.")
        return

    written = 0
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        for ai_pick in ai_picks:
            fixture_id = ai_pick.get("fixture_id")
            if not fixture_id:
                continue
            try:
                engine_picks = _run_engine_for_fixture(fixture_id)
                if not engine_picks:
                    print(f"[SHADOW] Fixture {fixture_id}: motor nao gerou pick comparavel, pulando.")
                    continue

                engine_match = next(
                    (p for p in engine_picks if p["market_type"] == ai_pick["market_type"]),
                    engine_picks[0],
                )
                comparison = consensus.compare_ai_vs_engine(ai_pick, engine_match)
                comparison["logged_at"] = datetime.now().isoformat()
                comparison["ai_source"] = ai_pick["source"]

                log_file.write(json.dumps(comparison, ensure_ascii=False) + "\n")
                written += 1

            except Exception as e:
                print(f"[SHADOW] Erro no fixture {fixture_id}, pulando: {e}")
                continue

    print(f"[SHADOW] {written} comparações gravadas em {LOG_PATH}")


if __name__ == "__main__":
    run_shadow_comparison()
