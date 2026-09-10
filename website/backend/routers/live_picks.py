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
import time
import os
import uuid
import sys
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from auth_utils import get_current_user, is_vip_active, require_admin, require_vip
from database import get_connection
from settlement_bridge import settlement

# Reuso da camada de dado ao vivo. Os nomes com underscore sao privados por
# convencao dentro daquele modulo, mas sao exatamente a fronteira que este
# produto precisa -- a alternativa seria duplicar a leitura da API-Football.
from routers.live import (  # noqa: F401
    FT_STATUSES, LIVE_STATUSES, _anulacao_sem_estatistica, _calc_result,
    _motivo_da_anulacao, _save_live_pick_result,
    _fetch_fixture, _fetch_fixtures_bulk, _fetch_stats, _leg_needs_stats,
    _parse_stats, _pick_status, _profit_for_result, _stat_for_market,
    _sync_followed_result, _travado_antes_do_apito,
    _fetch_live_odds_mundo, _find_live_odd,
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

    POR QUE ESTAVA "TUDO PENDENTE" (2026-08-29)
    -------------------------------------------
    Faltavam as duas metades da mesma coisa.

    a) NAO HAVIA SAIDA PRA QUEM NUNCA VAI RESOLVER. `_calc_result` devolve None
       quando o provedor nao publica a folha do jogo -- e isso e' correto, sem
       o numero inventar resultado e' pior que nao ter. Mas aqui o codigo so'
       fazia `continue`, e o pick ficava Pendente pra sempre. O pre-jogo ja
       tinha a rede: `_anulacao_sem_estatistica` (routers/live.py) anula como
       PUSH depois de 12h, com motivo nomeado, so' nas duas causas que sabemos
       ser definitivas. O Live nao a chamava. E o Live e' o produto que MAIS
       depende de folha: escanteios, chutes e faltas sao quase todo o cardapio
       dele.

    b) A FILA TRAVAVA. Sao 30 por passada, `ORDER BY created_at` -- do mais
       velho pro mais novo. Como os irresolviveis do item (a) nunca saiam da
       fila, bastava acumular 30 deles pra que NENHUM pick novo chegasse a ser
       tentado. Dai o sintoma que o usuario viu: tudo pendente, inclusive jogos
       que acabaram ha' horas e tinham resultado obvio.

    A ordem virou DESC pelo mesmo motivo: cada pendente custa de uma a duas
    chamadas a' API-Football, entao a passada tem que gastar o orcamento no
    jogo que acabou agora -- que e' o que a pessoa esta olhando na tela -- e
    nao num pick de tres dias atras. Com a anulacao do item (a) a cauda velha
    se esvazia sozinha em vez de crescer.
    """
    resumo = {"liquidados": 0, "erros": 0}
    try:
        cur.execute("""
            SELECT id, fixture_id, market, market_type, line, odd,
                   home_team_name, away_team_name, home_team_id, away_team_id
            FROM picks_live
            WHERE result IS NULL
              AND status IN (%s, %s)
            ORDER BY created_at DESC
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
            # JOGO EM ANDAMENTO TAMBEM LIQUIDA, quando nao ha mais o que
            # esperar (29/08, caso relatado pelo usuario).
            #
            # A regra era "so' em FT", e ela deixava na tela um pick de Mais de
            # 11 escanteios com 12 escanteios em campo, aos 75', marcado como
            # Pendente e com a faixa de "odd vencida" -- ou seja, um GREEN
            # matematicamente fechado sendo mostrado como indefinido por mais
            # de quinze minutos. Escanteio nao volta.
            #
            # Quem decide isso e' `_travado_antes_do_apito`, que e' o mesmo
            # early-lock do ticker de Minhas Apostas (routers/live.py), com as
            # mesmas cautelas: linha de quarto so' trava quando o resultado
            # final nao pode virar meia-vitoria, e Under so' trava pra RED.
            # Nao ha' regra nova aqui, ha' uma regra que o Live nao usava.
            if status not in FT_STATUSES and status not in LIVE_STATUSES:
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

            if status in FT_STATUSES:
                resultado = _calc_result(
                    p["market"], p["line"], valor, home_goals, away_goals,
                    market_type=p["market_type"],
                    home_team=p["home_team_name"], away_team=p["away_team_name"],
                    home_stats=home_stats, away_stats=away_stats,
                    went_to_extra_time=prorrogacao,
                )
            else:
                # Com a bola rolando so' existe UMA saida: resultado travado.
                # Nada de anulacao por falta de estatistica aqui -- o jogo nao
                # acabou, entao "o provedor nao publicou" ainda pode virar
                # "publicou", e anular agora seria desistir cedo.
                resultado = _travado_antes_do_apito(
                    p["market"], p["line"], valor, p["market_type"])
                if not resultado:
                    continue
            if not resultado:
                # MESMA rede do pre-jogo, e nao uma regra propria do Live: PUSH
                # depois de 12h do apito, so' quando a causa e' nomeavel (folha
                # que o provedor nao publicou, ou prorrogacao sem o recorte de
                # 90). Qualquer outro pick que nao resolveu continua Pendente e
                # visivel de proposito · isso e' bug pra investigar, nao pick
                # pra anular em silencio. Ver _anulacao_sem_estatistica.
                resultado = _anulacao_sem_estatistica({
                    "status": status,
                    "precisa_stats": _leg_needs_stats(p["market"], p["market_type"]),
                    "current_val": valor,
                    "went_to_extra_time": prorrogacao,
                    "kickoff_ts": fixture.get("timestamp"),
                    "fixture_id": p["fixture_id"],
                    "market": p["market"],
                    "line": p["line"],
                })
            if not resultado:
                continue

            odd = float(p["odd"] or 1)
            profit = _profit_for_result(resultado, odd)
            # O QUE DECIDIU, GRAVADO JUNTO (06/09). Este UPDATE era o unico
            # caminho de liquidacao do projeto que nao gravava
            # `settled_value`/`void_reason` -- as duas colunas que todos os
            # outros produtos escrevem por `_colunas_de_auditoria`.
            #
            # No Ao Vivo a falta doia mais que em qualquer outro lugar: o card
            # ao vivo nao mostra o campo "Deu" (decisao de 04/09) e mostra o
            # contador de AGORA, relido da API. Sem o valor gravado, um PUSH
            # por empate com a linha aparecia como "Menos de 9.0", barra em 4 e
            # selo PUSH, sem nada na tela capaz de explicar -- nem pro usuario,
            # nem pra quem fosse investigar.
            _save_live_pick_result(p["id"], resultado, odd, conn,
                                   valor=valor, motivo=_motivo_da_anulacao())
            # QUEM SEGUIU PRECISA SER AVISADO (2026-08-29). Vem de graca
            # junto do `_save_live_pick_result` acima: ele passa por
            # `_sync_followed_result`, que e' o PONTO UNICO por onde todo
            # resultado do site alimenta o sino. Aqui havia um UPDATE cru em
            # `user_followed_picks` que pulava esse ponto, e o dinheiro mudava
            # na banca do assinante sem nenhum aviso -- pior no Ao Vivo que em
            # qualquer outro produto, porque o pick nasce e morre dentro de uma
            # partida e ninguem esta com a aba aberta esperando o apito.
            resumo["liquidados"] += 1
            logger.info("[LIVE-PICKS] #%s -> %s (%+.4fu)", p["id"], resultado, profit)
        except Exception as e:
            conn.rollback()
            resumo["erros"] += 1
            logger.error("[LIVE-PICKS] liquidacao do #%s falhou: %s", p["id"], e)

    return resumo


