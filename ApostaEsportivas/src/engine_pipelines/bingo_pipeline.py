"""Bingo do Dia via motor deterministico (pick_engine) -- UMA cartela de
QUATRO pernas por dia, cada perna cotada entre 1.40 e 2.00.

O QUE E' O PRODUTO
------------------
Uma cartela. Quatro jogos diferentes, quatro mercados, todos precificados na
mesma regiao. Ou o dia fecha os quatro, ou nao fecha -- e' o formato, e e' o
que o nome promete.

A REGUA E' A DO VIP, DE PROPOSITO
---------------------------------
`BINGO_CONFIG` e' `VIP_CONFIG` com uma unica diferenca: a faixa de odd
(1.40-2.00 contra 1.45-2.00) e o teto de sanidade que a acompanha. Todo o
resto -- min_taxa, min_confidence, min_ev, min_edge, min_amostra,
min_bookmakers_count, `odd_evaluation="consensus"`, os pesos do line_score --
vem do mesmo default que o VIP usa. Foi o pedido: "motor identico ao do VIP,
com todas as premissas mapeadas". Uma perna do bingo passa exatamente pelos
mesmos cortes que um pick VIP passaria, e a IA revisa a cartela pelo mesmo
gate (`review_gate("bingo")`, OpenAI, o mesmo provedor do VIP).

TRES DIFERENCAS PARA A MULTIPLA, E O PORQUE DE CADA UMA
------------------------------------------------------
1. QUATRO JOGOS DIFERENTES, nao quatro pernas. A multipla aceita duas pernas
   da mesma partida desde 28/08 (familias diferentes) porque ela procura a
   melhor COMBINACAO do dia. O bingo procura outra coisa: quatro
   oportunidades. Duas pernas do mesmo jogo sao uma partida contada duas
   vezes -- a cartela pareceria ter quatro chances e teria tres, e o RED de
   um jogo derrubaria duas casas de uma vez.

   Isso tambem devolve, de graca, a premissa de independencia que a multipla
   teve que argumentar em prosa (ver `_save_multipla` la'): pernas de jogos
   diferentes foi o recorte MEDIDO em 2026-08-20 (1.960 bilhetes, produto
   -0,7pp de vies). O `prob_combinada` daqui roda dentro dessa medicao, nao
   ao lado dela.

2. NAO HA FAIXA DE ODD TOTAL. Na multipla a faixa total e' o produto; aqui o
   produto e' a faixa POR PERNA, e o total e' consequencia dela (entre
   1.40^4 = 3.84 e 2.00^4 = 16.00). Somar um segundo intervalo por cima
   rejeitaria cartela boa por aritmetica, que foi exatamente o problema que
   obrigou a alargar ODD_TOTAL_MAX da multipla pra 4.00 em 21/07.

3. UMA POR DIA, ponto. A multipla publica ate' 8 porque pernas sobram e cada
   bilhete usa as suas. O bingo e' "o bingo do dia" -- dois bingos nao sao
   dois produtos, sao a mesma promessa dita duas vezes.

O CRITERIO DE ESCOLHA
---------------------
`prob_combinada` (produto das probabilidades reais), com a media dos
`final_score` de desempate -- o mesmo criterio que _find_combo da multipla e
o da alavancagem ja' usam. NAO ordena por EV nem por odd: dentro de uma faixa
de preco fixa, maximizar EV e' maximizar odd, e odd alta e' alerta, nao
qualidade.
"""
import json
import textwrap
import traceback
import itertools

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from services.fixtures_service import FixturesService
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.team_stats_service import TeamStatsService
from services.referee_stats_service import RefereeStatsService
from services.standings_service import StandingsService
from services.pick_engine import analyze_fixture_markets, explain, homologation
from services.pick_engine.ai_review import review_gate
from services.pick_engine.config import BINGO_CONFIG
from services.pick_engine.staking import calculate_stake
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
from services.pick_engine import competition_rules_store
from engine_pipelines.decision_log import (
    MOTIVO_HISTORICO_REPROVADO, MOTIVO_SEM_HISTORICO, MOTIVO_SEM_ODDS,
    log_decision, log_skip, registrar_selecao,
)
from services.engine_audit import amostra, auditar


#: O produto. Nao e' "ate' 4": cartela de 3 nao e' bingo, e' multipla.
PERNAS = 4

#: Faixa POR PERNA. Duplicada aqui de proposito, como leitura: quem enforce e'
#: `BINGO_CONFIG` (enforce_odd_band + min_odd/max_odd), la' no motor, antes de
#: a linha virar candidato. Estes dois numeros so' entram numa checagem final
#: de sanidade em `_find_cartela` -- se um dia a config e o produto
#: divergirem, a cartela nao sai errada em silencio.
ODD_PERNA_MIN = 1.40
ODD_PERNA_MAX = 2.00

