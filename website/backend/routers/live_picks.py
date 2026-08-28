"""API dos Picks Ao Vivo · produto separado do acompanhamento em routers/live.py.

A SEPARACAO DE RESPONSABILIDADE
-------------------------------
    routers/live.py        camada de DADO ao vivo + acompanhamento das apostas
                           que o usuario seguiu ("Minhas Apostas"). NAO decide
                           nada, so' acompanha pick que ja existe.
    routers/live_picks.py  o PRODUTO novo: as oportunidades que o Motor Live
                           encontrou. Listagem, expiracao, liquidacao e
                           estatistica -- todas proprias.

Este modulo IMPORTA de routers/live.py e nao modifica nada la'. E' reuso
deliberado: aquele arquivo ja resolveu cache com TTL adaptativo, busca em
lote, leitura de estatistica com o lado certo e conversao de status ao vivo.
Reescrever isso aqui criaria a segunda implementacao que a auditoria mostrou
ser a origem das divergencias historicas do projeto.

O QUE NAO ACONTECE AQUI
-----------------------
Nenhum endpoint deste modulo entra nos UNIONs de estatistica do pre-jogo. O
numero de performance do site continua descrevendo exatamente o mesmo
conjunto de picks que descrevia antes do Live existir. Misturar os dois e'
decisao de produto pendente, nao efeito colateral de codigo.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth_utils import get_current_user, require_admin, require_vip
from database import get_connection
from settlement_bridge import settlement

# Reuso da camada de dado ao vivo. Os nomes com underscore sao privados por
# convencao dentro daquele modulo, mas sao exatamente a fronteira que este
# produto precisa -- a alternativa seria duplicar a leitura da API-Football.
from routers.live import (  # noqa: F401
    FT_STATUSES, LIVE_STATUSES, _calc_result, _fetch_fixture,
    _fetch_fixtures_bulk, _fetch_stats, _leg_needs_stats, _parse_stats,
    _pick_status, _profit_for_result, _stat_for_market,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live-picks", tags=["live-picks"])

#: Vocabulario de CICLO DE VIDA. Deliberadamente separado do vocabulario de
#: RESULTADO (services/settlement.py: GREEN/RED/PUSH/HALF-WIN/HALF-LOSS).
#:
#: O pedido original falava em WON/LOST como status. Nao foi seguido ao pe' da
#: letra, e o motivo e' o proprio principio que o acompanhava: nao inventar um
#: segundo vocabulario pro que o settlement ja nomeia. WON e LOST seriam
#: apelidos de GREEN e RED, e duas palavras pra mesma coisa e' como nasce a
#: divergencia que a auditoria encontrou entre o job em lote e o caminho ao
#: vivo. Aqui `status` responde "este pick ainda esta de pe'?" e `result`
#: responde "como ele terminou?", nas palavras que o resto do sistema ja usa.
STATUS_ATIVO = "ACTIVE"
STATUS_EXPIRADO = "EXPIRED"
STATUS_LIQUIDADO = "SETTLED"


def require_live_reader(user: dict = Depends(require_vip)) -> dict:
    """Quem pode LER o feed/estatistica do Motor Live: todo assinante.

    Este gate teve tres vidas curtas. Nasceu admin-only (motor em validacao),
    virou "aberto salvo LIVE_PICKS_PUBLIC=off" quando o produto abriu, e em
    2026-08-28 perdeu a variavel: o usuario removeu as variaveis do Live no
    Railway, e um interruptor que ninguem configura e' so' um `if` a mais entre
    o assinante e o produto.

    `require_vip` faz o trabalho todo -- e' o mesmo gate dos outros produtos
    VIP, e "aberto pro assinante" nunca quis dizer aberto pra qualquer um.

    A funcao fica no lugar da dependencia direta porque o nome documenta a
    intencao nas seis rotas que a usam, e porque e' aqui que uma regra futura
    entraria sem tocar em todas elas.
    """
    return user


def _tabela_existe(cur) -> bool:
    """picks_live so' existe onde o motor Live ja rodou. Em producao a tabela
    nao deve existir, e o produto inteiro precisa responder 'vazio' em vez de
    500 -- e' o que mantem o site de producao intacto com este codigo
    implantado."""
    try:
        cur.execute("SELECT to_regclass('public.picks_live') IS NOT NULL")
        linha = cur.fetchone()
        return bool(linha and (linha[0] if not isinstance(linha, dict) else list(linha.values())[0]))
    except Exception:
        return False


def _agora_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─────────────────────────────────────────────────────────────────────────
# EXPIRACAO
# ─────────────────────────────────────────────────────────────────────────
def expirar_vencidos(cur, conn) -> int:
    """Marca como EXPIRED o pick cuja odd venceu antes de alguem seguir.

    EXPIRED NAO E' RED. Um pick que expirou sem ser apostado nao errou nada --
    a janela fechou. Contar isso como derrota inventaria um historico de erro
    que nunca existiu e puniria o motor por velocidade do mercado, nao por
    qualidade da analise. Por isso a estatistica Live ignora EXPIRED no
    denominador de acerto (ver `estatisticas`).

    Pick que ALGUEM seguiu nunca expira: virou aposta real, e aposta real e'
    liquidada pelo jogo, nao pelo relogio da odd.
    """
    try:
        cur.execute("""
            UPDATE picks_live pl
            SET status = %s,
                expiration_reason = 'odd expirou antes de ser seguida'
            WHERE pl.status = %s
              AND pl.result IS NULL
              AND pl.odd_valid_until IS NOT NULL
              AND pl.odd_valid_until < %s
              AND NOT EXISTS (
                  SELECT 1 FROM user_followed_picks uf
                  WHERE uf.pick_id = pl.id AND uf.pick_type = 'live'
              )
        """, (STATUS_EXPIRADO, STATUS_ATIVO, _agora_naive()))
        n = cur.rowcount or 0
        conn.commit()
        return n
    except Exception as e:
        conn.rollback()
        logger.error("[LIVE-PICKS] expiracao falhou: %s", e)
        return 0


# ─────────────────────────────────────────────────────────────────────────
# LIQUIDACAO
# ─────────────────────────────────────────────────────────────────────────
def liquidar_pendentes(cur, conn, limite: int = 30) -> dict:
    """Liquida pick Live cujo jogo encerrou (ou cujo resultado ja travou).

    Toda a matematica vem de services/settlement.py, via _calc_result de
    routers/live.py -- exatamente a mesma funcao que grada VIP, Free, faltas e
    goleiros. Nao existe aritmetica de resultado propria do Live.

    A REGRA QUE PRECISA FICAR EXPLICITA: o pick e' liquidado pelo TOTAL DA
    PARTIDA, nao pelos eventos posteriores a' criacao. Um "Over 2.5 gols"
    criado aos 60' com 1x0 no placar e' GREEN se o jogo terminar 2x1, porque
    o total foi 3. E' assim que a casa liquida, e e' por isso que
    residual_model soma o ja-observado antes de perguntar a probabilidade.
    """
    resumo = {"liquidados": 0, "erros": 0}
    try:
        cur.execute("""
            SELECT id, fixture_id, market, market_type, line, odd,
                   home_team_name, away_team_name, home_team_id, away_team_id
            FROM picks_live
            WHERE result IS NULL
              AND status IN (%s, %s)
            ORDER BY created_at
            LIMIT %s
        """, (STATUS_ATIVO, STATUS_EXPIRADO, limite))
        pendentes = cur.fetchall()
    except Exception as e:
        logger.error("[LIVE-PICKS] consulta de pendentes falhou: %s", e)
        return resumo

    if not pendentes:
        return resumo

    _fetch_fixtures_bulk([p["fixture_id"] for p in pendentes if p["fixture_id"]])

    for p in pendentes:
        try:
            dados = _fetch_fixture(p["fixture_id"])
            fixture = dados.get("fixture", {}) or {}
            status = (fixture.get("status") or {}).get("short", "NS")
            if status not in FT_STATUSES:
                continue

            gols = dados.get("goals", {}) or {}
            home_goals = int(gols.get("home") or 0)
            away_goals = int(gols.get("away") or 0)
            prorrogacao = status in ("AET", "PEN")
            if prorrogacao:
                ft90 = (dados.get("score") or {}).get("fulltime") or {}
                if ft90.get("home") is not None and ft90.get("away") is not None:
                    home_goals, away_goals = int(ft90["home"]), int(ft90["away"])

            times = dados.get("teams", {}) or {}
            home_stats, away_stats = {}, {}
            if _leg_needs_stats(p["market"], p["market_type"]):
                home_stats, away_stats = _parse_stats(
                    _fetch_stats(p["fixture_id"], status),
                    p["home_team_id"] or (times.get("home") or {}).get("id"),
                    p["away_team_id"] or (times.get("away") or {}).get("id"),
                )

            valor, _rotulo, _dir = _stat_for_market(
                p["market"], p["line"], home_stats, away_stats,
                home_goals, away_goals, p["market_type"])

            resultado = _calc_result(
                p["market"], p["line"], valor, home_goals, away_goals,
                market_type=p["market_type"],
                home_team=p["home_team_name"], away_team=p["away_team_name"],
                home_stats=home_stats, away_stats=away_stats,
                went_to_extra_time=prorrogacao,
            )
            if not resultado:
                continue

            odd = float(p["odd"] or 1)
            profit = _profit_for_result(resultado, odd)
            cur.execute("""
                UPDATE picks_live
                SET result = %s, profit = %s, status = %s, settled_at = NOW()
                WHERE id = %s AND result IS NULL
            """, (resultado, profit, STATUS_LIQUIDADO, p["id"]))
            cur.execute(
                "UPDATE user_followed_picks SET result=%s WHERE pick_id=%s AND pick_type='live'",
                (resultado, p["id"]),
            )
            conn.commit()
            resumo["liquidados"] += 1
            logger.info("[LIVE-PICKS] #%s -> %s (%+.4fu)", p["id"], resultado, profit)
        except Exception as e:
            conn.rollback()
            resumo["erros"] += 1
            logger.error("[LIVE-PICKS] liquidacao do #%s falhou: %s", p["id"], e)

    return resumo


# ─────────────────────────────────────────────────────────────────────────
# LEITURA
# ─────────────────────────────────────────────────────────────────────────
def _enriquecer(pick: dict) -> dict:
    """Acrescenta o estado ATUAL do jogo ao pick gravado.

    O snapshot da criacao continua intacto nas colunas `*_at_creation` -- este
    bloco e' o "agora", pra o card mostrar a distancia entre o que o motor viu
    e o que o jogo virou. Sao duas informacoes diferentes e o card mostra as
    duas.
    """
    dados = _fetch_fixture(pick["fixture_id"])
    fixture = dados.get("fixture", {}) or {}
    status = (fixture.get("status") or {}).get("short", "NS")
    gols = dados.get("goals", {}) or {}
    home_goals = gols.get("home")
    away_goals = gols.get("away")

    home_stats, away_stats = {}, {}
    if (status in LIVE_STATUSES or status in FT_STATUSES) and _leg_needs_stats(
            pick["market"], pick["market_type"]):
        times = dados.get("teams", {}) or {}
        home_stats, away_stats = _parse_stats(
            _fetch_stats(pick["fixture_id"], status),
            pick.get("home_team_id") or (times.get("home") or {}).get("id"),
            pick.get("away_team_id") or (times.get("away") or {}).get("id"))

    valor, rotulo, direcao = _stat_for_market(
        pick["market"], pick["line"], home_stats, away_stats,
        int(home_goals or 0), int(away_goals or 0), pick["market_type"])

    return {
        **pick,
        "live_status": status,
        "elapsed": (fixture.get("status") or {}).get("elapsed"),
        "home_goals": home_goals,
        "away_goals": away_goals,
        "current_val": valor,
        "stat_label": rotulo,
        "direction": direcao,
        "is_live": status in LIVE_STATUSES,
        "is_ft": status in FT_STATUSES,
        "pick_status": _pick_status(valor, pick["line"], int(home_goals or 0),
                                    int(away_goals or 0), pick.get("home_team_name"),
                                    pick.get("away_team_name")),
    }


@router.get("/feed")
def feed(
    current_user: dict = Depends(require_live_reader),
    incluir_encerrados: bool = Query(True, description="mostra tambem os ja liquidados de hoje"),
    dias: int = Query(1, ge=0, le=365,
                      description="quantos dias para tras alem de hoje (0 = so hoje)"),
    limit: int = Query(30, ge=1, le=100),
):
    """Oportunidades do Motor Live. E' o que a aba Ao Vivo consome.

    Abrir a aba tambem expira o que venceu e liquida o que ja encerrou --
    mesmo padrao de `maybe_resolve_pending` no /today: a visita e' o gatilho,
    site parado nao gasta nada.

    `dias` NASCE EM 1 pra a aba publica nao mudar de comportamento: la' o feed
    e' "o que esta acontecendo", e pick de tres dias atras nao e' ao vivo.

    Ele existe porque o PAINEL DO ADMIN tem outra pergunta -- "o motor esta'
    acertando?" -- e essa nao cabe numa janela de dois dias. Ate' 2026-08-16 o
    admin reusava este endpoint com o default, e o resultado era um painel que
    se contradizia na mesma tela: `/stats` conta o historico INTEIRO (nao tem
    filtro de data nenhum), entao o cabecalho dizia "5 resolvidos, 2 greens"
    enquanto a lista logo abaixo mostrava 2 picks -- escondendo justamente as
    3 que formaram o numero.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not _tabela_existe(cur):
            return {"disponivel": False, "picks": [], "motivo": "motor Live nao rodou neste ambiente"}

        expirados = expirar_vencidos(cur, conn)
        liquidacao = liquidar_pendentes(cur, conn)

        cur.execute("""
            SELECT id, fixture_id, match_date, league_id, league_name,
                   home_team_id, away_team_id, home_team_name, away_team_name,
                   market, market_type, line, line_value, odd, bet_house,
                   minute_at_creation, home_goals_at_creation, away_goals_at_creation,
                   corners_at_creation, shots_at_creation, shots_on_target_at_creation,
                   dangerous_attacks_at_creation, possession_home_at_creation,
                   yellow_cards_at_creation, red_cards_at_creation,
                   observed_at_creation, remaining_minutes,
                   pressure_home, pressure_away, pressure_total,
                   rhythm_score, rhythm_level, rhythm_trend,
                   live_signal_score, data_freshness, projected_total,
                   probability, ev, edge, confidence, stake_units, reasoning,
                   odd_at_creation, odd_timestamp, odd_valid_until, status,
                   expiration_reason, engine_version, result, profit, created_at
            FROM picks_live
            WHERE match_date >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
                                - (%s * INTERVAL '1 day')
            ORDER BY (result IS NOT NULL), created_at DESC
            LIMIT %s
        """, (dias, limit))
        linhas = [dict(r) for r in cur.fetchall()]

        if not incluir_encerrados:
            linhas = [p for p in linhas if p["result"] is None]

        seguidos: dict = {}
        if linhas:
            cur.execute("""
                SELECT pick_id, stake_units, actual_odd, bet_house
                FROM user_followed_picks
                WHERE user_id = %s AND pick_type = 'live' AND pick_id = ANY(%s)
            """, (current_user["id"], [p["id"] for p in linhas]))
            seguidos = {r["pick_id"]: dict(r) for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()

    if linhas:
        _fetch_fixtures_bulk([p["fixture_id"] for p in linhas if p["fixture_id"]])

    agora = _agora_naive()
    saida = []
    for p in linhas:
        item = _enriquecer(p)
        seguido = seguidos.get(p["id"])
        validade = p.get("odd_valid_until")
        item["is_followed"] = seguido is not None
        item["user_stake_units"] = float(seguido["stake_units"]) if seguido else None
        item["user_actual_odd"] = float(seguido["actual_odd"]) if seguido and seguido["actual_odd"] else None
        item["user_bet_house"] = seguido["bet_house"] if seguido else None
        item["segundos_de_validade"] = (
            max(0, int((validade - agora).total_seconds())) if validade else None
        )
        item["pick_type"] = "live"
        saida.append(item)

    # AVISAR QUE O MOTOR ACHOU PICK NOVO (2026-08-27).
    #
    # O produto tem uma janela de minutos: a odd vence, e "abrir o site mais
    # tarde" -- que e' o que o sino resolve pros picks de pre-jogo -- nao
    # existe aqui. Sem aviso, o assinante so' encontra o pick por acaso.
    #
    # O gatilho e' a VISITA, mesmo padrao do resto do backend desde que o
    # agendador foi removido em 01/08: quem abrir a aba primeiro cria o item
    # pra base inteira, e as proximas passadas caem no dedupe por pick_id. Nao
    # ha' laco nem relogio.
    #
    # So' o que esta' DE PE': pick ja' liquidado ou com a odd vencida nao e'
    # oportunidade, e notificar sobre ele seria mandar o assinante correr atras
    # de um preco que nao existe mais.
    try:
        from routers.notifications import notificar_pick_live_novo

        vivos = [p for p in saida
                 if not p.get("result") and p.get("status") == STATUS_ATIVO]
        if vivos:
            notificar_pick_live_novo(vivos)
    except Exception as e:
        # Falha ao notificar nao pode derrubar o feed · o pick esta' na tela de
        # quem ja' esta' olhando, que e' o mais importante.
        logger.warning("[LIVE] Falha ao notificar pick novo: %s", e)

    return {
        "disponivel": True,
        "picks": saida,
        "expirados_agora": expirados,
        "liquidados_agora": liquidacao["liquidados"],
        # ESTADO DO MOTOR, no minimo que o assinante precisa (2026-08-27).
        #
        # "Nenhuma oportunidade ao vivo agora" e' ambiguo e o usuario apontou:
        # ela diz a mesma coisa quando o motor varreu os jogos e nao achou nada
        # (que e' o caso NORMAL, e uma boa noticia sobre o filtro) e quando ele
        # simplesmente nao esta' rodando. As duas leituras pedem reacoes
        # opostas -- esperar, ou parar de esperar.
        #
        # So' `ligado` e `ultima_rodada`. O diagnostico completo (falhas
        # seguidas, motivo da parada, intervalo, dry run, cota) continua sendo
        # de admin, em /watch-status e /diagnostico: o assinante precisa saber
        # SE esta' ligado, nao por que parou.
        "motor": {
            "ligado": bool(_watch_state["ativo"]),
            "ultima_rodada": _watch_state["ultima_rodada"],
        },
    }


#: Quanto tempo uma observação continua descrevendo "agora".
#:
#: O motor roda a cada 8 minutos no mínimo, e uma partida some da varredura
#: quando acaba · sem janela, o painel mostraria o jogo de ontem como se ele
#: ainda estivesse rolando. Uma hora é folgado o bastante pra sobreviver a uma
#: rodada que falhou e curto o bastante pra não inventar jogo em andamento.
_JANELA_EM_LEITURA_MIN = 60


@router.get("/em-leitura")
def em_leitura(current_user: dict = Depends(require_live_reader), limit: int = Query(12, ge=1, le=40)):
    """As partidas que o motor Live LEU na última varredura, com o placar.

    POR QUE ISTO EXISTE (2026-08-28, pedido do usuário)
    ---------------------------------------------------
    A aba Ao Vivo passa a maior parte do tempo mostrando "nenhuma oportunidade
    ao vivo agora", e essa frase é verdadeira e vazia ao mesmo tempo: ela não
    distingue "o motor varreu doze jogos e nenhum pagava" de "não há jogo
    nenhum acontecendo". As duas leituras pedem reações opostas · esperar, ou
    fechar o site. O aviso de motor ligado (28/08) resolveu metade disso; esta
    rota resolve a outra, mostrando O QUE ele está olhando.

    NÃO CUSTA REQUISIÇÃO DE API NENHUMA. A fonte é `live_match_observations`,
    que o próprio motor grava a cada partida processada (ver
    live_pipeline.gravar_observacao) · o número que aparece aqui é literalmente
    o que ele leu, não uma segunda consulta que poderia divergir dele.

    Só entram as partidas com status EM ANDAMENTO na última observação: jogo
    encerrado dentro da janela já não é o que o motor está lendo.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        try:
            cur.execute("""
                WITH ultima AS (
                    SELECT DISTINCT ON (fixture_id)
                           fixture_id, minuto, status,
                           goals_observado, corners_observado,
                           shots_observado, shots_on_target_observado,
                           red_cards_observado, observed_at
                      FROM live_match_observations
                     WHERE observed_at >= NOW() - (%s * INTERVAL '1 minute')
                  ORDER BY fixture_id, observed_at DESC
                )
                SELECT u.fixture_id, u.minuto, u.status,
                       u.goals_observado, u.corners_observado,
                       u.shots_observado, u.shots_on_target_observado,
                       u.red_cards_observado, u.observed_at::text AS lido_em,
                       f.home_team, f.away_team,
                       COALESCE(l.name, 'Liga ' || f.league_id::text) AS liga,
                       -- Se o motor já publicou pick desta partida hoje. É o
                       -- que separa "está olhando" de "já achou": sem isso, um
                       -- jogo com pick vivo apareceria na lista de espera como
                       -- se nada tivesse saído dele.
                       EXISTS (SELECT 1 FROM picks_live p
                                WHERE p.fixture_id = u.fixture_id
                                  AND p.match_date >= (NOW() AT TIME ZONE
                                      'America/Sao_Paulo')::date) AS tem_pick
                  FROM ultima u
             LEFT JOIN fixtures f ON f.fixture_id = u.fixture_id
             LEFT JOIN leagues  l ON l.league_id  = f.league_id
                 WHERE u.status = ANY(%s)
              ORDER BY u.observed_at DESC, u.minuto DESC NULLS LAST
                 LIMIT %s
            """, (_JANELA_EM_LEITURA_MIN, list(LIVE_STATUSES), limit))
            linhas = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            conn.rollback()
            # Banco que nunca rodou o motor Live não tem a tabela · não é
            # defeito, é ambiente. Mesma saída do resto do módulo.
            logger.info("[LIVE] em-leitura indisponivel: %s", str(e)[:200])
            return {"disponivel": False, "partidas": []}
    finally:
        cur.close()
        conn.close()

    return {
        "disponivel": True,
        "janela_min": _JANELA_EM_LEITURA_MIN,
        "total": len(linhas),
        "partidas": linhas,
        # O mesmo estado que o /feed devolve · a tela mostra os dois juntos, e
        # duas chamadas trariam dois retratos de instantes diferentes.
        "motor": {
            "ligado": bool(_watch_state["ativo"]),
            "ultima_rodada": _watch_state["ultima_rodada"],
        },
    }


@router.get("/stats")
def estatisticas(current_user: dict = Depends(require_live_reader)):
    """Performance do Live, SEPARADA da do pre-jogo.

    Nenhuma consulta daqui toca picks_vip, picks_free ou as outras quatro
    tabelas. O numero de performance do site continua descrevendo o mesmo
    conjunto de sempre; este e' um segundo numero, ao lado, com rotulo
    proprio. Juntar os dois e' decisao de produto que ainda nao foi tomada.

    TODO PICK GERADO ENTRA NA CONTA, SEGUIDO OU NAO
    -----------------------------------------------
    A assertividade do motor tem que descrever o motor, e o motor decidiu
    igual nos dois casos. Um pick que ninguem seguiu nao vira "pick que nao
    conta": ele e' gravado na criacao, e' liquidado pelo jogo como qualquer
    outro (`liquidar_pendentes` busca ACTIVE **e** EXPIRED) e entra aqui pelo
    mesmo `result`. Deixar de fora o que nao foi seguido produziria uma taxa
    de acerto medida so' no que o usuario teve tempo de pegar, que e' outra
    coisa -- e sempre mais bonita.

    Por isso `expirados` conta por `expiration_reason`, e nao por `status`: a
    liquidacao troca o status pra SETTLED, entao contar por status fazia o
    numero cair pra zero sozinho ao longo da noite, ao passo que o motivo da
    expiracao fica gravado pra sempre. E' informacao de OPERACAO (quantas
    janelas de odd fecharam antes de alguem pegar), nao de acerto.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not _tabela_existe(cur):
            return {"disponivel": False}
        cur.execute("""
            SELECT
                COUNT(*)                                          AS total_gerados,
                COUNT(*) FILTER (WHERE expiration_reason IS NOT NULL) AS expirados,
                COUNT(*) FILTER (WHERE result IS NOT NULL)        AS resolvidos,
                COUNT(*) FILTER (WHERE result = 'GREEN')          AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')            AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')           AS push,
                COUNT(*) FILTER (WHERE result = 'HALF-WIN')       AS half_wins,
                COUNT(*) FILTER (WHERE result = 'HALF-LOSS')      AS half_losses,
                COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit,
                AVG(ev)         FILTER (WHERE result IS NOT NULL) AS ev_medio,
                AVG(confidence) FILTER (WHERE result IS NOT NULL) AS confianca_media,
                AVG(minute_at_creation)                           AS minuto_medio
            FROM picks_live
        """)
        linha = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT market_type,
                   COUNT(*) FILTER (WHERE result IS NOT NULL) AS resolvidos,
                   COUNT(*) FILTER (WHERE result = 'GREEN')   AS greens,
                   COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
            FROM picks_live
            GROUP BY market_type
            ORDER BY resolvidos DESC
        """)
        por_mercado = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    resolvidos = int(linha.get("resolvidos") or 0)
    greens = int(linha.get("greens") or 0)
    lucro = float(linha.get("profit") or 0)
    return {
        "disponivel": True,
        "escopo": "somente picks_live · nao inclui pre-jogo",
        "base": "todo pick gerado pelo motor, seguido ou nao",
        "total_gerados": int(linha.get("total_gerados") or 0),
        # Quantos tiveram a janela da odd fechada antes de alguem seguir. E'
        # metrica de OPERACAO: eles continuam liquidados e continuam contando
        # no acerto abaixo.
        "expirados": int(linha.get("expirados") or 0),
        "pendentes": max(0, int(linha.get("total_gerados") or 0) - resolvidos),
        "resolvidos": resolvidos,
        "greens": greens,
        "reds": int(linha.get("reds") or 0),
        "push": int(linha.get("push") or 0),
        "half_wins": int(linha.get("half_wins") or 0),
        "half_losses": int(linha.get("half_losses") or 0),
        "win_rate": round(greens / resolvidos * 100, 1) if resolvidos else 0.0,
        "profit": round(lucro, 2),
        # ROI sobre 1 unidade por pick, mesma convencao do resto do site.
        "roi": round(lucro / resolvidos * 100, 1) if resolvidos else 0.0,
        "ev_medio": round(float(linha["ev_medio"]), 4) if linha.get("ev_medio") is not None else None,
        "confianca_media": round(float(linha["confianca_media"]), 4) if linha.get("confianca_media") is not None else None,
        "minuto_medio": round(float(linha["minuto_medio"]), 1) if linha.get("minuto_medio") is not None else None,
        "por_mercado": por_mercado,
    }


@router.get("/{pick_id}/detail")
def detalhe(pick_id: int, current_user: dict = Depends(require_live_reader)):
    """O pick com o rastro completo do motor. Responde literalmente 'o que o
    motor sabia quando criou este pick'."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not _tabela_existe(cur):
            raise HTTPException(404, "Motor Live nao rodou neste ambiente.")
        cur.execute("SELECT * FROM picks_live WHERE id = %s", (pick_id,))
        linha = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not linha:
        raise HTTPException(404, "Pick nao encontrado.")
    return _enriquecer(dict(linha))