#: Coluna de `match_statistics` que responde cada familia de mercado do Live.
#:
#: O TOTAL DA PARTIDA, os dois times somados · e' assim que a casa liquida e e'
#: assim que o settlement do projeto conta. Cartao sai em PONTOS (amarelo=1,
#: vermelho=2), a mesma unidade do mercado no resto do sistema.
_COLUNA_DA_FOLHA = {
    "corners": "COALESCE(ms.total_corners, ms.home_corners + ms.away_corners)",
    "goals":   "COALESCE(ms.total_goals, ms.home_goals + ms.away_goals)",
    # SEM COALESCE(x, 0) DE PROPOSITO (2026-09-02). Vermelho e' o campo de
    # menor cobertura da folha -- ja' esteve em 68,7%, e o `or 0` nele e' o
    # mesmo erro que o stats_model fechou com `_tem_folha_de_cartao_completa`:
    # ausencia virando zero SUBESTIMA os pontos, e aqui isso liquidaria um
    # "Under cartoes" como GREEN num jogo que teve expulsao nao registrada.
    #
    # Com a soma crua, folha sem vermelho devolve NULL e o pick NAO liquida --
    # fica pendente ate' a folha completar, que e' o comportamento certo: pick
    # sem estatistica vira PUSH pelo caminho proprio, nao GREEN por engano.
    #
    # Hoje nao ha' pick ao vivo de cartao (so' escanteio e gol) e a cobertura de
    # vermelho esta' em 100% nos FT -- isto e' pra quando o mercado ligar.
    "cards":   "(ms.total_yellow_cards + 2 * ms.total_red_cards)",
}


def reconferir_liquidados(cur, conn, dias: int = 7) -> dict:
    """Corrige pick ao vivo cujo resultado nao bate com a folha final.

    POR QUE ISTO EXISTE (2026-08-30, apontado pelo usuario)
    -------------------------------------------------------
    A liquidacao acontece uma vez, com o numero que a API tem NAQUELE momento,
    e nunca era revista. Sao dois jeitos de errar, os dois medidos em producao:

      #40  Over 16 escanteios, liquidado 20:51 como PUSH. A folha final chegou
           as 00:26 com 17 escanteios · era GREEN, e ficou PUSH.

      #27  Under 3.0 gols, liquidado 15:25 como RED. A folha final tem 3 gols
           exatos · era PUSH, e ficou RED. O pick #14, o mesmo mercado e a
           mesma linha, saiu PUSH corretamente no mesmo minuto -- a diferenca
           nao estava na regra, estava em QUANDO cada um foi lido.

    O provedor completa e corrige folha por horas depois do apito. Quem liquida
    durante esse periodo esta lendo um numero provisorio, e nao ha como saber
    disso na hora: um total incompleto e' indistinguivel de um total baixo.

    A FOLHA FINAL E' A FONTE, e nao a API: `match_statistics` e' de onde o site
    inteiro conta resultado (a pagina publica, o placar dos produtos, a
    Auditoria). Se o pick do Live discorda dela, e' o pick que esta errado --
    ele e' o unico numero do sistema que vinha de outro lugar.

    NAO CUSTA REQUISICAO NENHUMA: le a folha que a coleta ja gravou.

    So' mexe onde ha folha COMPLETA (status FT/AET/PEN e o contador presente).
    Folha ausente nao desfaz liquidacao: seria trocar um resultado por um
    palpite, que e' pior que o resultado errado.
    """
    resumo = {"conferidos": 0, "corrigidos": 0, "correcoes": []}
    for familia, coluna in _COLUNA_DA_FOLHA.items():
        try:
            cur.execute(f"""
                SELECT pl.id, pl.market, pl.market_type, pl.line, pl.odd, pl.result,
                       {coluna} AS observado,
                       ms.home_goals, ms.away_goals,
                       pl.home_team_name, pl.away_team_name
                  FROM picks_live pl
                  JOIN match_statistics ms ON ms.fixture_id = pl.fixture_id
                 WHERE pl.result IS NOT NULL
                   AND pl.market_type = %s
                   AND ms.status IN ('FT','AET','PEN')
                   AND {coluna} IS NOT NULL
                   AND pl.match_date >= CURRENT_DATE - %s
            """, (familia, dias))
            linhas = cur.fetchall()
        except Exception as e:
            conn.rollback()
            logger.warning("[LIVE-RECONF] %s: %s", familia, str(e)[:200])
            continue

        for linha in linhas:
            resumo["conferidos"] += 1
            # `_calc_result` E NAO `_travado_antes_do_apito`, e a diferenca
            # custou uma correcao errada antes de eu perceber.
            #
            # As duas funcoes respondem perguntas diferentes. O early-lock vale
            # com a BOLA ROLANDO: la, um Under 3.0 com 3 gols e' RED, porque o
            # total so' cresce e 3 vira 4 a qualquer momento. Depois do apito o
            # mesmo 3 e' PUSH -- empatou com a linha, aposta devolvida.
            #
            # Aqui o jogo acabou. Quem manda e' a regra de liquidacao, a mesma
            # de services/settlement.py que grada os outros oito produtos.
            correto = _calc_result(
                linha["market"], linha["line"], linha["observado"],
                int(linha["home_goals"] or 0), int(linha["away_goals"] or 0),
                market_type=linha["market_type"],
                home_team=linha["home_team_name"], away_team=linha["away_team_name"],
            )
            if not correto or correto == linha["result"]:
                continue

            odd = float(linha["odd"] or 1)
            profit = _profit_for_result(correto, odd)
            cur.execute("""
                UPDATE picks_live
                   SET result = %s, profit = %s, settled_at = NOW()
                 WHERE id = %s
            """, (correto, profit, linha["id"]))
            # Quem seguiu tem que ver a correcao no saldo E no sino · e' o
            # mesmo ponto unico da liquidacao normal.
            _sync_followed_result(linha["id"], "live", correto, cur)
            conn.commit()
            resumo["corrigidos"] += 1
            resumo["correcoes"].append({
                "id": linha["id"],
                "jogo": f"{linha['home_team_name']} x {linha['away_team_name']}",
                "linha": linha["line"], "observado": linha["observado"],
                "de": linha["result"], "para": correto,
            })
            logger.info("[LIVE-RECONF] #%s %s: %s -> %s (folha=%s)",
                        linha["id"], linha["line"], linha["result"], correto,
                        linha["observado"])
    return resumo


