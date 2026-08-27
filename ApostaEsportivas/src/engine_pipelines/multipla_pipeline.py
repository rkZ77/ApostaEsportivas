"""Multipla via motor deterministico (pick_engine) -- unico gerador de
picks_multiplas desde 2026-07-17 (decisao do usuario de cortar IA em
producao tambem, nao so em dev). Reimplementa localmente selecao de
fixtures/checagem de "ja rodou hoje"/bloqueio de pares ja usados (nao
importa de ai/multipla_pipeline.py -- esse modulo instancia Anthropic()
no nivel de modulo). O algoritmo de escolha de pernas (2-3 jogos ate
bater a odd total exigida) nao existe hoje em lugar nenhum -- aqui e um
guloso deterministico: ordena candidatos elegiveis por Score Final, testa
combinacoes de fixtures diferentes ate achar uma cujo produto real das
odds (nunca um valor "esperado") caia na faixa exigida."""
import json
import textwrap
import traceback
import itertools
from datetime import datetime

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR, data_br
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.team_stats_service import TeamStatsService
from services.referee_stats_service import RefereeStatsService
from services.standings_service import StandingsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain
from services.pick_engine.ai_review import review_gate
from services.pick_engine.staking import calculate_stake
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import context_gate
from services.pick_engine import stats_model
from services.pick_engine import competition_rules_store
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_run, log_skip,
)
from services.engine_audit import auditar


ODD_TOTAL_MIN = 2.00
ODD_TOTAL_MAX = 4.00  # era 3.00 -- achado real (2026-07-21): com poucos jogos
                      # no dia, o menor produto possivel entre 2 pernas de
                      # jogos diferentes ja passa de 3.00 (ex: 1.82x1.85=3.37),
                      # bloqueando a multipla o dia inteiro sem motivo real de
                      # qualidade. Decisao do usuario: alargar o teto pra 4.00.
# Sem teto de fixtures desde 2026-08-05 (pedido do usuario): todas as pernas
# do dia entram no pool. O teto de 4 era heranca da era em que a IA MONTAVA a
# multipla e cada fixture ia dentro do prompt ("controla tokens", ver
# ai/alavancagem_pipeline.py) -- hoje a IA so' revisa a combo JA montada, uma
# chamada unica no fim. Quem segura o custo de combinacao continua sendo
# MAX_CANDIDATES_FOR_COMBO abaixo (itertools.combinations sobre o pool
# ordenado), nao o numero de jogos lidos.
MAX_CANDIDATES_FOR_COMBO = 12  # limita o espaco de busca das combinacoes


def _create_table_if_needed(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_multiplas (
            id            SERIAL PRIMARY KEY,
            multipla_name TEXT,
            games         JSONB,
            total_odd     NUMERIC,
            stake         NUMERIC,
            stake_pct     NUMERIC,
            score_combo   NUMERIC,
            prob_combinada NUMERIC,
            ev_combined   NUMERIC,
            match_date    DATE,
            result        TEXT,
            profit        NUMERIC,
            sent          BOOLEAN DEFAULT FALSE,
            reasoning     TEXT,
            created_at    TIMESTAMP DEFAULT NOW()
        );
    """)
    # Indice unico: no maximo 1 multipla por dia, mesma regra de negocio de
    # _has_today_multipla() -- backstop contra 2 execucoes concorrentes do
    # pipeline (achado real 2026-07-25: duplicata identica gerada com 2.5s
    # de diferenca porque o check em Python e' select-then-insert, corrida
    # entre processos passa por cima dele).
    # PARCIAL de proposito (so' multipla_name='MULTIPLA_ENGINE'): historico
    # anterior a 2026-07-17 tem MULTIPLA_1/MULTIPLA_2 legitimos no mesmo
    # match_date (2 slots do sistema antigo de IA, nao duplicata) -- indice
    # global quebraria contra esse historico real (achado ao rodar a
    # migracao em prod: 12 datas de junho "falharam" o indice global antes
    # dessa correcao, todas dado legitimo, nao duplicata).
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_multiplas_match_date_unique
        ON picks_multiplas (match_date) WHERE multipla_name = 'MULTIPLA_ENGINE';
    """)
    # Colunas novas (2026-08-05) em tabela que ja' existe em producao --
    # CREATE TABLE IF NOT EXISTS acima nao adiciona coluna em tabela criada
    # antes, entao o ALTER e' obrigatorio aqui. Ver run_migrations()/o gap de
    # migracao ja' conhecido: sem isto o INSERT quebraria em PROD no primeiro
    # jogo, e o pipeline inteiro cairia no except.
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS prob_combinada NUMERIC;")
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS ev_combined NUMERIC;")


