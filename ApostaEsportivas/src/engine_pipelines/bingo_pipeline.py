"""BINGO via motor deterministico (pick_engine) -- junta 2-4 jogos
DIFERENTES no mesmo bilhete. Cada jogo entra com o seu proprio sub-combo
(1 a 3 mercados do MESMO jogo, ja garantidos nao-correlacionados por
rank_market_candidates -- no maximo 1 pick por grupo de correlacao, ver
services/pick_engine/ranking.py::select_final_picks) cujo PRODUTO REAL de
odds cai em [GAME_ODD_MIN, GAME_ODD_MAX] por jogo. Alem disso (regra do
usuario, 2026-07-21), o ODD FINAL do bilhete inteiro (produto dos
sub-combos dos jogos escolhidos) tambem precisa cair em
[ODD_FINAL_MIN, ODD_FINAL_MAX] -- sem esse teto o bingo podia sair com
odd final parecida com a da Multipla (2.00-3.00), perdendo a identidade
do produto. _select_bingo() busca, entre os jogos elegiveis, a combinacao
de 2-4 jogos cujo produto bate essa faixa (nao so pega os melhores por
score).

Reimplementa localmente selecao de fixtures/checagem "ja rodou hoje"/
bloqueio de pares ja usados em VIP/Free, mesmo padrao ja usado em
engine_pipelines/multipla_pipeline.py e engine_pipelines/alavancagem_pipeline.py
(nao compartilha codigo entre os tres de proposito -- cada um evoluiu
esses detalhes de forma independente).

CONFIG COM min_odd REBAIXADO (achado testando com jogos reais em dev,
2026-07-20): o DEFAULT_CONFIG do motor tem min_odd=1.39 (piso pensado pro
VIP, pick unico) -- combinar DUAS pernas com odd >=1.39 cada sempre da um
produto >=1.93, que ja estoura o teto original de 1.60 do sub-combo por
jogo. Ou seja, com o piso padrao, sub-combo de 2-3 pernas e matematicamente
quase impossivel (so sobra selecao de 1 perna so, quando ela cai sozinha no
range) -- mesmo problema que a alavancagem ja resolveu, com o mesmo
remedio: piso de odd individual bem mais baixo (1.05, igual
ODD_INDIVIDUAL_MIN de alavancagem_pipeline.py) so pra permitir o produto
de 2-3 pernas convergir pro range. Os outros criterios de qualidade (taxa
minima, confidence minima, EV>0, bookmakers>=2) continuam os mesmos do
DEFAULT_CONFIG.

FAIXA E MIN_GAMES AFROUXADOS (mesmo teste, 2026-07-20): rodando contra 8
jogos reais do Brasileirao A/B, so 1 jogo teve sub-combo valido na faixa
original 1.40-1.60 (mesmo com o piso de odd corrigido acima) -- e raro um
jogo ter 2+ mercados independentes "baratos" o bastante ao mesmo tempo pra
multiplicar e cair numa faixa tao estreita. Decisao do usuario: alargar pra
1.30-1.70 por jogo e reduzir MIN_GAMES de 3 para 2, pra o bingo fechar com
mais frequencia mesmo em dias com poucos jogos disponiveis.

Exclusivo VIP. Precisa de pelo menos MIN_GAMES jogos elegiveis no dia
para rodar; usa os MAX_GAMES melhores (por combo_score medio das legs)
quando houver mais candidatos do que o teto."""
import json
import itertools
from dataclasses import replace

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine.config import DEFAULT_CONFIG
from engine_pipelines.decision_log import log_decision

GAME_ODD_MIN = 1.30
GAME_ODD_MAX = 1.70
MIN_GAMES = 2
MAX_GAMES = 4
MAX_FIXTURES = 20  # teto de fixtures analisados por rodada (custo do motor por fixture)

# ODD FINAL do bilhete (produto do combo_odd de cada jogo escolhido) --
# regra do usuario (2026-07-21): tem que ficar entre 3.00 e 6.00, senao o
# bingo fica indistinguivel da Multipla (que ja mira 2.00-3.00). Aplicada
# em _select_bingo(), que busca entre 2-4 jogos elegiveis a combinacao que
# bate essa faixa (nao so pega os N melhores por score, como antes).
ODD_FINAL_MIN = 3.0
ODD_FINAL_MAX = 6.0
MAX_CANDIDATES_FOR_BINGO = 10  # limita o espaco de busca das combinacoes de jogos

BINGO_CONFIG = replace(DEFAULT_CONFIG, min_odd=1.05)