# ─────────────────────────────────────────────────────────────────────────
# EXECUCAO MANUAL (ADMIN, DEV)
# ─────────────────────────────────────────────────────────────────────────
_run_status: dict = {"status": "idle", "started_at": None, "finished_at": None,
                     "returncode": None, "log": None, "error": None}


class RunBody(BaseModel):
    fixture_id: int | None = None
    #: None = seguir `LIVE_ENGINE_DRY_RUN`. Ver `_resolver_dry_run`.
    dry_run: bool | None = None
    max_partidas: int | None = None


def _dry_run_do_ambiente() -> bool:
    """`LIVE_ENGINE_DRY_RUN`, com o mesmo default do motor · FALSE desde 28/08.

    O default era TRUE, e era o certo enquanto o Live estava em validacao. Com
    a aba publicada, dry run que nasce ligado quer dizer aba que nunca recebe
    pick -- e ninguem reclama de uma tela que so' diz que nao tem nada.

    O ponto que NAO mudou: a leitura continua sendo a mesma de
    `pick_engine_live/config.py::_flag`, e nao um `== "true"` proprio. As duas
    divergirem seria o painel dizendo uma coisa e o motor fazendo outra -- que
    e' exatamente o bug de 24/08 que este arquivo ja' pagou uma vez.
    """
    return (os.getenv("LIVE_ENGINE_DRY_RUN") or "false").strip().lower() in (
        "1", "true", "on", "yes", "sim")


