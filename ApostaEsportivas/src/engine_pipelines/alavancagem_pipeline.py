"""Alavancagem via motor deterministico (pick_engine) -- unico gerador de
picks_alavancagem desde 2026-07-17 (decisao do usuario de cortar IA em
producao tambem, nao so em dev). Reimplementa localmente a busca de
fixtures/checagem de "ja rodou hoje" (nao importa de
ai/alavancagem_pipeline.py -- esse modulo instancia Anthropic() no nivel
de modulo). Mesmo algoritmo guloso da multipla, adaptado: aceita fixtures
de QUALQUER liga cadastrada (nao mais restrito a Copa do Mundo -- ver
atualizacao abaixo), permite pernas do mesmo fixture ou de fixtures
diferentes (regra original), e tenta dupla -> tripla -> simples ate bater
[1.40, 1.55] de odd combinada. Essa faixa e' unica e nao tem fallback: os
tres formatos validos (dois mercados no mesmo jogo, dois jogos, ou um pick
so') sao aceitos desde que o TOTAL caia entre 1.40 e 1.55 -- pedido
explicito do usuario (2026-08-07, depois de uma alavancagem sair @1.80 pelo
fallback antigo [1.45, 1.90], que foi removido).

Atualizacao: pipeline nasceu restrito a WC_LEAGUE_ID (so fixtures da Copa
do Mundo, torneio concentrado que facilitava achar combos no mesmo dia).
Com o torneio acabando (semifinal sabado, final domingo), passou a aceitar
fixtures de QUALQUER liga cadastrada em `leagues`, mesmo criterio de
selecao de fixture-do-dia que VIP/Dica/Multipla ja usam -- so 1 alavancagem
por dia, escolhida entre todos os candidatos elegiveis de todas as ligas."""
import itertools
import json
import textwrap
import traceback
from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.team_stats_service import TeamStatsService
from services.referee_stats_service import RefereeStatsService
from services.standings_service import StandingsService
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain
from services.pick_engine.ai_review import review_gate
from services.pick_engine.config import ALAVANCAGEM_CONFIG
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import context_gate
from services.pick_engine import stats_model
from services.pick_engine import ranking
from services.pick_engine import competition_rules_store
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_run, log_skip,
)
from services.engine_audit import auditar


# Faixa da alavancagem ("odd 1.50"), unica e sem fallback: o TOTAL do bilhete
# tem que cair aqui, seja ele dois mercados no mesmo jogo, dois jogos ou um
# pick so'. Pedido explicito do usuario em 2026-08-07.
#
# O fallback [1.45, 1.90] que existia aqui foi REMOVIDO nessa mesma data. Ele
# nasceu em 2026-07-21 pra salvar dia magro (com poucos jogos, a odd individual
# mais barata do dia ja passa de 1.65 e zera os candidatos), mas o efeito real
# foi publicar alavancagem @1.80 -- fora do que o produto promete. Dia sem combo
# na faixa agora e' dia sem alavancagem, que e' a decisao correta: e' melhor nao
# publicar do que publicar uma odd que nao e' alavancagem.
ODD_COMBINED_MIN = 1.40
ODD_COMBINED_MAX = 1.55
ODD_INDIVIDUAL_MIN = 1.05
# Teto individual = teto do combinado. Perna acima de 1.55 nao entra em combo
# nenhum: multiplicar por outra perna (>= 1.05) so' afasta mais da faixa, e
# sozinha ela ja' estoura o teto. Antes era 2.00 (fallback 1.90 + folga), o que
# so' servia pra carregar candidato impossivel pelo pipeline inteiro.
ODD_INDIVIDUAL_MAX = ODD_COMBINED_MAX
# Sem teto de fixtures desde 2026-08-05 (pedido do usuario): todos os jogos do
# dia entram. O LIMIT 15 era heranca da era em que a IA montava a alavancagem e
# cada fixture ia dentro do prompt ("teto de fixtures por chamada · controla
# tokens", ver ai/alavancagem_pipeline.py) -- hoje a IA so' revisa a combo JA
# montada, uma chamada unica no fim. O custo de combinacao continua limitado
# por MAX_CANDIDATES_FOR_COMBO abaixo.
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
    # A alavancagem era o unico pipeline que chamava a revisao de IA e jogava o
    # parecer fora: `apply()` devolvia as pernas com ai_review e _save_pick nao
    # gravava nada. Resultado pratico -- no painel de desempenho por modelo, a
    # alavancagem aparecia como "sem revisao", como se o gate nem rodasse nela.
    # Tabela ja' existe em PROD, entao ALTER (CREATE TABLE IF NOT EXISTS acima
    # nao adiciona coluna em tabela criada antes; mesmo gap de migracao ja'
    # documentado em multipla_pipeline.py).
    cur.execute("ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS ai_review JSONB;")