def _create_table_if_needed(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_bingo (
            id                SERIAL PRIMARY KEY,
            tipo              TEXT,
            games             JSONB,
            odd_final         NUMERIC,
            confidence_media  NUMERIC,
            ev_media          NUMERIC,
            match_date        DATE,
            result            TEXT,
            profit            NUMERIC,
            reasoning         TEXT,
            checked_at        TIMESTAMP,
            created_at        TIMESTAMP DEFAULT NOW()
        );
    """)


def _has_today_bingo(cur) -> bool:
    cur.execute("SELECT COUNT(*) FROM picks_bingo WHERE match_date = CURRENT_DATE")
    return cur.fetchone()[0] >= 1


def _today_used_pairs(cur) -> set:
    """(fixture_id, market_type) ja usados em picks_vip/picks_free hoje --
    mesma regra de bloqueio ja aplicada em multipla_pipeline, pra bingo
    (exclusivo VIP) nao repetir pro assinante um mercado que ja saiu como
    pick simples no dia."""
    pairs = set()
    cur.execute("SELECT fixture_id, market_type FROM picks_vip WHERE match_date = CURRENT_DATE")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    cur.execute("SELECT fixture_id, market_type FROM picks_free WHERE match_date = CURRENT_DATE")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    return pairs


def _load_history(match_stats: MatchStatsService, team_id: int, season: int, league_id: int) -> list:
    if cp.is_national_team_league(league_id):
        return match_stats.get_last_n_all_competitions(team_id)
    return match_stats.get_all_matches_full(team_id, season, league_id)


def _fixture_picks(fixture: dict, used_pairs: set, match_stats: MatchStatsService, odds_service: OddsService) -> list:
    """Roda o motor pro fixture e devolve os candidatos elegiveis dele (ja
    decorrelacionados por rank_market_candidates, ate 3), excluindo quem
    repete (fixture_id, market_type) ja usado em VIP/Free hoje."""
    structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
    if not structured_odds:
        return []

    last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
    last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
    if not last10_home or not last10_away:
        return []

    hist_home_val = dv.validate_history(last10_home)
    hist_away_val = dv.validate_history(last10_away)
    if not hist_home_val["passed"] or not hist_away_val["passed"]:
        return []

    profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
    profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
    matchup = tpm.compare_matchup(profile_home, profile_away)
    context_data = ctx.build_context(
        last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
        None, None, fixture["league_id"], round_str=fixture.get("round"),
    )
    team_strength_data = ts.compare_team_strength(profile_home, profile_away)

    coverage_val = dv.validate_coverage(
        structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
        context_data=context_data,
    )
    quality = dv.data_quality_score(
        {"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val,
    )

    candidates = analyze_fixture_markets(
        structured_odds, last10_home, last10_away,
        config=BINGO_CONFIG,
        context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
        data_quality_score=quality["score"],
    )
    picks = rank_market_candidates(candidates, config=BINGO_CONFIG)
    log_decision("BINGO_ENGINE", fixture, candidates, picks, matchup=matchup, context_data=context_data)

    return [p for p in picks if (fixture["fixture_id"], p["market_type"]) not in used_pairs]


def _build_game_combo(picks: list) -> dict | None:
    """Entre os candidatos JA decorrelacionados de UM fixture, procura o
    MENOR sub-combo (1, depois 2, depois 3 pernas) cujo produto real de
    odds cai em [GAME_ODD_MIN, GAME_ODD_MAX] -- para no primeiro tamanho
    com qualquer combo valido (mesmo criterio ja usado em
    alavancagem_pipeline: prefere o sub-combo mais simples que bate a
    faixa, em vez de forcar mais pernas que o necessario)."""
    for combo_size in range(1, min(len(picks), 3) + 1):
        best = None
        for combo in itertools.combinations(picks, combo_size):
            odd = round(1.0, 4)
            for p in combo:
                odd *= p["odd"]
            odd = round(odd, 4)
            if not (GAME_ODD_MIN <= odd <= GAME_ODD_MAX):
                continue
            score = round(sum(p["final_score"] for p in combo) / len(combo), 4)
            if best is None or score > best[1]:
                best = (combo, score, odd)
        if best:
            return {"legs": list(best[0]), "combo_score": best[1], "combo_odd": best[2]}
    return None


def _gather_game_combos(fixtures: list, used_pairs: set) -> list:
    match_stats = MatchStatsService()
    odds_service = OddsService()
    combos = []

    for fixture in fixtures[:MAX_FIXTURES]:
        try:
            picks = _fixture_picks(fixture, used_pairs, match_stats, odds_service)
            if not picks:
                continue
            combo = _build_game_combo(picks)
            if combo:
                combo["fixture"] = fixture
                combos.append(combo)
        except Exception as e:
            print(f"[BINGO_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            continue

    return combos


def _select_bingo(game_combos: list) -> list | None:
    """Busca, entre os jogos elegiveis (2 a MAX_GAMES), a combinacao cujo
    ODD FINAL (produto do combo_odd de cada jogo) cai em
    [ODD_FINAL_MIN, ODD_FINAL_MAX] -- regra do usuario (2026-07-21): sem
    esse teto o bingo podia sair com odd final parecida com a da propria
    Multipla (2.00-3.00), perdendo a identidade do produto. Entre as
    combinacoes validas, prefere a de maior score medio."""
    if len(game_combos) < MIN_GAMES:
        return None
    pool = sorted(game_combos, key=lambda g: g["combo_score"], reverse=True)[:MAX_CANDIDATES_FOR_BINGO]

    best = None
    for combo_size in range(MIN_GAMES, min(len(pool), MAX_GAMES) + 1):
        for combo in itertools.combinations(pool, combo_size):
            odd_final = round(1.0, 4)
            for g in combo:
                odd_final *= g["combo_odd"]
            odd_final = round(odd_final, 4)
            if not (ODD_FINAL_MIN <= odd_final <= ODD_FINAL_MAX):
                continue
            score = round(sum(g["combo_score"] for g in combo) / len(combo), 4)
            if best is None or score > best[1]:
                best = (list(combo), score, odd_final)

    if not best:
        return None
    return best[0]


def _save_bingo(cur, selected: list) -> float:
    games_info = []
    for g in selected:
        fx = g["fixture"]
        legs_info = [{
            "market": p["market_name"],
            "market_type": p["market_type"],
            "line": p["value_label"],
            "odd": p["odd"],
            "bet_house": p["best_bookmaker"],
            "confidence": p["confidence"],
            "prob_real": p["taxa_real"],
        } for p in g["legs"]]
        games_info.append({
            "fixture_id": fx["fixture_id"],
            "home_team": fx["home_team"],
            "away_team": fx["away_team"],
            "home_team_id": fx["home_team_id"],
            "away_team_id": fx["away_team_id"],
            "combo_odd": g["combo_odd"],
            "combo_score": g["combo_score"],
            "legs": legs_info,
        })

    odd_final = round(1.0, 4)
    for g in selected:
        odd_final *= g["combo_odd"]
    odd_final = round(odd_final, 4)

    all_legs = [p for g in selected for p in g["legs"]]
    confidence_media = round(sum(g["combo_score"] for g in selected) / len(selected), 4)
    ev_media = round(sum(p["ev"] for p in all_legs) / len(all_legs), 4)
    match_date = min(g["fixture"]["match_datetime"] for g in selected).date()
    reasoning = " | ".join(explain(p) for p in all_legs)
    tipo = f"bingo_{len(selected)}"

    cur.execute("""
        INSERT INTO picks_bingo
        (tipo, games, odd_final, confidence_media, ev_media, match_date, reasoning)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        tipo,
        json.dumps(games_info, default=str),
        odd_final,
        confidence_media,
        ev_media,
        match_date,
        reasoning,
    ))
    return odd_final