def _resolver_dry_run(valor: bool | None) -> bool:
    """O dry run que a rodada VAI usar.

    POR QUE O CAMPO PASSOU A ACEITAR None (2026-08-24)
    --------------------------------------------------
    O campo nascia `True` fixo, e o valor era sempre repassado ao pipeline como
    `--dry-run`/`--gravar` -- que SOBRESCREVE a config de ambiente em
    `run_live_engine`. O efeito pratico: `LIVE_ENGINE_DRY_RUN=false` no Railway
    nao ligava a gravacao, porque o corpo da requisicao chegava depois e dizia
    `true`. Trocar a variavel e continuar sem pick, sem mensagem de erro
    nenhuma, e' o pior tipo de falha que este painel pode ter.

    Agora ausente significa "segue o ambiente" e presente significa "eu decidi
    nesta rodada". O valor resolvido continua indo explicito pra linha de
    comando, pra o que o painel mostra e o que o motor faz nunca divergirem.
    """
    return _dry_run_do_ambiente() if valor is None else bool(valor)


def _pipeline_dir() -> str:
    if env := os.getenv("PIPELINE_SRC_PATH"):
        return env
    for candidato in (
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ApostaEsportivas/src")),
        os.path.abspath(os.path.join(os.getcwd(), "ApostaEsportivas/src")),
    ):
        if os.path.isdir(candidato):
            return candidato
    return ""


