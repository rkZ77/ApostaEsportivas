"""Modo sombra do motor de picks (services/pick_engine) para o VIP --
SOMENTE LEITURA, roda contra o banco de PRODUCAO real. Nunca escreve em
picks_vip nem em nenhuma outra tabela de picks; so acrescenta linhas a
`ApostaEsportivas/logs/vip_engine_shadow.jsonl`.

Objetivo: comparar o pick que o motor determinista teria escolhido com o
pick que a IA de fato salvou (e o resultado real, quando ja resolvido),
para os MESMOS fixtures, antes de trocar o pipeline VIP de verdade
(Sprint 4 do plano de refatoracao). Diferente de shadow_consensus.py (que
so existe em dev e so comparou 1 fixture com dado fake), este roda contra
dado real e persiste um historico continuo.

Duas fontes de fixtures, processadas da mesma forma:
  1. Picks VIP ja salvos pela IA nos ultimos N dias (comparacao motor x IA,
     incluindo resultado real quando ja resolvido) -- so funciona se as odds
     daquele momento ainda existirem em odds_values (normalmente NAO existem
     mais depois que o jogo comeca, ver nota abaixo).
  2. Fixtures NS (ainda nao comecaram) sem pick VIP ainda -- sem comparacao
     com a IA (pipeline diario pode estar pausado), mas valida o motor
     sozinho contra dados reais e atuais.

NOTA sobre retencao de odds: `odds_values` e efemera -- confirmado em
producao que fica vazia entre coletas (jogos ja jogados nao tem odds
salvas). Pra fonte 1 gerar comparacoes de verdade, rode logo depois de uma
coleta de odds fresca (capturar_odds), antes do jogo comecar.

Uso:
    python -m ai.vip_engine_shadow              # ultimos 7 dias de picks_vip + fixtures NS
    python -m ai.vip_engine_shadow --dias 14     # janela customizada
"""
import os
import json
import argparse
from datetime import datetime

# Mesma logica de mapeamento de env que run_prod.py -- garante que todas as
# services usadas aqui (FixturesService/OddsService/MatchStatsService),
# que resolvem a conexao via get_connection() sem argumentos, apontem para
# o banco de PRODUCAO real.
for _key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE"):
    _prod_val = os.getenv(f"{_key}_PROD")
    if _prod_val:
        os.environ[_key] = _prod_val
os.environ["DB_ENV"] = "prod"

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
from services.odds_service import OddsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "vip_engine_shadow.jsonl")


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    if league_id in NATIONAL_TEAM_LEAGUE_IDS:
        return match_stats.get_last_n_all_competitions(team_id)
    return match_stats.get_all_matches_full(team_id, season, league_id)


def _build_signals(last10_home, last10_away, home_team_id, away_team_id, league_id):
    profile_home = tpm.build_profile(last10_home, home_team_id)
    profile_away = tpm.build_profile(last10_away, away_team_id)
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, home_team_id, away_team_id,
        None, None, league_id,
    )
    team_strength_data = ts.compare_team_strength(profile_home, profile_away)
    return context_data, matchup, team_strength_data


