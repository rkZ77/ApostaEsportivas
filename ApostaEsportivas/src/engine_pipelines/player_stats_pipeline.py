"""Player Stats -- props de JOGADOR, um metodo por estatistica.

    saves · shots_on · shots · fouls · tackles · passes

SUBSTITUI O MOTOR DE GOLEIROS
-----------------------------
Defesa de goleiro deixou de ser motor independente em 27/08 e virou o metodo
`saves` daqui. O CALCULO dele nao mudou: continua sendo
services/pick_engine/goalkeeper_model.py, com a recalibragem por rodada de
saves_calibration.py -- foi medido contra jogo real (correlacao 0.88 entre
defesas e chutes no alvo sofridos) e nao ficaria melhor por ser reescrito de
forma generica. O que mudou e' que ele agora divide leitura de historico,
casamento de nome, Score, gravacao e auditoria com outros cinco metodos, em
vez de ter um pipeline de 30 KB so' pra ele.

`engine_pipelines/goleiros_pipeline.py` fica no disco, sem ser chamado, como
rollback -- mesma politica dos pipelines de IA em ai/*.py.

ONDE O DIA VAZIO E' NORMAL
--------------------------
Defesas apareceram em 0.86% das atuacoes medidas. Chutes no alvo e passes sao
muito mais frequentes NA BASE, mas dependem de a casa OFERECER o mercado, que
e' outra coisa -- e prop de jogador e' oferta escassa fora dos grandes jogos.
Dia sem pick e' o caso comum deste motor, nao falha. A auditoria distingue os
dois pelo MOTIVO de cada jogo descartado, e nao pela contagem: desde 04/09 todo
jogo do dia aparece na execucao de todo metodo, com o motivo daquele metodo
("nenhuma casa ofereceu mercado de jogador" e' oferta ausente; "abaixo do
minimo" e' limiar). `analisados` zero passou a significar so' uma coisa:
nenhum jogo de hoje tinha odds coletadas.
"""
import json
import textwrap
import traceback

from services.engine_audit import EngineRun
from services.match_stats_service import MatchStatsService
from services.standings_service import StandingsService
from services.odds_service import OddsService
from services.pick_engine import context_gate, tie_effect
from services.pick_engine.ai_review import review_gate
from services.pick_engine.goalkeeper_model import analyze_saves_market
from services.pick_engine.market_pick_score import pick_score
from services.pick_engine.saves_calibration import recalibrar as recalibrar_saves
from services.pick_engine.staking import calculate_stake
from services.player_stats_engine import config as cfg
from services.player_stats_engine import count_model, explanation, name_match
from services.player_stats_engine import methods as cat
from services.player_stats_engine import player_history
from utils.data_br import HOJE_BR
from utils.db_utils import get_connection

MOTOR = "PLAYER_STATS"

# Motivos de descarte -- curtos e estaveis, viram GROUP BY no painel.
MOTIVO_SEM_ODDS = "sem odds coletadas para o jogo"
MOTIVO_SEM_MERCADO = "nenhuma casa ofereceu mercado de jogador"
MOTIVO_SEM_JOGADORES = "nenhum jogador com histórico suficiente nos dois times"
MOTIVO_NENHUM_APROVADO = "nenhum candidato passou nos critérios"


def _fixtures_de_hoje(cur) -> list:
    cur.execute(f"""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, l.name
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        LEFT JOIN leagues l ON l.league_id = f.league_id
        WHERE f.match_datetime::date = {HOJE_BR}
          AND f.status IN ('NS', 'TBD')
        ORDER BY f.match_datetime
    """)
    return [
        {"fixture_id": r[0], "league_id": r[1], "season": r[2],
         "home_team_id": r[3], "away_team_id": r[4],
         "home_team": r[5], "away_team": r[6],
         "match_datetime": r[7], "league_name": r[8]}
        for r in cur.fetchall()
    ]


