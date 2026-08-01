"""Alavancagem via motor deterministico (pick_engine) -- unico gerador de
picks_alavancagem desde 2026-07-17 (decisao do usuario de cortar IA em
producao tambem, nao so em dev). Reimplementa localmente a busca de
fixtures/checagem de "ja rodou hoje" (nao importa de
ai/alavancagem_pipeline.py -- esse modulo instancia Anthropic() no nivel
de modulo). Mesmo algoritmo guloso da multipla, adaptado: aceita fixtures
de QUALQUER liga cadastrada (nao mais restrito a Copa do Mundo -- ver
atualizacao abaixo), permite pernas do mesmo fixture ou de fixtures
diferentes (regra original), tenta simples -> dupla -> tripla ate bater o
alvo [1.39, 1.55] de odd combinada (2-3 pernas de odd individual bem baixa
somando ~1.50 -- pedido explicito do usuario, 2026-07-22); so' cai pro
fallback [1.45, 1.90] se o alvo estreito nao achar combo nenhum no dia (ver
ODD_COMBINED_TARGET_*/ODD_COMBINED_FALLBACK_*).

Atualizacao: pipeline nasceu restrito a WC_LEAGUE_ID (so fixtures da Copa
do Mundo, torneio concentrado que facilitava achar combos no mesmo dia).
Com o torneio acabando (semifinal sabado, final domingo), passou a aceitar
fixtures de QUALQUER liga cadastrada em `leagues`, mesmo criterio de
selecao de fixture-do-dia que VIP/Dica/Multipla ja usam -- so 1 alavancagem
por dia, escolhida entre todos os candidatos elegiveis de todas as ligas."""
import itertools

import textwrap
import traceback
from utils.db_utils import get_connection
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.referee_stats_service import RefereeStatsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain
from services.pick_engine.ai_review import review_gate
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from engine_pipelines.decision_log import log_decision


# Alvo real da alavancagem ("odd 1.50"): 2-3 pernas de odd individual bem
# baixa somando ~1.50 de odd combinada -- pedido explicito do usuario
# (2026-07-22). Tentado PRIMEIRO; so cai no fallback largo abaixo se nenhum
# combo bater essa faixa estreita no dia.
ODD_COMBINED_TARGET_MIN = 1.39
ODD_COMBINED_TARGET_MAX = 1.55

# Fallback: mesmo range largo criado em 2026-07-21 (achado real: com poucos
# jogos no dia, a odd individual mais barata disponivel ja passa de 1.65,
# zerando os candidatos elegiveis o dia inteiro se so existisse a faixa
# estreita acima). So' usado quando o alvo 1.39-1.55 nao acha combo nenhum.
ODD_COMBINED_FALLBACK_MIN = 1.45
ODD_COMBINED_FALLBACK_MAX = 1.90
ODD_INDIVIDUAL_MIN = 1.05
ODD_INDIVIDUAL_MAX = 2.00  # = ODD_COMBINED_FALLBACK_MAX(1.90) + 0.10, mesma folga de sempre
MAX_FIXTURES = 15
MAX_CANDIDATES_FOR_COMBO = 12

_TIPO_POR_TAMANHO = {1: "simples", 2: "dupla", 3: "tripla"}