# ─────────────────────────────────────────────────────────────────────────
# LEITURA
# ─────────────────────────────────────────────────────────────────────────
def _sem_enriquecer(pick: dict) -> dict:
    """O pick como esta gravado, sem tocar na API.

    Mesmas CHAVES que `_enriquecer` devolve, porque quem consome e o mesmo card
    -- faltar chave aqui quebraria a tela em vez de mostra-la mais simples.

    O que muda e a origem: em vez do estado de agora, o snapshot do instante da
    criacao. `is_live` sai False de proposito, e e' isso que faz o card se
    desenhar como leitura registrada em vez de fingir acompanhamento em tempo
    real de uma partida que ninguem esta olhando.
    """
    home = pick.get("home_goals_at_creation")
    away = pick.get("away_goals_at_creation")
    return {
        **pick,
        "live_status": None,
        "elapsed": pick.get("minute_at_creation"),
        "home_goals": home,
        "away_goals": away,
        # O contador do mercado no instante da decisao. Nao e' o total de agora
        # e a tela nao promete que seja: sem motor em campo, o "agora" nao esta
        # sendo lido por ninguem.
        "current_val": pick.get("observed_at_creation"),
        "stat_label": None,
        "direction": None,
        "is_live": False,
        "is_ft": pick.get("result") is not None,
        "pick_status": "neutral",
    }


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
    current_user: dict = Depends(get_current_user),
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
        # A reconferencia anda junto da liquidacao, no mesmo gatilho de visita:
        # e' a mesma pergunta ("este pick esta com o resultado certo?") feita
        # sobre quem ja foi liquidado. Custo zero de API, e sem ela a correcao
        # dependeria de alguem clicar em algum lugar -- que e' como o defeito
        # ficou de pe.
        reconferir_liquidados(cur, conn)

        # PICK QUE A PESSOA PEGOU NÃO SAI DA LISTA ANTES DO APITO (2026-08-29,
        # pedido do usuário).
        #
        # A lista era só uma janela: `match_date >= hoje - N dias` cortado por
        # `LIMIT`. Isso descreve bem "o que está acontecendo agora", que é a
        # pergunta da aba · mas é a regra errada pra quem JÁ APOSTOU. Numa noite
        # movimentada, o pick seguido às 21h era empurrado pra fora do LIMIT
        # pelos que nasceram depois, e um jogo que virava o dia (criado 23h50,
        # apito 00:40) caía fora da janela de data no meio da partida. Nos dois
        # casos a aposta sumia da tela com o jogo rolando, que é justamente
        # quando ela precisa ser acompanhada.
        #
        # O UNION garante o piso: tudo que este usuário segue e ainda não foi
        # liquidado volta, custe o que custar à janela. Sai sozinho quando o
        # `liquidar_pendentes` acima grava o resultado · e ele só grava com o
        # jogo em FT, então "até acabar a partida" é literal.
        cur.execute("""
            WITH escopo AS (
                SELECT id FROM picks_live
                WHERE match_date >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
                                    - (%s * INTERVAL '1 day')
                ORDER BY (result IS NOT NULL), created_at DESC
                LIMIT %s
            ),
            seguidos_vivos AS (
                SELECT pl.id
                FROM picks_live pl
                JOIN user_followed_picks uf
                  ON uf.pick_id = pl.id AND uf.pick_type = 'live'
                WHERE uf.user_id = %s AND pl.result IS NULL
            )
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
                   expiration_reason, engine_version, result, profit, created_at,
                   -- O QUE DECIDIU O RESULTADO (06/09). As duas colunas ja'
                   -- existiam (migrations.py, 02/09: "com os dois na tela, a
                   -- conferencia deixa de depender de nos") e o feed do Ao Vivo
                   -- nao as mandava, entao o card nao tinha como distinguir
                   -- "empatou com a linha" de "anulamos porque o provedor nao
                   -- publicou": os dois chegavam como o mesmo PUSH, +0.00u.
                   settled_value, void_reason
            FROM picks_live
            WHERE id IN (SELECT id FROM escopo UNION SELECT id FROM seguidos_vivos)
            ORDER BY (result IS NOT NULL), created_at DESC
        """, (dias, limit, current_user["id"]))
        linhas = [dict(r) for r in cur.fetchall()]

        if not incluir_encerrados:
            linhas = [p for p in linhas if p["result"] is None]

        seguidos: dict = {}
        banca = None
        if linhas:
            cur.execute("""
                SELECT pick_id, stake_units, actual_odd, bet_house
                FROM user_followed_picks
                WHERE user_id = %s AND pick_type = 'live' AND pick_id = ANY(%s)
            """, (current_user["id"], [p["id"] for p in linhas]))
            seguidos = {r["pick_id"]: dict(r) for r in cur.fetchall()}

            # A UNIDADE SUGERIDA VEM DA BANCA DE QUEM ESTA LENDO (29/08).
            #
            # O site ja' fazia essa conta, mas do lado dele: LivePicksFeed.tsx
            # roda o mesmo Kelly do card VIP em cima da banca carregada na
            # tela. O APP nao tem Kelly nenhum de proposito -- justamente pra
            # nao existir uma segunda implementacao da mesma conta -- entao o
            # card ao vivo dele nao sabia dizer quanto apostar.
            #
            # E' o mesmo buraco que /suggestions/today ja' fechou pra faltas,
            # jogadores e Pick Boost em 28/08, e a correcao e' a mesma funcao.
            from routers.suggestions import _compute_suggested_stake_units, _get_user_banca
            banca = _get_user_banca(cur, current_user["id"])
    finally:
        cur.close()
        conn.close()

    # SEM MOTOR EM CAMPO, A PAGINA NAO PERGUNTA NADA A API (2026-08-30, pedido
    # do usuario).
    #
    # `_enriquecer` traz o ESTADO ATUAL de cada partida, e ele custa requisicao
    # -- e' o que faz o card mostrar o placar de agora e a barra da linha se
    # mexer. Isso vale com jogo rolando. Fora disso e' pagar pra confirmar que
    # nada mudou: o motor hibernando ja disse que nao ha partida em campo, e
    # todo pick na tela ou ja liquidou ou espera um jogo que ainda nao comecou.
    #
    # A tela nao fica vazia: o pick continua com o snapshot da criacao, que e'
    # justamente o que o motor viu quando decidiu -- o mesmo dado que a aba
    # mostra quando a partida acabou.
    #
    # PICKS JA LIQUIDADOS NAO CONSULTAM A API (2026-09).
    #
    # `result IS NOT NULL` significa jogo encerrado: o placar e as stats sao
    # definitivos e estao no banco. Chamar `_enriquecer` sobre eles custava
    # uma req de fixture + uma de stats por pick liquidado a cada poll -- e
    # picks liquidados ficam na lista o dia inteiro. Com 10 picks encerrados
    # e poll de 30s, isso era ~60 req/hora gratuitas de informacao que ja
    # esta gravada. `_sem_enriquecer` devolve o snapshot da criacao, que e'
    # o dado correto pra um pick que ja foi resolvido.
    ao_vivo = _watch_state["ativo"] and not _watch_state.get("hibernando")
    # Bulk so' para os picks SEM resultado que precisam de estado atual.
    if linhas and ao_vivo:
        _fetch_fixtures_bulk([
            p["fixture_id"] for p in linhas
            if p["fixture_id"] and p.get("result") is None
        ])

    agora = _agora_naive()
    saida = []
    for p in linhas:
        # Pick liquidado: dado definitivo no banco, nao precisa de API.
        pick_ativo = p.get("result") is None
        item = _enriquecer(p) if (ao_vivo and pick_ativo) else _sem_enriquecer(p)
        seguido = seguidos.get(p["id"])
        validade = p.get("odd_valid_until")
        item["is_followed"] = seguido is not None
        item["user_stake_units"] = float(seguido["stake_units"]) if seguido else None
        # So' pra quem ainda nao apostou · quem apostou tem o numero dele, e
        # sugerir outro por cima seria discutir uma aposta ja' feita.
        item["suggested_stake_units"] = (
            _compute_suggested_stake_units(
                "live", None, p.get("confidence"), p.get("odd"), p.get("ev"),
                banca[0], banca[1],
            ) if banca and not seguido else None
        )
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

    # UM PICK AO VIVO POR DIA E' FREE (01/09/2026, decisao do usuario).
    #
    # Mesma regra do Pick Boost, e pelo mesmo motivo: o Ao Vivo publica varios
    # picks ao longo da noite, entao liberar um nao esvazia o produto -- e e' o
    # unico jeito de quem nao assina entender o que ele e'. Ate' hoje a aba
    # respondia 403 pro free, e a tela mostrava "nao foi possivel carregar":
    # um produto inteiro parecendo defeito.
    #
    # O liberado e' o de MAIOR `live_signal_score` entre os que estao de pe',
    # que e' o mesmo criterio de qualidade do motor. Nao e' o mais recente de
    # proposito: "o primeiro que apareceu" daria ao free um pick pior so' por
    # sorte de horario.
    #
    # O `plano` e' explicito e nao inferido pela posicao -- a tela reordena, e
    # a marca tem que sobreviver a isso. Mesma decisao de `_marcar_boost_free`.
    e_vip = is_vip_active(current_user)
    bloqueados = []
    if not e_vip:
        de_pe = [p for p in saida
                 if p.get("result") is None and p.get("status") == STATUS_ATIVO]
        liberado = max(
            de_pe,
            key=lambda p: (p.get("live_signal_score") or 0),
            default=None,
        )
        novo = []
        for p in saida:
            if liberado is not None and p["id"] == liberado["id"]:
                p["plano"] = "free"
                novo.append(p)
                continue
            # O QUE O TEASER MOSTRA e' o mesmo contrato do link publico de pick
            # e do teaser dos outros produtos: times, liga, horario e odd.
            # NUNCA market, line, reasoning, probability, ev, edge, confidence
            # ou stake -- a analise e' o que se paga, e ela nao sai daqui.
            if p.get("result") is None:
                bloqueados.append({
                    "id": p["id"],
                    "match_date": p.get("match_date"),
                    "league_name": p.get("league_name"),
                    "home_team_name": p.get("home_team_name"),
                    "away_team_name": p.get("away_team_name"),
                    "home_team_id": p.get("home_team_id"),
                    "away_team_id": p.get("away_team_id"),
                    "odd": p.get("odd"),
                    "minute_at_creation": p.get("minute_at_creation"),
                })
        saida = novo
    else:
        for p in saida:
            p["plano"] = "vip"

    return {
        "disponivel": True,
        "picks": saida,
        "e_vip": e_vip,
        # So' preenchido pra quem nao assina · o VIP ve' tudo em `picks`.
        "bloqueados": bloqueados,
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
            # Ligado E com jogo em campo. A tela usa os dois pra dizer
            # "buscando" x "aguardando jogo" x "pausada".
            "hibernando": bool(_watch_state.get("hibernando")),
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


#: Cache proprio das estatisticas do bloco "em leitura", com TTL LONGO.
#:
#: POR QUE NAO USAR O TTL DE 20s DO RESTO DO LIVE. `_fetch_stats` custa UMA
#: requisicao POR PARTIDA, e este bloco olha ate' 12 jogos ao mesmo tempo. Com o
#: TTL de 20s e a tela pesquisando de 30 em 30 segundos, uma unica aba aberta
#: geraria ~24 requisicoes por minuto -- que e' a ordem de grandeza que estourou
#: a cota em 01/08 e custou o agendador.
#:
#: 180 segundos (era 90s): o poll do front passou de 15s para 30s, logo o TTL
#: pode dobrar mantendo a mesma proporcao de cache hit (TTL > 2x poll).
#: Escanteio e chute mudam no ritmo do provedor (~1min), entao 3 minutos de
#: cache nao perde dado util nenhum. O placar e o minuto NAO passam por aqui:
#: eles vem do bulk de fixtures, que custa uma requisicao pra vinte jogos.
_LEITURA_STATS_TTL = 180
_LEITURA_STATS_MAX = 12
_leitura_stats: dict = {}


def _stats_do_jogo(fixture_id: int, status: str, home_id, away_id) -> dict:
    """Escanteios, chutes e chutes no alvo AGORA, somando os dois times.

    Devolve {} quando a folha nao esta publicada · e o chamador mantem o que o
    motor leu, porque numero velho identificado e' melhor que numero ausente.
    """
    agora = time.time()
    cacheado = _leitura_stats.get(fixture_id)
    if cacheado and agora - cacheado[0] < _LEITURA_STATS_TTL:
        return cacheado[1]

    casa, fora = _parse_stats(_fetch_stats(fixture_id, status), home_id, away_id)
    if not casa and not fora:
        _leitura_stats[fixture_id] = (agora, {})
        return {}

    def soma(chave):
        a, b = casa.get(chave), fora.get(chave)
        if a is None and b is None:
            return None
        return int(a or 0) + int(b or 0)

    lido = {
        "corners_observado": soma("Corner Kicks"),
        "shots_observado": soma("Total Shots"),
        "shots_on_target_observado": soma("Shots on Goal"),
        "red_cards_observado": soma("Red Cards"),
    }
    _leitura_stats[fixture_id] = (agora, lido)
    return lido


def _atualizar_leitura(linhas: list) -> None:
    """Poe o JOGO DE AGORA por cima do que o motor leu na ultima varredura.

    POR QUE ISTO EXISTE (2026-08-29, pedido do usuario)
    ---------------------------------------------------
    O bloco mostrava `live_match_observations` cru, e essa e' a leitura do
    MOTOR: ela so' muda quando ele varre. Entre duas varreduras -- e o usuario
    viu 46 minutos entre elas -- o cartao ficava com o minuto e os contadores
    congelados enquanto os cards de pick logo acima, que leem a API, mostravam
    o jogo andando. Duas partes da mesma tela discordando sobre o mesmo jogo.

    O minuto projetado (`idade_seg` no front) disfarcava metade do problema e
    piorava a outra: o relogio andava e os numeros nao, entao o cartao dizia
    "45 minutos de jogo, 3 escanteios" com a partida em outro ponto.

    A fonte agora e a mesma dos cards: `_fetch_fixture` pro minuto e o placar,
    `_fetch_stats` pros contadores. `fresco` diz de qual das duas veio cada
    linha, pra a tela nao prometer atualidade que nao tem.
    """
    ids = [l["fixture_id"] for l in linhas if l.get("fixture_id")]
    if not ids:
        return
    # Mesma regra do feed: motor fora de campo nao atualiza nada, porque nao ha
    # nada acontecendo pra atualizar. As linhas continuam sendo a ultima
    # leitura do motor, e o front ja esconde o bloco inteiro quando a busca
    # esta parada.
    if not (_watch_state["ativo"] and not _watch_state.get("hibernando")):
        for linha in linhas:
            linha["fresco"] = False
        return
    _fetch_fixtures_bulk(ids)

    orcamento = _LEITURA_STATS_MAX
    for linha in linhas:
        linha["fresco"] = False
        try:
            dados = _fetch_fixture(linha["fixture_id"])
        except Exception:
            continue
        fixture = dados.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short")
        if not status:
            continue

        minuto = (fixture.get("status") or {}).get("elapsed")
        if minuto is not None:
            linha["minuto"] = minuto
        linha["status"] = status
        gols = dados.get("goals") or {}
        if gols.get("home") is not None and gols.get("away") is not None:
            linha["goals_observado"] = int(gols["home"]) + int(gols["away"])
        linha["fresco"] = True

        # A folha so' e' pedida com a bola rolando: jogo em FT ja' nao e' o que
        # o motor esta lendo, e pedir a folha dele gastaria cota pra atualizar
        # um cartao que sai da lista na proxima passada.
        if status not in LIVE_STATUSES or orcamento <= 0:
            continue
        times = dados.get("teams") or {}
        atual = _stats_do_jogo(
            linha["fixture_id"], status,
            linha.get("home_team_id") or (times.get("home") or {}).get("id"),
            linha.get("away_team_id") or (times.get("away") or {}).get("id"))
        orcamento -= 1
        for chave, valor in atual.items():
            if valor is not None:
                linha[chave] = valor


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
                       -- HA QUANTO TEMPO ESSA LEITURA FOI FEITA, em segundos,
                       -- calculado NO BANCO (29/08).
                       --
                       -- `observed_at` e' TIMESTAMP sem fuso, gravado pelo
                       -- relogio do motor · a tela nao tem como transformar
                       -- isso em idade sem adivinhar de que fuso ele veio, e
                       -- adivinhar erra por horas. Aqui a subtracao acontece
                       -- do lado de quem gravou, e o que viaja e' um numero
                       -- sem fuso nenhum.
                       --
                       -- E' o que faz o cartao envelhecer sozinho entre duas
                       -- varreduras, em vez de estampar um minuto congelado
                       -- que parecia dado velho travado.
                       GREATEST(0, EXTRACT(EPOCH FROM (NOW() - u.observed_at)))::int
                           AS idade_seg,
                       f.home_team, f.away_team,
                       -- Os ids viajam junto porque a tela desenha escudo, e o
                       -- escudo sai do proxy por id (/api/proxy/team/<id>.png).
                       -- Sem eles a linha teria que casar por NOME, que e'
                       -- justamente o casamento que o resto do projeto evita.
                       f.home_team_id, f.away_team_id, f.league_id,
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
             -- JOIN, e nao LEFT JOIN, em `fixtures` (2026-09-05).
             --
             -- O motor observa o que a API devolve como ao vivo, e nem toda
             -- partida observada existe na nossa tabela -- a coleta pode nao ter
             -- trazido aquele jogo. Com LEFT JOIN essas linhas viravam cartao
             -- "liga ? / Time ? x Time ?", com placar e contadores mas sem
             -- dizer de que jogo se tratava: metade da tela era isso.
             --
             -- Partida que nao da' pra nomear nao e' informacao. Ela sai da
             -- lista e sai da contagem, que passa a dizer quantos jogos a
             -- pessoa consegue de fato ler.
                  JOIN fixtures f ON f.fixture_id = u.fixture_id
                                 AND f.home_team IS NOT NULL
             LEFT JOIN leagues  l ON l.league_id  = f.league_id
                 WHERE u.status = ANY(%s)
                   -- JOGO QUE JA' ACABOU NAO ESTA' SENDO LIDO (2026-09-05).
                   --
                   -- A observacao e' um retrato: o motor leu a partida aos 90'
                   -- com status "2H" e nunca mais voltou nela -- ninguem reescreve
                   -- aquela linha quando o juiz apita. Dentro da janela de 60
                   -- minutos ela continuava aparecendo, e a tela anunciava como
                   -- "acompanhando agora" cinco jogos encerrados.
                   --
                   -- Duas travas, e as duas custam zero requisicao:
                   --
                   --   1. o status ATUAL da fixture, que o coletor mantem. Se
                   --      ela ja' esta' FT/AET/PEN, acabou, ponto.
                   --   2. minuto >= 90 com leitura velha. Existe pra quando a
                   --      fixture ainda nao foi atualizada: 90' e' o fim do
                   --      tempo normal, e um jogo que segue em campo recebe
                   --      leitura nova a cada rodada -- entao leitura parada ha'
                   --      mais de 20 minutos num jogo de 90' e' jogo que acabou.
                   AND COALESCE(f.status, '') <> ALL(%s)
                   AND NOT (COALESCE(u.minuto, 0) >= 90
                            AND EXTRACT(EPOCH FROM (NOW() - u.observed_at)) > 1200)
              ORDER BY u.observed_at DESC, u.minuto DESC NULLS LAST
                 LIMIT %s
            """, (_JANELA_EM_LEITURA_MIN, list(LIVE_STATUSES),
                  list(FT_STATUSES) + ["PST", "CANC", "ABD", "AWD", "WO"], limit))
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

    _atualizar_leitura(linhas)

    return {
        "disponivel": True,
        "janela_min": _JANELA_EM_LEITURA_MIN,
        "total": len(linhas),
        "partidas": linhas,
        # O mesmo estado que o /feed devolve · a tela mostra os dois juntos, e
        # duas chamadas trariam dois retratos de instantes diferentes.
        "motor": {
            "ligado": bool(_watch_state["ativo"]),
            # Ligado E com jogo em campo. A tela usa os dois pra dizer
            # "buscando" x "aguardando jogo" x "pausada".
            "hibernando": bool(_watch_state.get("hibernando")),
            "ultima_rodada": _watch_state["ultima_rodada"],
        },
    }


@router.get("/stats")
def estatisticas(
    date: str | None = Query(None, description="YYYY-MM-DD · só este dia"),
    month: str | None = Query(None, description="YYYY-MM · só este mês"),
    current_user: dict = Depends(require_live_reader),
):
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
        # RECORTE DE PERIODO (2026-08-30).
        #
        # O placar do Live nasceu como numero unico "desde sempre", que e o que
        # a aba do produto mostra. Os cards de divulgacao precisam do dia e do
        # mes -- os outros produtos ja tinham isso em /public/results, e o Live
        # e medido a parte de proposito (ver a docstring abaixo), entao o
        # recorte tem que existir aqui tambem.
        #
        # Corta por `match_date` e nao por `created_at`: o pick nasce durante a
        # partida, entao os dois quase sempre coincidem -- mas quando um jogo
        # vira o dia, o resultado pertence ao dia da PARTIDA, que e como o
        # placar dos outros produtos ja conta.
        #
        # Data invalida vira "sem recorte" em vez de erro: isto alimenta card
        # de divulgacao, e um 422 na tela do admin seria pior que um numero
        # mais largo do que o pedido.
        onde, params = "", []
        if date:
            onde = "WHERE match_date = %s"
            params = [date]
        elif month:
            onde = "WHERE to_char(match_date, 'YYYY-MM') = %s"
            params = [month]

        cur.execute(f"""
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
            {onde}
        """, params)
        linha = dict(cur.fetchone() or {})

        cur.execute(f"""
            SELECT market_type,
                   COUNT(*) FILTER (WHERE result IS NOT NULL) AS resolvidos,
                   COUNT(*) FILTER (WHERE result = 'GREEN')   AS greens,
                   COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
            FROM picks_live
            {onde}
            GROUP BY market_type
            ORDER BY resolvidos DESC
        """, params)
        por_mercado = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    resolvidos = int(linha.get("resolvidos") or 0)
    greens = int(linha.get("greens") or 0)
    lucro = float(linha.get("profit") or 0)
    return {
        "disponivel": True,
        # Vai na resposta pra o card de divulgacao nao ter que reconstruir o
        # rotulo do periodo por conta dele -- e pra a tela poder dizer de que
        # recorte o numero e', que e' a diferenca entre "5 picks" e "5 picks
        # hoje".
        "periodo": {"date": date, "month": month} if (date or month) else None,
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


#: HISTORICO DE RODADAS, em memoria (2026-09-05, pedido do usuario).
#:
#: `_run_status` guarda a ULTIMA rodada e nada mais -- e a rodada seguinte
#: sobrescreve. Enquanto o motor era um botao isso bastava; com o
#: acompanhamento continuo ligado ele dispara sozinho de 8 em 8 minutos, e o
#: log de uma passada dura ate' a proxima. Quem abre o painel depois de uma
#: noite de motor ligado nao tinha como saber o que aconteceu nela.
#:
#: Em MEMORIA, e nao em tabela: e' diagnostico de operacao, nao dado do
#: produto. Reiniciar o servico limpa, e limpar e' aceitavel -- o que precisa
#: sobreviver a um restart ja' vive em `engine_runs` e nos proprios picks.
_HISTORICO_RODADAS: deque = deque(maxlen=40)


def _registrar_rodada(origem: str, body: RunBody, resultado: dict) -> None:
    """Uma linha do log por rodada. O stdout entra cortado."""
    _HISTORICO_RODADAS.appendleft({
        "origem": origem,                       # 'manual' | 'watch'
        "started_at": resultado.get("started_at"),
        "finished_at": resultado.get("finished_at"),
        "status": resultado.get("status"),
        "returncode": resultado.get("returncode"),
        "dry_run": _resolver_dry_run(body.dry_run),
        "fixture_id": body.fixture_id,
        # 4000 caracteres cobrem uma rodada inteira com folga; o teto existe
        # pra 40 rodadas guardadas nao virarem megabytes de RAM no container.
        "log": (resultado.get("log") or "")[-4000:],
        "error": (resultado.get("error") or "")[-1500:] or None,
    })


async def _rodar(body: RunBody, origem: str = "manual") -> None:
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
    finally:
        _registrar_rodada(origem, body, _run_status)


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
    # LIGADO mas sem jogo em campo. Nao e' "desligado": o laco esta de pe e
    # volta sozinho. A tela precisa dos dois estados separados, senao
    # "aguardando o primeiro jogo do dia" e "alguem desligou o motor" viram a
    # mesma frase -- e sao situacoes opostas pra quem esta esperando pick.
    "hibernando": False,
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


#: Quanto tempo depois do apito inicial uma partida ainda pode estar rolando.
#:
#: 150 minutos cobre 90 de bola rolando + intervalo + acrescimo + atraso de
#: inicio com folga. Nao precisa ser justo: errar pra mais so' faz o motor
#: acordar um pouco antes da hora, e errar pra menos faz ele dormir com jogo
#: em campo -- que e' o unico erro que custa pick.
_JANELA_DE_JOGO_MIN = 150

#: Espera entre duas checagens quando nao ha jogo nenhum. Ela e' longa porque
#: nao ha nada acontecendo: o pior caso e' um jogo comecar logo depois de uma
#: checagem e o motor so' perceber 20 minutos depois -- e a janela do motor
#: comeca aos 15' de partida, entao ele nao perdeu nada que ja pudesse usar.
_INTERVALO_HIBERNANDO_MIN = 20


def _ha_jogo_na_janela() -> bool:
    """Existe partida das nossas ligas que pode estar em campo AGORA?

    POR QUE ISTO EXISTE (2026-08-30, pedido do usuario)
    ---------------------------------------------------
    O laco rodava a passada completa de 8 em 8 minutos o tempo todo, inclusive
    de madrugada, sem jogo nenhum. Cada passada dessas custa pelo menos a
    varredura `/fixtures?live=all` -- barata sozinha, cara repetida 180 vezes
    por dia pra receber "nenhuma partida elegivel". Foi consumo assim que
    estourou a cota em 01/08 e custou o agendador do projeto.

    A PERGUNTA E' RESPONDIDA NO BANCO, e por isso custa ZERO requisicao. A
    tabela `fixtures` ja sabe o horario de cada partida das ligas ativas: se
    nenhuma comecou dentro da janela de um jogo, nao ha o que a API pudesse
    dizer de diferente.

    Falha aberta de proposito: erro de banco devolve True, ou seja, o motor
    roda. Um SELECT que falhou nao e' prova de que nao ha jogo, e dormir por
    engano custa pick -- enquanto acordar por engano custa uma varredura.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                  FROM fixtures f
                  JOIN leagues l ON l.league_id = f.league_id
                                AND COALESCE(l.ativa, TRUE)
                 WHERE f.match_datetime BETWEEN
                       (NOW() AT TIME ZONE 'America/Sao_Paulo') - (%s * INTERVAL '1 minute')
                   AND (NOW() AT TIME ZONE 'America/Sao_Paulo')
                   AND COALESCE(f.status, 'NS') NOT IN ('FT','AET','PEN','PST','CANC','ABD','AWD','WO')
            ) AS tem
        """, (_JANELA_DE_JOGO_MIN,))
        return bool((cur.fetchone() or {}).get("tem"))
    except Exception as e:
        logger.warning("[LIVE-WATCH] checagem de janela falhou (%s) · seguindo com a rodada", e)
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


async def _laco_de_acompanhamento(intervalo_min: int, dry_run: bool,
                                  max_partidas: int | None) -> None:
    """Roda rodadas sucessivas até alguém desligar."""
    intervalo = max(_INTERVALO_MIN_MINUTOS, int(intervalo_min)) * 60
    body = RunBody(dry_run=dry_run, max_partidas=max_partidas)
    agora = _relogio_do_watch

    try:
        while _watch_state["ativo"]:
            # HIBERNACAO. Sem jogo em campo a rodada nao acontece -- nem a
            # varredura. O laco continua vivo e volta ao ritmo normal sozinho
            # na primeira checagem que encontrar partida, que e' o "liga
            # automaticamente" pedido: nao ha nada pra alguem religar.
            hibernando = not await run_in_threadpool(_ha_jogo_na_janela)
            _watch_state["hibernando"] = hibernando
            if hibernando:
                _watch_state["proxima_rodada_em"] = _INTERVALO_HIBERNANDO_MIN * 60
                _salvar_watch()
                restante = _INTERVALO_HIBERNANDO_MIN * 60
                while restante > 0 and _watch_state["ativo"]:
                    _watch_state["proxima_rodada_em"] = restante
                    await asyncio.sleep(min(5, restante))
                    restante -= 5
                continue

            await _rodar(body, origem="watch")
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

    # Loga se a task morrer por exception nao tratada · sem isto o laco
    # simplesmente some e o painel continua dizendo "ligado" pra sempre.
    def _ao_terminar(task: asyncio.Task) -> None:
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("[LIVE-WATCH] laco encerrou com excecao: %s", exc, exc_info=exc)

    _watch_task.add_done_callback(_ao_terminar)

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


def _lado_oposto(line: str | None) -> str | None:
    """"Over 9.5" -> "Under 9.5". O par e' o que permite tirar a margem da casa."""
    if not line:
        return None
    texto = str(line).strip()
    baixo = texto.lower()
    if baixo.startswith("over"):
        return "Under" + texto[4:]
    if baixo.startswith("under"):
        return "Over" + texto[5:]
    return None