def _pode_disparar() -> tuple[bool, str]:
    """Quem pode disparar o motor Live neste servico: quem e' admin.

    Havia uma flag propria (`LIVE_ENGINE_ALLOW_RUN`), separada da nocao de
    ambiente por uma razao de seguranca que continua valida e vale registrar:
    `APP_ENV` tambem controla a flag `Secure` do cookie de sessao, entao baixar
    APP_ENV pra "development" so' pra liberar este botao tiraria o `Secure` do
    cookie de autenticacao de todo mundo naquele dominio. A flag existia pra
    ninguem ser tentado a fazer isso.

    Em 2026-08-28 o usuario removeu as variaveis do Live no Railway, e a flag
    perdeu funcao: ela protegia um motor em validacao de rodar onde nao devia, e
    o motor virou produto que PRECISA rodar em producao.

    O que protege agora: a rota inteira ja' exige `require_admin`, e o motor
    nunca roda sozinho -- nao ha' agendador neste projeto desde 01/08.
    """
    return True, ""


def _rodar_em_prod() -> bool:
    """O motor escreve no banco DESTE servico · sempre, desde 2026-08-28.

    Era `LIVE_ENGINE_ALLOW_PROD`, a valvula consciente pro dia em que a promocao
    fosse decidida. O dia chegou: a aba esta' publicada pro assinante, e um
    motor que so' escreve em DEV nao alimenta uma tela de producao.
    """
    return True