def _create_table_if_needed(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_alavancagem (
            id              SERIAL PRIMARY KEY,
            match_date      DATE UNIQUE,
            tipo            TEXT NOT NULL DEFAULT 'simples',
            fixture_id_1    INTEGER, home_team_1 TEXT, away_team_1 TEXT,
            market_1        TEXT, market_type_1 TEXT, line_1 TEXT, odd_1 NUMERIC,
            bet_house_1     TEXT, confidence_1 NUMERIC, prob_real_1 NUMERIC, reasoning_1 TEXT,
            fixture_id_2    INTEGER, home_team_2 TEXT, away_team_2 TEXT,
            market_2        TEXT, market_type_2 TEXT, line_2 TEXT, odd_2 NUMERIC,
            bet_house_2     TEXT, confidence_2 NUMERIC, prob_real_2 NUMERIC, reasoning_2 TEXT,
            fixture_id_3    INTEGER, home_team_3 TEXT, away_team_3 TEXT,
            market_3        TEXT, market_type_3 TEXT, line_3 TEXT, odd_3 NUMERIC,
            bet_house_3     TEXT, confidence_3 NUMERIC, prob_real_3 NUMERIC, reasoning_3 TEXT,
            odd_combined    NUMERIC,
            confidence_media NUMERIC,
            ev_combined     NUMERIC,
            result          TEXT,
            profit          NUMERIC,
            checked_at      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)


def _has_today_pick(cur) -> bool:
    cur.execute("SELECT COUNT(*) FROM picks_alavancagem WHERE match_date = CURRENT_DATE")
    return cur.fetchone()[0] >= 1


def _fixtures_with_odds_today(cur) -> list:
    """Fixtures de hoje, de qualquer liga cadastrada, com pelo menos 1 odd
    na faixa individual -- antes restrito a WC_LEAGUE_ID, ver docstring do
    modulo."""
    cur.execute("""
        SELECT DISTINCT f.fixture_id, f.home_team_id, f.away_team_id,
               f.home_team, f.away_team, f.season, f.match_datetime, f.league_id, f.round,
               f.referee
        FROM fixtures f
        INNER JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE f.match_datetime::date = CURRENT_DATE
          AND f.status = 'NS'
          AND ov.odd_value BETWEEN %s AND %s
        ORDER BY f.match_datetime
        LIMIT %s
    """, (ODD_INDIVIDUAL_MIN, ODD_INDIVIDUAL_MAX, MAX_FIXTURES))

    return [
        {
            "fixture_id": r[0], "home_team_id": r[1], "away_team_id": r[2],
            "home_team": r[3], "away_team": r[4], "season": r[5],
            "match_datetime": r[6], "league_id": r[7], "round": r[8],
            "referee": r[9],
        }
        for r in cur.fetchall()
    ]


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    # Fase 1.6 (2026-07-25): jogos anteriores a uma mudanca estrutural
    # marcada (troca de tecnico/elenco relevante) nao entram no historico --
    # ver teams.structural_change_date / MatchStatsService.get_structural_change_date.
    since_date = match_stats.get_structural_change_date(team_id)
    # Copa de clube usa o mesmo caminho que selecao desde 2026-08-01:
    # a competicao nao acumula jogo suficiente pra sustentar analise
    # sozinha (ver competition_profile.uses_all_competitions_history).
    if cp.uses_all_competitions_history(league_id):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since_date)
    return match_stats.get_all_matches_full(team_id, season, league_id, since_date=since_date)


