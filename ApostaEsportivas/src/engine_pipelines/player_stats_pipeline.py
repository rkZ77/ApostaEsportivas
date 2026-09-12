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
from services.player_stats_engine import (contradiction, count_model, decision,
                                          explanation, minutes_model, name_match,
                                          opponent_model, quality, selection)
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


def _dias_desde_a_ultima(atuacoes: list, fixture: dict) -> int | None:
    """Quantos dias separam a ultima atuacao lida do jogo de hoje (§32).

    Uma media de dois meses atras descreve um jogador que pode ter trocado de
    funcao, de forma ou de clube -- e o motor nao tem como saber qual dos tres.
    O numero nao reprova nada sozinho; ele entra na qualidade do dado.
    """
    if not atuacoes:
        return None
    ultima = atuacoes[0].get("match_date")
    # `.date()` DIRETO, sem `data_br_de`: `fixtures.match_datetime` ja' e'
    # Brasilia (o coletor grava convertido). Passar por `data_br_de` tirava 3
    # horas de um horario que ja era BR e devolvia o dia anterior pra todo jogo
    # entre 00:00 e 02:59 BRT, somando um dia falso nesta conta. Ver o
    # docstring de utils.data_br.data_br_de.
    inicio = fixture.get("match_datetime")
    hoje = inicio.date() if inicio else None
    if not ultima or not hoje:
        return None
    try:
        return (hoje - ultima).days
    except TypeError:
        return None


def _mando_do_jogador(jogador: dict, fixture: dict) -> str | None:
    if jogador.get("team_id") == fixture["home_team_id"]:
        return "home"
    if jogador.get("team_id") == fixture["away_team_id"]:
        return "away"
    return None