def _dev_configurado() -> list[str]:
    """Vazio, SEMPRE · a funcao sobrevive so' pra nao espalhar a remocao.

    Ela listava as variaveis `*_DEV` que faltavam, porque o motor era disparado
    sempre com `DB_ENV=dev` e `utils/db_utils` le com esse sufixo. A regra que a
    justificava continua valida e vale registrar: essas credenciais NAO eram
    fabricadas a partir de `DB_HOST` (mesma decisao de `routers/admin.py::
    _dev_env`), porque `DB_HOST` neste processo aponta pra producao e fabricar
    credencial "de dev" a partir dele criaria o risco real de o motor gravar
    pick na base errada acreditando que e' DEV.

    Em 2026-08-28 o motor passou a gravar no banco deste servico, entao nao ha'
    mais banco de dev pra ter credencial. Exigir as variaveis seria pedir a
    senha de um banco que a rodada nao vai tocar.
    """
    return []


async def _rodar(body: RunBody) -> None:
    agora = _relogio_do_watch
    _run_status.update({"status": "running", "started_at": agora(),
                        "finished_at": None, "returncode": None, "error": None})
    diretorio = _pipeline_dir()
    script = os.path.join(diretorio, "engine_pipelines", "live_pipeline.py")
    argumentos: list[str] = []
    if body.fixture_id:
        argumentos += ["--fixture", str(body.fixture_id)]
    argumentos.append("--dry-run" if _resolver_dry_run(body.dry_run) else "--gravar")
    if body.max_partidas:
        argumentos += ["--max", str(body.max_partidas)]

    try:
        # Onde a rodada escreve: no banco deste servico, e ponto.
        #
        # `DB_ENV` era cravado em "dev" aqui, sempre, pra que o botao do /admin
        # nao virasse o caminho acidental ate' producao. A trava saiu em
        # 2026-08-28 junto com as variaveis do Live no Railway: a aba esta'
        # publicada pro assinante, e um motor que so' escreve em DEV nao
        # alimenta uma tela de producao.
        #
        # Nao ha' mais override nenhum · o subprocesso herda o ambiente de quem
        # o disparou, que e' a mesma regra dos outros seis motores.
        env = {**os.environ, "PYTHONPATH": diretorio}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script, *argumentos,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=diretorio, env=env,
        )
        try:
            saida, erro = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("Rodada Live passou de 3 minutos e foi encerrada.")
        _run_status.update({
            "status": "ok" if proc.returncode == 0 else "error",
            "finished_at": agora(), "returncode": proc.returncode,
            "log": saida.decode(errors="replace")[-6000:],
            "error": erro.decode(errors="replace")[-2000:] if proc.returncode else None,
        })
    except Exception as e:
        _run_status.update({"status": "error", "finished_at": agora(),
                            "returncode": -1, "error": str(e)})


