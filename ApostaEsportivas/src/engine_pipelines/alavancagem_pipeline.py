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
from services.pick_engine import bet_house
from services.pick_engine import bilhetes_do_dia
from services.pick_engine import combo_engine
from services.pick_engine import competition_rules_store
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_run, log_skip, registrar_selecao,
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
# Sem piso individual desde 2026-09-02 (pedido do usuario): a alavancagem e' o
# complemento do VIP/Dica, que subiram pra 1.45-2.00 -- aqui embaixo qualquer
# piso so' amputava a regiao que o produto existe pra usar. 1.01 e' o menor
# preco cotado, ou seja, "sem piso" escrito em numero. Quem barra perna ruim
# continua sendo o min_edge de 0.05 do motor, nao o preco.
ODD_INDIVIDUAL_MIN = 1.01
# Teto individual = teto do combinado. Perna acima de 1.55 nao entra em combo
# nenhum: multiplicar por outra perna (>= 1.01) so' afasta mais da faixa, e
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

#: QUEM SEGURA A ALAVANCAGEM E' `JOGOS_POR_CAMINHO_EXTRA`, o de baixo.
#:
#: "BASTANTE JOGOS" (pedido do usuario, 2026-09-05) VIROU UM NUMERO, e ele nao
#: e' o total do dia: e' quantos jogos DIFERENTES ainda tem perna elegivel
#: sobrando. Um caminho come 2 a 3 jogos, entao e' essa a moeda -- num dia de
#: 4 jogos o segundo nao cabe, por mais alta que seja a confianca. O primeiro
#: caminho sai como sempre saiu, sem exigencia nova.
#:
#: MAX_CAMINHOS_POR_DIA e' so' a rede de seguranca -- o teto do acidente (uma
#: falha de calibragem abrindo trinta caminhos), nao o do dia bom. Mesmo papel
#: que `MAX_PICKS_POR_RODADA` tem no Player Stats. Na pratica o piso de jogos
#: morde primeiro: pra abrir o quarto caminho o dia precisaria de 6 jogos com
#: perna livre DEPOIS de gastar as pernas dos tres anteriores.
MAX_CAMINHOS_POR_DIA = 5
JOGOS_POR_CAMINHO_EXTRA = 6

_TIPO_POR_TAMANHO = {1: "simples", 2: "dupla", 3: "tripla"}