def _ofertas_do_metodo(odds_cruas: list, metodo: cat.Metodo) -> list:
    """As linhas de jogador oferecidas pra este metodo, ja' parseadas.

    RAW e nao load_odds_structured, pelo mesmo motivo do antigo pipeline de
    goleiros: aquele agrupa por line_value e descarta o que nao parear como
    Over/Under. "Everson - 1" nao e' par de nada e sairia fora.
    """
    ofertas = []
    for o in odds_cruas:
        nome_mercado = (o.get("market_name") or "").strip().lower()
        if nome_mercado not in metodo.nomes_mercado:
            continue
        # O MANDO VEM NO NOME DO MERCADO (2026-09-04). "Home Player Shots" so'
        # lista jogador do mandante. Guardar isso restringe a busca de nome ao
        # lado certo -- e' a mesma protecao que o `resolver` ja' da' contra dois
        # "Weverton" no mesmo jogo, so' que uma etapa antes.
        lado = ("home" if nome_mercado.startswith("home ")
                else "away" if nome_mercado.startswith("away ") else None)
        try:
            odd = float(o.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        # Teto opcional: `ODD_MAX` e' None desde 04/09 e o motor deixa a odd
        # alta passar pro modelo decidir. Quem reprova evento raro sao
        # PROB_MINIMA e EDGE_MINIMO, que olham a probabilidade -- o teto olhava
        # so' o preco.
        if odd < cfg.ODD_MIN or (cfg.ODD_MAX is not None and odd > cfg.ODD_MAX):
            continue
        parsed = name_match.parse_valor(o.get("value_name"))
        if not parsed:
            continue
        nome, n = parsed
        ofertas.append({
            "nome_ofertado": nome, "n": n, "odd": odd, "lado": lado,
            "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
            "market_id": o.get("market_id"),
            "market_name": o.get("market_pt") or o.get("market_name"),
        })
    return ofertas


def _frequencia(valores: list, n: int) -> tuple:
    """(acertos, frequencia) da linha "N ou mais" nas atuacoes lidas.

    E' o numero que a tela mostra ao lado da probabilidade do modelo. Os dois
    juntos de proposito: so' o modelo joga fora que o evento ja' aconteceu; so'
    a frequencia trata 7/8 e 70/80 como a mesma afirmacao.
    """
    validos = [float(v) for v in valores if v is not None]
    if not validos:
        return (0, None)
    acertos = sum(1 for v in validos if v >= n)
    return (acertos, round(acertos / len(validos), 4))


def _avaliar_saves(oferta: dict, jogador: dict, fixture: dict, cur,
                   constantes: dict) -> dict | None:
    """Metodo `saves` -- delega pro goalkeeper_model, que foi MEDIDO.

    O sinal forte e' o volume ofensivo do ADVERSARIO, nao o historico do
    goleiro. De qual lado ele esta' define de qual time pegar esse volume, e em
    que mando esse time joga hoje: o goleiro da casa enfrenta o visitante
    jogando como visitante, e vice-versa. Chutar o lado inverte a previsao.
    """
    if jogador["team_id"] == fixture["home_team_id"]:
        adversario_id, mando_adversario = fixture["away_team_id"], "away"
    elif jogador["team_id"] == fixture["away_team_id"]:
        adversario_id, mando_adversario = fixture["home_team_id"], "home"
    else:
        return None

    media_adv, n_adv = player_history.volume_do_adversario(
        cur, adversario_id, "shots_on", mando_adversario,
        fixture["league_id"], fixture["season"])

    # Mesma competicao e temporada que `volume_do_adversario` acabou de usar,
    # duas linhas acima. Ate' 27/08 os dois lados do MESMO pick liam recortes
    # diferentes: o time era filtrado por liga e o goleiro nao.
    proprias = player_history.carregar(
        cur, jogador["player_id"], cat.SAVES.coluna,
        league_id=fixture["league_id"], season=fixture["season"])
    valores = [j["valor"] for j in proprias]
    media_propria = count_model.media_ponderada(valores)

    # "N ou mais" e' P(X >= N), que no modelo (definido como P(X > line)) vira
    # prob_over(N - 0.5). Passar N direto contaria uma defesa a menos.
    linha = oferta["n"] - 0.5
    analise = analyze_saves_market(
        opponent_shots_on_avg=media_adv, keeper_saves_avg=media_propria,
        sample_size=n_adv, odd=oferta["odd"], line=linha,
        constantes=constantes, keeper_sample=len(valores))
    if not analise:
        return None

    # Formato comum dos metodos, pra o resto do pipeline nao ter um ramo por
    # metodo. `esperado` e' o nome generico do que o modelo de defesas chama
    # de expected_saves.
    return {
        "analise": {
            "linha": linha, "esperado": analise.get("expected_saves"),
            "esperado_bruto": media_propria, "ajuste_adversario": None,
            "phi": constantes.get("dispersion_r"), "amostra": len(valores),
            "probability": analise.get("probability"),
            "fair_odd": analise.get("fair_odd"),
            "odd": analise.get("odd"), "edge": analise.get("edge"),
            "ev": analise.get("ev"),
        },
        "serie": valores,
        "composicao": player_history.composicao(proprias),
        "adversario": {"media": media_adv, "amostra": n_adv,
                       "mando": mando_adversario, "contador": "chutes no alvo"},
    }


def _avaliar_generico(oferta: dict, jogador: dict, metodo: cat.Metodo,
                      cur, phi: float, fixture: dict) -> dict | None:
    """Metodos sem modelo especifico -- Binomial Negativa sobre o historico.

    `fixture` entrou em 2026-08-27 e serve a uma coisa so': dizer de qual
    COMPETICAO e temporada o historico pode vir (ver player_history.carregar).
    O efeito colateral esperado e' menos pick, porque um jogador que tinha 12
    atuacoes somando Brasileirao e Libertadores pode ter 7 no Brasileirao e
    cair abaixo de `min_atuacoes`. E' o mesmo custo que o lado dos times ja'
    paga, e pela mesma razao: amostra de outra competicao nao e' amostra maior,
    e' amostra de outra coisa.
    """
    proprias = player_history.carregar(
        cur, jogador["player_id"], metodo.coluna,
        league_id=fixture["league_id"], season=fixture["season"])
    if len(proprias) < metodo.min_atuacoes:
        return None
    valores = [j["valor"] for j in proprias]

    analise = count_model.analisar(
        valores=valores, linha=oferta["n"] - 0.5, phi=phi, odd=oferta["odd"])
    if not analise:
        return None
    return {"analise": analise, "serie": valores, "adversario": None,
            "composicao": player_history.composicao(proprias)}


def _avaliar_fixture(fixture: dict, cur, odds_service: OddsService,
                     match_stats: MatchStatsService,
                     calibragem: dict, constantes_saves: dict,
                     standings_service: StandingsService | None = None) -> tuple:
    """(candidatos, motivo_por_metodo) de uma partida.

    O motivo e' POR METODO, e nao um so' pro jogo inteiro (corrigido em
    2026-09-04). Antes, um jogo que rendia candidato em QUALQUER metodo saia da
    lista de descartados de TODOS -- entao a execucao de `shots_on` num dia em
    que so' `saves` achou oferta terminava com `analisados = 0`, que a propria
    docstring do modulo ensina a ler como "mercado ausente na coleta". A
    auditoria dizia que o jogo nao existiu, em vez de dizer por que aquele
    metodo nao aproveitou o jogo.
    """
    odds_cruas = odds_service.load_odds_by_fixture(fixture["fixture_id"])
    if not odds_cruas:
        return ([], {m.slug: MOTIVO_SEM_ODDS for m in cat.METODOS})

    # CONTEXTO DE COMPETICAO · uma vez por jogo, pros seis metodos.
    #
    # REGRESSAO CORRIGIDA EM 2026-08-28. O goleiros_pipeline, que gerava
    # defesas ate' 27/08, montava este contexto e o aplicava em cada linha. Na
    # migracao pro Player Stats a chamada nao veio junto, e ninguem percebeu
    # porque o teste que a cobrava continuou lendo o arquivo antigo -- que ja'
    # nao rodava. So' apareceu quando o arquivo morto foi apagado.
    #
    # O QUE ELE FAZ AQUI e' menos do que o nome sugere, e importa saber: os
    # deslocamentos POR PAPEL de `saves` e `shots_on_target` foram medidos e
    # deram nulo (+0.79 ep 1.22 e +0.87 ep 0.96), entao o efeito de contagem
    # nao age nesses dois. O que age e' o DESCONTO DE REGIME: a media do
    # jogador sai dos jogos normais dele, e uma volta de mata-mata com o
    # agregado aberto nao pertence aquela distribuicao. Isso e' incerteza sobre
    # a estimativa, e vira desconto de probabilidade.
    #
    # Nunca levanta: `build_for_fixture` devolve None em qualquer falha, e o
    # gate inerte deixa o motor igual ao de antes.
    #
    # `league_table` entrou em 2026-09-02. Sem ela a pressao competitiva
    # nascia None e o desconto de regime descrito acima so' enxergava
    # mata-mata -- um jogo de fim de campeonato com time lutando contra o
    # rebaixamento tambem foge da distribuicao normal do jogador, e agora
    # conta. Mesma correcao que o commit de 01/09 fez nos tres pipelines de
    # pick generico.
    #
    # `conv_cartoes` segue None de proposito: rivalidade e' medida em pontos de
    # cartao sobre o historico do TIME, e este motor le' historico de JOGADOR
    # (player_history). O baseline nao existe neste caminho -- ligar exigiria
    # consulta nova, nao um argumento a mais.
    league_table = (standings_service.get_league_table(
        fixture["league_id"], fixture["season"]) if standings_service else None)
    contexto = context_gate.build_for_fixture(
        match_stats, fixture, league_table=league_table)

    candidatos = []
    motivos: dict = {}

    for metodo in cat.METODOS:
        ofertas = _ofertas_do_metodo(odds_cruas, metodo)
        if not ofertas:
            motivos[metodo.slug] = MOTIVO_SEM_MERCADO
            continue

        jogadores = player_history.jogadores_dos_times(
            cur, [fixture["home_team_id"], fixture["away_team_id"]],
            posicoes=metodo.posicoes or None, min_atuacoes=metodo.min_atuacoes)

        # SO' QUEM TEM CHANCE REAL DE COMECAR (2026-09-02).
        #
        # `min_atuacoes` cobra HISTORICO -- quatro jogos de 60+ minutos bastam,
        # mesmo espalhados em vinte rodadas do time. Isso deixava o motor
        # escolher reserva: medido em PROD, 45 dos jogadores elegiveis comecavam
        # em menos de 40% dos jogos, e 16 de 49 nos cinco times de maior
        # amostra.
        #
        # A varredura de escalacao oficial (lineups_sweep) ja' ANULA o pick de
        # quem fica fora do XI, mas ela age tarde: o pick ja' foi publicado, ja'
        # ocupou o slot do dia e quem seguiu ja' registrou a aposta. Este corte
        # age na ESCOLHA -- e as duas coisas se completam, uma antes e outra
        # depois de a escalacao sair.
        #
        # A API-Football nao publica escalacao provavel, so' a oficial de 20 a
        # 40 minutos antes. Titularidade recente e' a melhor aproximacao que o
        # dado permite, e e' medida (`is_substitute`, cobertura total).
        antes = len(jogadores)
        jogadores = [j for j in jogadores if player_history.e_titular_provavel(j)]
        if antes != len(jogadores):
            print(f"[PLAYER_STATS] {metodo.slug}: {antes - len(jogadores)} de {antes} "
                  f"jogador(es) fora por titularidade baixa.")
        if not jogadores:
            motivos[metodo.slug] = MOTIVO_SEM_JOGADORES
            continue

        phi = (calibragem.get(metodo.slug) or {}).get("phi") or metodo.phi_congelado

        do_metodo = []
        for oferta in ofertas:
            # Mercado publicado por mando so' lista jogador daquele lado -- ver
            # o comentario em `_ofertas_do_metodo`. Sem lado declarado, procura
            # nos dois times, que e' o comportamento de sempre.
            if oferta.get("lado"):
                time_do_lado = (fixture["home_team_id"] if oferta["lado"] == "home"
                                else fixture["away_team_id"])
                elegiveis = [j for j in jogadores if j.get("team_id") == time_do_lado]
            else:
                elegiveis = jogadores

            jogador = name_match.resolver(
                oferta["nome_ofertado"], elegiveis,
                fixture["home_team_id"], fixture["away_team_id"])
            if not jogador:
                # Jogador que ainda nao aparece na base por nenhum dos dois
                # times, ou nome ambiguo entre eles. Descarta em vez de chutar.
                continue

            if metodo.slug == "saves":
                avaliado = _avaliar_saves(oferta, jogador, fixture, cur, constantes_saves)
            else:
                avaliado = _avaliar_generico(oferta, jogador, metodo, cur, phi, fixture)
            if not avaliado:
                continue

            acertos, frequencia = _frequencia(avaliado["serie"], oferta["n"])

            # ANTES dos cortes de `_aprovado`, e nao depois: o contexto tem que
            # poder REPROVAR uma linha, e nao so' enfeitar a explicacao de uma
            # que ja passou. Mesma ordem do faltas_pipeline.
            #
            # `escopo` e' o lado do JOGADOR. O tie_effect inverte sozinho pra
            # `saves` (defesa e' consequencia do ataque do outro), e essa
            # inversao mora la' de proposito -- ver `_lado_do_escopo`.
            analise = tie_effect.aplicar_em_analise(
                avaliado["analise"], contexto,
                familia=cat.familia_do_contexto(metodo),
                escopo=("home" if jogador.get("team_id") == fixture["home_team_id"]
                        else "away"),
                direcao="over", linha=oferta["n"] - 0.5,
                lambda_esperado=avaliado["analise"].get("esperado"))
            do_metodo.append({
                "fixture": fixture, "metodo": metodo, "jogador": jogador,
                "oferta": oferta, "analise": analise,
                "serie": avaliado["serie"], "adversario": avaliado.get("adversario"),
                "acertos": acertos, "frequencia": frequencia,
                "rotulo_linha": metodo.rotulo_linha.format(n=oferta["n"]),
                "calibragem": calibragem.get(metodo.slug),
                "pick_score": pick_score(
                    probability=analise.get("probability") or 0,
                    odd=analise.get("odd") or 0,
                    edge=analise.get("edge") or 0,
                    amostra=analise.get("amostra"),
                    amostra_saturacao=cfg.AMOSTRA_SATURACAO,
                    config=cfg.SCORE_CONFIG),
            })

        if not do_metodo:
            # Houve oferta e houve jogador, mas nenhuma das duas pontas casou:
            # nome que a casa publica e a base nao tem, ou historico curto
            # demais na competicao de hoje.
            motivos[metodo.slug] = MOTIVO_SEM_JOGADORES
        candidatos.extend(do_metodo)

    return (candidatos, motivos)


def _aprovado(c: dict) -> tuple:
    """(passou, motivo). Cortes duros, antes de qualquer ordenacao."""
    analise = c["analise"]
    prob = analise.get("probability") or 0
    edge = analise.get("edge")
    if prob < cfg.PROB_MINIMA:
        return (False, f"probabilidade {prob * 100:.0f}% abaixo do mínimo "
                       f"({cfg.PROB_MINIMA * 100:.0f}%)")
    if edge is None or edge < cfg.EDGE_MINIMO:
        return (False, f"margem {(edge or 0) * 100:+.1f}% abaixo do mínimo "
                       f"({cfg.EDGE_MINIMO * 100:.0f}%)")
    if (analise.get("amostra") or 0) < c["metodo"].min_atuacoes:
        return (False, f"amostra de {analise.get('amostra')} atuações abaixo do "
                       f"mínimo do método ({c['metodo'].min_atuacoes})")
    return (True, None)


def _pick_para_ia(c: dict) -> dict:
    """O candidato traduzido pras chaves que `ai_review.build_review_payload` le.

    O payload da revisao nasceu dos motores de MERCADO DE TIME e le nomes que
    este pipeline nao usa (`market_name`, `taxa_real`, `value_label`). Passar o
    candidato cru faria a chamada acontecer com quase tudo None -- a IA
    responderia sobre um pick em branco, e o gate pareceria estar funcionando.

    O que a IA precisa ver aqui e' o que distingue prop de jogador: QUEM e' o
    jogador, de que time, e sobre quantas atuacoes a media foi tirada.
    """
    analise, jogador, metodo = c["analise"], c["jogador"], c["metodo"]
    return {
        "market_name": metodo.label,
        "market_type": metodo.slug,
        "value_label": f"{jogador['player_name']} ({jogador['team_name']}) · "
                       f"{c['rotulo_linha']}",
        "odd": analise.get("odd"),
        "taxa_real": analise.get("probability"),
        "confidence": analise.get("probability"),
        "edge": analise.get("edge"),
        "ev": analise.get("ev"),
        "market_sample": analise.get("amostra"),
        "match_context": c.get("composicao"),
    }


def _engine_debug(c: dict) -> str:
    return json.dumps({
        "modelo": ("goalkeeper_model/binomial_negativa" if c["metodo"].slug == "saves"
                   else "player_stats_engine/binomial_negativa"),
        "metodo": c["metodo"].slug,
        "analise": c["analise"],
        "adversario": c.get("adversario"),
        "acertos": c.get("acertos"), "frequencia": c.get("frequencia"),
        "pick_score": c.get("pick_score"),
        # A AMOSTRA do jogador: as atuacoes que entraram na conta, ate' 10 pra
        # exibicao. Mesmo papel que a amostra de time tem nos outros motores --
        # e' o que a tela "Entenda esta analise" mostra.
        "amostra": {
            "max_exibidos": 10,
            "atuacoes_lidas": len(c.get("serie") or []),
            "valores": (c.get("serie") or [])[:10],
            # De QUAL competicao vieram essas atuacoes. Mesmo papel que
            # `multi_competicao` tem na amostra do time: sem isso, media tirada
            # de duas competicoes e media tirada de uma sao o mesmo numero na
            # tela, e so' reproduzindo a consulta da' pra saber qual e' qual.
            **(c.get("composicao") or {}),
        },
        # De quais constantes saiu esta probabilidade. Sem isto, um pick de
        # hoje e um de dois meses atras com a mesma entrada e saidas
        # diferentes ficariam inexplicaveis.
        "calibragem": c.get("calibragem"),
        "ai_review": c.get("ai_review"),
    }, default=str, ensure_ascii=False)


def _salvar(cur, c: dict) -> int | None:
    f, j, metodo, analise = c["fixture"], c["jogador"], c["metodo"], c["analise"]
    stake_pct, stake_units = calculate_stake(
        confidence=analise.get("probability"), odd=analise.get("odd"),
        ev=analise.get("ev") or 0, pick_type="free",
    )
    cur.execute(f"""
        INSERT INTO picks_player_stats
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id, league_id, league_name,
             player_id, player_name, team_id, team_name, position,
             method, stat_column, market, market_type, line, line_value,
             odd, bet_house, market_id,
             score, confidence, prob_real, fair_odd, edge, ev,
             reasoning, stake_pct, stake_units, engine_debug)
        VALUES (%s, {HOJE_BR}, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s)
        ON CONFLICT (match_date, fixture_id, player_id, method) DO NOTHING
        RETURNING id
    """, (
        f["fixture_id"], f["home_team"], f["away_team"],
        f["home_team_id"], f["away_team_id"], f["league_id"], f.get("league_name"),
        j["player_id"], j["player_name"], j["team_id"], j["team_name"], j.get("position"),
        metodo.slug, metodo.coluna,
        c["oferta"]["market_name"], metodo.slug,
        # A LINHA GRAVADA NAO USA PONTO DO MEIO (02/09). Ela sai em texto no
        # card, no compartilhamento e no ledger, e "Fulano · 2 ou mais chutes"
        # e' a pontuacao que o site nao usa em lugar nenhum. Quem separa o
        # jogador do mercado na TELA e' o card, que desenha os dois em linhas
        # proprias -- aqui fica a frase corrida, com virgula.
        f"{j['player_name']}, {c['rotulo_linha']}", c["oferta"]["n"],
        analise.get("odd"), c["oferta"]["bookmaker"], c["oferta"]["market_id"],
        c.get("pick_score"), analise.get("probability"), analise.get("probability"),
        analise.get("fair_odd"), analise.get("edge"), analise.get("ev"),
        explanation.frase(c), stake_pct, stake_units, _engine_debug(c),
    ))
    linha = cur.fetchone()
    if not linha:
        return None
    return linha["id"] if isinstance(linha, dict) else linha[0]


def _dados_da_auditoria(c: dict, motivo: str | None) -> dict:
    return {
        "metodo": c["metodo"].slug,
        "jogador": {"player_id": c["jogador"]["player_id"],
                    "player_name": c["jogador"]["player_name"],
                    "team_name": c["jogador"].get("team_name")},
        "resumo": explanation.resumo_estruturado(c),
        "conclusao": motivo or explanation.frase(c),
        "amostra": {"atuacoes_lidas": len(c.get("serie") or []),
                    "valores": (c.get("serie") or [])[:10],
                    **(c.get("composicao") or {})},
    }


def run_player_stats_engine(metodos: tuple | None = None):
    """Uma execucao POR METODO -- a auditoria e' por motor+metodo.

    Rodar os seis metodos sob um run_id so' apagaria a pergunta que a
    auditoria existe pra responder: "qual metodo falhou hoje". Cada metodo
    abre a propria execucao, com a propria contagem e o proprio status.

    MAS A ANALISE ACONTECE UMA VEZ SO'. Os jogos sao percorridos antes do laco
    de metodos, e o resultado e' agrupado por metodo. A alternativa obvia --
    um laco de fixtures dentro de cada metodo -- reavaliaria os seis metodos
    de cada jogo seis vezes, e reler odds e historico so' pra jogar cinco
    sextos fora e' exatamente o processamento duplicado que a arquitetura
    proibe.
    """
    alvos = metodos or cat.METODOS
    conn = get_connection()
    cur = conn.cursor()

    # Calibragem UMA vez pra a rodada inteira, e nao por metodo dentro do
    # laco: sao consultas de agregacao na tabela toda.
    calibragem = count_model.calibragem_de_todos(cur, alvos)
    for slug, c in calibragem.items():
        print(f"[PLAYER_STATS] {slug}: dispersão {c['phi']} ({c['origem']}, "
              f"{c['atuacoes']} atuações)" + (f" · erro: {c['erro']}" if c.get("erro") else ""))

    # As constantes do metodo `saves` continuam vindo da recalibragem propria
    # dele -- ela mede a relacao chute-no-alvo -> defesa, que a dispersao
    # generica nao substitui.
    constantes_saves, calibragem_saves = recalibrar_saves(cur)

    fixtures = _fixtures_de_hoje(cur)
    odds_service = OddsService()
    standings_service = StandingsService()
    # Uma instancia pra rodada inteira · ela e' so' o caminho ate' o h2h que o
    # contexto le, e abrir uma por jogo seria conexao nova por partida.
    match_stats = MatchStatsService()

    # UMA passada pelos jogos, para todos os metodos. `por_metodo` guarda os
    # candidatos e `sem_candidato` guarda, por jogo, o motivo POR METODO de nao
    # ter saido nada -- os dois alimentam a auditoria de cada metodo depois.
    por_metodo: dict = {m.slug: [] for m in alvos}
    sem_candidato: list = []
    falhas: list = []
    for fixture in fixtures:
        try:
            do_jogo, motivos = _avaliar_fixture(
                fixture, cur, odds_service, match_stats, calibragem,
                constantes_saves, standings_service)
        except Exception as e:
            # Guardado e nao registrado agora: o erro pertence a uma execucao,
            # e as execucoes so' abrem no laco de baixo. Registrar aqui exigiria
            # um run aberto por jogo, que e' a estrutura errada.
            falhas.append((fixture, e))
            print(f"[PLAYER_STATS] Erro no fixture {fixture.get('fixture_id')}: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            continue
        for c in do_jogo:
            por_metodo.setdefault(c["metodo"].slug, []).append(c)
        if motivos:
            sem_candidato.append((fixture, motivos))

    for metodo in alvos:
        with EngineRun(MOTOR, metodo.slug, resumo={
            "prob_minima": cfg.PROB_MINIMA, "edge_minimo": cfg.EDGE_MINIMO,
            "faixa_odd": [cfg.ODD_MIN, cfg.ODD_MAX],   # teto None = sem teto
            "calibragem": calibragem.get(metodo.slug),
            "jogos_do_dia": len(fixtures),
        }) as run:
            if not fixtures:
                print(f"[PLAYER_STATS/{metodo.slug}] Nenhum jogo de hoje com odds.")
                continue

            # O erro de leitura de um jogo atingiu TODOS os metodos daquele
            # jogo, entao ele aparece na execucao de cada um -- e' o unico
            # jeito de "qual metodo falhou hoje" ter resposta honesta.
            for fixture, e in falhas:
                run.erro(e, contexto=f"{fixture.get('home_team')} x {fixture.get('away_team')}",
                         fixture_id=fixture.get("fixture_id"))

            candidatos = por_metodo.get(metodo.slug) or []
            fixtures_com_candidato = {c["fixture"]["fixture_id"] for c in candidatos}
            for fixture, motivos in sem_candidato:
                motivo = motivos.get(metodo.slug)
                if motivo and fixture["fixture_id"] not in fixtures_com_candidato:
                    run.analisado(fixture, selecionado=False, motivo=motivo)

            aprovados, reprovados = [], []
            for c in candidatos:
                passou, motivo = _aprovado(c)
                (aprovados if passou else reprovados).append((c, motivo))

            # Um pick por jogador: duas linhas do mesmo jogador sao a mesma
            # aposta em graus diferentes. Fica a de maior Score.
            aprovados.sort(key=lambda par: par[0]["pick_score"], reverse=True)
            vistos, publicaveis, repetidos = set(), [], []
            for c, _ in aprovados:
                chave = c["jogador"]["player_id"]
                if cfg.UM_PICK_POR_JOGADOR and chave in vistos:
                    repetidos.append((c, "linha de menor Score do mesmo jogador"))
                    continue
                vistos.add(chave)
                publicaveis.append(c)

            excedentes = publicaveis[cfg.MAX_PICKS_POR_RODADA:]
            publicaveis = publicaveis[:cfg.MAX_PICKS_POR_RODADA]

            # GATE DE IA (2026-09-04). Ate' aqui este pipeline era o unico
            # dos sete que nunca chamava a revisao -- e mentia sobre isso: o
            # rastro ja' gravava um campo `ai_review` (ver `_engine_debug`) que
            # nascia None sempre, entao a auditoria lia "a IA nao vetou" onde a
            # verdade era "a IA nunca olhou".
            #
            # Um por vez, e nao a lista inteira numa chamada so': aqui cada
            # candidato e' um JOGADOR diferente, muitas vezes de partidas
            # diferentes. Vetar em bloco derrubaria picks bons junto com o
            # ruim, que e' o oposto do que o gate faz nos outros motores (la' a
            # lista e' UMA selecao: as pernas de uma multipla, um pick de um
            # jogo). A multipla e' o contraexemplo proposital -- ela chama com
            # a combinacao inteira porque o veto e' sobre o bilhete.
            gate = review_gate("player_stats")
            salvos = 0
            for c in publicaveis:
                revisados = gate.apply([_pick_para_ia(c)], "player_stats", c["fixture"])
                if not revisados:
                    print(f"[PLAYER_STATS/{metodo.slug}] "
                          f"{c['jogador']['player_name']} vetado pela revisao de IA.")
                    run.analisado(c["fixture"], selecionado=False,
                                  score=c.get("pick_score"),
                                  probabilidade=c["analise"].get("probability"),
                                  odd=c["analise"].get("odd"),
                                  motivo="vetado pela revisao de IA",
                                  dados=_dados_da_auditoria(c, "vetado pela revisao de IA"))
                    continue
                # O parecer entra no candidato pra `_engine_debug` grava-lo --
                # e' o campo que ate' hoje ficava vazio. O `c` original
                # continua sendo o que grava o pick: o dicionario que foi pra
                # IA e' uma TRADUCAO, nao o candidato.
                c = {**c, "ai_review": revisados[0].get("ai_review")}
                pick_id = None
                try:
                    pick_id = _salvar(cur, c)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    run.erro(e, contexto="gravacao do pick",
                             fixture_id=c["fixture"].get("fixture_id"))
                if pick_id:
                    salvos += 1
                    print(f"[PLAYER_STATS/{metodo.slug}] {c['jogador']['player_name']} "
                          f"({c['jogador']['team_name']}) · {c['rotulo_linha']} @ "
                          f"{c['analise'].get('odd')} "
                          f"(prob={(c['analise'].get('probability') or 0) * 100:.1f}%, "
                          f"margem={(c['analise'].get('edge') or 0) * 100:+.1f}%)")
                run.analisado(c["fixture"], selecionado=bool(pick_id),
                              score=c.get("pick_score"),
                              probabilidade=c["analise"].get("probability"),
                              odd=c["analise"].get("odd"),
                              motivo=None if pick_id else "pick equivalente já existia",
                              dados=_dados_da_auditoria(c, None), pick_id=pick_id)

            for c, motivo in reprovados + repetidos + [(c, "fora do teto da rodada")
                                                       for c in excedentes]:
                run.analisado(c["fixture"], selecionado=False,
                              score=c.get("pick_score"),
                              probabilidade=c["analise"].get("probability"),
                              odd=c["analise"].get("odd"), motivo=motivo,
                              dados=_dados_da_auditoria(c, motivo))

            run.anotar(picks_salvos=salvos, candidatos=len(candidatos))
            if metodo.slug == "saves":
                run.anotar(calibragem_saves=calibragem_saves.get("origem"))
            if not salvos:
                print(f"[PLAYER_STATS/{metodo.slug}] {MOTIVO_NENHUM_APROVADO} "
                      f"({len(candidatos)} candidato(s) avaliados).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    # Metodo por argv, espelhando `main.py playerstats saves`.
    #
    # NAO E' CONVENIENCIA: o /admin roda pipeline POR CAMINHO DE SCRIPT, nunca
    # pelo registro de comandos do main.py. Sem isto, o botao "Gerar Defesas"
    # nao tinha como pedir so' o metodo `saves` e continuava apontando pro
    # goleiros_pipeline.py -- o pipeline ANTIGO, que desde 27/08 so' existe no
    # disco como rollback. O resultado era o botao e a rodada diaria gravando
    # em tabelas diferentes (picks_goleiros contra picks_player_stats).
    import sys

    from services.player_stats_engine import methods as _cat

    _pedidos = [a.lower() for a in sys.argv[1:] if a]
    if not _pedidos:
        run_player_stats_engine()
    else:
        _alvos = tuple(m for m in _cat.METODOS if m.slug in _pedidos)
        _desconhecidos = [x for x in _pedidos if x not in _cat.POR_SLUG]
        if _desconhecidos:
            print(f"[PLAYER_STATS] Metodo(s) desconhecido(s): {', '.join(_desconhecidos)}. "
                  f"Disponiveis: {', '.join(m.slug for m in _cat.METODOS)}")
        if _alvos:
            run_player_stats_engine(_alvos)