# ─── Acompanhamento contínuo ────────────────────────────────────────────────
#
# POR QUE ISTO EXISTE, DEPOIS DE O SCHEDULER TER SIDO DELETADO
# ------------------------------------------------------------
# Uma rodada sozinha não é o motor ao vivo funcionando. /fixtures/statistics
# devolve só acumulado, então "escanteios nos últimos 10 minutos" não existe no
# feed · existe na diferença entre duas leituras nossas. Na primeira passada
# sobre uma partida o motor não tem janela nem tendência, e não finge ter. São
# a segunda e a terceira que fazem o modelo de ritmo valer alguma coisa.
#
# `engine_pipelines/live_watch.py` já resolvia isso na linha de comando, mas só
# em DEV e só enquanto o terminal ficasse aberto. Este laço é o mesmo conceito
# dentro do serviço, ligado e desligado por quem opera.
#
# A DIFERENÇA PRO SCHEDULER QUE FOI REMOVIDO em 2026-08-01 é inteira:
#
#   · nada sobe ligado. O laço só existe depois de alguém clicar em ligar;
#   · não sobrevive a restart do serviço. Deploy do Railway derruba o laço, e o
#     painel diz isso em vez de fingir que continua rodando;
#   · o intervalo é declarado no clique, não escondido em código;
#   · o contador de rodadas fica na cara de quem ligou.
#
# O que ele NÃO faz é desligar sozinho por tempo · foi pedido explicitamente
# que só pare quando mandarem parar. O único freio automático é o disjuntor de
# falhas consecutivas abaixo, que não é "cansou": é o motor quebrado parando de
# bater na API-Football de graça, com o motivo escrito no painel.

#: Falhas seguidas que derrubam o laço. Uma rodada que erra por rede volta na
#: seguinte; cinco seguidas é problema que dormir mais não conserta.
_MAX_FALHAS_SEGUIDAS = 5

#: Piso do intervalo. Abaixo disso a rodada seguinte começa antes de a
#: estatística da anterior ter mudado no provedor · gasta cota pra reler o
#: mesmo número.
_INTERVALO_MIN_MINUTOS = 3

#: Identidade DESTE processo. Se a linha no banco tem outro dono, o laco que a
#: escreveu morreu junto com o processo anterior · e' o que separa "o servico
#: reiniciou" de "alguem desligou no painel".
_BOOT_ID = uuid.uuid4().hex

#: Religar sozinho depois de um restart. DESLIGADO por padrao, e o padrao e' a
#: decisao: "nada sobe ligado" foi o que se estabeleceu quando o scheduler foi
#: removido, em 2026-08-01, depois de a cota da API estourar. Ligar isto e' um
#: pedido explicito de quem opera, feito numa variavel do Railway, nao um
#: efeito colateral de um deploy.
def _rearmar_apos_restart() -> bool:
    return os.getenv("LIVE_WATCH_REARM", "").strip().lower() in ("1", "true", "on", "yes", "sim")