def _prob_do_mercado(odd: float, odd_oposta: float | None) -> dict:
    """Probabilidade implicita do lado do pick, sem vig quando ha' o par.

    Mesma conta do pre-jogo (market_model.no_vig_pair_prob): 1/odd de cada lado
    somam mais que 1 -- o excedente e' a margem --, e a proporcao entre elas e'
    a chance que a casa esta' precificando. Sem o par, devolve a implicita crua
    e marca `sem_vig=False`, porque ela carrega a margem inteira e nao pode ser
    comparada com a nossa como se fosse a mesma medida.
    """
    if not odd or odd <= 1:
        return {"valor": None, "sem_vig": False}
    crua = 1.0 / float(odd)
    if odd_oposta and float(odd_oposta) > 1:
        total = crua + 1.0 / float(odd_oposta)
        if total > 0:
            return {"valor": round(crua / total, 4), "sem_vig": True}
    return {"valor": round(crua, 4), "sem_vig": False}


#: Quanto tempo a odd de um pick vale depois de a leitura confirmar que ela
#: continua cotada. Curto porque a odd ao vivo muda em minutos -- o que a
#: renovacao evita e' o pick morrer com o mercado ABERTO, nao prometer preco.
_RENOVACAO_DA_ODD_MIN = 5


@router.get("/odds-agora")
def odds_agora(current_user: dict = Depends(require_live_reader)):
    """A odd de AGORA dos picks ao vivo em aberto.

    POR QUE ISTO EXISTE (2026-09-06, pedido do usuario)
    ---------------------------------------------------
    O card mostrava a odd do instante da publicacao e, passados alguns minutos,
    trocava aquilo por "odd vencida" -- um pick que o mercado ainda estava
    cotando aparecia morto porque o RELOGIO venceu, nao porque a casa fechou.

    O CUSTO FOI O QUE DECIDIU O DESENHO. `_fetch_live_odds` pergunta por UMA
    fixture: com 5 picks abertos e leitura por minuto seriam 300 requisicoes por
    hora. `/odds/live` sem `fixture` devolve o mundo, e uma leitura cobre todos
    os picks de todos os usuarios: ~60 por hora de jogo, ~240 num dia de 4
    horas, contra as 7.500 do plano. O cache de 60s no servidor e' o que segura
    isso mesmo com a aba de dez pessoas abertas pedindo a cada 15 segundos.

    NAO GRAVA PRECO NOVO NO PICK. O `odd` do pick continua sendo o da
    publicacao -- e' o que a IA analisou e e' contra ele que o resultado e'
    medido. O que a leitura faz e' (1) devolver a odd corrente pra tela mostrar
    ao lado, e (2) ADIAR a expiracao enquanto o mercado continuar de pe'.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not _tabela_existe(cur):
            return {"disponivel": False, "picks": {}}
        # SO' PICK PENDENTE DE JOGO QUE NAO ACABOU (2026-09-06, decisao do
        # usuario). `result IS NULL` sozinho nao basta: entre o apito final e a
        # liquidacao o pick fica pendente com a partida encerrada, e perguntar
        # a odd dele e' trabalho sobre um mercado que nao existe mais. O status
        # sai de `fixtures`, que o coletor mantem -- custo zero de API.
        # O EXPIRADO ENTRA JUNTO (2026-09-06, pedido do usuario).
        #
        # E' o caso que mais precisa da leitura: pick que NINGUEM pegou e que o
        # relogio marcou como "odd vencida". Se a casa continua cotando, ele
        # nao venceu coisa nenhuma -- so' o nosso cronometro achou que sim --,
        # e deixa-lo fora da consulta congelava o card na frase errada pra
        # sempre. Pick com resultado nao entra: ai' acabou de verdade.
        cur.execute("""
            SELECT pl.id, pl.fixture_id, pl.market_type, pl.line, pl.odd, pl.status
              FROM picks_live pl
              LEFT JOIN fixtures f ON f.fixture_id = pl.fixture_id
             WHERE pl.result IS NULL
               AND pl.status = ANY(%s)
               AND pl.match_date >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
               AND COALESCE(f.status, '') <> ALL(%s)
        """, ([STATUS_ATIVO, STATUS_EXPIRADO],
              list(FT_STATUSES) + ["PST", "CANC", "ABD", "AWD", "WO"]))
        abertos = [dict(r) for r in cur.fetchall()]
        if not abertos:
            return {"disponivel": True, "picks": {}}

        mundo = _fetch_live_odds_mundo()
        if not mundo:
            # Leitura falhou ou o provedor nao esta' servindo: a tela mantem o
            # que ja' tinha em vez de anunciar que o mercado fechou.
            return {"disponivel": False, "picks": {}, "motivo": "sem leitura de odd agora"}

        agora = _agora_naive()
        saida: dict[str, dict] = {}
        renovar: list[int] = []
        for p in abertos:
            mercados = mundo.get(int(p["fixture_id"])) or []
            odd_agora = _find_live_odd(p.get("market_type"), p.get("line"), mercados)
            if odd_agora is None:
                # Sem cotacao AGORA nao e' erro: mercado suspenso no meio de um
                # ataque perigoso e' rotina, e ele volta minutos depois.
                saida[str(p["id"])] = {"odd": None, "cotado": False}
                continue
            renovar.append(int(p["id"]))
            # PROBABILIDADE DO MERCADO AGORA (2026-09-06, pedido do usuario).
            #
            # E' a chance que a CASA esta' precificando neste minuto, nao um
            # recalculo do nosso modelo: o modelo le' escanteio, chute e
            # posse por partida, e refazer isso no site custaria uma
            # requisicao de estatistica POR JOGO a cada leitura -- exatamente o
            # consumo que a leitura global de odd existe pra evitar.
            #
            # Com os dois lados cotados ela sai SEM VIG (a margem da casa
            # dividida entre eles); com um lado so', e' a implicita crua e a
            # tela diz isso. As duas respondem a mesma pergunta util: pra onde
            # o mercado andou desde que o pick nasceu.
            oposta = _find_live_odd(p.get("market_type"), _lado_oposto(p.get("line")), mercados)
            prob = _prob_do_mercado(float(odd_agora), oposta)
            saida[str(p["id"])] = {
                "odd": round(float(odd_agora), 2),
                "cotado": True,
                "variacao": round(float(odd_agora) - float(p["odd"] or 0), 2),
                "prob_mercado": prob["valor"],
                "prob_sem_vig": prob["sem_vig"],
            }

        if renovar:
            # RESSUSCITA O QUE O RELOGIO MATOU. `status` volta pra ACTIVE e o
            # motivo da expiracao e' apagado: o mercado provou que estava la'.
            # So' pra quem nao tem resultado -- e sem tocar em pick seguido, que
            # nunca expira (ver `expirar_vencidos`).
            cur.execute("""
                UPDATE picks_live
                   SET odd_valid_until = %s,
                       status = %s,
                       expiration_reason = NULL
                 WHERE id = ANY(%s) AND result IS NULL
            """, (agora + timedelta(minutes=_RENOVACAO_DA_ODD_MIN), STATUS_ATIVO, renovar))
            conn.commit()

        return {"disponivel": True, "picks": saida,
                "atualizado_em": agora.isoformat(timespec="seconds")}
    finally:
        cur.close()
        conn.close()


@router.get("/run-status")
def status_da_rodada(current_user: dict = Depends(require_admin)):
    return dict(_run_status)


@router.get("/log")
def log_do_motor(
    limit: int = Query(15, ge=1, le=40),
    current_user: dict = Depends(require_admin),
):
    """As ultimas rodadas do motor, com o log de cada uma.

    Existe porque `/run-status` responde "como foi A ULTIMA", e com o
    acompanhamento continuo ligado a ultima e' de oito minutos atras -- o que
    aconteceu na noite inteira nao ficava em lugar nenhum consultavel pela tela.

    Memoria do processo, entao um restart zera. Ver `_HISTORICO_RODADAS`.
    """
    return {
        "rodadas": list(_HISTORICO_RODADAS)[:limit],
        "total": len(_HISTORICO_RODADAS),
        "capacidade": _HISTORICO_RODADAS.maxlen,
        # A rodada EM CURSO nao esta no historico (ele so' recebe no fim), e sem
        # isto a tela mostraria a lista parada enquanto o motor trabalha.
        "em_curso": _run_status.get("status") == "running",
    }


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