def _create_table_if_needed(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_alavancagem (
            id              SERIAL PRIMARY KEY,
            match_date      DATE UNIQUE,
            tipo            TEXT NOT NULL DEFAULT 'simples',
            fixture_id_1    INTEGER, home_team_1 TEXT, away_team_1 TEXT,
            home_team_id_1  INTEGER, away_team_id_1 INTEGER,
            market_1        TEXT, market_type_1 TEXT, line_1 TEXT, odd_1 NUMERIC,
            bet_house_1     TEXT, confidence_1 NUMERIC, prob_real_1 NUMERIC, reasoning_1 TEXT,
            fixture_id_2    INTEGER, home_team_2 TEXT, away_team_2 TEXT,
            home_team_id_2  INTEGER, away_team_id_2 INTEGER,
            market_2        TEXT, market_type_2 TEXT, line_2 TEXT, odd_2 NUMERIC,
            bet_house_2     TEXT, confidence_2 NUMERIC, prob_real_2 NUMERIC, reasoning_2 TEXT,
            fixture_id_3    INTEGER, home_team_3 TEXT, away_team_3 TEXT,
            home_team_id_3  INTEGER, away_team_id_3 INTEGER,
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
    # engine_debug (2026-09-11, V2): o documento de decisao do bilhete. Mesmo
    # gap de migracao das colunas abaixo -- a tabela ja' existe em PROD, o
    # CREATE acima nao a adiciona, e sem o ALTER o INSERT quebra no deploy.
    cur.execute("ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS engine_debug JSONB;")
    # Mesmo gap: a tabela ja' existe em PROD, e o CREATE acima nao adiciona
    # coluna nova nela. Sem estes ALTERs o INSERT de _save_pick quebra na
    # primeira rodada depois do deploy. Ver a migracao equivalente do site em
    # website/backend/migrations.py, que tambem faz o backfill do historico.
    for _n in (1, 2, 3):
        cur.execute(f"ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS home_team_id_{_n} INTEGER;")
        cur.execute(f"ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS away_team_id_{_n} INTEGER;")


def _has_today_pick(cur) -> bool:
    cur.execute(f"SELECT COUNT(*) FROM picks_alavancagem WHERE match_date = {HOJE_BR}")
    return cur.fetchone()[0] >= MAX_CAMINHOS_POR_DIA


def _caminhos_de_hoje(cur) -> int:
    """Quantos caminhos o dia ja' abriu · o teto e' por DIA e nao por
    execucao, senao rodar o motor duas vezes dobraria a exposicao."""
    cur.execute(f"SELECT COUNT(*) FROM picks_alavancagem WHERE match_date = {HOJE_BR}")
    return int(cur.fetchone()[0])


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

    Desde 2026-09-10 os BILHETES do dia entram na mesma conta (multipla,
    bingo): a mesma perna em dois bilhetes derruba os dois de uma vez, com
    todas as outras pernas junto -- ver bilhetes_do_dia.py.
    """
    pares = set()
    for tabela in ("picks_vip", "picks_free"):
        cur.execute(f"SELECT fixture_id, market_type FROM {tabela} WHERE match_date = {HOJE_BR}")
        pares |= {(r[0], ranking.correlation_group(r[1])) for r in cur.fetchall() if r[0] and r[1]}
    pares |= bilhetes_do_dia.pares_em_bilhetes(cur, HOJE_BR, exceto=("picks_alavancagem",))
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
            # league_table: faltava aqui ate 2026-09-01.
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
    """CAMADA 3 -- CONSTRUCAO DA ALAVANCAGEM (V2, 2026-09-11).

    Recebe as pernas que ja' passaram pela camada 1 (geracao, em
    `_gather_leg_candidates`) e pela camada 2 (validacao individual, dentro do
    `pick_engine`), monta TODOS os formatos possiveis na faixa, avalia cada um
    como BILHETE em `combo_engine.avaliar`, e devolve o que a regra de escolha
    selecionar. Retorna (pernas, confidence_do_bilhete, odd_combinada,
    avaliacao) ou None.

    O QUE MUDOU EM RELACAO AO MOTOR ANTIGO
    --------------------------------------
    O antigo tentava dupla -> tripla -> simples e PARAVA no primeiro formato
    que fechasse na faixa, desempatando pelo produto das confidences. Duas
    consequencias, as duas medidas no historico:

      1. Nenhuma pergunta era feita sobre a COMBINACAO. Correlacao era um veto
         binario por (fixture_id, familia); probabilidade combinada era o
         produto cru; risco do bilhete nao existia. Uma dupla de duas pernas
         boas era um bilhete bom por construcao.
      2. A ORDEM DOS FORMATOS DECIDIA A APOSTA. Com dupla primeiro, uma dupla
         que apenas coubesse na faixa vencia uma simples melhor que tambem
         cabia -- e as duas pagam o mesmo, porque a faixa e' do TOTAL.

    Agora os tres formatos concorrem no MESMO pool avaliado, e quem escolhe e'
    `combo_engine.escolher`: simples por padrao, combo so' quando entrega mais
    probabilidade pelo mesmo preco (ver a docstring de la').

    O VETO DE (fixture_id, familia) CONTINUA AQUI, como pre-filtro barato: ele
    corta o par na geracao em vez de deixa'-lo caminhar ate' a avaliacao so'
    pra ser reprovado no gate de correlacao. O gate la' e' quem manda; este
    aqui so' evita o trabalho.
    """
    pool = sorted(legs, key=lambda p: p["final_score"], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]

    avaliacoes = []
    # Simples primeiro, e sem `break` em nenhum formato: o motor precisa ver
    # TODOS os bilhetes possiveis pra poder comparar formatos entre si. O custo
    # e' limitado por MAX_CANDIDATES_FOR_COMBO (12 pernas -> 12 + 66 + 220
    # combinacoes no pior caso, todas aritmetica pura, sem I/O).
    for combo_size in (1, 2, 3):
        if combo_size > combo_engine.DEFAULT_COMBO_CONFIG.max_combination_legs:
            break
        for combo in itertools.combinations(pool, combo_size):
            chaves = [
                (p["_fixture"]["fixture_id"], ranking.correlation_group(p["market_type"]))
                for p in combo
            ]
            if len(set(chaves)) != len(chaves):
                continue

            # CASA UNICA: o caminho inteiro sai de uma casa so' (achado do
            # usuario, 2026-09-10) -- inclusive o formato 'simples', que assim
            # publica a odd real da casa indicada.
            aplicado = bet_house.aplicar_casa(
                combo, ODD_INDIVIDUAL_MIN, ODD_INDIVIDUAL_MAX)
            if aplicado is None:
                continue
            combo, _casa, odd_combined = aplicado

            if not (odd_min <= odd_combined <= odd_max):
                continue

            avaliacao = combo_engine.avaliar(list(combo), odd_combined)
            avaliacao["_legs"] = tuple(combo)
            avaliacoes.append(avaliacao)

    if not avaliacoes:
        return None

    escolhida = combo_engine.escolher(avaliacoes)
    if escolhida is None:
        # §51 -- o motivo E' o produto. Sem isto, "nenhuma combinacao passou"
        # e' um silencio, e silencio nao se audita. Publica o bilhete que
        # chegou mais perto e o que exatamente o reprovou.
        perto = max(avaliacoes, key=lambda a: sum(a["gates"].values()))
        print(f"[ALAVANCAGEM_ENGINE] NO_PICK · {len(avaliacoes)} bilhete(s) na faixa, "
              f"nenhum aprovado. O mais proximo ({perto['type']}) parou em: "
              f"{'; '.join(perto['reasons'][:3]) or 'sem motivo registrado'}")
        return None

    combo = escolhida.pop("_legs")
    # Confianca do BILHETE (produto), nao a media das pernas: a aposta so' paga
    # se todas baterem. A media premiava combo desequilibrado (uma perna otima
    # + uma fraca ganhava de duas boas), que e' justamente o pior bilhete dos
    # dois. Com 1 perna o produto e' o proprio confidence dela.
    confidence_combo = 1.0
    for p in combo:
        confidence_combo *= float(p["confidence"])
    return combo, round(confidence_combo, 4), escolhida["combined"]["odd"], escolhida


def _save_pick(cur, legs: tuple, confidence_media: float, odd_combined: float,
               avaliacao: dict | None = None):
    tipo = _TIPO_POR_TAMANHO[len(legs)]
    cols, vals = ["match_date", "tipo"], [HOJE_BR, "%s"]
    params = [tipo]

    for i, p in enumerate(legs, start=1):
        fx = p["_fixture"]
        # O ID DO TIME GRAVA JUNTO COM O NOME (2026-08-28), igual picks_free e
        # picks_vip ja' faziam.
        #
        # So' o nome era guardado, e o site descobria o escudo relendo
        # `fixtures` na hora de desenhar o card. Duas falhas vinham dai:
        # `fixtures` guarda so' a janela corrente, entao o escudo sumia quando
        # o pick era liquidado; e o plano B, que casava o nome solto, trazia
        # time errado onde ha homonimo · "Athletic Club" e' o mineiro e
        # tambem o Bilbao, e as duas ligas sao acompanhadas.
        #
        # `fx` ja' tem os dois ids em maos aqui, no instante da decisao. Nao
        # ha' motivo pra jogar fora e reconsultar depois.
        cols += [f"fixture_id_{i}", f"home_team_{i}", f"away_team_{i}",
                 f"home_team_id_{i}", f"away_team_id_{i}",
                 f"market_{i}", f"market_type_{i}", f"line_{i}", f"odd_{i}",
                 f"bet_house_{i}", f"confidence_{i}", f"prob_real_{i}", f"reasoning_{i}"]
        vals += ["%s"] * 13
        params += [
            fx["fixture_id"], fx["home_team"], fx["away_team"],
            fx.get("home_team_id"), fx.get("away_team_id"),
            p["market_name"], p["market_type"], p["value_label"], p["odd"],
            p["best_bookmaker"], p["confidence"], p["taxa_real"], explain(p),
        ]

    # EV da aposta COMBINADA, nao a media dos EVs das pernas -- essa media nao
    # tem significado: a alavancagem so' paga se TODAS as pernas baterem, entao
    # a probabilidade da aposta e' o produto das probabilidades, nao a media.
    # Com 2 pernas de 75% e EV +12% cada, a media dizia "+12%" enquanto o EV
    # real do bilhete e' negativo (0.75*0.75=56% de chance).
    #
    # DESDE A V2 O NUMERO GRAVADO E' O AJUSTADO (§24). O produto cru assume
    # independencia, e a V2 mede o quanto essa suposicao custa: correlacao,
    # amostra, qualidade de dado e divergencia viram um desconto aplicado
    # PERNA A PERNA antes da multiplicacao (ver combo_engine.probabilidade_
    # combinada). Gravar o EV cru aqui e o ajustado no engine_debug faria a
    # tabela e a auditoria contarem duas historias diferentes sobre o mesmo
    # bilhete. Pro formato 'simples' os dois numeros sao identicos: perna
    # unica nao leva desconto nenhum.
    if avaliacao:
        ev_combined = avaliacao["combined"]["EV"]
    else:
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

    # ENGINE DEBUG (§41/§50). O documento inteiro da decisao: cada perna com
    # probabilidade bruta/modelo/calibrada, amostra, qualidade de dado, risco e
    # contradicoes; o bloco combinado com correlacao par a par, os descontos
    # aplicados um a um, o score com todos os termos; e cada gate com o
    # veredito dele. E' o que permite responder depois POR QUE um RED saiu --
    # e, mais importante pro §42, permite separar o desempenho por ESTRUTURA
    # (mesmo jogo x jogos diferentes, mesma familia x familias diferentes,
    # faixa de correlacao) sem ter que reconstruir a decisao a partir do
    # resultado. Mesma coluna e mesmo papel que picks_vip.engine_debug.
    cols += ["engine_debug"]
    vals += ["%s"]
    params += [json.dumps(avaliacao, ensure_ascii=False, default=str) if avaliacao else None]

    # RETURNING id: e' o que permite a aba de Auditoria ligar as pernas ao
    # BILHETE. Sem ele o vinculo teria que ser adivinhado por partida, e um
    # jogo pode virar perna aqui e pick no VIP no mesmo dia.
    cur.execute(
        f"INSERT INTO picks_alavancagem ({', '.join(cols)}) VALUES ({', '.join(vals)}) "
        f"RETURNING id", params)
    linha = cur.fetchone()
    return tipo, (linha[0] if linha else None)


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

    ja_abertos = _caminhos_de_hoje(cur)
    if ja_abertos >= MAX_CAMINHOS_POR_DIA:
        print(f"[ALAVANCAGEM_ENGINE] Dia já tem {ja_abertos} caminho(s), "
              f"que é o teto ({MAX_CAMINHOS_POR_DIA}).")
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
        print(f"[ALAVANCAGEM_ENGINE] {len(used_pairs)} perna(s) ja' publicada(s) hoje bloqueada(s) "
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

    def _jogos_com_perna(pool: list) -> int:
        """Jogos DIFERENTES ainda representados no pool · a moeda do dia."""
        return len({p["_fixture"]["fixture_id"] for p in pool})

    gastas: set = set()
    salvos = 0
    vagas = MAX_CAMINHOS_POR_DIA - ja_abertos
    while salvos < vagas:
        # Perna gasta sai das duas tentativas. Dois caminhos que dividem uma
        # perna nao sao dois caminhos: o RED daquela perna fecha os dois, e o
        # usuario teria posto duas entradas na mesma aposta.
        pools = [(rotulo, [p for p in pool if id(p) not in gastas])
                 for rotulo, pool in tentativas]

        # "BASTANTE JOGOS" pro caminho EXTRA. O primeiro sai como sempre saiu;
        # do segundo em diante o dia precisa ter jogo de sobra, senao o motor
        # so' estaria reciclando o mesmo punhado de partidas.
        if salvos or ja_abertos:
            disponiveis = max((_jogos_com_perna(pool) for _, pool in pools), default=0)
            if disponiveis < JOGOS_POR_CAMINHO_EXTRA:
                print(f"[ALAVANCAGEM_ENGINE] Só {disponiveis} jogo(s) com perna livre · "
                      f"abaixo do mínimo pra abrir outro caminho "
                      f"({JOGOS_POR_CAMINHO_EXTRA}).")
                break

        result = None
        for rotulo, pool in pools:
            if not pool:
                continue
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
            if not salvos:
                log_run("ALAVANCAGEM_ENGINE", motivo)
            break

        combo, confidence_media, odd_combined, avaliacao = result
        # Saem do pool ANTES da IA: vetado ou nao, este combo ja' foi
        # considerado, e reoferece-lo daria um laco com a mesma resposta.
        gastas.update(id(p) for p in combo)

        # §47 -- A IA RECEBE O BILHETE, NAO SO' AS PERNAS.
        #
        # Ate' aqui a revisao da alavancagem recebia uma LISTA DE PICKS e mais
        # nada: cada perna com a probabilidade dela, e nenhuma informacao de
        # que elas iam juntas num bilhete. A IA nao via a odd combinada, nao
        # via a probabilidade do produto, nao via correlacao entre as pernas --
        # ou seja, nao tinha como vetar "combinacao incoerente" ou "correlacao
        # perigosa", que sao justamente os dois vetos que o §48 pede dela.
        # Cada perna passava nos criterios individuais, entao o parecer era
        # aprovar.
        #
        # Vai no bloco `bilhete`, so' quando existe: chave ausente nao muda o
        # cache_key dos outros pipelines (mesma precaucao de `player` e
        # `league_profile` em ai_review.build_review_payload).
        for _p in combo:
            _p["bilhete"] = avaliacao
        reviewed = review_gate("alavancagem").apply(list(combo), "alavancagem")
        if not reviewed:
            print("[ALAVANCAGEM_ENGINE] Combinacao vetada pela revisao de IA.")
            continue
        combo = tuple(reviewed)
        tipo, pick_id = _save_pick(cur, combo, confidence_media, odd_combined,
                                   avaliacao=avaliacao)
        conn.commit()
        if not pick_id:
            continue
        salvos += 1
        # Aba de Auditoria: fecha a contagem e liga TODAS as pernas ao bilhete --
        # e' o caminho de volta de um RED ate' o que o motor viu em cada jogo.
        registrar_selecao("ALAVANCAGEM_ENGINE",
                          [p["_fixture"]["fixture_id"] for p in combo],
                          pick_id=pick_id)

        pernas = " + ".join(
            f"{p['_fixture']['home_team']} x {p['_fixture']['away_team']} "
            f"({p['market_name']} {p['value_label']} @ {p['odd']})"
            for p in combo
        )
        comb = avaliacao["combined"]
        print(f"[ALAVANCAGEM_ENGINE] Salva ({tipo}) {salvos}/{vagas}: {pernas} | "
              f"odd_combined={odd_combined} | confidence_media={confidence_media}")
        print(f"[ALAVANCAGEM_ENGINE]   {avaliacao.get('escolha', '')} | "
              f"prob {comb['probability_raw']:.1%} -> {comb['probability_adjusted']:.1%} "
              f"(desconto {comb['discount_per_leg']:.0%}/perna) | "
              f"edge {0 if comb['edge'] is None else comb['edge']:+.1%} | "
              f"EV {comb['EV']:+.1%} | risco {comb['risk']} | "
              f"correlacao {comb['correlation']} | score {comb['score']:.3f}")

    cur.close()
    conn.close()
    if not salvos:
        print("[ALAVANCAGEM_ENGINE] Nenhum caminho aberto hoje.")


if __name__ == "__main__":
    run_alavancagem_engine()