def _salvar_watch(motivo: str | None = None) -> None:
    """Grava o estado do laco. Falhar aqui NAO pode derrubar a rodada.

    A tabela pode nao existir ainda -- `run_migrations()` nao roda sozinha
    depois de um merge (ver o historico de `engine_debug` em 2026-07-23). Sem
    ela o painel volta a se comportar como antes, que e' ruim mas conhecido;
    estourar no meio de uma rodada seria pior.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO live_watch_state
                    (id, ativo, boot_id, iniciado_em, ultimo_sinal, rodadas,
                     intervalo_min, dry_run, max_partidas, motivo_parada)
                VALUES (1, %s, %s, NOW(), NOW(), %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    ativo         = EXCLUDED.ativo,
                    boot_id       = EXCLUDED.boot_id,
                    ultimo_sinal  = NOW(),
                    rodadas       = EXCLUDED.rodadas,
                    intervalo_min = EXCLUDED.intervalo_min,
                    dry_run       = EXCLUDED.dry_run,
                    max_partidas  = EXCLUDED.max_partidas,
                    motivo_parada = EXCLUDED.motivo_parada
            """, (bool(_watch_state["ativo"]), _BOOT_ID, _watch_state["rodadas"],
                  _watch_state["intervalo_min"], _watch_state["dry_run"],
                  _watch_state["max_partidas"],
                  motivo if motivo is not None else _watch_state["motivo_parada"]))
            conn.commit()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        logger.warning("[LIVE-WATCH] nao consegui gravar o estado: %s", e)