def _fetch_recent_vip_picks(cur, dias: int) -> list[dict]:
    """Fixtures que ja tem pick VIP salvo pela IA nos ultimos N dias --
    o motor roda para os MESMOS fixtures, pra comparacao ser 1:1. Traz
    tambem o pick da IA e o resultado real (se ja resolvido).

    Junta com match_statistics (nao fixtures!) para achar league_id/season --
    a tabela `fixtures` e efemera (so guarda jogos NS pendentes, e limpa depois
    que o jogo acontece; confirmado em producao: so 2 linhas na tabela toda),
    enquanto match_statistics e o registro historico durable."""
    cur.execute("""
        SELECT
            v.fixture_id, ms.league_id, ms.season,
            v.home_team_id, v.away_team_id, v.home_team_name, v.away_team_name,
            ms.match_date,
            v.market, v.line, v.odd, v.confidence, v.probability AS ev_prob,
            v.result, v.profit
        FROM picks_vip v
        JOIN match_statistics ms ON ms.fixture_id = v.fixture_id
        WHERE v.match_date >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY ms.match_date DESC
    """, (dias,))
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _process_fixture(
    fixture_id, league_id, season, home_team_id, away_team_id,
    home_team_name, away_team_name, match_date,
    match_stats: MatchStatsService, odds_service: OddsService,
    ai_pick: dict | None,
) -> dict | None:
    """Roda o motor pra 1 fixture e monta o registro de log. Retorna None
    se nao houver dado suficiente (odds ou historico) pra analisar."""
    structured_odds = odds_service.load_odds_structured(fixture_id)
    if not structured_odds:
        print(f"[VIP_SHADOW] Fixture {fixture_id}: sem odds estruturadas, pulando.")
        return None

    last10_home = _load_history(match_stats, home_team_id, season, league_id)
    last10_away = _load_history(match_stats, away_team_id, season, league_id)
    if not last10_home or not last10_away:
        print(f"[VIP_SHADOW] Fixture {fixture_id}: sem historico suficiente, pulando.")
        return None

    context_data, matchup, team_strength_data = _build_signals(
        last10_home, last10_away, home_team_id, away_team_id, league_id
    )

    candidates = analyze_fixture_markets(
        structured_odds, last10_home, last10_away,
        context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
    )
    engine_picks = rank_market_candidates(candidates)
    engine_best = next((p for p in engine_picks if p.get("is_best_pick")), None)

    record = {
        "logged_at": datetime.now().isoformat(),
        "fixture_id": fixture_id,
        "home_team": home_team_name,
        "away_team": away_team_name,
        "league_id": league_id,
        "match_datetime": match_date.isoformat() if match_date else None,
        "ai_pick": ai_pick,
        "engine_best_pick": {
            "market_name":  engine_best["market_name"],
            "value_label":  engine_best["value_label"],
            "odd":          engine_best["odd"],
            "confidence":   engine_best["confidence"],
            "ev":           engine_best["ev"],
            "taxa_real":    engine_best["taxa_real"],
            "risco":        engine_best["risco"],
            "market_type":  engine_best["market_type"],
            "variance_penalty": engine_best.get("variance_penalty"),
            "poisson_probability": engine_best.get("poisson_probability"),
            "model_fit_adjustment": engine_best.get("model_fit_adjustment"),
        } if engine_best else None,
        "team_strength": team_strength_data,
        "engine_candidates_count": len(candidates),
        "engine_eligible_count": len(engine_picks),
        "reasoning_preview": explain(engine_best)[:200] if engine_best else None,
    }

    ai_label = (
        f"{ai_pick['market']} {ai_pick['line']} @ {ai_pick['odd']}"
        if ai_pick and ai_pick.get("market") else ("sem pick da IA (fixture novo)" if ai_pick is None else "sem pick")
    )
    eng_label = (
        f"{engine_best['market_name']} {engine_best['value_label']} @ {engine_best['odd']} "
        f"(conf={engine_best['confidence']*100:.0f}%)"
        if engine_best else "sem candidato aprovado"
    )
    print(f"[VIP_SHADOW] Fixture {fixture_id} ({home_team_name} x {away_team_name}): "
          f"IA={ai_label} | MOTOR={eng_label}")

    return record


def run_shadow(dias: int = 7):
    fixtures_service = FixturesService()
    match_stats = MatchStatsService()
    odds_service = OddsService()

    conn = get_connection("prod")
    cur = conn.cursor()

    historico = _fetch_recent_vip_picks(cur, dias)
    ns_fixtures = fixtures_service.get_ns_without_suggestions()

    print(f"[VIP_SHADOW] {len(historico)} pick(s) VIP dos ultimos {dias} dia(s) "
          f"+ {len(ns_fixtures)} fixture(s) NS ainda sem pick.")

    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
    logged = 0

    with open(_LOG_PATH, "a", encoding="utf-8") as log_file:
        for row in historico:
            ai_pick = {
                "market": row["market"],
                "line": row["line"],
                "odd": float(row["odd"]) if row["odd"] is not None else None,
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
                "result": row["result"],
                "profit": float(row["profit"]) if row["profit"] is not None else None,
            }
            try:
                record = _process_fixture(
                    row["fixture_id"], row["league_id"], row["season"],
                    row["home_team_id"], row["away_team_id"],
                    row["home_team_name"], row["away_team_name"], row["match_date"],
                    match_stats, odds_service, ai_pick,
                )
            except Exception as e:
                print(f"[VIP_SHADOW] Erro no fixture {row['fixture_id']}, pulando: {e}")
                continue
            if record:
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                logged += 1

        for fx in ns_fixtures:
            try:
                record = _process_fixture(
                    fx["fixture_id"], fx["league_id"], fx["season"],
                    fx["home_team_id"], fx["away_team_id"],
                    fx["home_team"], fx["away_team"], fx.get("match_datetime"),
                    match_stats, odds_service, ai_pick=None,
                )
            except Exception as e:
                print(f"[VIP_SHADOW] Erro no fixture {fx['fixture_id']}, pulando: {e}")
                continue
            if record:
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                logged += 1

    cur.close()
    conn.close()
    print(f"[VIP_SHADOW] {logged} registro(s) gravado(s) em {os.path.abspath(_LOG_PATH)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=7)
    args = parser.parse_args()
    run_shadow(dias=args.dias)