def _gather_leg_candidates(fixtures: list) -> list:
    """Roda o motor por fixture da Copa, mantem so candidatos com odd
    individual na faixa exigida pra combos."""
    match_stats = MatchStatsService()
    odds_service = OddsService()
    referee_service = RefereeStatsService()
    legs = []

    for fixture in fixtures:
        try:
            structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
            if not structured_odds:
                continue

            last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
            last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
            if not last10_home or not last10_away:
                continue

            hist_home_val = dv.validate_history(last10_home)
            hist_away_val = dv.validate_history(last10_away)
            if not hist_home_val["passed"] or not hist_away_val["passed"]:
                continue

            profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
            profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
            matchup = tpm.compare_matchup(profile_home, profile_away)
            context_data = ctx.build_context(
                last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
                None, None, fixture["league_id"], round_str=fixture.get("round"),
            )
            team_strength_data = ts.compare_team_strength(profile_home, profile_away)
            referee_stats = referee_service.get_stats(fixture.get("referee"), fixture["season"])
            league_stats = referee_service.get_league_stats(fixture["league_id"], fixture["season"])

            coverage_val = dv.validate_coverage(
                structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
                referee_stats=referee_stats, context_data=context_data,
            )
            integrity_val, outlier_info = dv.aggregate_fixture_quality_checks(last10_home, last10_away)
            quality = dv.data_quality_score(
                {"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val,
                integrity_validation=integrity_val, outlier_info=outlier_info,
            )

            candidates = analyze_fixture_markets(
                structured_odds, last10_home, last10_away,
                context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
                referee_stats=referee_stats, league_stats=league_stats,
                league_id=fixture["league_id"], data_quality_score=quality["score"],
            )
            picks = rank_market_candidates(candidates)
            log_decision("ALAVANCAGEM_ENGINE", fixture, candidates, picks, matchup=matchup, context_data=context_data)

            for p in picks:
                if not (ODD_INDIVIDUAL_MIN <= p["odd"] <= ODD_INDIVIDUAL_MAX):
                    continue
                legs.append({**p, "_fixture": fixture, "data_quality_score": quality["score"]})

        except Exception as e:
            # Stack trace completo: sem ele, "pulou 8 fixtures" nao diz
            # ONDE quebrou -- e o caminho de gravacao mudou em 2026-08-01.
            print(f"[ALAVANCAGEM_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue

    return legs


def _find_combo(legs: list, odd_min: float, odd_max: float) -> tuple | None:
    """Tenta simples -> dupla -> tripla (pernas podem ser do mesmo fixture
    ou de fixtures diferentes) ate o produto real das odds cair em
    [odd_min, odd_max]. Rejeita combo com todas as pernas do mesmo
    market_type. Faixa recebida por parametro pra permitir tentar o alvo
    estreito primeiro e cair pro fallback largo depois (ver
    run_alavancagem_engine)."""
    pool = sorted(legs, key=lambda p: p["final_score"], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]

    for combo_size in (1, 2, 3):
        best = None
        for combo in itertools.combinations(pool, combo_size):
            market_types = {p["market_type"] for p in combo}
            if combo_size > 1 and len(market_types) == 1:
                continue  # todas as pernas com o mesmo mercado -- correlacionado, rejeita

            odd_combined = round(1.0, 4)
            for p in combo:
                odd_combined *= p["odd"]
            odd_combined = round(odd_combined, 4)

            if not (odd_min <= odd_combined <= odd_max):
                continue

            confidence_media = round(sum(p["confidence"] for p in combo) / len(combo), 4)
            if best is None or confidence_media > best[1]:
                best = (combo, confidence_media, odd_combined)

        if best:
            return best[0], best[1], best[2]

    return None


def _save_pick(cur, legs: tuple, confidence_media: float, odd_combined: float):
    tipo = _TIPO_POR_TAMANHO[len(legs)]
    cols, vals = ["match_date", "tipo"], ["CURRENT_DATE", "%s"]
    params = [tipo]

    for i, p in enumerate(legs, start=1):
        fx = p["_fixture"]
        cols += [f"fixture_id_{i}", f"home_team_{i}", f"away_team_{i}",
                 f"market_{i}", f"market_type_{i}", f"line_{i}", f"odd_{i}",
                 f"bet_house_{i}", f"confidence_{i}", f"prob_real_{i}", f"reasoning_{i}"]
        vals += ["%s"] * 11
        params += [
            fx["fixture_id"], fx["home_team"], fx["away_team"],
            p["market_name"], p["market_type"], p["value_label"], p["odd"],
            p["best_bookmaker"], p["confidence"], p["taxa_real"], explain(p),
        ]

    ev_combined = round(sum(p["ev"] for p in legs) / len(legs), 4)

    cols += ["odd_combined", "confidence_media", "ev_combined"]
    vals += ["%s", "%s", "%s"]
    params += [odd_combined, confidence_media, ev_combined]

    cur.execute(f"INSERT INTO picks_alavancagem ({', '.join(cols)}) VALUES ({', '.join(vals)})", params)
    return tipo


def run_alavancagem_engine():
    conn = get_connection()
    cur = conn.cursor()
    _create_table_if_needed(cur)
    conn.commit()

    if _has_today_pick(cur):
        print("[ALAVANCAGEM_ENGINE] Já existe pick de hoje.")
        cur.close()
        conn.close()
        return

    fixtures = _fixtures_with_odds_today(cur)
    if not fixtures:
        print("[ALAVANCAGEM_ENGINE] Nenhum fixture com odd na faixa individual hoje.")
        cur.close()
        conn.close()
        return

    legs = _gather_leg_candidates(fixtures)
    if not legs:
        print("[ALAVANCAGEM_ENGINE] Nenhum candidato elegível com odd individual na faixa.")
        cur.close()
        conn.close()
        return

    result = _find_combo(legs, ODD_COMBINED_TARGET_MIN, ODD_COMBINED_TARGET_MAX)
    if not result:
        print(f"[ALAVANCAGEM_ENGINE] Nenhum combo no alvo [{ODD_COMBINED_TARGET_MIN}, {ODD_COMBINED_TARGET_MAX}] · tentando fallback largo...")
        result = _find_combo(legs, ODD_COMBINED_FALLBACK_MIN, ODD_COMBINED_FALLBACK_MAX)
    if not result:
        print(f"[ALAVANCAGEM_ENGINE] Nenhuma combinação bateu nem o alvo [{ODD_COMBINED_TARGET_MIN}, {ODD_COMBINED_TARGET_MAX}] nem o fallback [{ODD_COMBINED_FALLBACK_MIN}, {ODD_COMBINED_FALLBACK_MAX}].")
        cur.close()
        conn.close()
        return

    combo, confidence_media, odd_combined = result
    reviewed = review_gate("alavancagem").apply(list(combo), "alavancagem")
    if not reviewed:
        print("[ALAVANCAGEM_ENGINE] Combinacao vetada pela revisao de IA.")
        cur.close()
        conn.close()
        return
    combo = tuple(reviewed)
    tipo = _save_pick(cur, combo, confidence_media, odd_combined)
    conn.commit()
    cur.close()
    conn.close()

    pernas = " + ".join(
        f"{p['_fixture']['home_team']} x {p['_fixture']['away_team']} ({p['market_name']} {p['value_label']} @ {p['odd']})"
        for p in combo
    )
    print(f"[ALAVANCAGEM_ENGINE] Salva ({tipo}): {pernas} | odd_combined={odd_combined} | confidence_media={confidence_media}")


if __name__ == "__main__":
    run_alavancagem_engine()