def reconciliar_watch_no_boot() -> dict | None:
    """Chamado uma vez na subida do servico. Devolve o que achou, ou None.

    Se a linha diz `ativo` e o dono e' OUTRO processo, o laco morreu com ele.
    Nao ha o que "recuperar" -- ha o que CONTAR: quantas rodadas deu, quando
    foi o ultimo sinal, e que a queda foi restart e nao decisao.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM live_watch_state WHERE id = 1")
            linha = cur.fetchone()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        logger.info("[LIVE-WATCH] sem estado persistido (%s)", e)
        return None

    if not linha or not linha["ativo"] or linha["boot_id"] == _BOOT_ID:
        return None

    quando = linha["ultimo_sinal"].strftime("%d/%m %H:%M") if linha["ultimo_sinal"] else "?"
    motivo = (f"o servico reiniciou · estava rodando ate' {quando}, "
              f"{linha['rodadas']} rodada(s)")
    _watch_state.update({
        "ativo": False, "rodadas": linha["rodadas"] or 0,
        "intervalo_min": linha["intervalo_min"], "dry_run": linha["dry_run"],
        "max_partidas": linha["max_partidas"], "motivo_parada": motivo,
    })
    _salvar_watch(motivo)
    logger.warning("[LIVE-WATCH] %s", motivo)
    return dict(linha)


#: O relógio do Motor Live · ISO COM DATA e no fuso de Brasília.
#:
#: Era `strftime("%H:%M:%S")` em UTC, e as duas escolhas erravam de formas que
#: se escondiam:
#:
#:   · sem data, `horaCurta` no front (que fatia [11:16], como todo horário
#:     deste projeto) lia string vazia · a aba Ao Vivo mostrava literalmente
#:     "Última varredura às ." pro assinante;
#:   · em UTC, o painel do admin exibia a string crua e o horário aparecia três
#:     horas adiantado, sem nada na tela dizendo que era outro fuso.
#:
#: Gravado JÁ em Brasília de propósito: assim a fatia continua sendo a leitura
#: certa e ninguém precisa converter fuso no cliente, que é a regra do projeto
#: pra todo horário exibido.
def _relogio_do_watch() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds")


_watch_state: dict = {
    "ativo": False, "iniciado_em": None, "rodadas": 0, "falhas_seguidas": 0,
    "ultima_rodada": None, "proxima_rodada_em": None, "motivo_parada": None,
    "intervalo_min": None, "dry_run": None, "max_partidas": None,
}

#: Referência forte pra tarefa. Sem isto o event loop pode coletar o laço no
#: meio de uma espera (asyncio guarda só weakrefs das tasks).
_watch_task: asyncio.Task | None = None


class WatchBody(BaseModel):
    ligar: bool = True
    intervalo_min: int = 8
    #: None = seguir `LIVE_ENGINE_DRY_RUN`. Ver `_resolver_dry_run`.
    dry_run: bool | None = None
    max_partidas: int | None = None


async def _laco_de_acompanhamento(intervalo_min: int, dry_run: bool,
                                  max_partidas: int | None) -> None:
    """Roda rodadas sucessivas até alguém desligar."""
    intervalo = max(_INTERVALO_MIN_MINUTOS, int(intervalo_min)) * 60
    body = RunBody(dry_run=dry_run, max_partidas=max_partidas)
    agora = _relogio_do_watch

    try:
        while _watch_state["ativo"]:
            await _rodar(body)
            _watch_state["rodadas"] += 1
            _watch_state["ultima_rodada"] = agora()
            # Sinal de vida. E' o que permite dizer DEPOIS "estava rodando ate'
            # as 14:32" em vez de "desligado, sem motivo".
            _salvar_watch()

            if _run_status.get("status") == "error":
                _watch_state["falhas_seguidas"] += 1
                if _watch_state["falhas_seguidas"] >= _MAX_FALHAS_SEGUIDAS:
                    _watch_state["motivo_parada"] = (
                        f"{_MAX_FALHAS_SEGUIDAS} rodadas seguidas falharam · "
                        f"último erro: {(_run_status.get('error') or '')[:200]}"
                    )
                    break
            else:
                _watch_state["falhas_seguidas"] = 0

            # Espera fatiada: desligar não precisa esperar o intervalo inteiro.
            restante = intervalo
            while restante > 0 and _watch_state["ativo"]:
                _watch_state["proxima_rodada_em"] = restante
                await asyncio.sleep(min(5, restante))
                restante -= 5
            _watch_state["proxima_rodada_em"] = 0
    except asyncio.CancelledError:
        _watch_state["motivo_parada"] = "laço cancelado"
        raise
    except Exception as e:
        _watch_state["motivo_parada"] = f"erro inesperado no laço: {e}"
        logger.exception("[LIVE-WATCH] laço morreu")
    finally:
        _watch_state["ativo"] = False
        _watch_state["proxima_rodada_em"] = None
        # Grava o fim COM o motivo. Morte dentro do processo sempre deixa
        # bilhete · so' o restart nao deixava, e e' o que a linha do banco
        # passa a cobrir.
        _salvar_watch()
        logger.info("[LIVE-WATCH] encerrado após %s rodadas (%s)",
                    _watch_state["rodadas"], _watch_state["motivo_parada"] or "desligado no painel")


@router.post("/watch")
async def acompanhar_continuo(body: WatchBody, current_user: dict = Depends(require_admin)):
    """Liga/desliga o laço de rodadas sucessivas do Motor Live."""
    global _watch_task

    if not body.ligar:
        _watch_state["ativo"] = False
        _watch_state["motivo_parada"] = "desligado no painel"
        _salvar_watch()
        return {"ok": True, "ativo": False}

    if not _pipeline_dir():
        raise HTTPException(500, "Diretorio do motor nao encontrado (PIPELINE_SRC_PATH).")
    if _watch_state["ativo"]:
        raise HTTPException(409, "O acompanhamento continuo ja esta ligado.")

    # Resolvido UMA vez, no clique: o laco pode durar horas, e reler a variavel
    # a cada rodada faria um deploy no meio da noite trocar o comportamento sem
    # ninguem ter pedido.
    dry_run = _resolver_dry_run(body.dry_run)
    _watch_state.update({
        "ativo": True,
        "iniciado_em": _relogio_do_watch(),
        "rodadas": 0, "falhas_seguidas": 0, "motivo_parada": None,
        "ultima_rodada": None, "proxima_rodada_em": None,
        "intervalo_min": max(_INTERVALO_MIN_MINUTOS, int(body.intervalo_min)),
        "dry_run": dry_run, "max_partidas": body.max_partidas,
    })
    _salvar_watch()
    _watch_task = asyncio.create_task(_laco_de_acompanhamento(
        body.intervalo_min, dry_run, body.max_partidas))
    return {"ok": True, "ativo": True, "dry_run": dry_run,
            "intervalo_min": _watch_state["intervalo_min"]}


@router.get("/watch-status")
def status_do_acompanhamento(current_user: dict = Depends(require_admin)):
    return dict(_watch_state)


@router.post("/run")
async def rodar_motor(body: RunBody, current_user: dict = Depends(require_admin)):
    """Dispara UMA rodada do Motor Live. Admin, e so' onde for autorizado.

    Nao existe laco, nao existe agendamento. E' o botao que a V1 tem no lugar
    de um scheduler, de proposito -- o consumo real precisa ser medido rodada
    a rodada antes de qualquer automacao.
    """
    if _run_status["status"] == "running":
        raise HTTPException(409, "Ja existe uma rodada em andamento.")
    if _watch_state["ativo"]:
        raise HTTPException(409, (
            "O acompanhamento continuo esta ligado e ja dispara rodadas sozinho. "
            "Desligue antes de disparar uma rodada avulsa."
        ))
    if not _pipeline_dir():
        raise HTTPException(500, "Diretorio do motor nao encontrado (PIPELINE_SRC_PATH).")
    asyncio.create_task(_rodar(body))
    return {"ok": True, "iniciado": True, "dry_run": _resolver_dry_run(body.dry_run)}


@router.get("/run-status")
def status_da_rodada(current_user: dict = Depends(require_admin)):
    return dict(_run_status)


@router.get("/diagnostico")
def diagnostico(current_user: dict = Depends(require_admin)):
    """O que falta pra ESTE servico conseguir rodar o motor Live.

    Eram seis pre-condicoes independentes; sobraram quatro depois que as
    variaveis do Live sairam do Railway em 28/08. As que restam sao as que de
    fato podem faltar num deploy, e descobrir qual falhou sem isto exigiria ler
    log de subprocesso num ambiente remoto -- mais caro que a propria rodada.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        tabela = _tabela_existe(cur)
    finally:
        cur.close()
        conn.close()

    # O motor nasce LIGADO desde 28/08 (ver pick_engine_live/config): a variavel
    # so' serve pra DESLIGAR num ambiente especifico.
    ligado = os.getenv("LIVE_ENGINE_ENABLED", "on").strip().lower() not in (
        "0", "off", "false", "no", "nao")
    em_prod = _rodar_em_prod()

    # A LISTA ENCOLHEU EM 2026-08-28, junto com as variaveis do Railway.
    #
    # Sairam "disponivel pro assinante" (a rota nao gateia mais, so' exige VIP),
    # "credenciais _DEV" (o motor nao roda mais em DEV) e "disparo autorizado"
    # (a rota ja' exige admin). Checagem que nao pode falhar nao e' diagnostico,
    # e' ruido -- e ruido em painel de diagnostico ensina a ignorar o painel.
    #
    # Sobrou o que de fato pode faltar num deploy.
    checagens = [
        {"item": "motor habilitado", "ok": ligado,
         "detalhe": "ligado (padrao)" if ligado
                    else "LIVE_ENGINE_ENABLED desligado neste ambiente"},
        {"item": "codigo do motor", "ok": bool(_pipeline_dir()),
         "detalhe": _pipeline_dir() or "PIPELINE_SRC_PATH nao resolve"},
        {"item": "chave da API-Football", "ok": bool(os.getenv("API_FOOTBALL_KEY")),
         "detalhe": "configurada" if os.getenv("API_FOOTBALL_KEY") else "API_FOOTBALL_KEY ausente"},
        {"item": "tabela picks_live no banco que o site le", "ok": tabela,
         "detalhe": "existe" if tabela else
                    "ausente -- o motor cria na primeira rodada"},
    ]

    return {
        "pronto": all(c["ok"] for c in checagens),
        "checagens": checagens,
        # Constante desde 28/08 · o campo fica porque o painel o exibe, e
        # "some da tela" seria pior sinal que "diz sempre sim".
        "publico": True,
        "dry_run_padrao": os.getenv("LIVE_ENGINE_DRY_RUN", "false"),
        # O MESMO texto ja' interpretado. O painel precisa do booleano, e nao
        # do texto cru: "off", "0" e "nao" sao valores validos que uma leitura
        # ingenua no frontend (`=== 'false'`) entenderia ao contrario -- que e'
        # exatamente a divergencia que este campo existe pra fechar.
        "dry_run_padrao_ativo": _dry_run_do_ambiente(),
        # Onde o pick vai parar · e' a informacao que decide se a rodada e'
        # teste ou producao, e ela nao pode ficar implicita num painel.
        "grava_em": "produção" if em_prod else "desenvolvimento",
    }


@router.post("/settle")
def liquidar_agora(current_user: dict = Depends(require_admin)):
    """Forca expiracao e liquidacao sem esperar alguem abrir a aba."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not _tabela_existe(cur):
            return {"disponivel": False}
        expirados = expirar_vencidos(cur, conn)
        resumo = liquidar_pendentes(cur, conn, limite=100)
    finally:
        cur.close()
        conn.close()
    return {"disponivel": True, "expirados": expirados, **resumo}