#: Teto do espaco de busca. combinations(30, 4) = 27.405 combos, custo
#: irrelevante -- e o veto de fixture repetida corta a maior parte antes da
#: conta. Mesmo numero da multipla pelo mesmo motivo: o pool ordenado por
#: final_score ja' pos as melhores linhas do dia na frente.
MAX_CANDIDATES_FOR_COMBO = 30


def _create_table_if_needed(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_bingo (
            id             SERIAL PRIMARY KEY,
            bingo_name     TEXT,
            games          JSONB,
            total_odd      NUMERIC,
            stake          NUMERIC,
            stake_pct      NUMERIC,
            score_combo    NUMERIC,
            prob_combinada NUMERIC,
            ev_combined    NUMERIC,
            match_date     DATE,
            result         TEXT,
            profit         NUMERIC,
            sent           BOOLEAN DEFAULT FALSE,
            reasoning      TEXT,
            engine_debug   JSONB,
            created_at     TIMESTAMP DEFAULT NOW()
        );
    """)
    # UMA cartela por dia, e o indice e' o backstop contra duas execucoes
    # concorrentes do pipeline -- o check em Python e' select-then-insert, e
    # corrida entre processos passa por cima dele (foi assim que a multipla
    # duplicou em 2026-07-25, com 2,5s de diferenca).
    #
    # PARCIAL como o da multipla, so' por simetria de manutencao: se um dia
    # existir um segundo `bingo_name` (uma cartela de teste, um formato
    # sazonal), o indice nao precisa ser recriado pra caber.
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_bingo_match_date_unique
        ON picks_bingo (match_date) WHERE bingo_name = 'BINGO_ENGINE';
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_bingo_date ON picks_bingo(match_date DESC);")


def _bingo_de_hoje(cur) -> int:
    """O teto e' por DIA, nao por execucao - rodar o motor duas vezes nao
    publica duas cartelas."""
    cur.execute(f"SELECT COUNT(*) FROM picks_bingo WHERE match_date = {HOJE_BR}")
    return int(cur.fetchone()[0])


def _today_used_pairs(cur) -> set:
    """(fixture_id, market_type) ja' usados em picks_vip/picks_free hoje.

    Mesma regra da multipla: o bingo nunca repete o mercado do mesmo jogo que
    ja' saiu como pick avulso. Repetir seria vender a mesma aposta duas vezes
    -- quem segue os dois produtos dobraria a exposicao achando que
    diversificou.

    A MULTIPLA PASSOU A ENTRAR (2026-09-10, pedido do usuario). Ate' aqui ela
    ficava de fora com o argumento de nao esvaziar o pool em dia curto -- o
    que ignorava o risco real: bilhete e' tudo ou nada, entao a perna
    repetida nos dois produtos nao dobra a exposicao, ela derruba os DOIS
    bilhetes inteiros no mesmo lance, levando junto as outras seis pernas.
    Ver services/pick_engine/bilhetes_do_dia.py.

    A cartela tambem nao pode repetir jogo dentro de si, e disso continua
    cuidando `_find_cartela`.
    """
    pairs = set()
    cur.execute(f"SELECT fixture_id, market_type FROM picks_vip WHERE match_date = {HOJE_BR}")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    cur.execute(f"SELECT fixture_id, market_type FROM picks_free WHERE match_date = {HOJE_BR}")
    pairs |= {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}
    # Pernas ja' dentro de um bilhete de hoje (multipla; alavancagem roda
    # depois). Vem por correlation_group, e a checagem no pool testa as duas
    # chaves -- ver _gather_leg_candidates.
    pairs |= bilhetes_do_dia.pares_em_bilhetes(cur, HOJE_BR, exceto=("picks_bingo",))
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
    """Roda o motor com a regua do VIP em cada fixture do dia e devolve a
    lista achatada dos candidatos ELEGIVEIS, com o fixture anexado.

    O pool leva o elegivel INTEIRO (`ranking.rank_all_candidates`), nao o
    corte final de 3-por-familia: esse corte existe pra escolher O pick de um
    jogo, e a cartela escolhe outra coisa. Mesma decisao ja' tomada na
    multipla em 2026-08-28.
    """
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
                log_skip("BINGO_ENGINE", fixture, MOTIVO_SEM_ODDS)
                continue

            last10_home = _load_history(match_stats, fixture["home_team_id"], fixture["season"], fixture["league_id"])
            last10_away = _load_history(match_stats, fixture["away_team_id"], fixture["season"], fixture["league_id"])
            if not last10_home or not last10_away:
                log_skip("BINGO_ENGINE", fixture, MOTIVO_SEM_HISTORICO)
                continue

            # Data Validation Engine -- roda ANTES de qualquer analise de
            # mercado; historico insuficiente de qualquer time aborta a
            # fixture inteira. Identico ao VIP.
            hist_home_val = dv.validate_history(last10_home)
            hist_away_val = dv.validate_history(last10_away)
            if not hist_home_val["passed"] or not hist_away_val["passed"]:
                log_skip("BINGO_ENGINE", fixture, MOTIVO_HISTORICO_REPROVADO)
                continue

            profile_home = tpm.build_profile(last10_home, fixture["home_team_id"])
            profile_away = tpm.build_profile(last10_away, fixture["away_team_id"])
            matchup = tpm.compare_matchup(profile_home, profile_away)
            standing_home, standing_away = standings_service.get_for_fixture(
                fixture["home_team_id"], fixture["away_team_id"],
                fixture["league_id"], fixture["season"])
            # A tabela INTEIRA, nao so' as duas linhas: e' o que permite medir
            # distancia ate a fronteira que importa (ver competitive_pressure).
            league_table = standings_service.get_league_table(
                fixture["league_id"], fixture["season"])
            context_data = ctx.build_context(
                last10_home, last10_away, fixture["home_team_id"], fixture["away_team_id"],
                standing_home, standing_away, fixture["league_id"],
                round_str=fixture.get("round"), league_table=league_table,
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
                config=BINGO_CONFIG,
                rastro=rastro,
            )
            elegiveis = ranking.rank_all_candidates(candidates, config=BINGO_CONFIG)
            # O log recebe a MESMA lista que vira pool. Se ele recebesse o
            # corte final e o pool viesse daqui, a cartela salvaria uma perna
            # que o proprio log dela chama de reprovada (achado real na
            # multipla, 2026-08-28).
            log_decision("BINGO_ENGINE", fixture, candidates, elegiveis, matchup=matchup,
                         context_data=context_data, rastro=rastro)

            # A AMOSTRA: quais jogos o motor leu, com o contexto do confronto.
            # Uma por FIXTURE (nao por perna) -- e' propriedade da partida.
            # Puramente aditiva: nenhum calculo le' esta chave, ela existe pra
            # o "Entenda esta analise" mostrar a amostra que DECIDIU em vez de
            # reconsultar o banco e arriscar exibir outro recorte.
            amostra_fixture = amostra.build(
                home_team_id=fixture["home_team_id"],
                away_team_id=fixture["away_team_id"],
                historico_home=last10_home, historico_away=last10_away,
                home_team=fixture.get("home_team"),
                away_team=fixture.get("away_team"),
                match_context=match_context)

            for p in elegiveis:
                # Duas chaves: o market_type cru (como VIP/Free gravam) e a
                # familia (como os bilhetes do dia entram).
                if ((fixture["fixture_id"], p["market_type"]) in used_pairs
                        or (fixture["fixture_id"],
                            ranking.correlation_group(p["market_type"])) in used_pairs):
                    continue
                legs.append({**p, "_fixture": fixture,
                             "data_quality_score": quality["score"],
                             "amostra": amostra_fixture})

        except Exception as e:
            # Stack trace completo: sem ele, "pulou 8 fixtures" nao diz ONDE
            # quebrou.
            print(f"[BINGO_ENGINE] Erro no fixture {fixture['fixture_id']}, pulando: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue

    return legs


def _na_faixa(perna: dict) -> bool:
    """Checagem final de sanidade da faixa por perna.

    Quem enforce e' `BINGO_CONFIG` dentro do motor -- esta funcao nunca
    deveria reprovar nada. Ela existe pra o dia em que alguem mexer na config
    e o produto mudar sem ninguem notar: prefiro a cartela nao sair a ela sair
    com uma perna de 1.15.
    """
    return ODD_PERNA_MIN <= float(perna["odd"]) <= ODD_PERNA_MAX


def _find_cartela(legs: list) -> tuple | None:
    """A melhor cartela de 4 pernas em 4 jogos diferentes.

    Retorna (pernas, score_combo, odd_total) ou None.

    Ordena por `prob_combinada` -- o produto das probabilidades reais, a
    chance de a cartela pagar -- com a media dos `final_score` de desempate.
    A media dos final_score sozinha premiaria cartela desequilibrada (uma
    perna excelente com uma fraca ganhando de quatro boas), e a cartela so'
    paga se TODAS baterem.
    """
    pool = [p for p in legs if _na_faixa(p)]
    pool = sorted(pool, key=lambda p: p["final_score"], reverse=True)[:MAX_CANDIDATES_FOR_COMBO]
    if len(pool) < PERNAS:
        return None

    best = None
    for combo in itertools.combinations(pool, PERNAS):
        fixtures = {p["_fixture"]["fixture_id"] for p in combo}
        if len(fixtures) != PERNAS:
            continue

        # CASA UNICA: a cartela inteira tem que caber numa casa so'. Cartela
        # que nenhuma casa cota por completo nao e' apostavel e por isso nem
        # concorre -- o laco segue e tenta a proxima. A partir daqui as pernas
        # ja' vem com a odd DAQUELA casa.
        aplicado = bet_house.aplicar_casa(combo, ODD_PERNA_MIN, ODD_PERNA_MAX)
        if aplicado is None:
            continue
        combo, _casa, odd_total = aplicado

        prob_combinada = 1.0
        for p in combo:
            prob_combinada *= float(p["taxa_real"])
        score_combo = round(sum(p["final_score"] for p in combo) / PERNAS, 4)

        # Ordena por probabilidade, nunca por preco: a casa unica so' decide
        # ONDE a cartela e' apostada, nao qual cartela ganha.
        chave_ordem = (round(prob_combinada, 6), score_combo)
        if best is None or chave_ordem > best[0]:
            best = (chave_ordem, tuple(combo), score_combo, odd_total)

    if best is None:
        return None
    return best[1], best[2], best[3]


def _save_bingo(cur, legs: tuple, score_combo: float, odd_total: float) -> int | None:
    """Grava a cartela e devolve o id - None quando o ON CONFLICT nao gravou.

    O id e' o que liga TODAS as pernas a' cartela na aba de Auditoria: e' o
    caminho de volta de um RED ate' o que o motor viu em cada jogo.
    """
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
            # Sem market_id nao ha' como casar a perna contra a odd de
            # fechamento: 'Over 4.5' existe em ate' 19 mercados da mesma
            # partida, e casar so' pelo rotulo trazia a odd de outro mercado
            # (ver picks_ledger_sync_service._closing_odd_for).
            "market_id": p.get("market_id"),
            "market_type": p["market_type"],
            "line": p["value_label"],
            "odd": p["odd"],
            "bet_house": p["best_bookmaker"],
            "confidence": p["confidence"],
            "prob_real": p["taxa_real"],
            "ev": p.get("ev"),
            "reasoning": explain(p),
            "ai_review": p.get("ai_review"),
        })

    match_date = min(p["_fixture"]["match_datetime"] for p in legs).date()
    reasoning = " | ".join(explain(p) for p in legs)

    # Probabilidade e EV da CARTELA, nao das pernas. Ela so' paga se as
    # QUATRO baterem, entao a chance e' o PRODUTO das probabilidades.
    #
    # A independencia aqui e' a mesma que foi MEDIDA em 2026-08-20 sobre
    # 1.960 bilhetes de pernas em jogos DIFERENTES: o produto dizia 70,1% e o
    # real foi 70,8% (-0,7pp de vies, dentro do ruido). O bingo exige jogos
    # diferentes por construcao, entao ele vive inteiro dentro desse recorte
    # medido -- ao contrario da multipla, que desde 28/08 tambem aceita duas
    # pernas da mesma partida e por isso precisa argumentar a extrapolacao.
    #
    # O que sobra e' a correlacao fraca de rodada (clima, arbitragem da
    # federacao, calendario), e ela puxa pro lado CONSERVADOR.
    prob_combinada = 1.0
    for p in legs:
        prob_combinada *= float(p["taxa_real"])
    prob_combinada = round(prob_combinada, 4)
    ev_combined = round(prob_combinada * float(odd_total) - 1.0, 4)

    # Kelly precisa da probabilidade do EVENTO, nao de um score de
    # ranqueamento: com score_combo o calculo satura o teto em qualquer
    # bilhete e o dimensionamento vira constante (erro ja' corrigido na
    # multipla em 2026-08-05).
    stake_pct, stake_units = calculate_stake(
        confidence=prob_combinada, odd=odd_total, ev=ev_combined, pick_type="bingo",
    )

    # O retrato do candidato no momento da escolha, POR PERNA -- variancia,
    # model-fit, edge, confidence, e a amostra que decidiu. E' o que o VIP
    # grava em picks_vip.engine_debug, e e' o que permite a
    # `red_analysis`/`calibration` distinguirem, num RED, evento imprevisivel
    # de erro de calibracao. A multipla nunca teve isso; o bingo nasce com.
    engine_debug = {
        "pernas": [
            {
                "fixture_id": p["_fixture"]["fixture_id"],
                **homologation.build_score_breakdown_section(p, p.get("data_quality_score")),
                "amostra": p.get("amostra"),
                "ai_review": p.get("ai_review"),
            }
            for p in legs
        ],
        "prob_combinada": prob_combinada,
        "ev_combined": ev_combined,
        "score_combo": score_combo,
    }

    cur.execute("""
        INSERT INTO picks_bingo
        (bingo_name, games, total_odd, stake_pct, stake, score_combo,
         prob_combinada, ev_combined, match_date, reasoning, engine_debug)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date) WHERE bingo_name = 'BINGO_ENGINE' DO NOTHING
        RETURNING id
    """, (
        "BINGO_ENGINE",
        json.dumps(games_info, default=str),
        odd_total,
        stake_pct,
        stake_units,
        score_combo,
        prob_combinada,
        ev_combined,
        match_date,
        reasoning,
        json.dumps(engine_debug, default=str, ensure_ascii=False),
    ))
    linha = cur.fetchone()
    return linha[0] if linha else None


# AUDITORIA. O decorador abre a execucao (run_id, contagens, status) e o
# decision_log carimba esse run_id sozinho nas linhas que ja' gravava --
# ver services/engine_audit/audit.py::auditar.
@auditar("PRE_LIVE", "bingo")
def run_bingo_engine():
    conn = get_connection()
    cur = conn.cursor()
    # Regulamento de mata-mata das competicoes nao cadastradas a mao, do banco
    # pra memoria, UMA vez por rodada. Sem isto o motor devolve DESCONHECIDO
    # pro formato dessas competicoes.
    competition_rules_store.carregar(cur)
    _create_table_if_needed(cur)
    conn.commit()

    if _bingo_de_hoje(cur):
        print("[BINGO_ENGINE] O dia ja tem a cartela dele.")
        cur.close()
        conn.close()
        return

    fixtures_service = FixturesService()
    fixtures = fixtures_service.get_fixtures_today()
    if not fixtures:
        print("[BINGO_ENGINE] Nenhum fixture hoje.")
        cur.close()
        conn.close()
        return

    used_pairs = _today_used_pairs(cur)
    legs = _gather_leg_candidates(fixtures, used_pairs)
    if len(legs) < PERNAS:
        print(f"[BINGO_ENGINE] So {len(legs)} candidato(s) elegivel(is) - "
              f"a cartela precisa de {PERNAS}.")
        cur.close()
        conn.close()
        return

    result = _find_cartela(legs)
    if not result:
        jogos = len({p["_fixture"]["fixture_id"] for p in legs if _na_faixa(p)})
        print(f"[BINGO_ENGINE] Nenhuma cartela fecha hoje - {jogos} jogo(s) com "
              f"perna na faixa [{ODD_PERNA_MIN:.2f}, {ODD_PERNA_MAX:.2f}], "
              f"precisa de {PERNAS}.")
        cur.close()
        conn.close()
        return

    combo, score_combo, odd_total = result

    # A IA revisa a CARTELA INTEIRA numa chamada -- ela veta, nunca escolhe
    # (ver services/pick_engine/ai_review.py). Falha do provedor mantem o
    # pick do motor: `unavailable` nao e' aprovacao, e' ausencia de parecer.
    reviewed = review_gate("bingo").apply(list(combo), "bingo")
    if not reviewed:
        print("[BINGO_ENGINE] Cartela vetada pela revisao de IA.")
        cur.close()
        conn.close()
        return
    combo = tuple(reviewed)

    pick_id = _save_bingo(cur, combo, score_combo, odd_total)
    conn.commit()
    cur.close()
    conn.close()

    if not pick_id:
        print("[BINGO_ENGINE] Outra execucao publicou a cartela de hoje primeiro.")
        return

    pernas = " + ".join(
        f"{p['_fixture']['home_team']} x {p['_fixture']['away_team']} "
        f"({p['market_name']} {p['value_label']} @ {p['odd']})"
        for p in combo
    )
    # As contagens da aba de Auditoria: `contabilizar` ja' somou cada jogo
    # como analisado/descartado quando o decision_log gravou a linha dele;
    # aqui a cartela salva move a contagem pro lado certo.
    registrar_selecao("BINGO_ENGINE",
                      [p["_fixture"]["fixture_id"] for p in combo],
                      pick_id=pick_id)
    print(f"[BINGO_ENGINE] Cartela salva: {pernas} | odd_total={odd_total} | "
          f"score_combo={score_combo}")


if __name__ == "__main__":
    run_bingo_engine()
