"""Dica do Dia via motor deterministico (pick_engine) -- unico gerador de
picks_free desde 2026-07-17 (decisao do usuario de cortar IA em producao
tambem, nao so em dev). Reimplementa localmente a selecao de fixtures/
checagem de "ja rodou hoje" (nao importa de ai/dica_do_dia_pipeline.py --
esse modulo instancia Anthropic() no nivel de modulo, import indevido
custaria uma inicializacao de client sem necessidade e acopla este
pipeline ao de IA)."""
import json

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR, APITO_FUTURO
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.team_stats_service import TeamStatsService
from services.pick_engine import dossie_da_partida
from services.pick_engine import analyze_fixture_markets, rank_market_candidates, explain, homologation
from services.pick_engine.ai_review import review_gate
from services.pick_engine.config import DICA_CONFIG
from services.pick_engine.staking import calculate_stake
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import context_gate
from services.pick_engine import stats_model
from services.referee_stats_service import RefereeStatsService
from services.standings_service import StandingsService
from services.pick_engine import competition_rules_store
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_run, log_skip, registrar_selecao,
)
from services.engine_audit import amostra, auditar


WC_LEAGUE_ID = 1
# Prefiltro SQL de candidatos. DERIVADO da DICA_CONFIG e nao cravado
# (2026-09-02): esta consulta roda ANTES do motor, entao um numero solto aqui
# mataria em silencio qualquer faixa nova da config -- foi o que aconteceu ate'
# hoje, com 1.39/1.90 sobrevivendo a duas mudancas de faixa.
ODD_MIN = DICA_CONFIG.min_odd
ODD_MAX = DICA_CONFIG.max_odd

_LEAGUE_PRIORITY = {
    1: 1, 2: 2, 3: 3, 848: 4, 39: 5, 140: 6, 135: 7, 78: 8,
    61: 9, 94: 10, 88: 11, 13: 12, 11: 13, 71: 14, 72: 15,
}


#: MAIS DE UMA FREE NUM DIA CHEIO (2026-10-07, pedido do usuario).
#:
#: De 05/09 ate' aqui a Free era UMA por dia por decisao de produto ("a
#: vitrine diaria"). O usuario reabriu: num dia com muito jogo, uma so' deixa
#: pick bom na mesa. A moeda e' a mesma da multipla -- jogos com pelo menos um
#: candidato APROVADO no DICA_CONFIG, nao jogos do calendario --, mas com piso
#: mais alto, porque a Free continua sendo a isca do VIP e nao pode virar um
#: segundo VIP de graca. Nunca repete jogo: uma Free por partida.
#: (piso de jogos com candidato aprovado, quantas Free o dia pode ter)
FREE_POR_JOGOS = ((16, 3), (8, 2), (1, 1))
MAX_FREE_POR_DIA = max(teto for _piso, teto in FREE_POR_JOGOS)


def teto_de_free(jogos_com_aprovado: int) -> int:
    """Quantas Free o dia PODE publicar -- nunca quantas deve."""
    for piso, teto in FREE_POR_JOGOS:
        if jogos_com_aprovado >= piso:
            return teto
    return 0