def _contexto_do_jogador(cur, jogador: dict, metodo: cat.Metodo,
                         fixture: dict) -> dict | None:
    """Tudo que vale pro jogador NESTE jogo, independente da linha ofertada.

    UMA VEZ POR JOGADOR, E NAO POR LINHA. A casa publica de tres a seis linhas
    do mesmo jogador ("1 ou mais", "2 ou mais"...), e ate' 10/09 cada uma delas
    refazia a consulta de historico inteira -- seis leituras identicas pra
    escolher uma. Agora a parte que nao muda com a linha e' montada aqui e
    reaproveitada, que e' a mesma razao pela qual a rodada percorre os jogos uma
    vez so' e agrupa por metodo depois (ver run_player_stats_engine).

    Devolve None quando nem vale a pena avaliar linha nenhuma: sem historico no
    recorte de hoje, o metodo nao tem o que projetar.
    """
    atuacoes = player_history.carregar(
        cur, jogador["player_id"], metodo.coluna,
        league_id=fixture["league_id"], season=fixture["season"])
    if len(atuacoes) < metodo.min_atuacoes:
        return None

    serie = [a["valor"] for a in atuacoes]
    mando_hoje = _mando_do_jogador(jogador, fixture)
    # §7 · as atuacoes NO MANDO de hoje, pra a media ser puxada na direcao
    # delas. Sem mando resolvido (fixture antiga sem os dois ids) a lista sai
    # vazia e o combinador devolve a media geral, que e' o comportamento de
    # antes desta camada.
    serie_no_mando = ([a["valor"] for a in atuacoes if a.get("mando") == mando_hoje]
                      if (metodo.mando_relevante and mando_hoje) else [])

    perfil_min = minutes_model.perfil(
        cur, jogador["player_id"],
        league_id=fixture["league_id"], season=fixture["season"])
    esperados = minutes_model.minutos_esperados(perfil_min)
    # O fator compara os minutos de HOJE com os minutos que geraram a media --
    # e nao com 90. Ver a docstring do minutes_model.
    minutos_lidos = [int(a.get("minutes") or 0) for a in atuacoes if a.get("minutes")]
    minutos_da_amostra = (round(sum(minutos_lidos) / len(minutos_lidos), 1)
                          if minutos_lidos else None)
    fator = (minutes_model.fator_de_minutos(esperados, minutos_da_amostra)
             if metodo.depende_de_minutos else 1.0)
    risco_funcao, posicao = minutes_model.risco_de_funcao(perfil_min, atuacoes, metodo)

    minutos = {
        "status": minutes_model.status_de_titularidade(jogador, perfil_min),
        "esperados": esperados,
        "da_amostra": minutos_da_amostra,
        "fator": fator,
        "risco": minutes_model.risco_de_minutos(perfil_min, jogador),
        "risco_funcao": risco_funcao,
        "posicao": posicao,
        "perfil": perfil_min,
    }

    # §8 · o adversario. Em `saves` ele ja' e' o sinal forte e vem pelo caminho
    # medido do goalkeeper_model -- ligar os dois contaria o mesmo efeito duas
    # vezes, e por isso o catalogo deixa `coluna_concedida` vazia la'.
    ajuste_adv = {"disponivel": False, "motivo": "método sem ajuste de adversário",
                  "ajuste": None}
    if metodo.coluna_concedida and mando_hoje:
        ajuste_adv = opponent_model.avaliar(
            cur, metodo,
            adversario_id=(fixture["away_team_id"] if mando_hoje == "home"
                           else fixture["home_team_id"]),
            # O adversario joga no mando OPOSTO ao do jogador. Errar isto
            # inverte o ajuste, e um ajuste invertido e' pior que nenhum.
            mando_do_adversario=("away" if mando_hoje == "home" else "home"),
            league_id=fixture["league_id"], season=fixture["season"])

    disp = quality.dispersao(serie)
    dias = _dias_desde_a_ultima(atuacoes, fixture)
    return {
        "atuacoes": atuacoes,
        "serie": serie,
        "serie_no_mando": serie_no_mando,
        "composicao": player_history.composicao(atuacoes),
        "minutos": minutos,
        "dispersao": disp,
        "outliers": quality.outliers(serie, disp),
        "classe_amostra": quality.classificar_amostra(len(serie)),
        "penalidade_variancia": quality.penalidade_de_variancia(
            disp.get("cv"), metodo.cv_referencia),
        "adversario_ajuste": ajuste_adv,
        "matchup": opponent_model.matchup(metodo, ajuste_adv),
        "dias_desde_ultima": dias,
        "data_quality": quality.data_quality_score(
            amostra=len(serie), min_atuacoes=metodo.min_atuacoes,
            perfil_minutos=perfil_min, status_titular=minutos["status"],
            risco_minutos=minutos["risco"], dias_desde_ultima=dias,
            adversario=ajuste_adv),
        "mando": mando_hoje,
    }


