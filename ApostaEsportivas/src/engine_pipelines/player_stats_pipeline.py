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
dois: `analisados` alto com `selecionados` zero e' limiar; `analisados` zero e'
mercado ausente na coleta.
"""
import json
import textwrap
import traceback

from services.engine_audit import EngineRun
from services.odds_service import OddsService
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
        try:
            odd = float(o.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        if odd < cfg.ODD_MIN or odd > cfg.ODD_MAX:
            continue
        parsed = name_match.parse_valor(o.get("value_name"))
        if not parsed:
            continue
        nome, n = parsed
        ofertas.append({
            "nome_ofertado": nome, "n": n, "odd": odd,
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
                     calibragem: dict, constantes_saves: dict) -> tuple:
    """(candidatos, motivo_se_vazio) de uma partida, em todos os metodos."""
    odds_cruas = odds_service.load_odds_by_fixture(fixture["fixture_id"])
    if not odds_cruas:
        return ([], MOTIVO_SEM_ODDS)

    candidatos = []
    houve_mercado = False

    for metodo in cat.METODOS:
        ofertas = _ofertas_do_metodo(odds_cruas, metodo)
        if not ofertas:
            continue
        houve_mercado = True

        jogadores = player_history.jogadores_dos_times(
            cur, [fixture["home_team_id"], fixture["away_team_id"]],
            posicoes=metodo.posicoes or None, min_atuacoes=metodo.min_atuacoes)
        if not jogadores:
            continue

        phi = (calibragem.get(metodo.slug) or {}).get("phi") or metodo.phi_congelado

        for oferta in ofertas:
            jogador = name_match.resolver(
                oferta["nome_ofertado"], jogadores,
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
            analise = avaliado["analise"]
            candidatos.append({
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

    if not candidatos:
        return ([], MOTIVO_SEM_MERCADO if not houve_mercado else MOTIVO_SEM_JOGADORES)
    return (candidatos, None)


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
        f"{j['player_name']} · {c['rotulo_linha']}", c["oferta"]["n"],
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

    # UMA passada pelos jogos, para todos os metodos. `por_metodo` guarda os
    # candidatos e `sem_candidato` guarda, por jogo, o motivo de nao ter saido
    # nada -- os dois alimentam a auditoria de cada metodo depois.
    por_metodo: dict = {m.slug: [] for m in alvos}
    sem_candidato: list = []
    falhas: list = []
    for fixture in fixtures:
        try:
            do_jogo, motivo = _avaliar_fixture(
                fixture, cur, odds_service, calibragem, constantes_saves)
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
        if not do_jogo:
            sem_candidato.append((fixture, motivo or MOTIVO_SEM_MERCADO))

    for metodo in alvos:
        with EngineRun(MOTOR, metodo.slug, resumo={
            "prob_minima": cfg.PROB_MINIMA, "edge_minimo": cfg.EDGE_MINIMO,
            "faixa_odd": [cfg.ODD_MIN, cfg.ODD_MAX],
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
            for fixture, motivo in sem_candidato:
                if fixture["fixture_id"] not in fixtures_com_candidato:
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

            salvos = 0
            for c in publicaveis:
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
    run_player_stats_engine()