def _has_today_pick(cur) -> bool:
    cur.execute(f"SELECT COUNT(*) FROM picks_alavancagem WHERE match_date = {HOJE_BR}")
    return cur.fetchone()[0] >= 1


def _fixtures_with_odds_today(cur) -> list:
    """Fixtures de hoje, de qualquer liga cadastrada, com pelo menos 1 odd
    na faixa individual -- antes restrito a WC_LEAGUE_ID, ver docstring do
    modulo."""
    cur.execute(f"""
        SELECT DISTINCT f.fixture_id, f.home_team_id, f.away_team_id,
               f.home_team, f.away_team, f.season, f.match_datetime, f.league_id, f.round,
               f.referee
        FROM fixtures f
        INNER JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE f.match_datetime::date = {HOJE_BR}
          AND f.status = 'NS'
          AND ov.odd_value BETWEEN %s AND %s
        ORDER BY f.match_datetime
    """, (ODD_INDIVIDUAL_MIN, ODD_INDIVIDUAL_MAX))

    return [
        {
            "fixture_id": r[0], "home_team_id": r[1], "away_team_id": r[2],
            "home_team": r[3], "away_team": r[4], "season": r[5],
            "match_datetime": r[6], "league_id": r[7], "round": r[8],
            "referee": r[9],
        }
        for r in cur.fetchall()
    ]