def _garantir_esquema(cur):
    """Tira a unicidade de `match_date` e poe a de (dia, jogo) no lugar.

    `picks_free` nasceu com UMA linha por dia garantida pelo banco, e o INSERT
    usava `ON CONFLICT (match_date) DO UPDATE` -- a segunda Free do dia
    SOBRESCREVERIA a primeira em silencio. Mesmo defeito que a alavancagem
    teve em 15/09 com MAX_CAMINHOS_POR_DIA. O nome da constraint nao e'
    garantido (tabela criada a mao ha' meses), entao procura pelo que ela e':
    UNIQUE so' em match_date.
    """
    cur.execute("""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT c.conname FROM pg_constraint c
                 WHERE c.conrelid = 'picks_free'::regclass AND c.contype IN ('u', 'p')
                   AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                          WHERE attrelid = 'picks_free'::regclass
                                            AND attname = 'match_date')]::smallint[]
            LOOP
                EXECUTE format('ALTER TABLE picks_free DROP CONSTRAINT %I', r.conname);
            END LOOP;
            FOR r IN
                SELECT i.indexrelid::regclass::text AS nome FROM pg_index i
                 WHERE i.indrelid = 'picks_free'::regclass AND i.indisunique
                   AND NOT i.indisprimary
                   AND i.indkey::text = (SELECT attnum::text FROM pg_attribute
                                          WHERE attrelid = 'picks_free'::regclass
                                            AND attname = 'match_date')
            LOOP
                EXECUTE format('DROP INDEX IF EXISTS %s', r.nome);
            END LOOP;
        END $$;
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS picks_free_dia_jogo "
                "ON picks_free (match_date, fixture_id)")


def _frees_de_hoje(cur) -> set:
    """Jogos que ja' tem Free hoje · o teto e' por DIA e nao por execucao,
    senao rodar o motor duas vezes dobraria a vitrine."""
    cur.execute(f"SELECT fixture_id FROM picks_free WHERE match_date = {HOJE_BR}")
    return {r[0] for r in cur.fetchall()}


def _picks_vip_de_hoje(cur) -> set:
    """{(fixture_id, market_type, linha)} do VIP de hoje -- o UNICO veto que
    sobrou da exclusividade.

    ATE 2026-09-15 AQUI HAVIA UMA ESCADA. O VIP rodava primeiro, reservava a
    partida, e a Free escolhia entre tres degraus de sobra (jogo livre com
    mercado novo, jogo livre com mercado repetido, jogo do VIP com outro
    mercado). A escada fazia exatamente o que prometia, e era esse o problema:
    a Free e' UM pick por dia e e' a isca de aquisicao, entao ela precisava ser
    o melhor pick do dia -- e por construcao ela era o melhor pick RESTANTE.

    Invertida a ordem (ver COMANDOS em main.py), a Free escolhe primeiro e nao
    tem nada pra evitar. Este conjunto existe so' pelo caso em que o VIP rodou
    antes assim mesmo: o /admin dispara cada pipeline como subprocesso separado,
    entao a ordem de cmd_tudo() nao e' garantia. Num dia desses a Free ainda
    recusa o pick IDENTICO (mesmo jogo, mesmo market_type, mesma linha) -- ela
    pode repetir o jogo do VIP e pode repetir o mercado, so' nao pode repetir a
    aposta inteira.
    """
    cur.execute(
        f"SELECT fixture_id, market_type, line FROM picks_vip WHERE match_date = {HOJE_BR}"
    )
    return {(fid, mt, (line or "").strip().lower())
            for fid, mt, line in cur.fetchall()}


def _repete_pick_do_vip(pick: dict, fixture_id: int, picks_vip: set) -> bool:
    """O candidato e' a mesma aposta que o VIP ja publicou neste jogo?"""
    linha = (pick.get("value_label") or "").strip().lower()
    return (fixture_id, pick["market_type"], linha) in picks_vip


def _fixtures_with_odds_in_range(cur) -> list:
    """Mesma query de ai/dica_do_dia_pipeline.py::get_fixtures_with_odds_in_range,
    reimplementada aqui para nao acoplar a esse modulo (que instancia
    Anthropic() no import).

    'LIVE' saiu do filtro de status em 2026-08-11. A dica e' um pick PRE-JOGO:
    o motor le historico, contexto e odd de abertura e nao olha placar nem
    tempo de jogo (isso e' o motor Ao Vivo, pick_engine_live/). Com 'LIVE' na
    lista, um jogo que ja tinha comecado -- eventualmente ja perdendo de 1 a 0
    -- continuava elegivel, e a odd usada era a pre-jogo, que naquele momento
    ja nao existia mais em lugar nenhum. Era o unico dos seis geradores que
    aceitava jogo em andamento: VIP e alavancagem exigem 'NS', faltas e
    goleiros usam 'NS'/'TBD'.
    """
    cur.execute(f"""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.status, f.round, f.referee, l.name
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        LEFT JOIN leagues l ON l.league_id = f.league_id
        WHERE f.match_datetime::date = {HOJE_BR}
          AND f.status IN ('NS', 'TBD')
          AND f.match_datetime > {APITO_FUTURO}
          AND ov.odd_value BETWEEN %s AND %s
    """, (ODD_MIN, ODD_MAX))

    rows = cur.fetchall()
    fixtures = [
        {
            "fixture_id": r[0], "league_id": r[1], "season": r[2],
            "home_team_id": r[3], "away_team_id": r[4],
            "home_team": r[5], "away_team": r[6],
            "match_datetime": r[7], "status": r[8], "round": r[9],
            "referee": r[10], "league_name": r[11],
        }
        for r in rows
    ]
    # Sem teto de fixtures desde 2026-08-05 (pedido do usuario): avalia TODOS
    # os jogos do dia. O teto de 3 era heranca da era em que a IA GERAVA o pick
    # e cada fixture entrava dentro do prompt -- o comentario do codigo legado
    # (ai/alavancagem_pipeline.py) diz literalmente "controla tokens". Hoje a
    # IA so' REVISA o pick ja escolhido, numa unica chamada no fim de
    # run_dica_engine, entao ampliar o pool nao custa token nenhum: o custo
    # extra e' so' leitura de historico/odds por fixture.
    # A ordenacao por prioridade de liga fica: deixou de cortar jogo e virou
    # criterio de desempate/leitura do log.
    fixtures.sort(key=lambda f: (_LEAGUE_PRIORITY.get(f["league_id"], 99), f["match_datetime"]))
    return fixtures


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


def _melhores_por_jogo(fixtures: list, picks_vip: set | None = None) -> list:
    """Roda o motor pra cada fixture candidato e devolve o melhor pick DE CADA
    JOGO que passa DICA_CONFIG, como [(final_score, fixture, pick,
    data_quality_score)] do maior Score Final pro menor. Lista vazia se nenhum
    passar. O tamanho da lista e' a moeda do teto (`teto_de_free`).

    Desde 2026-09-02 a DICA_CONFIG e' a mesma regua do VIP -- a Free deixou de
    ter limiar proprio (o `min_confidence` de 0.72 saiu) e passa a buscar o
    MELHOR pick do dia, nao o melhor pick acima de um corte extra.

    Desde 2026-09-15 esse "melhor pick do dia" e' literal: a Free roda ANTES do
    VIP e escolhe o maior final_score de todos os jogos, sem escada e sem
    reserva de partida. O unico candidato recusado e' o que repetiria uma
    aposta identica ja publicada no VIP -- situacao que so' acontece quando o
    VIP rodou antes por fora do cmd_tudo (ver _picks_vip_de_hoje)."""
    picks_vip = picks_vip or set()
    match_stats = MatchStatsService()
    odds_service = OddsService()
    team_stats_service = TeamStatsService()
    referee_service = RefereeStatsService()
    standings_service = StandingsService()

    # O melhor de CADA jogo · desde 07/10 o dia pode publicar mais de uma Free,
    # e nunca duas no mesmo jogo.
    por_jogo: list = []

    for fixture in fixtures:
        structured_odds = odds_service.load_odds_structured(fixture["fixture_id"])
        if not structured_odds:
            log_skip("DICA_ENGINE", fixture, MOTIVO_SEM_ODDS)
            continue

        last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
        last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
        if not last10_home or not last10_away:
            log_skip("DICA_ENGINE", fixture, MOTIVO_SEM_HISTORICO)
            continue

        hist_home_val = dv.validate_history(last10_home)
        hist_away_val = dv.validate_history(last10_away)
        if not hist_home_val["passed"] or not hist_away_val["passed"]:
            log_skip("DICA_ENGINE", fixture, MOTIVO_HISTORICO_REPROVADO)
            continue

        profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
        profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
        matchup = tpm.compare_matchup(profile_home, profile_away)
        # Classificacao dos dois lados: ate' 2026-08-05 ia None/None aqui, o
        # que travava table_pressure() em 'desconhecido' e desligava o termo
        # de pressao no context_score e no gate de cartoes (game_intensity).
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
        # league_table: a tabela inteira permite medir pressao competitiva
        # (competitive_pressure) -- faltava aqui ate 2026-09-01.
        conv_cartoes = stats_model.expected_value_convergence(
            last10_home, last10_away, "cards", "total",
            home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
            team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
        )
        league_table = standings_service.get_league_table(
            fixture["league_id"], fixture["season"])
        match_context = context_gate.build_for_fixture(
            match_stats, fixture, conv_cartoes, league_table=league_table)

        # Lista que o motor preenche com TODA linha e TODA familia que ele
        # viu, inclusive as que morreram antes de virar candidato. Vai
        # inteira pro log de decisao -- e' o que faz a tela do admin
        # mostrar o mercado que perdeu, e nao so' o que venceu.
        rastro: list = []
        candidates = analyze_fixture_markets(
            structured_odds, last10_home, last10_away,
            config=DICA_CONFIG, context_data=context_data, matchup_data=matchup,
            team_strength_data=team_strength_data, referee_stats=referee_stats,
            league_stats=league_stats,
            league_id=fixture["league_id"], data_quality_score=quality["score"],
            match_context=match_context,
            home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
            # DESFALQUES E TECNICO NOVO (2026-09-27): derrubam o Score Final
            # via news_score. Mesmo dado do dossie da IA -- ver dossie_da_partida.
            news_data=dossie_da_partida.sinal_de_desfalques(fixture["fixture_id"]),
            team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
            rastro=rastro,
        )
        picks = rank_market_candidates(candidates, config=DICA_CONFIG)
        log_decision("DICA_ENGINE", fixture, candidates, picks, matchup=matchup,
                      context_data=context_data, rastro=rastro)
        if not picks:
            continue

        # Avaliar TODOS os aprovados do jogo, e nao so' o is_best_pick dele:
        # se o melhor do jogo for justamente o que o VIP ja publicou identico,
        # o segundo colocado do mesmo jogo continua valendo.
        aceitos = 0
        melhor = None
        for p in picks:
            if _repete_pick_do_vip(p, fixture["fixture_id"], picks_vip):
                continue
            aceitos += 1
            if melhor is None or p["final_score"] > melhor[0]:
                melhor = (p["final_score"], fixture,
                          {**p, "data_quality_score": quality["score"],
                                           # Ver a nota em vip_pipeline: o BLOCO
                                           # nunca ocupa a chave do CONTADOR.
                                           "amostra_exibida": amostra.build(
                                               home_team_id=fixture["home_team_id"],
                                               away_team_id=fixture["away_team_id"],
                                               historico_home=last10_home,
                                               historico_away=last10_away,
                                               home_team=fixture.get("home_team"),
                                               away_team=fixture.get("away_team"),
                                               match_context=match_context)},
                          quality["score"])

        if aceitos == 0:
            print(f"[DICA_ENGINE] Fixture {fixture['fixture_id']}: os {len(picks)} candidato(s) "
                  f"aprovados no DICA_CONFIG repetiriam o pick que o VIP ja publicou neste jogo.")
        if melhor is not None:
            por_jogo.append(melhor)

    por_jogo.sort(key=lambda m: m[0], reverse=True)
    return por_jogo


def _save_pick(cur, fixture: dict, pick: dict, data_quality_score: float | None):
    stake_pct, stake_units = calculate_stake(
        confidence=pick["confidence"], odd=pick["odd"], ev=pick["ev"], pick_type="free",
    )
    reasoning = explain(pick)
    # Retrato do candidato no momento da escolha -- mesma logica de
    # engine_pipelines/vip_pipeline.py::_save_pick, usado depois por
    # services/pick_engine/red_analysis.py + calibration.py.
    engine_debug_data = homologation.build_score_breakdown_section(pick, data_quality_score)
    engine_debug_data["ai_review"] = pick.get("ai_review")
    # A AMOSTRA (2026-08-27): quais jogos o motor leu, ate' 10 por time, com o
    # contexto do confronto (classico, jogo de volta, placar da ida). Puramente
    # ADITIVO -- nenhum calculo le esta chave; ela existe pra o "Entenda esta
    # analise" poder mostrar a amostra que DECIDIU, em vez de reconsultar o
    # banco e arriscar exibir um recorte diferente (que e' o que acontecia em
    # jogo de copa, onde o motor le todas as competicoes e a tela lia so' a
    # liga). Ver services/engine_audit/amostra.py.
    if pick.get("amostra_exibida"):
        engine_debug_data["amostra"] = pick["amostra_exibida"]
    # `nivel_repeticao_vip` sai daqui em 2026-09-15, junto com a escada que ele
    # media. Os picks antigos continuam com a chave gravada -- quem le
    # engine_debug le por .get(), entao o historico nao quebra.
    engine_debug = json.dumps(
        engine_debug_data,
        default=str, ensure_ascii=False,
    )

    # INSERT ... SELECT ... WHERE NOT EXISTS, e nao VALUES: a checagem contra
    # `picks_vip` acontece DENTRO da mesma instrucao, no momento do commit.
    #
    # `_repete_pick_do_vip` ja recusa o pick identico ao do VIP, mas ele
    # le picks_vip no COMECO da rodada -- e' select-then-insert, e nao enxerga um
    # VIP que commitou no meio do caminho. O /admin dispara cada pipeline como
    # subprocesso separado, entao os dois correm juntos de verdade.
    #
    # Caso real (17/08/2026): Internacional x Remo, "Ambas as Equipes Marcam
    # Yes @1.90" identico em picks_vip e picks_free -- mesma odd, mesma
    # probabilidade (60.19%), mesma confianca. Free gravado 19:26:44, VIP
    # 19:27:21.
    #
    # E' a mesma licao que picks_live ja aprendeu ("trava de duplicata no BANCO,
    # nao em Python... foi exatamente assim que a multipla duplicou em
    # 2026-07-25") e que este pipeline nunca recebeu.
    #
    # Fecha o caso do VIP commitar PRIMEIRO. O caso oposto (Free antes do VIP)
    # e' o normal desde 2026-09-15 e quem o resolve e' o gate espelhado no
    # vip_pipeline.py -- ninguem pode checar contra uma linha que ainda nao
    # existe, entao a checagem tem que existir dos DOIS lados.
    cur.execute(f"""
        INSERT INTO picks_free
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id,
             league_id, league_name, market, market_type, line, odd, bet_house,
             market_id, confidence, prob_real, edge, reasoning,
             stake_pct, stake_units, engine_debug)
        SELECT %s, {HOJE_BR}, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
         WHERE NOT EXISTS (
             SELECT 1 FROM picks_vip v
              WHERE v.match_date  = {HOJE_BR}
                AND v.fixture_id  = %s
                AND v.market_type = %s
                AND LOWER(TRIM(COALESCE(v.line, ''))) = LOWER(TRIM(COALESCE(%s, '')))
         )
           -- Uma Free por JOGO (2026-10-07). Era `ON CONFLICT (match_date) DO
           -- UPDATE`, que com mais de uma Free por dia trocaria a primeira pela
           -- segunda em silencio. Esta guarda vale mesmo antes de o indice
           -- (match_date, fixture_id) existir; o indice fecha a corrida.
           AND NOT EXISTS (
             SELECT 1 FROM picks_free f
              WHERE f.match_date = {HOJE_BR} AND f.fixture_id = %s
         )
        ON CONFLICT DO NOTHING
    """, (
        fixture["fixture_id"], fixture["home_team"], fixture["away_team"],
        fixture["home_team_id"], fixture["away_team_id"],
        # league_name vinha fixo como None desde 2026-07-17 (o pipeline nasceu
        # sem o JOIN em `leagues`). A consulta que monta o card da Dica do Dia
        # -- routers/suggestions.py::_picks_free_sql -- le pf.league_name puro,
        # sem COALESCE contra l.name, entao o front escondia liga e escudo
        # (Picks.tsx e PickPublico.tsx so' renderizam o bloco se league_name
        # existir). Picks VIP nunca sofreram: a query deles ja fazia o JOIN.
        fixture["league_id"], fixture.get("league_name"),
        pick["market_name"], pick["market_type"], pick["value_label"], pick["odd"], pick["best_bookmaker"],
        pick["market_id"], pick["confidence"], pick["taxa_real"], pick["edge"], reasoning,
        stake_pct, stake_units, engine_debug,
        # Os tres do WHERE NOT EXISTS contra o VIP, e o jogo da guarda da Free.
        fixture["fixture_id"], pick["market_type"], pick["value_label"],
        fixture["fixture_id"],
    ))
    if cur.rowcount == 0:
        print("[DICA_ENGINE] Pick descartado no gravar: o VIP publicou este mesmo "
              "pick (jogo + mercado + linha) enquanto a Free rodava, ou o jogo "
              "ja' tem Free hoje.")
        return False
    return True


# AUDITORIA (2026-08-27). Duas linhas, e nenhuma no corpo da funcao: o Pre
# Live esta' congelado. O decorador abre a execucao (run_id, contagens,
# status) e o decision_log carimba esse run_id sozinho nas linhas que ja'
# gravava -- ver services/engine_audit/audit.py::auditar.
@auditar("PRE_LIVE", "dica")
def run_dica_engine():
    conn = get_connection()
    cur = conn.cursor()
    # Regulamento de mata-mata das competicoes nao cadastradas a mao, do
    # banco pra memoria, UMA vez por rodada. Sem isto o motor devolve
    # DESCONHECIDO pro formato dessas competicoes, que e' o comportamento
    # de antes -- nada quebra, so' se sabe menos.
    competition_rules_store.carregar(cur)

    try:
        _garantir_esquema(cur)
        conn.commit()
    except Exception as e:
        # Sem a troca de indice a Free continua saindo, so' que uma por dia:
        # a segunda bate na unicidade antiga e o ON CONFLICT DO NOTHING a
        # descarta sem derrubar a rodada.
        conn.rollback()
        print(f"[DICA_ENGINE] Nao consegui trocar o indice de picks_free ({e}) · "
              f"o dia fica limitado a uma Free.")

    ja_publicadas = _frees_de_hoje(cur)
    if len(ja_publicadas) >= MAX_FREE_POR_DIA:
        print(f"[DICA_ENGINE] Já existem {len(ja_publicadas)} Free hoje, que é o teto "
              f"absoluto ({MAX_FREE_POR_DIA}).")
        cur.close()
        conn.close()
        return

    # AQUI HAVIA UM GATE QUE BARRAVA A FREE ENQUANTO O VIP NAO TIVESSE RODADO.
    # Ele existia porque a escada lia `picks_vip` pra saber o que estava
    # reservado, e ler uma tabela vazia era concluir que o dia inteiro estava
    # livre. Sem escada, nao ha' o que esperar: a Free e' a primeira a escolher.
    fixtures = _fixtures_with_odds_in_range(cur)
    if not fixtures:
        print("[DICA_ENGINE] Nenhum fixture com odd na faixa hoje.")
        cur.close()
        conn.close()
        return

    print(f"[DICA_ENGINE] Avaliando {len(fixtures)} fixtures (motor deterministico)...")

    picks_vip = _picks_vip_de_hoje(cur)
    if picks_vip:
        print(f"[DICA_ENGINE] O VIP rodou antes da Free hoje ({len(picks_vip)} pick(s)) · "
              f"o jogo e o mercado dele continuam liberados, so' a aposta identica nao sai")

    melhores = _melhores_por_jogo(fixtures, picks_vip)
    if not melhores:
        motivo = ("nenhum candidato passou no DICA_CONFIG, ou o que sobrou repetiria "
                  "uma aposta identica a que o VIP ja publicou hoje")
        print(f"[DICA_ENGINE] {motivo}.")
        log_run("DICA_ENGINE", motivo)
        cur.close()
        conn.close()
        return

    teto = teto_de_free(len(melhores))
    vagas = teto - len(ja_publicadas)
    print(f"[DICA_ENGINE] {len(melhores)} jogo(s) com candidato aprovado · teto do dia "
          f"{teto} Free · {len(ja_publicadas)} ja' publicada(s) · {max(vagas, 0)} vaga(s)")
    if vagas <= 0:
        cur.close()
        conn.close()
        return

    salvas = 0
    for _score, fixture, pick, quality_score in melhores:
        if salvas >= vagas:
            break
        if fixture["fixture_id"] in ja_publicadas:
            continue
        reviewed = review_gate("dica").apply([pick], "dica", fixture)
        if not reviewed:
            # Vetado nao encerra mais o dia: o proximo jogo da fila ainda pode
            # ser a Free. Antes do teto, um veto deixava o dia sem Free nenhuma.
            print(f"[DICA_ENGINE] Fixture {fixture['fixture_id']}: pick vetado pela revisao de IA.")
            continue
        pick = reviewed[0]
        gravou = _save_pick(cur, fixture, pick, quality_score)
        conn.commit()
        if not gravou:
            continue
        salvas += 1
        ja_publicadas.add(fixture["fixture_id"])
        # As contagens da aba de Auditoria: `contabilizar` ja' somou este jogo
        # como analisado/descartado quando o decision_log gravou a linha dele;
        # aqui a pick salva move a contagem pro lado certo.
        registrar_selecao("DICA_ENGINE", [fixture["fixture_id"]])
        print(f"[DICA_ENGINE] Salvo ({salvas}/{vagas}): fixture {fixture['fixture_id']} · "
              f"{pick['market_name']} {pick['value_label']} @ {pick['odd']} "
              f"(confidence={pick['confidence']*100:.0f}%, ev={pick['ev']*100:+.1f}%)")

    cur.close()
    conn.close()
    if not salvas:
        log_run("DICA_ENGINE",
                "candidatos vetados pela revisao de IA ou ja' publicados pelo VIP "
                "enquanto a Free rodava")


if __name__ == "__main__":
    run_dica_engine()
