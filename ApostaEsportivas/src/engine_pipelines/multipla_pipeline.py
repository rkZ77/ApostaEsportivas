"""Multipla V2 -- PORTFOLIO DIARIO de bilhetes, nao "a multipla do dia".

Unico gerador de picks_multiplas desde 2026-07-17 (decisao do usuario de
cortar a IA da GERACAO em producao tambem, nao so' em dev; ela continua no
gate de veto, no fim). Reimplementa localmente selecao de fixtures, checagem
de "ja rodou hoje" e bloqueio de pares ja' usados -- nao importa de
ai/multipla_pipeline.py porque esse modulo instancia Anthropic() no nivel de
modulo.

O QUE MUDOU NA V2 (2026-09-11)
------------------------------
A V1 perguntava "qual e' a melhor combinacao do dia?" e repetia a pergunta na
sobra ate' o teto. A V2 pergunta "quantas multiplas de qualidade existem
hoje?", e aceita ZERO como resposta.

Em ordem, o que passou a existir:

  * TETO POR OFERTA. Quantos bilhetes o dia pode publicar sai de quantas
    PARTIDAS entregaram perna aprovada -- 1 ate' 5 jogos, ate' 5 acima de 31.
    Maximo nao e' meta.
  * GATE DA PERNA. Probabilidade calibrada pelo que a amostra sustenta,
    qualidade de dado, risco, margem de projecao e score proprio. Antes a
    perna entrava crua, com o mesmo peso vindo de 4 jogos ou de 40.
  * ESCOLHA POR SCORE COMPOSTO, cujo maior peso e' o ELO MAIS FRACO. Nunca
    por EV: dentro de uma faixa de odd fixa, maximizar EV e' maximizar odd.
  * CORRELACAO MEDIDA, nao presumida: mesmo jogo e mesma equipe viram HIGH e
    nao combinam; desconhecido paga penalidade em vez de passar por
    independente.
  * O DIA COMO CONJUNTO: sobreposicao, exposicao por jogo e concentracao por
    familia limitam o portfolio inteiro, e nao cada bilhete isolado.

A logica de decisao inteira mora em services/pick_engine_multipla/. Aqui fica
o que e' de pipeline: ler o dia, chamar o motor por fixture, gravar e logar.
"""
import json
import textwrap
import traceback

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR, data_br
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.team_stats_service import TeamStatsService
from services.referee_stats_service import RefereeStatsService
from services.standings_service import StandingsService
from services.pick_engine import analyze_fixture_markets, explain
from services.pick_engine.ai_review import review_gate
from services.pick_engine.staking import calculate_stake
from services.pick_engine import team_profile_model as tpm
from services.pick_engine import context_model as ctx
from services.pick_engine import team_strength as ts
from services.pick_engine import data_validation as dv
from services.pick_engine import competition_profile as cp
from services.pick_engine import context_gate
from services.pick_engine import stats_model
from services.pick_engine import ranking
from services.pick_engine import bilhetes_do_dia
from services.pick_engine import competition_rules_store
from services.pick_engine_multipla import component, portfolio
from services.pick_engine_multipla import config as mcfg
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_run, log_skip, registrar_selecao,
)
from services.engine_audit import auditar


#: TUDO QUE DECIDE MUDOU DE LUGAR (V2, 2026-09-11).
#:
#: Faixa de odd, teto de bilhetes, pesos e limiares vivem em
#: services/pick_engine_multipla/config.py. Os nomes abaixo ficam como ALIAS
#: porque codigo antigo (testes, scripts de homologacao) importa daqui -- mas
#: o valor tem uma casa so'. Duas casas para o mesmo numero e' como uma regra
#: de produto vira duas regras diferentes sem ninguem editar nada.
#:
#: A FAIXA APERTOU: 2.00-4.00 virou 2.00-3.00. O teto largo entrou em
#: 2026-07-21 por uma razao real -- num dia magro, o menor produto possivel
#: entre duas pernas de jogos diferentes ja' passava de 3.00 (1.82 x 1.85 =
#: 3.37) e a multipla nao saia. O que mudou desde entao: o pool deixou de ser
#: "uma linha por jogo" e passou a levar o elegivel inteiro de cada fixture,
#: entao existem pernas de 1.40-1.55 que aquela versao nem via. Se a medicao
#: mostrar que a faixa nova zera dias demais, o teto volta EM UMA LINHA, no
#: config -- ver ODD_TOTAL_MAX_AGRESSIVO.
ODD_TOTAL_MIN = mcfg.ODD_TOTAL_MIN
ODD_TOTAL_MAX = mcfg.ODD_TOTAL_MAX