def _today_used_pairs(cur) -> set:
    """(fixture_id, familia_de_mercado) ja publicados em picks_vip/picks_free
    hoje. Perna que caia num desses pares e' PROIBIDA, nao ultima opcao.

    A multipla ja' tinha essa regra (_today_used_pairs la'), a alavancagem
    nao -- ela so' preferia jogo livre do VIP e, quando nao achava combo,
    reaproveitava o jogo sem olhar o mercado. O resultado em 2026-08-07 foi
    uma alavancagem publicando o pick IDENTICO do VIP do dia.

    Usa correlation_group e nao o market_type cru (a multipla usa o cru) pelo
    mesmo motivo que a Free: "cards" e "handicap_cards" saem do mesmo dado
    bruto, entao repetir um como se fosse outro e' o mesmo pick com outra
    roupa. O escopo e' por JOGO: a mesma familia continua liberada em outra
    partida, senao um bilhete de 2-3 pernas nao fecha.
    """
    pares = set()
    for tabela in ("picks_vip", "picks_free"):
        cur.execute(f"SELECT fixture_id, market_type FROM {tabela} WHERE match_date = {HOJE_BR}")
        pares |= {(r[0], ranking.correlation_group(r[1])) for r in cur.fetchall() if r[0] and r[1]}
    return pares


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
    """Roda o motor por fixture, mantem so candidatos com odd individual na
    faixa exigida pra combos e que nao repitam pick ja publicado hoje
    (used_pairs, ver _today_used_pairs)."""
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
                log_skip("ALAVANCAGEM_ENGINE", fixture, MOTIVO_SEM_ODDS)
                continue

            last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
            last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
            if not last10_home or not last10_away:
                log_skip("ALAVANCAGEM_ENGINE", fixture, MOTIVO_SEM_HISTORICO)
                continue

            hist_home_val = dv.validate_history(last10_home)
            hist_away_val = dv.validate_history(last10_away)
            if not hist_home_val["passed"] or not hist_away_val["passed"]:
                log_skip("ALAVANCAGEM_ENGINE", fixture, MOTIVO_HISTORICO_REPROVADO)
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

            # ALAVANCAGEM_CONFIG e nao a config padrao: o piso de 1.39 do motor
            # tornava a dupla aritmeticamente impossivel (1.39 * 1.39 = 1.93, ja'
            # acima do teto de 1.55 do bilhete). Ver o comentario da constante.
            # Lista que o motor preenche com TODA linha e TODA familia que ele
            # viu, inclusive as que morreram antes de virar candidato. Vai
            # inteira pro log de decisao -- e' o que faz a tela do admin
            # mostrar o mercado que perdeu, e nao so' o que venceu.
            rastro: list = []
            candidates = analyze_fixture_markets(
                structured_odds, last10_home, last10_away,
                config=ALAVANCAGEM_CONFIG,
                context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
                referee_stats=referee_stats, league_stats=league_stats,
                league_id=fixture["league_id"], data_quality_score=quality["score"],
                match_context=match_context,
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
            rastro=rastro,
            )
            picks = rank_market_candidates(candidates, config=ALAVANCAGEM_CONFIG)
            log_decision("ALAVANCAGEM_ENGINE", fixture, candidates, picks, matchup=matchup,
                          context_data=context_data, rastro=rastro)

            for p in picks:
                if not (ODD_INDIVIDUAL_MIN <= p["odd"] <= ODD_INDIVIDUAL_MAX):
                    continue
                if (fixture["fixture_id"], ranking.correlation_group(p["market_type"])) in used_pairs:
                    continue  # VIP/Free ja publicaram esse pick hoje
                legs.append({**p, "_fixture": fixture, "data_quality_score": quality["score"]})

        except Exception as e:
            # Stack trace completo: sem ele, "pulou 8 fixtures" nao diz
            # ONDE quebrou -- e o caminho de gravacao mudou em 2026-08-01.
            print(f"[ALAVANCAGEM_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue

    return legs


def _legs_sem_jogo_do_vip(cur, legs: list) -> list:
    """Pernas em jogos que o VIP NAO publicou hoje.

    O pareamento e' so' por fixture: diferente da Free, aqui nao interessa qual
    mercado o VIP usou. Uma alavancagem no mesmo jogo do pick VIP entrega ao
    assinante duas apostas que torcem pelo mesmo jogo, e o valor do produto e'
    justamente espalhar o risco entre partidas.
    """
    cur.execute(f"SELECT DISTINCT fixture_id FROM picks_vip WHERE match_date = {HOJE_BR}")
    do_vip = {r[0] for r in cur.fetchall()}
    if not do_vip:
        return legs
    return [p for p in legs if p["_fixture"]["fixture_id"] not in do_vip]


def _find_combo(legs: list, odd_min: float, odd_max: float) -> tuple | None:
    """Tenta dupla -> tripla -> simples (pernas podem ser do mesmo fixture
    ou de fixtures diferentes) ate o produto real das odds cair em
    [odd_min, odd_max]. Faixa continua por parametro pra facilitar teste, mas
    hoje so' existe uma: [ODD_COMBINED_MIN, ODD_COMBINED_MAX].

    CORRELACAO E' POR JOGO (corrigido 2026-08-08)
    ---------------------------------------------
    A regra anterior rejeitava todo combo cujas pernas tivessem o MESMO
    market_type, sem olhar de que partida cada uma vinha. Duas pernas de
    `goals` em jogos diferentes nao sao correlacionadas -- sao times
    diferentes, em estadios diferentes, no mesmo dia -- mas caiam no mesmo
    veto que "Over 1.5 gols + Ambas Marcam no mesmo jogo", que e' correlacao
    de verdade.

    O custo era o produto inteiro. Em 08/08 o motor gerou 12 pernas candidatas
    e TODAS eram `goals` (consequencia direta do teto de 1.55: mercado barato
    com probabilidade alta e' quase sempre Over 0.5 / Under 4.5 / Under 5.5 de
    gols). Toda dupla e toda tripla morreram nesse veto, sobrou o formato
    simples, e a maior odd do dia era 1.39 contra um piso de 1.40 -- dia sem
    alavancagem por um centavo, depois de um veto que nao descrevia risco
    nenhum.

    A chave do veto agora e' (fixture_id, correlation_group), a MESMA de
    _today_used_pairs: duas pernas so' se excluem quando falam do mesmo jogo E
    da mesma familia. Fica de pe o que o veto queria proteger, e some o que ele
    protegia por acidente.

    O QUE ESTA REGRA NAO COBRE, de proposito: erro sistematico do modelo. Tres
    pernas de `goals` em tres jogos sao independentes no resultado, mas nao no
    MODELO -- se a estimativa de gols estiver enviesada hoje, as tres erram
    juntas. Diversificar por familia protegeria disso; o preco medido foi ficar
    sem produto na maioria dos dias, entao a escolha aqui e' explicita, nao
    esquecimento.

    A ORDEM importa e ja' foi um bug: com (1, 2, 3), uma perna unica de odd
    1.40 sempre cabia na faixa e vencia antes de qualquer combo ser testado
    -- as 30 alavancagens geradas em producao ate 2026-08-02 sairam TODAS
    como 'simples'. Os tres formatos sao validos (o usuario confirmou em
    2026-08-07 que "somente um pick" tambem serve), mas combo e' o formato
    preferido do produto, entao simples fica por ultimo: e' o que se entrega
    quando nenhuma dupla ou tripla fecha na faixa."""
    pool = sorted(legs, key=lambda p: p["final_score"], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]

    for combo_size in (2, 3, 1):
        best = None
        for combo in itertools.combinations(pool, combo_size):
            # Mesmo jogo E mesma familia = a mesma aposta duas vezes. Familia
            # repetida em jogos diferentes passa (ver docstring).
            chaves = [
                (p["_fixture"]["fixture_id"], ranking.correlation_group(p["market_type"]))
                for p in combo
            ]
            if len(set(chaves)) != len(chaves):
                continue

            odd_combined = round(1.0, 4)
            for p in combo:
                odd_combined *= p["odd"]
            odd_combined = round(odd_combined, 4)

            if not (odd_min <= odd_combined <= odd_max):
                continue

            # Confianca do BILHETE (produto), nao a media das pernas: a aposta
            # so' paga se todas baterem. A media premiava combo desequilibrado
            # (uma perna otima + uma fraca ganhava de duas boas), que e'
            # justamente o pior bilhete dos dois. Com 1 perna o produto e' o
            # proprio confidence dela -- identico ao que ja' era gravado, entao
            # nada muda pro historico de 'simples' que existe hoje.
            confidence_combo = 1.0
            for p in combo:
                confidence_combo *= float(p["confidence"])
            confidence_combo = round(confidence_combo, 4)
            if best is None or confidence_combo > best[1]:
                best = (combo, confidence_combo, odd_combined)

        if best:
            return best[0], best[1], best[2]

    return None


def _save_pick(cur, legs: tuple, confidence_media: float, odd_combined: float):
    tipo = _TIPO_POR_TAMANHO[len(legs)]
    cols, vals = ["match_date", "tipo"], [HOJE_BR, "%s"]
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

    # EV da aposta COMBINADA, nao a media dos EVs das pernas -- essa media nao
    # tem significado: a alavancagem so' paga se TODAS as pernas baterem, entao
    # a probabilidade da aposta e' o produto das probabilidades, nao a media.
    # Com 2 pernas de 75% e EV +12% cada, a media dizia "+12%" enquanto o EV
    # real do bilhete e' negativo (0.75*0.75=56% de chance). Errava sempre pro
    # lado otimista, e piorava quanto mais pernas. Para 'simples' o resultado
    # e' identico ao de antes (produto de um termo so').
    #
    # Assume independencia entre as pernas. Nao e' exato quando duas pernas
    # saem do MESMO jogo (permitido aqui por regra do produto), mas o erro cai
    # pro lado conservador na pratica e _find_combo ja' recusa combo com todas
    # as pernas do mesmo market_type, que e' o caso de correlacao forte.
    prob_combinada = 1.0
    for p in legs:
        prob_combinada *= float(p["taxa_real"])
    ev_combined = round(prob_combinada * float(odd_combined) - 1.0, 4)

    cols += ["odd_combined", "confidence_media", "ev_combined"]
    vals += ["%s", "%s", "%s"]
    params += [odd_combined, confidence_media, ev_combined]

    # Parecer da IA sobre o bilhete. A revisao e' UMA por combo (review_gate
    # .apply recebe a combinacao inteira), entao todas as pernas carregam o
    # mesmo dict -- guardar o da primeira e' guardar o parecer do bilhete.
    ai_review = legs[0].get("ai_review") if legs else None
    cols += ["ai_review"]
    vals += ["%s"]
    params += [json.dumps(ai_review, ensure_ascii=False, default=str) if ai_review else None]

    cur.execute(f"INSERT INTO picks_alavancagem ({', '.join(cols)}) VALUES ({', '.join(vals)})", params)
    return tipo


# AUDITORIA (2026-08-27). Duas linhas, e nenhuma no corpo da funcao: o Pre
# Live esta' congelado. O decorador abre a execucao (run_id, contagens,
# status) e o decision_log carimba esse run_id sozinho nas linhas que ja'
# gravava -- ver services/engine_audit/audit.py::auditar.
@auditar("PRE_LIVE", "alavancagem")
def run_alavancagem_engine():
    conn = get_connection()
    cur = conn.cursor()
    # Regulamento de mata-mata das competicoes nao cadastradas a mao, do
    # banco pra memoria, UMA vez por rodada. Sem isto o motor devolve
    # DESCONHECIDO pro formato dessas competicoes, que e' o comportamento
    # de antes -- nada quebra, so' se sabe menos.
    competition_rules_store.carregar(cur)
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

    used_pairs = _today_used_pairs(cur)
    if used_pairs:
        print(f"[ALAVANCAGEM_ENGINE] {len(used_pairs)} pick(s) de VIP/Free bloqueado(s) hoje "
              f"(mesmo jogo + mesma familia de mercado).")

    legs = _gather_leg_candidates(fixtures, used_pairs)
    if not legs:
        motivo = ("nenhum candidato com odd individual na faixa que ja nao tenha "
                  "saido em VIP/Free hoje")
        print(f"[ALAVANCAGEM_ENGINE] {motivo}.")
        log_run("ALAVANCAGEM_ENGINE", motivo)
        cur.close()
        conn.close()
        return

    # Exclusividade de jogo do VIP (decisao do usuario, 2026-08-05): o jogo que
    # o VIP publicou hoje fica reservado. Aqui e' preferencia e nao veto por um
    # motivo estrutural -- a alavancagem precisa de 2 a 3 jogos DIFERENTES por
    # bilhete, entao num dia curto (05/08: 4 jogos, os 4 usados pelo VIP) a
    # regra dura simplesmente nao entregaria nada. A busca roda duas vezes: so'
    # com jogo livre primeiro, com todos depois.
    livres = _legs_sem_jogo_do_vip(cur, legs)
    tentativas = [("jogos livres do VIP", livres)] if livres else []
    tentativas.append(("todos os jogos", legs))

    result = None
    for rotulo, pool in tentativas:
        result = _find_combo(pool, ODD_COMBINED_MIN, ODD_COMBINED_MAX)
        if result:
            if rotulo != "jogos livres do VIP":
                print("[ALAVANCAGEM_ENGINE] Sem combo possivel so' com jogo livre · "
                      "reaproveitando jogo que o VIP ja usou hoje (com outro mercado: "
                      "o pick do VIP em si ja foi bloqueado antes).")
            break

    if not result:
        motivo = (f"nenhuma combinacao caiu na faixa [{ODD_COMBINED_MIN}, {ODD_COMBINED_MAX}] "
                  f"(nao existe mais fallback de odd mais alta)")
        print(f"[ALAVANCAGEM_ENGINE] {motivo}.")
        log_run("ALAVANCAGEM_ENGINE", motivo)
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