def run_bingo_engine():
    conn = get_connection()
    cur = conn.cursor()
    _create_table_if_needed(cur)
    conn.commit()

    if _has_today_bingo(cur):
        print("[BINGO_ENGINE] Já existe bingo de hoje.")
        cur.close()
        conn.close()
        return

    fixtures_service = FixturesService()
    fixtures = fixtures_service.get_fixtures_today()
    if len(fixtures) < MIN_GAMES:
        print(f"[BINGO_ENGINE] Só {len(fixtures)} fixture(s) hoje · precisa de pelo menos {MIN_GAMES}.")
        cur.close()
        conn.close()
        return

    used_pairs = _today_used_pairs(cur)
    game_combos = _gather_game_combos(fixtures, used_pairs)
    if len(game_combos) < MIN_GAMES:
        print(f"[BINGO_ENGINE] Só {len(game_combos)} jogo(s) com sub-combo válido em "
              f"[{GAME_ODD_MIN},{GAME_ODD_MAX}] · precisa de pelo menos {MIN_GAMES}.")
        cur.close()
        conn.close()
        return

    selected = _select_bingo(game_combos)
    if not selected:
        print(f"[BINGO_ENGINE] Nenhuma combinação de {MIN_GAMES}-{MAX_GAMES} jogos bateu a faixa de "
              f"odd final [{ODD_FINAL_MIN},{ODD_FINAL_MAX}] · {len(game_combos)} jogo(s) elegível(is) no total.")
        cur.close()
        conn.close()
        return

    odd_final = _save_bingo(cur, selected)
    conn.commit()
    cur.close()
    conn.close()

    jogos = " + ".join(
        f"{g['fixture']['home_team']} x {g['fixture']['away_team']} (@{g['combo_odd']})"
        for g in selected
    )
    print(f"[BINGO_ENGINE] Salvo ({len(selected)} jogos): {jogos} | odd_final={odd_final}")


if __name__ == "__main__":
    run_bingo_engine()