#: Limita o espaco de busca das combinacoes, NAO o numero de jogos lidos:
#: todas as pernas do dia continuam entrando no pool (pedido de 2026-08-05).
#: O corte e' pelas MELHORES pernas (component_score), entao alargar o teto so'
#: adiciona candidatas piores que as que ja' estao dentro.
#: combinations(30, 3) = 4.060 bilhetes, custo irrelevante.
MAX_CANDIDATES_FOR_COMBO = 30

#: O TETO DO DIA NAO E' MAIS UM NUMERO FIXO (V2).
#:
#: Ele vem da OFERTA: quantas PARTIDAS entregaram pelo menos uma perna
#: aprovada no gate individual (config.teto_de_multiplas). 1 bilhete num dia
#: de ate' 5 jogos elegiveis, 2 ate' 10, 3 ate' 20, 4 ate' 30, 5 acima disso.
#:
#: MAXIMO NAO E' META. O teto diz quantos bilhetes o dia PODE publicar; quem
#: diz quantos ele DEVE e' a qualidade -- e a resposta pode ser zero num dia
#: de 40 jogos. Nao existe cota de publicacao a cumprir.
#:
#: O numero aqui e' so' a rede de seguranca absoluta, o teto do ACIDENTE:
#: uma falha de calibragem nao pode publicar o dia inteiro de uma vez. Mesmo
#: papel de MAX_PICKS_POR_RODADA no Player Stats.
MAX_MULTIPLAS_POR_DIA = mcfg.TETO_ABSOLUTO_POR_DIA


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
    # O INDICE QUE IMPEDIA O PRODUTO (achado 2026-09-11).
    #
    # O indice antigo era UNIQUE (match_date) WHERE multipla_name =
    # 'MULTIPLA_ENGINE' -- uma multipla por dia, que era a regra correta em
    # 2026-07-25, quando ele entrou como backstop contra duas execucoes
    # concorrentes (o check em Python e' select-then-insert e nao pega corrida
    # entre processos).
    #
    # Em 2026-09-05 o produto passou a publicar MAIS DE UM bilhete por dia, e
    # o indice nao acompanhou. O laco do pipeline montava o segundo bilhete,
    # chamava a IA, chamava o INSERT -- e o ON CONFLICT ... DO NOTHING
    # engolia a gravacao em silencio. O motor dizia que ia publicar varios e o
    # banco publicava um, sem erro nenhum no log. Nenhum teste pegou porque
    # todos testavam a montagem em memoria, nunca a gravacao.
    #
    # A trava continua existindo, so' que na chave certa: (match_date,
    # multipla_name), com o nome carregando o numero do bilhete no dia
    # (MULTIPLA_ENGINE_1, _2, ...). Duas execucoes concorrentes ainda colidem
    # no mesmo slot, que e' o que o backstop precisa garantir.
    #
    # O DROP e' obrigatorio e nao pode ser IF NOT EXISTS de um indice novo: o
    # indice velho, se ficar, continua valendo sozinho.
    cur.execute("DROP INDEX IF EXISTS idx_picks_multiplas_match_date_unique;")
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_multiplas_slot_unique
        ON picks_multiplas (match_date, multipla_name)
        WHERE multipla_name LIKE 'MULTIPLA_ENGINE%';
    """)
    # Colunas novas (2026-08-05) em tabela que ja' existe em producao --
    # CREATE TABLE IF NOT EXISTS acima nao adiciona coluna em tabela criada
    # antes, entao o ALTER e' obrigatorio aqui. Ver run_migrations()/o gap de
    # migracao ja' conhecido: sem isto o INSERT quebraria em PROD no primeiro
    # jogo, e o pipeline inteiro cairia no except.
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS prob_combinada NUMERIC;")
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS ev_combined NUMERIC;")
    # V2 (2026-09-11), mesmo gap de migracao das duas de cima.
    #
    # engine_debug: o documento inteiro da decisao do bilhete -- cada perna com
    # probabilidade bruta e calibrada, amostra, qualidade de dado, risco e
    # score aberto em parcelas; o bloco combinado com a correlacao par a par,
    # diversificacao, sobreposicao contra os bilhetes ja' publicados e o score
    # com todos os termos. E' o que permite responder depois POR QUE um RED
    # saiu, e medir ROI por ESTRUTURA (gols+escanteio, mesma liga, faixa de
    # odd) sem reconstruir a decisao a partir do resultado. Mesma coluna e
    # mesmo papel de picks_vip.engine_debug e picks_alavancagem.engine_debug.
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS engine_debug JSONB;")
    # ai_review: o parecer do gate de IA sobre o bilhete. Ate' agora ele era
    # calculado e jogado fora aqui -- no painel de desempenho por modelo a
    # multipla aparecia como "sem revisao", como se o gate nem rodasse nela
    # (mesmo defeito ja' corrigido na alavancagem).
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS ai_review JSONB;")


def _multiplas_de_hoje(cur) -> int:
    """Quantos bilhetes o dia ja' tem · o teto e' por DIA, nao por execucao,
    senao rodar o motor duas vezes publicaria o dobro."""
    cur.execute(f"SELECT COUNT(*) FROM picks_multiplas WHERE match_date = {HOJE_BR}")
    return int(cur.fetchone()[0])


def _today_used_pairs(cur) -> set:
    """(fixture_id, market_type) ja usados em picks_vip/picks_free hoje --
    a multipla nunca repete o mesmo mercado do mesmo jogo que ja saiu em
    VIP/Free, mesma regra do pipeline de IA.

    Desde 2026-09-10 tambem cruza contra os BILHETES do dia (bingo,
    alavancagem): perna repetida entre dois bilhetes derruba os dois inteiros
    de uma vez -- ver services/pick_engine/bilhetes_do_dia.py. Na ordem atual
    a multipla roda primeiro e costuma nao achar nada aqui; a consulta existe
    pra a regra nao depender da ordem."""
    pairs = set()
    cur.execute(f"SELECT fixture_id, market_type FROM picks_vip WHERE match_date = {HOJE_BR}")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    cur.execute(f"SELECT fixture_id, market_type FROM picks_free WHERE match_date = {HOJE_BR}")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    pairs |= bilhetes_do_dia.pares_em_bilhetes(cur, HOJE_BR, exceto=("picks_multiplas",))
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

            # Lista que o motor preenche com TODA linha e TODA familia que ele
            # viu, inclusive as que morreram antes de virar candidato. Vai
            # inteira pro log de decisao -- e' o que faz a tela do admin
            # mostrar o mercado que perdeu, e nao so' o que venceu.
            rastro: list = []
            candidates = analyze_fixture_markets(
                structured_odds, last10_home, last10_away,
                context_data=context_data, matchup_data=matchup, team_strength_data=team_strength_data,
                referee_stats=referee_stats, league_stats=league_stats,
                league_id=fixture["league_id"], data_quality_score=quality["score"],
                match_context=match_context,
                home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
            rastro=rastro,
            )
            # Um pool so' pra as duas coisas: o log e as pernas. Antes o log
            # recebia `rank_market_candidates` (o corte final de 3, 1 por
            # familia) e as pernas vinham do mesmo lugar, entao os dois
            # concordavam por acidente. Com o pool alargado eles divergiriam:
            # log_decision marca `eligible` por presenca nesta lista, e a tela
            # do admin escreve "REJEITADO (nao passou nos criterios minimos)"
            # pra tudo que ficou de fora dela -- ou seja, a multipla salvaria
            # uma perna que o proprio log dela chama de reprovada.
            elegiveis = ranking.rank_all_candidates(candidates)
            log_decision("MULTIPLA_ENGINE", fixture, candidates, elegiveis, matchup=matchup,
                          context_data=context_data, rastro=rastro)

            # O LOG continua sendo `picks` (o corte final de 3, 1 por familia)
            # porque e' o que a tela do admin mostra como "o que este jogo
            # entregaria sozinho". O POOL DA MULTIPLA, nao: ele leva o elegivel
            # inteiro (2026-08-28).
            #
            # Por que mudou: select_final_picks corta 1 por grupo de correlacao
            # e para em 3. Esse corte existe pra escolher O pick de um jogo --
            # VIP e Free entregam uma aposta por partida, e duas linhas da mesma
            # familia ali seriam a mesma aposta duas vezes. A multipla escolhe
            # outra coisa: a MELHOR COMBINACAO DO DIA. Aplicar o corte antes da
            # combinacao jogava fora, sem nunca precificar, a 4a linha de um
            # jogo forte -- que podia ser melhor que a 1a de um jogo fraco.
            # Quem protege contra familia repetida no mesmo jogo agora e'
            # _find_combo, no momento certo: na hora de montar o bilhete.
            for p in elegiveis:
                # Duas chaves: market_type cru (VIP/Free) e familia (bilhetes).
                if ((fixture["fixture_id"], p["market_type"]) in used_pairs
                        or (fixture["fixture_id"],
                            ranking.correlation_group(p["market_type"])) in used_pairs):
                    continue
                legs.append({**p, "_fixture": fixture, "data_quality_score": quality["score"]})

        except Exception as e:
            # Stack trace completo: sem ele, "pulou 8 fixtures" nao diz
            # ONDE quebrou -- e o caminho de gravacao mudou em 2026-08-01.
            print(f"[MULTIPLA_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue

    return legs


def _pool_da_v2(legs: list, config) -> tuple:
    """(aprovadas, reprovadas, jogos_elegiveis) -- o GATE INDIVIDUAL da V2.

    Ate' aqui a perna passou pelos gates do motor (taxa, edge, EV, confidence,
    amostra, faixa de odd). O que este passo cobra a mais e' o que so' um
    BILHETE precisa: probabilidade calibrada pelo que a amostra sustenta,
    qualidade de dado, risco e margem de projecao. Uma pick simples que erra
    custa uma unidade; uma perna que erra derruba o bilhete inteiro, junto com
    duas outras pernas que acertaram.

    `jogos_elegiveis` e' quantas PARTIDAS diferentes sobreviveram -- e' esse
    numero, e nao o total de jogos do dia, que define o teto de bilhetes.
    """
    aprovadas, reprovadas = component.avaliar_pool(legs, config)
    jogos = {component.jogo(p) for p in aprovadas}
    return aprovadas, reprovadas, len(jogos)


def _save_multipla(cur, bilhete: dict, slot: int, contexto: dict) -> int | None:
    """Grava o bilhete e devolve o id · None quando o ON CONFLICT nao gravou.

    O id e' o que liga TODAS as pernas ao bilhete na aba de Auditoria: e' o
    caminho de volta de um RED ate' o que o motor viu em cada jogo.
    """
    legs = bilhete["pernas"]
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
            # V2: a probabilidade que a AMOSTRA sustenta, ao lado da crua. As
            # duas, e nao so' uma: a distancia entre elas e' a medida direta de
            # quanto aquela perna depende de pouca evidencia, e some se a
            # gravacao guardar so' o numero final.
            "prob_calibrada": p.get("probabilidade_calibrada"),
            "component_score": p.get("component_score"),
            "risco": p.get("risco"),
            "ai_review": p.get("ai_review"),
        })

    match_date = min(p["_fixture"]["match_datetime"] for p in legs).date()
    reasoning = " | ".join(explain(p) for p in legs)

    # A PROBABILIDADE GRAVADA E' A AJUSTADA, nao o produto cru.
    #
    # O produto (`prob_produto`) assume independencia. Isso foi MEDIDO em
    # 2026-08-20 sobre 2.677 bilhetes de 2 pernas, fora da amostra, e se
    # sustenta para pernas de JOGOS DIFERENTES: o produto erra -1.0pp com
    # familia repetida e -0.7pp com familias diferentes, ou seja, e' quase
    # nao-enviesado e erra pro lado conservador. Por isso a V2 nao reintroduz
    # piso de prob_combinada nem proibe familia repetida entre jogos: essa
    # ideia ja' foi medida e reprovada.
    #
    # O que a medicao NAO cobre e' o que o ajuste trata: correlacao dentro do
    # MESMO jogo (hoje bloqueada) e o desconhecido. Mais o encolhimento por
    # amostra, que entra antes, dentro de cada perna.
    #
    # Quanto isso pesa: 3 pernas de 72%/70%/68% dao 34,3% de chance real, e o
    # score_combo (media dos final_score das pernas) mostrava 86,0% -- 51,7
    # pontos de diferenca. score_combo nem e' probabilidade: e' a media de um
    # score de ranqueamento que mistura confidence, Q, contexto e perfil.
    prob_combinada = bilhete["probabilidade"]
    ev_combined = bilhete["ev"]
    odd_total = bilhete["odd_total"]
    # score_combo continua sendo a media dos final_score das pernas, e nao o
    # score novo: e' a coluna que o historico ja' tem, e trocar o significado
    # dela no meio faria a serie inteira comparar duas coisas diferentes. O
    # score da V2 vai pro engine_debug, onde nasce comparavel consigo mesmo.
    score_combo = round(sum(p["final_score"] for p in legs) / len(legs), 4)

    # Kelly precisa da probabilidade do evento, nao de um score de
    # ranqueamento. Com score_combo o calculo saturava o teto de 2,5% em
    # qualquer bilhete, o que fazia o dimensionamento ser constante na
    # pratica -- Kelly decorativo.
    stake_pct, stake_units = calculate_stake(
        confidence=prob_combinada, odd=odd_total, ev=ev_combined, pick_type="multipla",
    )

    engine_debug = {
        "versao": "multipla_v2",
        "bilhete": {
            "slot": slot,
            "odd_total": odd_total,
            "prob_produto": bilhete["prob_produto"],
            "prob_calibrada": bilhete["prob_calibrada"],
            "prob_ajustada": prob_combinada,
            "fair_odd": bilhete["fair_odd"],
            "edge": bilhete["edge"],
            "ev": ev_combined,
            "score": bilhete["score"],
            "score_liquido": bilhete.get("score_liquido"),
            "score_parcelas": bilhete["score_parcelas"],
            "faixa": bilhete["faixa"],
            "elo_mais_fraco": bilhete["elo_mais_fraco"],
            "risco": bilhete["risco"],
            "casa": bilhete.get("casa"),
            "correlacao": bilhete["correlacao"],
            "diversificacao": bilhete["diversificacao"],
            "overlap": bilhete.get("overlap"),
        },
        "pernas": [
            {
                "fixture_id": p["_fixture"]["fixture_id"],
                "market_type": p["market_type"],
                "line": p["value_label"],
                "odd": p["odd"],
                "taxa_real": p["taxa_real"],
                "probabilidade_calibrada": p.get("probabilidade_calibrada"),
                "amostra": p.get("amostra"),
                "sample_quality": p.get("sample_quality"),
                "data_quality_score": p.get("data_quality_score"),
                "risco": p.get("risco"),
                "risk_score": p.get("risk_score"),
                "projection_margin": p.get("projection_margin"),
                "ev": p.get("ev"),
                "edge": p.get("edge"),
                "component_score": p.get("component_score"),
                "component_parcelas": p.get("component_parcelas"),
            }
            for p in legs
        ],
        # A foto do DIA junto do bilhete: quantos jogos havia, quantos
        # candidatos sobreviveram e qual era o teto. Sem isso, comparar dois
        # bilhetes de dias diferentes compara decisoes tomadas com ofertas
        # diferentes sem saber disso.
        "dia": contexto,
    }

    # A revisao e' UMA por bilhete (review_gate.apply recebe a combinacao
    # inteira), entao todas as pernas carregam o mesmo dict -- guardar o da
    # primeira e' guardar o parecer do bilhete.
    ai_review = legs[0].get("ai_review") if legs else None

    cur.execute("""
        INSERT INTO picks_multiplas
        (multipla_name, games, total_odd, stake_pct, stake, score_combo,
         prob_combinada, ev_combined, match_date, reasoning, engine_debug, ai_review)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date, multipla_name)
            WHERE multipla_name LIKE 'MULTIPLA_ENGINE%%' DO NOTHING
        RETURNING id
    """, (
        f"MULTIPLA_ENGINE_{slot}",
        json.dumps(games_info, default=str),
        odd_total,
        stake_pct,
        stake_units,
        score_combo,
        prob_combinada,
        ev_combined,
        match_date,
        reasoning,
        json.dumps(engine_debug, ensure_ascii=False, default=str),
        json.dumps(ai_review, ensure_ascii=False, default=str) if ai_review else None,
    ))
    linha = cur.fetchone()
    return linha[0] if linha else None


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

    config = mcfg.padrao()

    ja_publicadas = _multiplas_de_hoje(cur)
    if ja_publicadas >= MAX_MULTIPLAS_POR_DIA:
        print(f"[MULTIPLA_ENGINE] Dia já tem {ja_publicadas} múltipla(s), "
              f"que é o teto absoluto ({MAX_MULTIPLAS_POR_DIA}).")
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

    aprovadas, reprovadas, jogos_elegiveis = _pool_da_v2(legs, config)
    print(f"[MULTIPLA_ENGINE] {len(fixtures)} jogo(s) no dia · {len(legs)} perna(s) do motor · "
          f"{len(aprovadas)} aprovada(s) no gate da múltipla em {jogos_elegiveis} jogo(s) · "
          f"teto do dia: {mcfg.teto_de_multiplas(jogos_elegiveis, config)}")
    if reprovadas:
        contagem = {}
        for p in reprovadas:
            for motivo in p["motivos"]:
                contagem[motivo] = contagem.get(motivo, 0) + 1
        # Distribuicao de motivo, e nao a lista de pernas: e' o que responde
        # "por que hoje nao saiu" sem ter que abrir perna por perna.
        detalhe = " · ".join(f"{k}={v}" for k, v in sorted(contagem.items(),
                                                           key=lambda kv: -kv[1]))
        print(f"[MULTIPLA_ENGINE] Pernas reprovadas: {detalhe}")

    # O PORTFOLIO DO DIA, de uma vez -- e nao um bilhete de cada vez como na
    # V1. A diferenca nao e' de forma: so' vendo o conjunto da' pra recusar um
    # bilhete que era bom SOZINHO e concentra exposicao DEPOIS do que ja' foi
    # publicado (mesmo jogo, mesma familia dominante, perna repetida).
    vagas = MAX_MULTIPLAS_POR_DIA - ja_publicadas
    resultado = portfolio.montar(aprovadas, jogos_elegiveis, config, vagas=vagas)

    if not resultado["multiples"]:
        # NO_MULTIPLA e' resposta valida, e e' a resposta certa em dia ruim.
        # Nao existe cota de publicacao a cumprir.
        print(f"[MULTIPLA_ENGINE] NO_MULTIPLA · {resultado.get('reason')}")
        cur.close()
        conn.close()
        return

    contexto = portfolio.resumo(resultado, data_br())
    salvas = 0
    for i, bilhete in enumerate(resultado["multiples"], start=1):
        # A IA SO' VETA, nunca monta nem reordena (regra do gate de IA). Ela
        # roda por ultimo, sobre o bilhete ja' escolhido: falha aberto, entao
        # "indisponivel" nunca vira "aprovado".
        reviewed = review_gate("multipla").apply(list(bilhete["pernas"]), "multipla")
        if not reviewed:
            print(f"[MULTIPLA_ENGINE] Bilhete {i} vetado pela revisão de IA.")
            continue
        bilhete = {**bilhete, "pernas": list(reviewed)}

        # O SLOT conta o dia, nao a execucao: rodar o motor duas vezes nao
        # pode reescrever o bilhete que ja' esta' publicado nem dobrar a
        # exposicao. E' a mesma chave do indice unico.
        slot = ja_publicadas + salvas + 1
        pick_id = _save_multipla(cur, bilhete, slot, contexto)
        conn.commit()
        if not pick_id:
            # O slot ja' existia: outra execucao publicou entre o SELECT e o
            # INSERT. E' exatamente o que o indice unico existe pra impedir.
            print(f"[MULTIPLA_ENGINE] Slot {slot} já ocupado por outra execução, pulando.")
            continue
        salvas += 1

        pernas = " + ".join(
            f"{p['_fixture']['home_team']} x {p['_fixture']['away_team']} "
            f"({p['market_name']} {p['value_label']} @ {p['odd']})"
            for p in bilhete["pernas"]
        )
        # As contagens da aba de Auditoria: `contabilizar` ja' somou este jogo
        # como analisado/descartado quando o decision_log gravou a linha dele;
        # aqui a pick salva move a contagem pro lado certo.
        registrar_selecao("MULTIPLA_ENGINE",
                          [p["_fixture"]["fixture_id"] for p in bilhete["pernas"]],
                          pick_id=pick_id)
        print(f"[MULTIPLA_ENGINE] Salva ({salvas}/{resultado['max_multiples']}): {pernas} | "
              f"odd_total={bilhete['odd_total']} | score={bilhete['score']} "
              f"({bilhete['faixa']}) | prob={bilhete['probabilidade']} | "
              f"casa={bilhete.get('casa')}")

    cur.close()
    conn.close()
    if not salvas:
        print("[MULTIPLA_ENGINE] Nenhuma múltipla publicada hoje.")


if __name__ == "__main__":
    run_multipla_engine()