def _analise_de_saves(oferta: dict, fixture: dict, cur, ctx: dict,
                      constantes: dict) -> dict | None:
    """Metodo `saves` -- delega pro goalkeeper_model, que foi MEDIDO.

    O sinal forte e' o volume ofensivo do ADVERSARIO, nao o historico do
    goleiro. De qual lado ele esta' define de qual time pegar esse volume, e em
    que mando esse time joga hoje: o goleiro da casa enfrenta o visitante
    jogando como visitante, e vice-versa. Chutar o lado inverte a previsao.

    O que a V2 acrescentou aqui e' so' a MOLDURA (minutos, qualidade de dado,
    contradicao, auditoria final): a conta continua sendo a de 01/08, sem uma
    linha alterada, porque ela foi medida contra jogo real e nao ficaria melhor
    por ser reescrita de forma generica.
    """
    mando = ctx.get("mando")
    if not mando:
        return None
    adversario_id = (fixture["away_team_id"] if mando == "home"
                     else fixture["home_team_id"])
    mando_adversario = "away" if mando == "home" else "home"

    media_adv, n_adv = player_history.volume_do_adversario(
        cur, adversario_id, "shots_on", mando_adversario,
        fixture["league_id"], fixture["season"])
    media_propria = count_model.media_ponderada(ctx["serie"])

    # "N ou mais" e' P(X >= N), que no modelo (definido como P(X > line)) vira
    # prob_over(N - 0.5). Passar N direto contaria uma defesa a menos.
    linha = oferta["n"] - 0.5
    analise = analyze_saves_market(
        opponent_shots_on_avg=media_adv, keeper_saves_avg=media_propria,
        sample_size=n_adv, odd=oferta["odd"], line=linha,
        constantes=constantes, keeper_sample=len(ctx["serie"]))
    if not analise:
        return None

    fator = ctx["minutos"].get("fator") or 1.0
    esperado = analise.get("expected_saves")
    # Formato comum dos metodos, pra o resto do pipeline nao ter um ramo por
    # metodo. `esperado` e' o nome generico do que o modelo de defesas chama de
    # expected_saves, e a probabilidade que sai daqui e' a DO MODELO -- o
    # abatimento e' aplicado depois, no mesmo ponto dos outros cinco.
    return {
        "linha": linha,
        "esperado": round(esperado * fator, 3) if esperado is not None else None,
        "esperado_bruto": media_propria,
        "esperado_no_mando": None, "peso_do_mando": 0.0, "amostra_no_mando": 0,
        "ajuste_adversario": None, "ajuste_minutos": fator,
        "phi": constantes.get("dispersion_r"), "amostra": len(ctx["serie"]),
        "probability_modelo": analise.get("probability"),
        "odd": analise.get("odd"),
        "adversario": {"media": media_adv, "amostra": n_adv,
                       "mando": mando_adversario, "contador": "chutes no alvo"},
    }