def _has_today_multipla(cur) -> bool:
    """NOTA: a versao original (ai/multipla_pipeline.py::has_today_multipla)
    compara DATE(created_at AT TIME ZONE ...) com CURRENT_DATE AT TIME ZONE
    ... -- essa segunda conversao aplica fuso a um DATE (vira timestamptz),
    comparado contra um DATE puro do outro lado, e nunca bate (bug
    encontrado durante o teste desta pipeline: rodava 2x no mesmo dia sem
    detectar duplicata). Aqui usa match_date = CURRENT_DATE, mesmo padrao
    ja usado (e correto) em has_today_dica()/has_today_pick()."""
    cur.execute(f"SELECT COUNT(*) FROM picks_multiplas WHERE match_date = {HOJE_BR}")
    return cur.fetchone()[0] >= 1


def _today_used_pairs(cur) -> set:
    """(fixture_id, market_type) ja usados em picks_vip/picks_free hoje --
    a multipla nunca repete o mesmo mercado do mesmo jogo que ja saiu em
    VIP/Free, mesma regra do pipeline de IA."""
    pairs = set()
    cur.execute(f"SELECT fixture_id, market_type FROM picks_vip WHERE match_date = {HOJE_BR}")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    cur.execute(f"SELECT fixture_id, market_type FROM picks_free WHERE match_date = {HOJE_BR}")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    return pairs


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


