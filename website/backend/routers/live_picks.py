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
    """Quem pode LER o feed/estatistica do Motor Live.

    Enquanto o motor esta em validacao, so' admin. A aba do usuario ja' esta
    desligada por `VITE_LIVE_PICKS_ENABLED`, mas isso e' o front: qualquer VIP
    que conheca a rota alcanca `/feed` e `/stats` do mesmo jeito, e `stats`
    publica taxa de acerto de um motor que ainda nao foi medido. Numero de
    motor em teste vazando como se fosse produto e' pior do que numero nenhum.

    `LIVE_PICKS_PUBLIC=true` libera pra VIP quando o produto abrir · e' o mesmo
    interruptor do front, do lado do servidor, e nao depende de rebuild.
    """
    if os.getenv("LIVE_PICKS_PUBLIC", "").strip().lower() in ("1", "true", "on", "yes", "sim"):
        return user
    if user.get("plan") != "admin":
        raise HTTPException(403, "Motor Ao Vivo em validação · disponível apenas para admin.")
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
    limit: int = Query(30, ge=1, le=100),
):
    """Oportunidades do Motor Live. E' o que a aba Ao Vivo consome.

    Abrir a aba tambem expira o que venceu e liquida o que ja encerrou --
    mesmo padrao de `maybe_resolve_pending` no /today: a visita e' o gatilho,
    site parado nao gasta nada.
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
            WHERE match_date >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date - INTERVAL '1 day'
            ORDER BY (result IS NOT NULL), created_at DESC
            LIMIT %s
        """, (limit,))
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

    return {
        "disponivel": True,
        "picks": saida,
        "expirados_agora": expirados,
        "liquidados_agora": liquidacao["liquidados"],
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
    dry_run: bool = True
    max_partidas: int | None = None


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


_CHAVES_DEV = ("DB_HOST_DEV", "DB_PORT_DEV", "DB_NAME_DEV",
               "DB_USER_DEV", "DB_PASS_DEV")


def _pode_disparar() -> tuple[bool, str]:
    """Quem pode disparar o motor Live neste servico.

    NAO usa `is_production()` sozinho, e a razao e' de seguranca, nao de
    conveniencia: `APP_ENV` tambem controla a flag `Secure` do cookie de sessao
    (auth_utils.py). Baixar APP_ENV pra "development" num servico exposto na
    internet, so' pra liberar este botao, tiraria o `Secure` do cookie de
    autenticacao de todo mundo que usa aquele dominio.

    Entao a autorizacao de disparo vira flag PROPRIA, separada da nocao de
    ambiente -- mesmo padrao de `SIDE_EFFECTS=off`, que separa staging de
    producao sem mexer em APP_ENV.

        LIVE_ENGINE_ALLOW_RUN=true   libera o disparo neste servico
        fora de producao             liberado sem precisar de flag
    """
    if os.getenv("LIVE_ENGINE_ALLOW_RUN", "").strip().lower() in ("1", "true", "on", "yes", "sim"):
        return True, ""
    from runtime_env import is_production
    if not is_production():
        return True, ""
    return False, (
        "Disparo do motor Live nao autorizado neste servico. Defina "
        "LIVE_ENGINE_ALLOW_RUN=true nas variaveis deste ambiente (nao baixe "
        "APP_ENV: ele controla a flag Secure do cookie de sessao)."
    )


def _dev_configurado() -> list[str]:
    """Variaveis _DEV que faltam. Vazio = pode rodar.

    O motor e' disparado sempre com DB_ENV=dev, e `utils/db_utils` le as
    variaveis com sufixo _DEV. Elas NAO sao fabricadas a partir de DB_HOST --
    mesma decisao de routers/admin.py::_dev_env, e pelo mesmo motivo: DB_HOST
    neste processo pode apontar pra producao, e fabricar credencial "de dev" a
    partir dele criaria o risco real de o motor gravar pick na base errada
    acreditando que e' DEV.
    """
    return [k for k in _CHAVES_DEV if not os.getenv(k)]


async def _rodar(body: RunBody) -> None:
    agora = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    _run_status.update({"status": "running", "started_at": agora(),
                        "finished_at": None, "returncode": None, "error": None})
    diretorio = _pipeline_dir()
    script = os.path.join(diretorio, "engine_pipelines", "live_pipeline.py")
    argumentos: list[str] = []
    if body.fixture_id:
        argumentos += ["--fixture", str(body.fixture_id)]
    argumentos.append("--dry-run" if body.dry_run else "--gravar")
    if body.max_partidas:
        argumentos += ["--max", str(body.max_partidas)]

    try:
        # DB_ENV=dev e' cravado aqui, nao herdado: o disparo pelo /admin nao
        # pode ser o caminho por onde o motor Live alcanca o banco de
        # producao. O proprio pipeline recusaria (exigir_ambiente_dev), mas
        # depender so' da checagem do outro lado deixa a intencao implicita.
        env = {**os.environ, "PYTHONPATH": diretorio, "DB_ENV": "dev"}
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


@router.post("/run")
async def rodar_motor(body: RunBody, current_user: dict = Depends(require_admin)):
    """Dispara UMA rodada do Motor Live. Admin, e so' onde for autorizado.

    Nao existe laco, nao existe agendamento. E' o botao que a V1 tem no lugar
    de um scheduler, de proposito -- o consumo real precisa ser medido rodada
    a rodada antes de qualquer automacao.
    """
    autorizado, motivo = _pode_disparar()
    if not autorizado:
        raise HTTPException(403, motivo)
    faltando = _dev_configurado()
    if faltando:
        raise HTTPException(400, (
            f"Faltam as variaveis de banco de desenvolvimento: {', '.join(faltando)}. "
            "O motor Live roda sempre com DB_ENV=dev e elas nao sao fabricadas a "
            "partir de DB_HOST, pra nao existir caminho em que ele grave pick na "
            "base errada acreditando que e' DEV."
        ))
    if _run_status["status"] == "running":
        raise HTTPException(409, "Ja existe uma rodada em andamento.")
    if not _pipeline_dir():
        raise HTTPException(500, "Diretorio do motor nao encontrado (PIPELINE_SRC_PATH).")
    asyncio.create_task(_rodar(body))
    return {"ok": True, "iniciado": True, "dry_run": body.dry_run}


@router.get("/run-status")
def status_da_rodada(current_user: dict = Depends(require_admin)):
    return dict(_run_status)


@router.get("/diagnostico")
def diagnostico(current_user: dict = Depends(require_admin)):
    """O que falta pra ESTE servico conseguir rodar o motor Live.

    Existe porque a V1 tem seis pre-condicoes independentes e, sem isto,
    descobrir qual delas falhou exige ler log de subprocesso num ambiente
    remoto -- o que custa mais tempo que a propria rodada.
    """
    autorizado, motivo = _pode_disparar()
    faltando = _dev_configurado()
    conn = get_connection()
    cur = conn.cursor()
    try:
        tabela = _tabela_existe(cur)
    finally:
        cur.close()
        conn.close()

    ligado = os.getenv("LIVE_ENGINE_ENABLED", "").strip().lower() in (
        "1", "true", "on", "yes", "sim")
    checagens = [
        {"item": "motor habilitado", "ok": ligado,
         "detalhe": f"LIVE_ENGINE_ENABLED={os.getenv('LIVE_ENGINE_ENABLED') or 'ausente'}"},
        {"item": "disparo autorizado", "ok": autorizado,
         "detalhe": motivo or "liberado neste ambiente"},
        {"item": "credenciais _DEV", "ok": not faltando,
         "detalhe": "todas presentes" if not faltando else f"faltam: {', '.join(faltando)}"},
        {"item": "codigo do motor", "ok": bool(_pipeline_dir()),
         "detalhe": _pipeline_dir() or "PIPELINE_SRC_PATH nao resolve"},
        {"item": "chave da API-Football", "ok": bool(os.getenv("API_FOOTBALL_KEY")),
         "detalhe": "configurada" if os.getenv("API_FOOTBALL_KEY") else "API_FOOTBALL_KEY ausente"},
        {"item": "tabela picks_live no banco que o site le", "ok": tabela,
         "detalhe": "existe" if tabela else
                    "ausente -- o motor cria na primeira rodada, no banco de DEV"},
    ]
    return {
        "pronto": all(c["ok"] for c in checagens),
        "checagens": checagens,
        "dry_run_padrao": os.getenv("LIVE_ENGINE_DRY_RUN", "true"),
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