def _analise_generica(oferta: dict, metodo: cat.Metodo, ctx: dict,
                      phi: float) -> dict | None:
    """Metodos sem modelo especifico -- Binomial Negativa sobre o historico."""
    return count_model.analisar(
        valores=ctx["serie"], valores_no_mando=ctx["serie_no_mando"],
        linha=oferta["n"] - 0.5, phi=phi, odd=oferta["odd"],
        ajuste_adversario=(ctx["adversario_ajuste"] or {}).get("ajuste"),
        ajuste_minutos=(ctx["minutos"].get("fator") if metodo.depende_de_minutos
                        else None))


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
        # O contexto do jogador NAO depende da linha ofertada, e a casa publica
        # varias linhas do mesmo jogador. Uma leitura por jogador, reusada em
        # todas as linhas dele -- ver `_contexto_do_jogador`.
        contextos: dict = {}
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

            chave_ctx = jogador["player_id"]
            if chave_ctx not in contextos:
                contextos[chave_ctx] = _contexto_do_jogador(
                    cur, jogador, metodo, fixture)
            ctx = contextos[chave_ctx]
            if not ctx:
                continue

            if metodo.slug == "saves":
                analise = _analise_de_saves(oferta, fixture, cur, ctx,
                                            constantes_saves)
            else:
                analise = _analise_generica(oferta, metodo, ctx, phi)
            if not analise:
                continue

            acertos, frequencia = _frequencia(ctx["serie"], oferta["n"])

            # ANTES dos cortes de `_aprovado`, e nao depois: o contexto tem que
            # poder REPROVAR uma linha, e nao so' enfeitar a explicacao de uma
            # que ja passou. Mesma ordem do faltas_pipeline.
            #
            # `escopo` e' o lado do JOGADOR. O tie_effect inverte sozinho pra
            # `saves` (defesa e' consequencia do ataque do outro), e essa
            # inversao mora la' de proposito -- ver `_lado_do_escopo`.
            analise = tie_effect.aplicar_em_analise(
                analise, contexto,
                familia=cat.familia_do_contexto(metodo),
                escopo=("home" if jogador.get("team_id") == fixture["home_team_id"]
                        else "away"),
                direcao="over", linha=oferta["n"] - 0.5,
                lambda_esperado=analise.get("esperado"))
            # O tie_effect desloca `probability` e recalcula edge e odd justa a
            # partir dela -- mas nao conhece a separacao entre probabilidade do
            # MODELO e CALIBRADA (§18), que nasceu aqui. Entao o que ele
            # devolve e' a nova probabilidade do modelo, e o abatimento e a
            # aritmetica de mercado sao refeitos uma vez so', logo abaixo. Sem
            # esta linha o EV ficaria congelado no valor de antes do contexto, e
            # a conferencia aritmetica do §26 reprovaria o proprio motor.
            analise["probability_modelo"] = analise.get("probability")

            margem = quality.margem_de_projecao(
                analise.get("esperado"), analise.get("linha"))

            # AS CONTRADICOES SAO DETECTADAS SOBRE A PROBABILIDADE SEM DESCONTO
            # e cobradas depois. A ordem inversa (descontar e depois detectar)
            # faria o desconto mudar a propria classificacao que o gerou -- um
            # pick com 81% cairia pra 77% e deixaria de disparar
            # CONFIANCA_ACIMA_DA_AMOSTRA, que e' a contradicao que estava
            # cobrando o desconto.
            achados = contradiction.detectar(
                analise=analise, disp=ctx["dispersao"], margem=margem,
                frequencia=frequencia, amostra=analise.get("amostra"),
                classe_amostra=ctx["classe_amostra"], minutos=ctx["minutos"],
                risco_minutos=ctx["minutos"]["risco"],
                risco_funcao=ctx["minutos"]["risco_funcao"],
                status_titular=ctx["minutos"]["status"],
                adversario=ctx["adversario_ajuste"],
                outliers_serie=ctx["outliers"])

            analise = count_model.aplicar_abatimento(
                analise, penalidade_variancia=ctx["penalidade_variancia"],
                desconto_contradicao=contradiction.desconto(achados))

            escolha = selection.score_de_selecao(
                probabilidade=analise.get("probability") or 0,
                amostra=analise.get("amostra"),
                amostra_saturacao=cfg.AMOSTRA_SATURACAO,
                data_quality=(ctx["data_quality"] or {}).get("score"),
                margem_relativa=margem.get("relativa"),
                penalidade_variancia=ctx["penalidade_variancia"],
                risco_minutos=ctx["minutos"]["risco"],
                risco_funcao=ctx["minutos"]["risco_funcao"])

            do_metodo.append({
                "fixture": fixture, "metodo": metodo, "jogador": jogador,
                "oferta": oferta, "analise": analise,
                "serie": ctx["serie"], "serie_no_mando": ctx["serie_no_mando"],
                "adversario": analise.get("adversario"),
                "adversario_ajuste": ctx["adversario_ajuste"],
                "matchup": ctx["matchup"], "minutos": ctx["minutos"],
                "dispersao": ctx["dispersao"], "outliers": ctx["outliers"],
                "classe_amostra": ctx["classe_amostra"],
                "data_quality": ctx["data_quality"],
                "dias_desde_ultima": ctx["dias_desde_ultima"],
                "composicao": ctx["composicao"],
                "contradicoes": achados,
                "margem": margem,
                "acertos": acertos, "frequencia": frequencia,
                "rotulo_linha": metodo.rotulo_linha.format(n=oferta["n"]),
                "calibragem": calibragem.get(metodo.slug),
                "selecao": escolha,
                "stake_fator": selection.fator_de_stake(
                    data_quality=(ctx["data_quality"] or {}).get("score"),
                    classe_amostra=ctx["classe_amostra"],
                    risco_minutos=ctx["minutos"]["risco"],
                    penalidade_variancia=ctx["penalidade_variancia"]),
                # O Score antigo continua gravado -- ele e' comparavel com o dos
                # outros pipelines de mercado proprio e e' a serie historica do
                # motor. O que ele nao faz mais e' escolher: quem ordena e'
                # `selecao`, que nao pontua preco (ver selection.py).
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
    """(passou, motivo). Cortes duros, antes de qualquer ordenacao.

    DOIS BLOCOS, E A ORDEM IMPORTA PRA QUEM LE' A AUDITORIA. Primeiro os cortes
    de sempre (probabilidade, margem sobre a odd, amostra), que respondem "este
    numero paga?"; depois a auditoria final do §42, que responde "este numero
    quer dizer alguma coisa?". Inverter faria o painel encher de "titularidade
    não sustentada" em candidatos que morreriam de probabilidade de qualquer
    jeito, e a leitura do dia ficaria sobre a camada errada.

    O resultado da auditoria fica no candidato (`checklist`, `decisao`) mesmo
    quando ela passa: e' ela que o `engine_debug` grava, e um pick aprovado
    precisa poder mostrar as vinte respostas tanto quanto um reprovado.
    """
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

    decisao, motivo, itens = decision.avaliar(c)
    c["checklist"] = itens
    c["decisao"] = decisao
    c["motivo"] = motivo
    return (decisao == "PICK", motivo)


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
    minutos = c.get("minutos") or {}
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
        # §35 · O CONTRATO DE DADOS DA REVISAO.
        #
        # "A IA nao deve rejeitar uma aposta simplesmente porque um campo
        # importante nao foi enviado. O contrato de dados precisa ser
        # corrigido." Ate' aqui a revisao recebia dez campos de mercado de time
        # e opinava sobre prop de jogador sem saber se o jogador comeca, quanto
        # ele joga, em que funcao, contra quem, nem a que distancia da linha a
        # projecao ficou -- ou seja, sem nada do que distingue este produto.
        #
        # Os quatro que o payload generico JA' TINHA slot, e que este pipeline
        # nunca preenchia -- por isso a revisao via' `data_quality: null` em
        # todo pick de jogador desde 04/09. Os nomes sao os de la'
        # (`build_review_payload`), nao os do §35: renomear do lado de ca'
        # deixaria os campos caindo no vazio de novo, que e' o defeito que este
        # bloco esta' corrigindo.
        "data_quality_score": (c.get("data_quality") or {}).get("score"),
        "variance_penalty": analise.get("penalidade_variancia"),
        "poisson_probability": analise.get("probability_modelo"),
        "model_fit_diff": analise.get("abatimento"),
        "matchup_raw": (c.get("matchup") or {}).get("motivo"),
        # E o que so' existe em prop de jogador. Bloco proprio porque o payload
        # generico descreve mercado de TIME e nao tem onde pendurar minutos,
        # titularidade e funcao -- os campos em ingles sao os nomes do §35, que
        # e' a lingua do prompt.
        "player_stats": {
            "player": jogador["player_name"],
            "team": jogador.get("team_name"),
            "market": metodo.slug,
            "line": (c.get("oferta") or {}).get("n"),
            "starter_status": minutos.get("status"),
            "minutes_expected": minutos.get("esperados"),
            "minutes_risk": minutos.get("risco"),
            "role": minutos.get("posicao"),
            "role_risk": minutos.get("risco_funcao"),
            "projection": analise.get("esperado"),
            "projection_margin": (c.get("margem") or {}).get("absoluta"),
            "probability_model": analise.get("probability_modelo"),
            "probability_calibrated": analise.get("probability_calibrada"),
            "sample": analise.get("amostra"),
            "sample_classification": c.get("classe_amostra"),
            "sample_home_away": analise.get("amostra_no_mando"),
            "dispersion_cv": (c.get("dispersao") or {}).get("cv"),
            "opponent_adjustment": (c.get("adversario_ajuste") or {}).get("ajuste"),
            "contradictions": [x["texto"] for x in (c.get("contradicoes") or [])],
        },
    }


def _engine_debug(c: dict) -> str:
    """O rastro do pick -- §41, com os nomes que o projeto ja' usa.

    A montagem mora em `decision.engine_debug` e nao aqui porque ela e' a outra
    metade da auditoria final: as vinte perguntas e o rastro respondem a mesma
    coisa e mudam juntos. O que sobra neste arquivo sao os campos que sao do
    PIPELINE e nao da decisao -- qual modelo rodou, que calibragem estava
    valendo naquela rodada e o que a IA disse.
    """
    decisao = c.get("decisao") or "PICK"
    itens = c.get("checklist") or decision.checklist(c)
    rastro = decision.engine_debug(c, decisao, c.get("motivo"), itens)
    rastro.update({
        "modelo": ("goalkeeper_model/binomial_negativa" if c["metodo"].slug == "saves"
                   else "player_stats_engine/binomial_negativa"),
        "metodo": c["metodo"].slug,
        "analise": c["analise"],
        "acertos": c.get("acertos"), "frequencia": c.get("frequencia"),
        "pick_score": c.get("pick_score"),
        # A AMOSTRA do jogador: as atuacoes que entraram na conta, ate' 10 pra
        # exibicao. Mesmo papel que a amostra de time tem nos outros motores --
        # e' o que a tela "Entenda esta analise" mostra.
        "amostra": {
            "max_exibidos": 10,
            "atuacoes_lidas": len(c.get("serie") or []),
            "valores": (c.get("serie") or [])[:10],
            "classificacao": c.get("classe_amostra"),
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
    })
    return json.dumps(rastro, default=str, ensure_ascii=False)


def _salvar(cur, c: dict) -> int | None:
    f, j, metodo, analise = c["fixture"], c["jogador"], c["metodo"], c["analise"]
    stake_pct, stake_units = calculate_stake(
        confidence=analise.get("probability"), odd=analise.get("odd"),
        ev=analise.get("ev") or 0, pick_type="free",
    )
    # §40 · O STAKE NAO SOBE POR EV, E DESCE POR QUALIDADE DE ESTIMATIVA.
    #
    # `calculate_stake` dimensiona por confianca e odd, que e' o eixo certo e
    # nao e' o unico: dois picks com a mesma confianca e a mesma odd nao
    # merecem a mesma unidade se um tem oito atuacoes atras e o outro tem
    # vinte. O fator so' REDUZ (ver selection.fator_de_stake) e tem piso, pra
    # nao produzir uma unidade que ninguem consegue colocar na casa.
    fator = max((c.get("stake_fator") or {}).get("fator", 1.0),
                cfg.STAKE_FATOR_MINIMO)
    if fator < 1.0:
        stake_pct = round(float(stake_pct) * fator, 4)
        stake_units = round(float(stake_units) * fator, 2)
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
                    "classificacao": c.get("classe_amostra"),
                    **(c.get("composicao") or {})},
        # A auditoria final e as contradicoes viajam junto com o motivo: o
        # painel precisa poder mostrar TODAS as perguntas que falharam, e nao
        # so' a primeira, que e' a unica que cabe na frase do motivo.
        "auditoria_final": c.get("checklist"),
        "contradicoes": c.get("contradicoes"),
        "qualidade_do_dado": c.get("data_quality"),
        "minutos": {k: v for k, v in (c.get("minutos") or {}).items()
                    if k != "perfil"},
        "selecao": c.get("selecao"),
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
            # aposta em graus diferentes. Fica a de maior valor AJUSTADO AO
            # RISCO -- que nao e' a de maior Score, e a diferenca e' o ponto:
            # o Score pontua odd e edge (38% dele e' preco) e o `selecao` nao
            # pontua preco nenhum. Odd e EV eliminam nos cortes, nunca ordenam.
            aprovados.sort(key=lambda par: par[0]["selecao"]["score"], reverse=True)
            vistos, publicaveis, repetidos = set(), [], []
            for c, _ in aprovados:
                chave = c["jogador"]["player_id"]
                if cfg.UM_PICK_POR_JOGADOR and chave in vistos:
                    repetidos.append((c, "linha de menor valor ajustado ao risco "
                                         "do mesmo jogador"))
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