def _gather_leg_candidates(fixtures: list, used_pairs: set) -> list:
    """Roda o motor pra cada fixture e devolve uma lista achatada de
    candidatos elegiveis (ate 3 por fixture), cada um com os dados do
    fixture anexados e os pares ja usados excluidos."""
    match_stats = MatchStatsService()
    odds_service = OddsService()
    team_stats_service = TeamStatsService()
    referee_service = RefereeStatsService()
    standings_service = StandingsService()
    legs = []

    for fixture in fixtures:
        try:
            structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
            if not structured_odds:
                log_skip("MULTIPLA_ENGINE", fixture, MOTIVO_SEM_ODDS)
                continue

            last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
            last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
            if not last10_home or not last10_away:
                log_skip("MULTIPLA_ENGINE", fixture, MOTIVO_SEM_HISTORICO)
                continue

            hist_home_val = dv.validate_history(last10_home)
            hist_away_val = dv.validate_history(last10_away)
            if not hist_home_val["passed"] or not hist_away_val["passed"]:
                log_skip("MULTIPLA_ENGINE", fixture, MOTIVO_HISTORICO_REPROVADO)
                continue

            profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
            profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
            matchup = tpm.compare_matchup(profile_home, profile_away)
            # Classificacao dos dois lados: ate' 2026-08-05 ia None/None aqui,
            # o que travava table_pressure() em 'desconhecido' e desligava o
            # termo de pressao no context_score e no gate de cartoes.
            standing_home, standing_away = standings_service.get_for_fixture(
                fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], fixture["season"])
            context_data = ctx.build_context(
                last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
                standing_home, standing_away, fixture["league_id"], round_str=fixture.get("round"),
            )
            team_strength_data = ts.compare_team_strength(profile_home, profile_away)
            referee_stats = referee_service.get_stats(fixture.get("referee"), fixture["season"])
            league_stats = referee_service.get_league_stats(fixture["league_id"], fixture["season"])
            league_baseline = team_stats_service.get_league_baseline(
                fixture["league_id"], fixture["season"])

            coverage_val = dv.validate_coverage(
                structured_odds=structured_odds, last10_home=last10_home, last10_away=last10_away,
                standings_home=standing_home, standings_away=standing_away,
                referee_stats=referee_stats, context_data=context_data,
            )
            integrity_val, outlier_info = dv.aggregate_fixture_quality_checks(
                last10_home, last10_away,
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"])
            quality = dv.data_quality_score(
                {"Q": min(hist_home_val["Q"], hist_away_val["Q"])}, coverage_val,
                integrity_validation=integrity_val, outlier_info=outlier_info,
            )

            team_stats_home, team_stats_away = team_stats_service.get_for_fixture(
                fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], fixture["season"])

            # Contexto da partida: mata-mata, ida/volta, placar da ida,
            # agregado e rivalidade medida no confronto direto. Alimenta o
            # context_gate, que barra Under contradizendo o que o jogo vai ser.
            conv_cartoes = stats_model.expected_value_convergence(
                last10_home, last10_away, "cards", "total",
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
                league_baseline=league_baseline,
            )
            match_context = context_gate.build_for_fixture(match_stats, fixture, conv_cartoes)

            candidates = analyze_fixture_markets(
                structured_odds, last10_home, last10_away,
                context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
                referee_stats=referee_stats, league_stats=league_stats,
                league_id=fixture["league_id"], data_quality_score=quality["score"],
                match_context=match_context,
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
            )
            picks = rank_market_candidates(candidates)
            log_decision("MULTIPLA_ENGINE", fixture, candidates, picks, matchup=matchup, context_data=context_data)

            for p in picks:
                if (fixture["fixture_id"], p["market_type"]) in used_pairs:
                    continue
                legs.append({**p, "_fixture": fixture, "data_quality_score": quality["score"]})

        except Exception as e:
            # Stack trace completo: sem ele, "pulou 8 fixtures" nao diz
            # ONDE quebrou -- e o caminho de gravacao mudou em 2026-08-01.
            print(f"[MULTIPLA_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue

    return legs


def _find_combo(legs: list) -> tuple | None:
    """Ordena por Score Final e testa combinacoes de 2, depois 3 pernas de
    FIXTURES DIFERENTES ate a primeira cujo produto real das odds caia em
    [ODD_TOTAL_MIN, ODD_TOTAL_MAX]. Retorna (legs_escolhidas, score_combo)
    ou None."""
    pool = sorted(legs, key=lambda p: p["final_score"], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]

    for combo_size in (2, 3):
        best = None
        for combo in itertools.combinations(pool, combo_size):
            fixture_ids = {p["_fixture"]["fixture_id"] for p in combo}
            if len(fixture_ids) != combo_size:
                continue  # exige fixtures diferentes

            odd_total = round(1.0, 4)
            for p in combo:
                odd_total *= p["odd"]
            odd_total = round(odd_total, 4)

            if not (ODD_TOTAL_MIN <= odd_total <= ODD_TOTAL_MAX):
                continue

            score_combo = round(sum(p["final_score"] for p in combo) / len(combo), 4)
            if best is None or score_combo > best[1]:
                best = (combo, score_combo, odd_total)

        if best:
            return best[0], best[1], best[2]

    return None


def _save_multipla(cur, legs: tuple, score_combo: float, odd_total: float):
    games_info = []
    for p in legs:
        fx = p["_fixture"]
        games_info.append({
            "fixture_id": fx["fixture_id"],
            "home_team": fx["home_team"],
            "away_team": fx["away_team"],
            "home_team_id": fx["home_team_id"],
            "away_team_id": fx["away_team_id"],
            "market": p["market_name"],
            # Sem market_id nao ha como casar a perna contra a odd de
            # fechamento: 'Over 4.5' existe em ate' 19 mercados da mesma
            # partida, e casar so' pelo rotulo trazia a odd de outro mercado
            # (ver picks_ledger_sync_service._closing_odd_for). Era por isso
            # que multipla nunca teve CLV confiavel.
            "market_id": p.get("market_id"),
            "market_type": p["market_type"],
            "line": p["value_label"],
            "odd": p["odd"],
            "bet_house": p["best_bookmaker"],
            "confidence": p["confidence"],
            "prob_real": p["taxa_real"],
            "ai_review": p.get("ai_review"),
        })

    match_date = min(p["_fixture"]["match_datetime"] for p in legs).date()
    reasoning = " | ".join(explain(p) for p in legs)

    # Probabilidade e EV do BILHETE, nao das pernas. A multipla so' paga se
    # TODAS as pernas baterem, entao a chance do bilhete e' o PRODUTO das
    # probabilidades -- exatamente o que alavancagem_pipeline.py ja' fazia
    # desde que o mesmo erro foi encontrado la'; nunca tinha sido propagado
    # pra ca (2026-08-05).
    #
    # Quanto isso pesava: 3 pernas de 72%/70%/68% dao 34,3% de chance real, e
    # o score_combo (media dos final_score das pernas) mostrava 86,0% -- 51,7
    # pontos percentuais de diferenca. E score_combo nem e' probabilidade: e'
    # a media de um score de ranqueamento que ja' mistura confidence, Q,
    # contexto e perfil.
    #
    # Assume independencia entre as pernas. _find_combo exige fixtures
    # DIFERENTES, entao nao ha correlacao dentro do mesmo jogo; sobra a
    # correlacao fraca de rodada (mesma liga, mesmo dia), que empurra a
    # probabilidade real um pouco pra cima da estimada -- erro pro lado
    # conservador.
    #
    # A INDEPENDENCIA FOI MEDIDA EM 2026-08-20, e ela se sustenta.
    #
    # A multipla vinha 2 GREEN em 14 nos ultimos 30 dias, com bilhetes
    # anunciando EV de +53% e +71%. A suspeita obvia era que o produto
    # estivesse errado -- ou por correlacao entre as pernas, ou por
    # concentracao de mercado (havia bilhete de escanteio+escanteio e de
    # chutes+chutes). Simulei 2.677 bilhetes de 2 pernas sobre o dado real,
    # fora da amostra:
    #
    #     recorte                bilhetes   produto diz   real     erro
    #     mesma familia               717        71.5%   72.5%   -1.0pp
    #     familias diferentes       1.960        70.1%   70.8%   -0.7pp
    #
    # O produto e' praticamente nao-enviesado, e perna repetida NAO e' pior --
    # e' marginalmente melhor, dentro do ruido. Nao ha caso pra proibir
    # familia repetida nem pra somar um piso de prob_combinada.
    #
    # O erro estava inteiro nas PERNAS: cada uma era estimada por Poisson numa
    # familia superdispersa e saia 3,5 a 5,6 pontos inflada
    # (probability_model._DISPERSAO). O produto entao elevava o erro ao
    # quadrado sem ter erro proprio nenhum. Corrigida a perna, a multipla se
    # corrige junto -- e qualquer regra extra aqui estaria tratando sintoma.
    prob_combinada = 1.0
    for p in legs:
        prob_combinada *= float(p["taxa_real"])
    prob_combinada = round(prob_combinada, 4)
    ev_combined = round(prob_combinada * float(odd_total) - 1.0, 4)

    # Kelly precisa da probabilidade do evento, nao de um score de
    # ranqueamento. Com score_combo o calculo saturava o teto de 2,5% em
    # qualquer bilhete, o que fazia o dimensionamento ser constante na
    # pratica -- Kelly decorativo.
    stake_pct, stake_units = calculate_stake(
        confidence=prob_combinada, odd=odd_total, ev=ev_combined, pick_type="multipla",
    )

    cur.execute("""
        INSERT INTO picks_multiplas
        (multipla_name, games, total_odd, stake_pct, stake, score_combo,
         prob_combinada, ev_combined, match_date, reasoning)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date) WHERE multipla_name = 'MULTIPLA_ENGINE' DO NOTHING
    """, (
        "MULTIPLA_ENGINE",
        json.dumps(games_info, default=str),
        odd_total,
        stake_pct,
        stake_units,
        score_combo,
        prob_combinada,
        ev_combined,
        match_date,
        reasoning,
    ))


# AUDITORIA (2026-08-27). Duas linhas, e nenhuma no corpo da funcao: o Pre
# Live esta' congelado. O decorador abre a execucao (run_id, contagens,
# status) e o decision_log carimba esse run_id sozinho nas linhas que ja'
# gravava -- ver services/engine_audit/audit.py::auditar.
@auditar("PRE_LIVE", "multipla")
def run_multipla_engine():
    conn = get_connection()
    cur = conn.cursor()
    # Regulamento de mata-mata das competicoes nao cadastradas a mao, do
    # banco pra memoria, UMA vez por rodada. Sem isto o motor devolve
    # DESCONHECIDO pro formato dessas competicoes, que e' o comportamento
    # de antes -- nada quebra, so' se sabe menos.
    competition_rules_store.carregar(cur)
    _create_table_if_needed(cur)
    conn.commit()

    if _has_today_multipla(cur):
        print("[MULTIPLA_ENGINE] Já existe múltipla de hoje.")
        cur.close()
        conn.close()
        return

    fixtures_service = FixturesService()
    fixtures = fixtures_service.get_fixtures_today()
    if not fixtures:
        print("[MULTIPLA_ENGINE] Nenhum fixture hoje.")
        cur.close()
        conn.close()
        return

    used_pairs = _today_used_pairs(cur)
    legs = _gather_leg_candidates(fixtures, used_pairs)
    if len(legs) < 2:
        print(f"[MULTIPLA_ENGINE] Só {len(legs)} candidato(s) elegível(is) · insuficiente pra combinar.")
        cur.close()
        conn.close()
        return

    result = _find_combo(legs)
    if not result:
        print(f"[MULTIPLA_ENGINE] Nenhuma combinação bateu a faixa de odd total "
              f"[{ODD_TOTAL_MIN:.2f}, {ODD_TOTAL_MAX:.2f}].")
        cur.close()
        conn.close()
        return

    combo, score_combo, odd_total = result
    reviewed = review_gate("multipla").apply(list(combo), "multipla")
    if not reviewed:
        print("[MULTIPLA_ENGINE] Combinacao vetada pela revisao de IA.")
        cur.close()
        conn.close()
        return
    combo = tuple(reviewed)
    _save_multipla(cur, combo, score_combo, odd_total)
    conn.commit()
    cur.close()
    conn.close()

    pernas = " + ".join(
        f"{p['_fixture']['home_team']} x {p['_fixture']['away_team']} ({p['market_name']} {p['value_label']} @ {p['odd']})"
        for p in combo
    )
    print(f"[MULTIPLA_ENGINE] Salva: {pernas} | odd_total={odd_total} | score_combo={score_combo}")


if __name__ == "__main__":
    run_multipla_engine()
