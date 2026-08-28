import os
import sys
import asyncio
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, field_validator
from typing import Optional
from database import get_connection
from data_br import HOJE_BR, data_br
from auth_utils import require_admin, hash_password, get_current_user, invalidar_cache_usuario
# Catalogo de motores/metodos do MOTOR, nao uma copia daqui -- ver o comentario
# em settlement_bridge.py. Alimenta a aba Auditoria dos Motores com os rotulos
# e as versoes que o proprio motor grava.
from settlement_bridge import engine_registry

_pipeline_status: dict = {}  # command -> {status, started_at, finished_at, returncode}


# ─── Log ao vivo do pipeline ─────────────────────────────────────────────────
# Ate 2026-08-13 o log so' existia DEPOIS: proc.communicate() espera o processo
# inteiro, e o que sobrava era o rabo de 1500 caracteres. Numa etapa de 30
# minutos (coleta de odds em dia cheio, ou o Stage 6 de historico) a tela ficava
# com uma bolinha amarela e nada mais -- nao dava pra saber se estava
# progredindo, travado ou esperando a API.
#
# Agora cada linha e' drenada assim que sai do processo. Buffer limitado porque
# isto vive na MEMORIA do processo web: log de pipeline nao pode competir por
# RAM com o site.
_LOG_MAX_LINHAS = 500


class _LogBuffer:
    """Fila de linhas com leitura incremental.

    `desde(indice)` devolve so' o que chegou depois da ultima consulta, pra a
    tela poder pesquisar de segundo em segundo sem rebaixar o log inteiro toda
    vez. `descartadas` mantem o indice global correto mesmo depois de o buffer
    girar -- sem isso, a tela repetiria linhas antigas ao passar do limite.
    """

    def __init__(self, maximo: int = _LOG_MAX_LINHAS):
        self.maximo = maximo
        self.linhas = deque(maxlen=maximo)
        self.descartadas = 0

    def append(self, linha: str) -> None:
        if len(self.linhas) == self.maximo:
            self.descartadas += 1
        self.linhas.append(linha)

    def desde(self, indice: int) -> tuple[list, int]:
        inicio = max(0, indice - self.descartadas)
        atuais = list(self.linhas)
        return atuais[inicio:], self.descartadas + len(atuais)

    def texto(self) -> str:
        return "\n".join(self.linhas)


_pipeline_logs: dict = {}  # command -> _LogBuffer

def _find_pipeline_dir() -> str:
    if env := os.getenv("PIPELINE_SRC_PATH"):
        return env
    # tenta relativo ao __file__ (3 níveis acima de routers/)
    candidate = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ApostaEsportivas/src"))
    if os.path.isdir(candidate):
        return candidate
    # tenta relativo ao cwd (raiz do repo no Railway costuma ser /app)
    candidate2 = os.path.abspath(os.path.join(os.getcwd(), "ApostaEsportivas/src"))
    if os.path.isdir(candidate2):
        return candidate2
    return candidate  # retorna mesmo sem existir; o endpoint vai dar erro claro

_PIPELINE_DIR = _find_pipeline_dir()

router = APIRouter(prefix="/api/admin", tags=["admin"])

_VALID_PLANS = {"free", "trial", "vip", "admin"}
_VALID_SUB_TYPES = {"mensal", "trimestral", "semestral", "anual", None}


class UpdateUserBody(BaseModel):
    plan: Optional[str] = None
    subscription_type: Optional[str] = None
    active: Optional[bool] = None
    expires_at: Optional[datetime] = None

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v):
        if v is not None and v not in _VALID_PLANS:
            raise ValueError(f"Plano inválido. Use: {_VALID_PLANS}")
        return v

    @field_validator("subscription_type")
    @classmethod
    def validate_sub_type(cls, v):
        if v not in _VALID_SUB_TYPES:
            raise ValueError(f"Tipo inválido. Use: mensal, trimestral, semestral, anual")
        return v


class CreateUserBody(BaseModel):
    name: str
    email: str
    password: str
    plan: str = "free"

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v):
        if v not in _VALID_PLANS:
            raise ValueError(f"Plano inválido. Use: {_VALID_PLANS}")
        return v


@router.get("/users")
def list_users(current_user: dict = Depends(require_admin)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT u.id, u.name, u.email, u.phone, u.plan, u.subscription_type,
                   u.active, u.expires_at, u.created_at, u.last_login_at,
                   ub.bankroll_start AS bankroll_current, ub.unit_value
            FROM users u
            LEFT JOIN user_banca ub ON ub.user_id = u.id
            ORDER BY u.created_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


@router.post("/users")
def create_user(body: CreateUserBody, current_user: dict = Depends(require_admin)):
    import re
    # Mesma política de senha do cadastro público
    if len(body.password) < 10:
        raise HTTPException(400, "Senha deve ter pelo menos 10 caracteres")
    if not re.search(r"[A-Z]", body.password):
        raise HTTPException(400, "Senha deve ter letra maiúscula")
    if not re.search(r"\d", body.password):
        raise HTTPException(400, "Senha deve ter número")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email já cadastrado")
        cur.execute(
            "INSERT INTO users (name, email, password_hash, plan) VALUES (%s, %s, %s, %s) RETURNING id, name, email, plan, active",
            (' '.join(w.capitalize() for w in body.name.strip().split()), body.email, hash_password(body.password), body.plan),
        )
        user = dict(cur.fetchone())
        conn.commit()
        return user
    finally:
        cur.close()
        conn.close()


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UpdateUserBody, current_user: dict = Depends(require_admin)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        fields, values = [], []
        sent = body.model_fields_set
        if body.plan is not None:
            fields.append("plan = %s"); values.append(body.plan)
        if "subscription_type" in sent:
            fields.append("subscription_type = %s"); values.append(body.subscription_type or None)
        if body.active is not None:
            fields.append("active = %s"); values.append(body.active)
        if "expires_at" in sent:
            fields.append("expires_at = %s"); values.append(body.expires_at)

        if not fields:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        fields.append("updated_at = NOW()")
        values.append(user_id)

        cur.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = %s RETURNING id, name, email, plan, subscription_type, active, expires_at",
            values,
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        conn.commit()
        # Mudanca de plano feita pelo admin tem que valer na proxima requisicao
        # do usuario, nao no fim do TTL do cache de sessao (auth_utils).
        invalidar_cache_usuario(user_id)
        return dict(row)
    finally:
        cur.close()
        conn.close()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(require_admin)):
    if user_id == current_user.get("id"):
        raise HTTPException(400, "Você não pode deletar sua própria conta")
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Soft-delete: desativa em vez de apagar para manter histórico
        cur.execute("UPDATE users SET active = FALSE WHERE id = %s RETURNING id", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        conn.commit()
        invalidar_cache_usuario(user_id)
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


_PIPELINE_SCRIPTS = {
    "atualizar_jogos":      "atualizar_jogos.py",
    "capturar_odds":        "capturar_odds.py",
    # Variantes DEV dos coletores: no pipeline de homologacao/no-prod, dados e
    # odds tambem precisam cair no DB_ENV=dev. Antes so os passos `dev_gerar_*`
    # tinham prefixo dev_; `atualizar_jogos` e `capturar_odds` rodavam sem
    # prefixo, entao _run_and_track() mantinha o ambiente de producao. Resultado:
    # o banco DEV ficava sem fixtures/odds frescos e o motor DEV nao tinha de
    # onde gerar picks, apesar de PROD/no-prod mostrar jogos no dia.
    "dev_atualizar_jogos":  "atualizar_jogos.py",
    "dev_capturar_odds":    "capturar_odds.py",
    # Motor deterministico (services/pick_engine), mesmos modulos que
    # main.py::cmd_vip/cmd_dica/cmd_multiplas/cmd_alavancagem chamam desde o
    # corte de IA em producao (2026-07-17) -- os scripts de IA antigos
    # (gerar_sugestao_vip.py, ai/dica_do_dia_pipeline.py, etc) ficaram
    # esquecidos aqui, ainda ligados nesses botoes do admin apos o corte:
    # clicar "Rodar Tudo" ou qualquer "Gerar X" individual chamava IA de
    # verdade (custo real), nao o motor. Os scripts antigos continuam no
    # disco (sem uso, ver docstring de cmd_vip) so pra reverter rapido se
    # precisar.
    "gerar_vip":            os.path.join("engine_pipelines", "vip_pipeline.py"),
    "gerar_free":           os.path.join("engine_pipelines", "dica_pipeline.py"),
    "gerar_multipla":       os.path.join("engine_pipelines", "multipla_pipeline.py"),
    "gerar_alavancagem":    os.path.join("engine_pipelines", "alavancagem_pipeline.py"),
    # Faltas e defesas de goleiro (2026-08-01). Nao passam pelo caminho
    # generico do motor: usam modelo proprio (fouls_model / goalkeeper_model),
    # medido contra 946 jogos reais. Ver a docstring de cada pipeline.
    "gerar_faltas":         os.path.join("engine_pipelines", "faltas_pipeline.py"),
    # DEFESAS APONTAVA PRO PIPELINE ERRADO ate' 2026-08-27. Na arquitetura de
    # motores, defesa de goleiro deixou de ser motor e virou o metodo `saves`
    # do Player Stats -- `main.py tudo` ja' chamava o novo, e este botao
    # continuou no `goleiros_pipeline.py`, que so' existe no disco como
    # rollback. Os dois gravavam em TABELAS DIFERENTES (picks_goleiros contra
    # picks_player_stats), entao clicar aqui produzia um pick que a rodada
    # diaria nao produziria, e vice-versa.
    "gerar_goleiros":       os.path.join("engine_pipelines", "player_stats_pipeline.py"),
    # Os outros cinco metodos do Player Stats, e o Pick Boost. Fora do "Rodar
    # Tudo" pelo mesmo criterio do main.py: motor sem historico medido nao vira
    # custo fixo da rodada diaria. Botao proprio, sob demanda.
    "gerar_playerstats":    os.path.join("engine_pipelines", "player_stats_pipeline.py"),
    "gerar_pickboost":      os.path.join("engine_pipelines", "pick_boost_pipeline.py"),
    "atualizar_resultados": "atualizar_resultados_sugestoes.py",
    # Estatistica por jogador (/fixtures/players). Fora do "Rodar Tudo" de
    # proposito: gasta 1 requisicao da API por fixture e disputa a mesma cota
    # diaria da coleta de odds. Botao separado, sob demanda.
    "player_stats":         os.path.join("collectors", "player_stats_collector_service.py"),
    "dev_player_stats":     os.path.join("collectors", "player_stats_collector_service.py"),
    # Fase de homologacao/validacao (compara motor vs IA em uma base DEV
    # separada, ANTES de promover mudanca pro motor de producao acima) --
    # prefixo "dev_" sinaliza que _run_and_track() precisa injetar DB_ENV=dev
    # (ver _dev_env()) e exige DB_HOST_DEV configurado de verdade. Nao e' o
    # gatilho de producao (isso e' os steps gerar_* acima, sem prefixo).
    "dev_gerar_vip":           os.path.join("engine_pipelines", "vip_pipeline.py"),
    "dev_gerar_dica":          os.path.join("engine_pipelines", "dica_pipeline.py"),
    "dev_gerar_multipla":      os.path.join("engine_pipelines", "multipla_pipeline.py"),
    "dev_gerar_alavancagem":   os.path.join("engine_pipelines", "alavancagem_pipeline.py"),
    "dev_homolog_vip":         os.path.join("ai", "vip_engine_shadow.py"),
    "dev_homolog_dica":        os.path.join("ai", "dica_homologation.py"),
    "dev_homolog_multipla":    os.path.join("ai", "multipla_homologation.py"),
    "dev_homolog_alavancagem": os.path.join("ai", "alavancagem_homologation.py"),
}

#: Argumentos fixos de alguns passos. O /admin roda script por CAMINHO, entao
#: e' aqui que "so' o metodo saves" e' dito -- ver o comentario de
#: gerar_goleiros acima e o __main__ de player_stats_pipeline.py.
_PIPELINE_ARGS = {
    "gerar_goleiros": ["saves"],
}

_DEV_PIPELINE_STEPS = [
    "dev_atualizar_jogos", "dev_capturar_odds",
    "dev_gerar_vip", "dev_gerar_dica", "dev_gerar_multipla", "dev_gerar_alavancagem",
    "dev_homolog_vip", "dev_homolog_dica", "dev_homolog_multipla", "dev_homolog_alavancagem",
]

# Timeouts por comando (segundos). atualizar_jogos roda 7 stages (0 a 6) + API
# externa → precisa de mais tempo. O Stage 6 (histórico por time, 2026-08-13)
# tem teto próprio de 60 requisições, então não muda a ordem de grandeza daqui.
# Teto por script. O padrao era 5 min e matava coleta no meio -- capturar_odds
# em dia cheio passa disso com facilidade (uma requisicao por fixture), e o
# sintoma nao era "demorou": era o script morto na metade, com odd de parte dos
# jogos faltando e nenhum erro obvio. Pedido do usuario em 2026-08-11: 30 min
# pra todo mundo.
#
# Backfill de liga nova fica maior ainda: e' uma requisicao por jogo ja
# finalizado da temporada inteira, centenas numa liga de pontos corridos.
_PIPELINE_TIMEOUTS = {
    "coletar_liga":    2700.0,  # 45 min
    "default":         1800.0,  # 30 min
}

# Mesma sequencia do `main.py tudo` (ver o registro COMANDOS la: as etapas do
# pipeline sao as que declaram `etapa`). `atualizar_resultados` estava faltando
# aqui desde que estes passos nasceram junto com o scheduler das 00:10
# (9cdeb70e) -- o "Rodar Tudo" do site nunca liquidou pick nenhum, so' o CLI e
# o botao avulso faziam isso. Hoje a varredura por visita (routers/live.py::
# maybe_resolve_pending) cobre o caso comum, entao a etapa aqui e' rede: quem
# clica "Rodar Tudo" espera o dia inteiro resolvido, e ela e' idempotente.
_TUDO_STEPS = ["atualizar_jogos", "capturar_odds", "gerar_vip", "gerar_free",
               "gerar_multipla", "gerar_alavancagem", "gerar_faltas", "gerar_goleiros",
               # Pick Boost entrou em 2026-08-28, junto com a publicacao dele
               # pro assinante · produto publicado tem que ser gerado todo dia,
               # senao a aba abre vazia sem ninguem saber por que.
               "gerar_pickboost",
               "atualizar_resultados"]

_STEP_LABELS = {
    "atualizar_jogos":      "Atualizando jogos",
    "capturar_odds":        "Capturando odds",
    "dev_atualizar_jogos":  "Atualizando jogos DEV",
    "dev_capturar_odds":    "Capturando odds DEV",
    "gerar_vip":            "Gerando picks VIP",
    "gerar_free":           "Gerando pick gratuito",
    "gerar_multipla":       "Gerando múltipla",
    "gerar_alavancagem":    "Gerando alavancagem",
    "gerar_faltas":         "Gerando picks de faltas",
    "gerar_goleiros":       "Gerando defesas de goleiro",
    "gerar_playerstats":    "Gerando props de jogador",
    "gerar_pickboost":      "Escolhendo jogos do Pick Boost",
    "atualizar_resultados": "Atualizando resultados",
}


class PipelineCommandBody(BaseModel):
    command: str


def _dev_env(base_env: dict) -> dict:
    """Env pros steps "dev_*" (motor deterministico + homologacao) --
    EXIGE que DB_HOST_DEV (e as demais _DEV) estejam configuradas de
    verdade neste servico Railway, nunca fabrica a partir de DB_HOST
    unsuffixed (que neste mesmo processo pode ser producao -- ver
    website/backend/database.py::get_connection, usa DATABASE_URL/
    DB_HOST_PROD, esquema DIFERENTE do DB_ENV usado pelos scripts do
    motor). Fabricar _DEV a partir de credenciais desconhecidas geraria o
    risco real de o motor escrever picks numa base errada acreditando
    que e' DEV. Falha alto e claro em vez disso."""
    if not base_env.get("DB_HOST_DEV"):
        raise RuntimeError(
            "DB_HOST_DEV nao configurado neste ambiente -- os steps dev_* exigem as "
            "variaveis _DEV (DB_HOST_DEV, DB_PORT_DEV, DB_NAME_DEV, DB_USER_DEV, "
            "DB_PASS_DEV, DB_SSLMODE_DEV) configuradas explicitamente no Railway."
        )
    env = dict(base_env)
    env["DB_ENV"] = "dev"
    return env


async def _drenar(stream, buffers: list, prefixo: str = "") -> list:
    """Le o processo linha a linha e joga em todos os buffers de uma vez.

    E' o que troca "log no fim" por "log agora". `buffers` e' lista porque uma
    etapa dentro do `tudo` escreve no proprio log E no log corrido do pipeline
    -- quem clica em "Rodar tudo" quer uma fita so, nao nove separadas.

    Devolve as linhas pra o rabo continuar disponivel em `log` como antes.
    """
    coletadas = []
    async for cru in stream:
        linha = cru.decode(errors="replace").rstrip()
        if not linha:
            continue
        coletadas.append(linha)
        for b in buffers:
            b.append(prefixo + linha)
    return coletadas


async def _run_and_track(command: str, script: str, args: list | None = None,
                         extra: dict | None = None, espelhar_em: str | None = None):
    """Roda o script e mantem _pipeline_status[command] atualizado.

    `extra` vai junto em TODA escrita do status (inicio, fim e erro) -- e' como
    a coleta de liga carrega qual liga esta rodando, pra tela saber em qual
    linha mostrar "Coletando...". Guardar so' no inicio nao serviria: o dict e'
    substituido inteiro no fim.

    `espelhar_em`: nome de outro buffer que recebe as mesmas linhas. E' o que o
    `tudo` usa pra ter um log continuo das nove etapas.
    """
    now = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    started = now()
    extra = extra or {}
    _pipeline_status[command] = {"status": "running", "started_at": started, "finished_at": None, "returncode": None, "error": None, **extra}
    buffer = _LogBuffer()
    _pipeline_logs[command] = buffer
    destinos = [buffer]
    if espelhar_em:
        destinos.append(_pipeline_logs.setdefault(espelhar_em, _LogBuffer()))
    timeout = _PIPELINE_TIMEOUTS.get(command, _PIPELINE_TIMEOUTS["default"])
    try:
        env = {**os.environ, "PYTHONPATH": _PIPELINE_DIR}
        env["AI_REVIEW_ENV"] = "dev" if command.startswith("dev_") else "prod"
        if command.startswith("dev_"):
            env = _dev_env(env)
        # PYTHONUNBUFFERED: sem isto o Python do subprocesso segura a saida num
        # buffer de 4KB quando nao ha terminal, e o log "ao vivo" chegaria em
        # blocos de minutos em minutos -- que e' quase o problema que ele veio
        # resolver.
        env["PYTHONUNBUFFERED"] = "1"
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script, *(args or []),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_PIPELINE_DIR,
            env=env,
        )
        tarefas = [
            asyncio.ensure_future(_drenar(proc.stdout, destinos)),
            asyncio.ensure_future(_drenar(proc.stderr, destinos, prefixo="! ")),
        ]
        try:
            await asyncio.wait_for(
                asyncio.gather(*tarefas, asyncio.ensure_future(proc.wait())),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            for t in tarefas:
                t.cancel()
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"Script excedeu o limite de {int(timeout // 60)} minutos e foi encerrado")
        returncode = proc.returncode
        linhas_out = tarefas[0].result() if tarefas[0].done() and not tarefas[0].cancelled() else []
        linhas_err = tarefas[1].result() if tarefas[1].done() and not tarefas[1].cancelled() else []
        out = "\n".join(linhas_out)[-1500:]
        err = "\n".join(linhas_err)[-1500:]
        _pipeline_status[command] = {
            "status": "ok" if returncode == 0 else "error",
            "started_at": started,
            "finished_at": now(),
            "returncode": returncode,
            "log": out,
            "error": err if returncode != 0 else (err or None),
            **extra,
        }
    except Exception as e:
        for destino in destinos:
            destino.append(f"! {e}")
        _pipeline_status[command] = {"status": "error", "started_at": started, "finished_at": now(), "returncode": -1, "error": str(e), **extra}


async def _run_tudo():
    now = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    started = now()
    _pipeline_status["tudo"] = {"status": "running", "started_at": started, "finished_at": None, "returncode": None, "error": None, "log": "Iniciando..."}
    # Buffer NOVO a cada rodada: log da rodada passada misturado com a de agora
    # e' pior que log nenhum, porque parece progresso.
    _pipeline_logs["tudo"] = _LogBuffer()
    total = len(_TUDO_STEPS)
    for i, cmd in enumerate(_TUDO_STEPS, start=1):
        script = os.path.join(_PIPELINE_DIR, _PIPELINE_SCRIPTS[cmd])
        _pipeline_status["tudo"]["log"] = f"Rodando {cmd}..."
        _pipeline_logs["tudo"].append(
            f"─── [{i}/{total}] {_STEP_LABELS.get(cmd, cmd)} " + "─" * 20)
        await _run_and_track(cmd, script, args=_PIPELINE_ARGS.get(cmd),
                             espelhar_em="tudo")
        if _pipeline_status[cmd]["status"] == "error":
            err = _pipeline_status[cmd].get("error") or _pipeline_status[cmd].get("log") or ""
            _pipeline_status["tudo"] = {"status": "error", "started_at": started, "finished_at": now(), "returncode": -1, "error": f"Falhou em '{cmd}': {err[:300]}"}
            return
    _pipeline_status["tudo"] = {"status": "ok", "started_at": started, "finished_at": now(), "returncode": 0, "log": "Pipeline completo!", "error": None}
    _notificar_picks_publicados()


def _notificar_picks_publicados():
    """Push + item no sino + limpeza de notificacao velha, depois que o
    pipeline gerou os picks do dia.

    Isso vivia no scheduler (_job_run_daily_pipeline), removido em 2026-08-01.
    Como agora o pipeline SO' roda por disparo manual, sem mover isso pra ca o
    usuario geraria os picks e ninguem seria avisado -- justamente o oposto do
    que ele quer ao publicar no horario que escolher.

    Cada bloco engole a propria excecao de proposito: falha de push ou de
    notificacao nao pode fazer o pipeline (que ja gravou os picks) parecer que
    falhou.
    """
    logger = logging.getLogger(__name__)

    try:
        from routers.notifications import send_push_to_all_vip

        send_push_to_all_vip(
            title="Picks do dia publicados",
            body="Seus picks de hoje estao disponiveis. Confira agora!",
            url="/picks",
        )
    except Exception as push_err:
        logger.warning("[PUSH] Erro ao enviar push pos-pipeline: %s", push_err)

    # In-app: o push some da bandeja e nao volta, o item do sino fica pra quem
    # so' abriu o site mais tarde (ou nunca aceitou push).
    try:
        from zoneinfo import ZoneInfo

        from routers.notifications import TYPE_NEW_PICKS, notify_all_users

        today_key = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
        created = notify_all_users(
            TYPE_NEW_PICKS,
            title="Picks do dia publicados",
            dedupe_key=f"new_picks:{today_key}",
            body="Os picks de hoje ja estao disponiveis.",
            url="/picks",
            payload={"date": today_key},
        )
        logger.info("[NOTIF] Picks do dia: %d notificacoes criadas.", created)
    except Exception as notif_err:
        logger.warning("[NOTIF] Erro ao criar notificacoes pos-pipeline: %s", notif_err)

    try:
        from routers.notifications import purge_old_notifications

        removed = purge_old_notifications()
        if removed:
            logger.info("[NOTIF] %d notificacoes antigas descartadas.", removed)
    except Exception as purge_err:
        logger.warning("[NOTIF] Erro na limpeza de notificacoes: %s", purge_err)


async def _run_dev_pipeline():
    """Motor deterministico + fase de homologacao (ver plano de validacao
    antes de promover pra producao) -- coleta jogos/odds do dia, roda os 4
    engine_pipelines de verdade (grava picks reais em DEV) e os 4 scripts
    de homologacao (so leitura + log JSONL, comparam contra o pick real
    da IA em PROD). Sem custo de API -- motor determinista, nunca chama
    Anthropic. So roda de fato quando DB_HOST_DEV existe (ver _dev_env)."""
    now = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    started = now()
    _pipeline_status["dev_tudo"] = {"status": "running", "started_at": started, "finished_at": None, "returncode": None, "error": None, "log": "Iniciando..."}
    for cmd in _DEV_PIPELINE_STEPS:
        script = os.path.join(_PIPELINE_DIR, _PIPELINE_SCRIPTS[cmd])
        _pipeline_status["dev_tudo"]["log"] = f"Rodando {cmd}..."
        await _run_and_track(cmd, script, args=_PIPELINE_ARGS.get(cmd))
        if _pipeline_status[cmd]["status"] == "error":
            err = _pipeline_status[cmd].get("error") or _pipeline_status[cmd].get("log") or ""
            _pipeline_status["dev_tudo"] = {"status": "error", "started_at": started, "finished_at": now(), "returncode": -1, "error": f"Falhou em '{cmd}': {err[:300]}"}
            return
    _pipeline_status["dev_tudo"] = {"status": "ok", "started_at": started, "finished_at": now(), "returncode": 0, "log": "Pipeline DEV completo!", "error": None}


@router.get("/db-pool")
def db_pool(current_user: dict = Depends(require_admin)):
    """Estado do pool de conexao.

    Serve pra responder duas perguntas sem adivinhar: o pool subiu mesmo, e
    esta havendo `fallback` (pool cheio, abrindo conexao direta). Fallback
    subindo e' o sinal de que DB_POOL_MAX ficou pequeno pro trafego.
    """
    from database import pool_stats
    return pool_stats()


@router.get("/pipeline-status")
def pipeline_status(current_user: dict = Depends(require_admin)):
    return _pipeline_status


@router.get("/pipeline-log")
def pipeline_log(command: str = "tudo", desde: int = 0,
                 current_user: dict = Depends(require_admin)):
    """Log ao vivo de uma etapa (ou do `tudo`, que junta as nove).

    SO' ADMIN, e nao e' formalidade: a saida crua dos scripts carrega host de
    banco, nome de liga em coleta, contagem de requisicao de API e traceback
    completo quando algo quebra. Nada disso pode vazar pra tela de espera do
    assinante -- essa continua em /pipeline-status-public, que expoe so' o
    rotulo da etapa.

    `desde` e' o indice devolvido na chamada anterior: a tela pesquisa de
    segundo em segundo e recebe so' o que chegou no intervalo, em vez de
    rebaixar o log inteiro toda vez. Reiniciar com desde=0 devolve tudo que o
    buffer ainda tem.
    """
    buffer = _pipeline_logs.get(command)
    if buffer is None:
        return {"linhas": [], "proximo": 0, "status": (_pipeline_status.get(command) or {}).get("status")}
    linhas, proximo = buffer.desde(desde)
    return {
        "linhas": linhas,
        "proximo": proximo,
        "status": (_pipeline_status.get(command) or {}).get("status"),
    }


@router.get("/ai-review-status")
def ai_review_status(current_user: dict = Depends(require_admin)):
    """Resumo persistido das revisoes, inclusive depois de restart do Railway."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS reviews_24h,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours' AND decision = 'reject') AS rejected_24h,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours' AND cached) AS cache_hits_24h,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS reviews_today
        FROM ai_pick_review_events""")
        summary = dict(cur.fetchone())
        cur.execute("""SELECT pipeline, mode, provider, model, status, decision, risk_level,
                              cached, review, created_at
                       FROM ai_pick_review_events
                       ORDER BY created_at DESC LIMIT 25""")
        events = [dict(row) for row in cur.fetchall()]
        return {
            "config": {
                "environment": os.getenv("AI_REVIEW_ENV", "prod"),
                "mode": os.getenv("AI_REVIEW_MODE_PROD", os.getenv("AI_REVIEW_MODE", "off")),
                "daily_limit": int(os.getenv("AI_REVIEW_DAILY_LIMIT_PROD", os.getenv("AI_REVIEW_DAILY_LIMIT", "15"))),
            },
            "summary": summary,
            "events": events,
        }
    except Exception as error:
        if "ai_pick_review_events" in str(error):
            return {"config": {"mode": "off"}, "summary": {}, "events": [], "migration_pending": True}
        raise
    finally:
        cur.close()
        conn.close()


# Pipeline do gate de IA -> pick_type gravado no ledger. Sao vocabularios
# diferentes pro mesmo fluxo ("dica" no motor, "free" no ledger) e a juncao
# abaixo depende deste mapa.
_PIPELINE_POR_PICK_TYPE = {
    "vip": "vip", "free": "dica", "multipla": "multipla",
    "alavancagem": "alavancagem", "faltas": "faltas", "goleiros": "goleiros",
    "player_stats": "player_stats", "boost": "boost",
}

#: Nome do mercado em portugues. `market_type` e' a chave estavel do motor
#: (o texto de `market` varia: "Escanteios Mais/Menos", "Total de Escanteios
#: Casa"...), entao a agregacao usa o tipo e a tela mostra este rotulo.
MERCADO_LABEL = {
    "corners": "Escanteios", "cards": "Cartões", "goals": "Gols",
    "shots": "Finalizações",
    "fouls": "Faltas", "saves": "Defesas de goleiro",
    "offsides": "Impedimentos", "result": "Resultado",
    "btts": "Ambas marcam", "handicap": "Handicap",
    "corner_race": "Corrida de escanteios", "possession": "Posse de bola",
    "shots_on_target": "Chutes no gol", "shots_on_goal": "Chutes no gol",
    "handicap_goals": "Handicap de gols", "handicap_cards": "Handicap de cartões",
    "handicap_corners": "Handicap de escanteios", "double_chance": "Dupla chance",
    "outcome": "Resultado", "unknown": "Sem tipo gravado", "outros": "Sem tipo gravado",
}


# Status em que um modelo de fato emitiu parecer. Fora desta lista, o gate
# falhou aberto (unavailable), nao rodou (disabled) ou bateu no teto do dia
# (daily_limit_reached) -- o pick foi publicado sem nenhuma IA ter olhado pra
# ele, e creditar esse resultado a um modelo seria mentira estatistica.
_STATUS_COM_PARECER = {"ok"}


def _bucket() -> dict:
    return {"n": 0, "green": 0, "red": 0, "push": 0, "pendentes": 0,
            "lucro": 0.0, "_clv": [], "_com_lucro": 0}


def _add(bucket: dict, row: dict) -> None:
    bucket["n"] += 1
    resultado = (row.get("result") or "").upper()
    if resultado == "GREEN":
        bucket["green"] += 1
    elif resultado == "RED":
        bucket["red"] += 1
    elif resultado == "PUSH":
        bucket["push"] += 1
    else:
        bucket["pendentes"] += 1
    if row.get("profit") is not None:
        bucket["lucro"] += float(row["profit"])
        bucket["_com_lucro"] += 1
    if row.get("clv") is not None:
        bucket["_clv"].append(float(row["clv"]))


def _fechar(bucket: dict) -> dict:
    resolvidos = bucket["green"] + bucket["red"]
    clvs = bucket.pop("_clv")
    com_lucro = bucket.pop("_com_lucro")
    return {
        **bucket,
        "resolvidos": resolvidos,
        # Sem PUSH no denominador: aposta anulada nao e' acerto nem erro.
        "hit": round(bucket["green"] / resolvidos * 100, 1) if resolvidos else None,
        "lucro": round(bucket["lucro"], 2),
        # ROI a 1 unidade por perna -- o stake real varia por usuario (Kelly),
        # entao unidade e' a unica base comparavel entre modelos.
        "roi": round(bucket["lucro"] / com_lucro * 100, 1) if com_lucro else None,
        "clv": round(sum(clvs) / len(clvs) * 100, 2) if clvs else None,
    }


@router.get("/ai-performance")
def ai_performance(days: int = 60, current_user: dict = Depends(require_admin)):
    """Compara os modelos que revisam os picks, pelo resultado do que cada um
    aprovou e do que cada um quis vetar.

    O motor de picks e' deterministico: nenhuma IA escolhe a aposta, ela so'
    aprova ou veta o que o motor ja' decidiu (ver AI_REVIEW.md). Entao "qual IA
    da' mais green" so' tem resposta honesta por dois numeros:

      1. hit dos picks que o modelo APROVOU;
      2. hit dos picks que ele quis VETAR -- que so' existe porque o gate roda
         em modo sombra, onde o veto e' registrado mas o pick sai assim mesmo.

    O segundo e' o que realmente mede a IA. Se o que ela vetou deu MAIS red que
    o que ela aprovou, o veto esta' separando certo e vale ligar o enforce; se
    deu menos, ligar o enforce so' derrubaria pick bom.

    A diferenca entre os dois e' o `lift`. Comparar `lift` entre modelos so'
    vale dentro do MESMO pipeline: cada fluxo tem provider proprio e
    dificuldade propria, entao o total por modelo mistura mercados diferentes.
    Por isso `por_pipeline` vem junto e a tela mostra os dois.
    """
    days = max(1, min(int(days), 365))
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'picks_ledger' AND column_name = 'ai_model' LIMIT 1""")
        if not cur.fetchone():
            return {"days": days, "migration_pending": True, "modelos": [],
                    "por_pipeline": [], "falhas": [], "cobertura": {}}

        cur.execute("""
            SELECT pick_type, ai_provider, ai_model, ai_decision, ai_status,
                   market, market_type, odd,
                   result, profit, clv, created_at::date AS dia
            FROM picks_ledger
            WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
        """, (days,))
        legs = [dict(r) for r in cur.fetchall()]

        # Contagem de chamadas por modelo: vem dos eventos, nao das pernas.
        # Uma revisao cobre o bilhete inteiro (multipla/alavancagem tem 2-3
        # pernas), entao contar perna inflaria o custo por modelo.
        eventos_por_modelo: dict = {}
        atribuicao_por_dia: dict = {}
        try:
            cur.execute("""
                SELECT provider, model, pipeline, created_at::date AS dia,
                       COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE cached) AS cache,
                       COUNT(*) FILTER (WHERE decision = 'reject') AS vetos,
                       COUNT(*) FILTER (WHERE status <> 'ok') AS falhas
                FROM ai_pick_review_events
                WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
                GROUP BY 1, 2, 3, 4
            """, (days,))
            for row in cur.fetchall():
                chave = (row["provider"], row["model"])
                acc = eventos_por_modelo.setdefault(chave, {
                    "reviews": 0, "cache": 0, "vetos": 0, "falhas": 0, "pipelines": set()})
                acc["reviews"] += row["n"]
                acc["cache"] += row["cache"]
                acc["vetos"] += row["vetos"]
                acc["falhas"] += row["falhas"]
                acc["pipelines"].add(row["pipeline"])
                # Pick anterior a 2026-08-08 nao guarda quem o revisou. O
                # provider e' configurado por pipeline, entao o modelo que mais
                # revisou aquele fluxo naquele dia e' a melhor atribuicao
                # possivel -- exata quando a configuracao nao mudou no dia, que
                # e' o caso normal. Marcada como "inferida" na resposta.
                dia_chave = (row["pipeline"], str(row["dia"]))
                atual = atribuicao_por_dia.get(dia_chave)
                if not atual or row["n"] > atual[1]:
                    atribuicao_por_dia[dia_chave] = (chave, row["n"])
        except Exception as error:
            if "ai_pick_review_events" not in str(error):
                raise
            conn.rollback()

        por_modelo: dict = {}
        por_pipeline: dict = {}
        # Por MERCADO, e nao por modelo · e' a pergunta que o painel nao
        # respondia. "Qual IA e' melhor" so' tem resposta marginal aqui (a IA
        # nao escolhe pick, so' veta), mas "escanteio esta' dando prejuizo?"
        # decide o que fazer com o motor amanha de manha.
        #
        # `todos` conta TODA perna do periodo, com parecer ou sem: e' o
        # desempenho real do mercado. `aprovados`/`vetados` so' contam onde
        # houve parecer, e servem pra ver se o veto acerta naquele mercado.
        por_mercado: dict = {}
        falhas_por_status: dict = {}
        cobertura = {"pernas": len(legs), "com_parecer": 0, "sem_parecer": 0,
                     "autor_gravado": 0, "autor_inferido": 0, "autor_desconhecido": 0}

        for leg in legs:
            mercado = por_mercado.setdefault(
                leg.get("market_type") or "outros",
                {"todos": _bucket(), "aprovados": _bucket(), "vetados": _bucket()},
            )
            _add(mercado["todos"], leg)

            status = leg.get("ai_status")
            if status and status not in _STATUS_COM_PARECER:
                falhas_por_status[status] = falhas_por_status.get(status, 0) + 1
            if status not in _STATUS_COM_PARECER:
                cobertura["sem_parecer"] += 1
                continue
            cobertura["com_parecer"] += 1

            if leg.get("ai_model"):
                chave = (leg.get("ai_provider"), leg["ai_model"])
                cobertura["autor_gravado"] += 1
            else:
                pipeline = _PIPELINE_POR_PICK_TYPE.get(leg["pick_type"], leg["pick_type"])
                inferido = atribuicao_por_dia.get((pipeline, str(leg["dia"])))
                if not inferido:
                    cobertura["autor_desconhecido"] += 1
                    continue
                chave = inferido[0]
                cobertura["autor_inferido"] += 1

            lado = "vetados" if leg.get("ai_decision") == "reject" else "aprovados"
            _add(mercado[lado], leg)

            modelo = por_modelo.setdefault(chave, {"aprovados": _bucket(), "vetados": _bucket()})
            _add(modelo[lado], leg)

            chave_pipe = (leg["pick_type"], chave)
            pipe = por_pipeline.setdefault(chave_pipe, {"aprovados": _bucket(), "vetados": _bucket()})
            _add(pipe[lado], leg)

        def _monta(provider, model, aprovados, vetados, evento=None) -> dict:
            ap, vt = _fechar(aprovados), _fechar(vetados)
            # Positivo = o modelo aprovou melhor do que vetou, ou seja, o veto
            # esta' separando pick ruim de pick bom. Negativo = o veto derrubaria
            # justamente os melhores.
            lift = (round(ap["hit"] - vt["hit"], 1)
                    if ap["hit"] is not None and vt["hit"] is not None else None)
            return {
                "provider": provider, "model": model,
                "aprovados": ap, "vetados": vt, "lift": lift,
                # Quanto o veto teria poupado (ou custado) em unidades se o
                # enforce estivesse ligado: o lucro dos vetados, invertido.
                "economia_do_veto": round(-vt["lucro"], 2) if vt["resolvidos"] else None,
                **({"reviews": evento["reviews"], "cache": evento["cache"],
                    "chamadas": evento["reviews"] - evento["cache"],
                    "vetos": evento["vetos"], "falhas": evento["falhas"],
                    "taxa_veto": round(evento["vetos"] / evento["reviews"] * 100, 1)
                                 if evento["reviews"] else None,
                    "pipelines": sorted(evento["pipelines"])} if evento else {}),
            }

        modelos = []
        for chave in set(por_modelo) | set(eventos_por_modelo):
            provider, model = chave
            dados = por_modelo.get(chave) or {"aprovados": _bucket(), "vetados": _bucket()}
            modelos.append(_monta(provider, model, dados["aprovados"], dados["vetados"],
                                  eventos_por_modelo.get(chave)))
        modelos.sort(key=lambda m: m["aprovados"]["resolvidos"], reverse=True)

        pipelines = []
        for (pick_type, chave), dados in por_pipeline.items():
            item = _monta(chave[0], chave[1], dados["aprovados"], dados["vetados"])
            pipelines.append({"pick_type": pick_type, **item})
        pipelines.sort(key=lambda p: (p["pick_type"], -p["aprovados"]["resolvidos"]))

        mercados = [
            {
                "market_type": mtype,
                "label": MERCADO_LABEL.get(mtype, mtype),
                "todos": _fechar(dados["todos"]),
                "aprovados": _fechar(dados["aprovados"]),
                "vetados": _fechar(dados["vetados"]),
            }
            for mtype, dados in por_mercado.items()
        ]
        # Ordena pelo que mais pesa no bolso, do pior pro melhor: quem abre a
        # tela precisa ver primeiro o mercado que esta' sangrando, nao o que
        # tem mais volume.
        mercados.sort(key=lambda m: m["todos"]["lucro"])

        return {
            "days": days,
            "cobertura": cobertura,
            "modelos": modelos,
            "por_mercado": mercados,
            "por_pipeline": pipelines,
            "falhas": [{"status": s, "n": n} for s, n in
                       sorted(falhas_por_status.items(), key=lambda kv: -kv[1])],
        }
    finally:
        cur.close()
        conn.close()


@router.get("/pipeline-status-public")
def pipeline_status_public(current_user: dict = Depends(get_current_user)):
    """Status simplificado do pipeline (sem logs/erros técnicos) para a tela de espera dos usuários."""
    tudo = _pipeline_status.get("tudo", {})
    steps = []
    for key in _TUDO_STEPS:
        raw = _pipeline_status.get(key, {}).get("status")
        if raw == "ok":
            status = "done"
        elif raw == "running":
            status = "running"
        elif raw == "error":
            status = "error"
        else:
            status = "pending"
        steps.append({"key": key, "label": _STEP_LABELS[key], "status": status})
    return {
        "running":  tudo.get("status") == "running",
        "finished": tudo.get("status") == "ok",
        "steps":    steps,
    }


@router.post("/run-pipeline")
async def run_pipeline(body: PipelineCommandBody, current_user: dict = Depends(require_admin)):
    if body.command == "tudo":
        asyncio.create_task(_run_tudo())
        return {"ok": True, "status": "iniciado"}

    if body.command == "dev_tudo":
        asyncio.create_task(_run_dev_pipeline())
        return {"ok": True, "status": "iniciado"}

    if body.command not in _PIPELINE_SCRIPTS:
        raise HTTPException(400, detail=f"Comando inválido. Use: {list(_PIPELINE_SCRIPTS)}")

    script = os.path.join(_PIPELINE_DIR, _PIPELINE_SCRIPTS[body.command])
    if not os.path.exists(script):
        raise HTTPException(500, detail=f"Script não encontrado: {script}")

    asyncio.create_task(_run_and_track(body.command, script,
                                       args=_PIPELINE_ARGS.get(body.command)))
    return {"ok": True, "status": "iniciado"}


class SyncPaymentBody(BaseModel):
    mp_payment_id: str


@router.post("/sync-payment")
async def sync_payment(body: SyncPaymentBody, current_user: dict = Depends(require_admin)):
    """Reprocessa um pagamento do MercadoPago pelo ID · ativa VIP manualmente se aprovado.

    A regra de ativação (estender em vez de sobrescrever, creditar indicação,
    mandar e-mail) vive em routers/payments.py e é a mesma do webhook. Esta
    rota já teve a sua própria cópia dela, que silenciosamente esquecia o
    crédito de indicação e o e-mail.
    """
    import mercadopago as _mp
    from routers.payments import _apply_approved_payment

    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        raise HTTPException(500, "MERCADOPAGO_ACCESS_TOKEN não configurado")

    sdk = _mp.SDK(access_token)
    payment = (sdk.payment().get(body.mp_payment_id) or {}).get("response") or {}

    resultado = _apply_approved_payment(payment, "admin_sync")
    if resultado["status"] == "not_approved":
        raise HTTPException(400, f"Pagamento não aprovado ({resultado['detail']})")
    if resultado["status"] == "error":
        raise HTTPException(400, resultado["detail"])
    if resultado["status"] == "duplicate":
        return {"ok": True, "duplicate": True, "detail": "Pagamento já estava registrado."}

    return {
        "ok":   True,
        "user": {"id": resultado["user_id"], "name": resultado["user_name"], "email": resultado["user_email"]},
        "plan": resultado["plan"],
        "expires_at": resultado["expires_at"].isoformat(),
    }


class ReconcileBody(BaseModel):
    days: int = 30


@router.post("/reconcile-payments")
async def reconcile_payments(body: ReconcileBody, current_user: dict = Depends(require_admin)):
    """Varre os pagamentos aprovados no MercadoPago e ativa o que faltou.

    Rede de segurança do dinheiro: não depende de webhook nenhum, pergunta ao
    MercadoPago o que ele registrou e compara com a tabela `payments`. Quem já
    está lá cai no ON CONFLICT, então rodar de novo não estende VIP de ninguém.
    """
    from routers.payments import _reconcile

    dias = max(1, min(int(body.days or 30), 180))
    return _reconcile(f"NOW-{dias}DAYS", "admin_reconcile")


@router.get("/payment-events")
def admin_payment_events(current_user: dict = Depends(require_admin)):
    """Últimas tentativas de processar pagamento · inclui as recusadas.

    É aqui que aparece webhook rejeitado por assinatura, que antes não deixava
    rastro em lugar nenhum.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT source, status, mp_payment_id, detail, created_at
            FROM payment_events
            ORDER BY created_at DESC
            LIMIT 50
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


@router.get("/revenue")
def admin_revenue(current_user: dict = Depends(require_admin)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                COALESCE(SUM(amount), 0)   AS total,
                COUNT(*)                    AS count,
                COALESCE(AVG(amount), 0)   AS avg_ticket
            FROM payments WHERE status = 'approved'
        """)
        totals = dict(cur.fetchone())

        # Mesmo erro de 6h que estava em banca.py: `created_at` e' timestamp
        # ingenuo em UTC, entao um AT TIME ZONE so' o trata como se ja fosse
        # horario de Brasilia. Pagamento feito depois das 18:00 BR caia no mes
        # seguinte na virada. Ver data_br.py.
        cur.execute(f"""
            SELECT
                TO_CHAR({data_br('created_at')}, 'YYYY-MM') AS month,
                COALESCE(SUM(amount), 0) AS total,
                COUNT(*)                 AS count
            FROM payments
            WHERE status = 'approved'
              AND created_at >= NOW() - INTERVAL '12 months'
            GROUP BY month
            ORDER BY month DESC
        """)
        monthly = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT
                plan_key,
                COALESCE(SUM(amount), 0) AS total,
                COUNT(*)                 AS count
            FROM payments
            WHERE status = 'approved'
            GROUP BY plan_key
            ORDER BY total DESC
        """)
        by_plan = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(*) AS active_vip FROM users
            WHERE plan = 'vip' AND expires_at > NOW() AND active = true
        """)
        active_vip = cur.fetchone()["active_vip"]

        return {
            "total":      float(totals["total"]),
            "count":      int(totals["count"]),
            "avg_ticket": float(totals["avg_ticket"]),
            "monthly":    [{"month": r["month"], "total": float(r["total"]), "count": int(r["count"])} for r in monthly],
            "by_plan":    [{"plan": r["plan_key"], "total": float(r["total"]), "count": int(r["count"])} for r in by_plan],
            "active_vip": int(active_vip),
        }
    finally:
        cur.close()
        conn.close()


@router.get("/payments")
def admin_payments(current_user: dict = Depends(require_admin)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT p.mp_payment_id, p.plan_key, p.amount, p.status,
                   p.payment_method, p.expires_at, p.created_at,
                   u.name AS user_name, u.email AS user_email
            FROM payments p
            JOIN users u ON u.id = p.user_id
            ORDER BY p.created_at DESC
            LIMIT 100
        """)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        cur.close()
        conn.close()


_PICK_TABLES = {
    "vip":         ("picks_vip",        "home_team_name", "away_team_name"),
    "free":        ("picks_free",        "home_team",      "away_team"),
    "multipla":    ("picks_multiplas",   "home_team_name", "away_team_name"),
    "alavancagem": ("picks_alavancagem", "home_team_1",    "away_team_1"),
    "faltas":      ("picks_faltas",      "home_team",      "away_team"),
    "goleiros":    ("picks_goleiros",    "home_team",      "away_team"),
    # Player Stats (27/08). Sem a entrada, marcar resultado a mao num pick de
    # jogador pelo /admin devolvia "tipo invalido" -- e e' justamente o tipo
    # mais novo, o que mais precisa de correcao manual enquanto e' medido.
    "player_stats": ("picks_player_stats", "home_team",     "away_team"),
    "boost":        ("picks_boost",        "home_team",     "away_team"),
}
_VALID_RESULTS = {"GREEN", "RED", "PUSH", "HALF-WIN", "HALF-LOSS", None}

#: Coluna de odd de cada tabela · NAO e' `odd` em todas.
#:
#: `SELECT odd FROM picks_alavancagem` estoura com "column odd does not exist",
#: e era por isso que marcar RED numa alavancagem pelo /admin devolvia erro em
#: qualquer ambiente. Multipla tinha o mesmo problema. O mapeamento ja existia
#: em /picks/search, escrito inline; aqui vira constante pra nao precisar
#: existir uma terceira vez.
_ODD_COL = {
    "vip": "odd", "free": "odd", "faltas": "odd", "goleiros": "odd",
    "player_stats": "odd", "boost": "odd",
    "multipla": "total_odd", "alavancagem": "odd_combined",
}


#: Tabelas com UMA fixture por pick · só nelas dá pra cruzar com
#: match_statistics e dizer se o provedor publicou a folha do jogo.
_PICK_TABLES_UMA_FIXTURE = ("vip", "free", "faltas", "goleiros", "player_stats", "boost")


@router.get("/users/engajamento")
def admin_users_engajamento(current_user: dict = Depends(require_admin)):
    """Quem ainda aparece, quem sumiu, e quem o WhatsApp alcançaria.

    As duas perguntas moram na mesma rota porque são a mesma consulta: a
    audiência de cada aviso do WhatsApp é um recorte de atividade, e calcular
    isso em dois lugares é como as contagens começam a divergir.

    O corte de inatividade é 10 dias porque é o segmento de reengajamento
    definido em website/scripts/whatsapp/ · alterar aqui sem alterar lá faz o
    painel prometer um número de envios que o disparo não cumpre.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                COUNT(*)                                                          AS total,
                COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '1 day')  AS hoje,
                COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '7 days') AS semana,
                COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '30 days') AS mes,
                COUNT(*) FILTER (WHERE last_login_at IS NULL)                      AS nunca_entrou,
                COUNT(*) FILTER (WHERE last_login_at <  NOW() - INTERVAL '10 days') AS inativos_10d,
                COUNT(*) FILTER (WHERE phone IS NOT NULL AND phone <> '')          AS com_telefone,
                COUNT(*) FILTER (WHERE COALESCE(whatsapp_opt_in, FALSE))           AS com_opt_in,
                COUNT(*) FILTER (WHERE plan IN ('vip','admin'))                    AS vips
            FROM users
        """)
        u = dict(cur.fetchone() or {})

        # Audiência de cada template. `com_opt_in` é o teto real de todos eles:
        # sem consentimento não sai mensagem, por mais que o telefone exista.
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE COALESCE(whatsapp_opt_in, FALSE))            AS picks_do_dia,
                COUNT(*) FILTER (WHERE COALESCE(whatsapp_opt_in, FALSE)
                                   AND (last_login_at IS NULL
                                        OR last_login_at < NOW() - INTERVAL '10 days')) AS reengajamento
            FROM users
            WHERE phone IS NOT NULL AND phone <> ''
        """)
        w = dict(cur.fetchone() or {})

        # Resultado green/red só alcança quem SEGUIU pick · é o que diferencia
        # esse aviso dos outros dois, e o motivo de ele ser barato.
        cur.execute("""
            SELECT COUNT(DISTINCT uf.user_id) AS n
              FROM user_followed_picks uf
              JOIN users us ON us.id = uf.user_id
             WHERE COALESCE(us.whatsapp_opt_in, FALSE)
               AND uf.followed_at >= NOW() - INTERVAL '30 days'
        """)
        seguidores = int((cur.fetchone() or {}).get("n") or 0)

        return {
            "usuarios": {k: int(v or 0) for k, v in u.items()},
            "whatsapp": {
                "picks_do_dia":   int(w.get("picks_do_dia") or 0),
                "resultado":      seguidores,
                "reengajamento":  int(w.get("reengajamento") or 0),
                # Nada foi implementado do lado do envio · o painel mostra
                # audiência, não fila de disparo, e dizer isso evita que o
                # número seja lido como "vai sair".
                "envio_ativo":    False,
            },
        }
    finally:
        cur.close()
        conn.close()


@router.get("/picks/pendentes")
def admin_picks_pendentes(
    horas: int = Query(4, ge=1, le=240),
    current_user: dict = Depends(require_admin),
):
    """Picks cujo jogo já devia ter terminado e que continuam sem resultado.

    POR QUE ISTO EXISTE. Estatística ausente nunca vira RED · é a invariante 1
    de services/settlement.py, escrita depois de um pick de escanteios ser
    gravado RED porque `home_stats.get("Corner Kicks", 0)` devolveu 0 no
    instante do apito final. A regra está certa e continua valendo.

    Só que "não liquida e espera" é silencioso por natureza: se a folha do jogo
    nunca chegar, o pick fica pendente pra sempre e ninguém fica sabendo. O
    preço de acertar a invariante foi trocar um erro barulhento por um silêncio,
    e é esse silêncio que esta rota quebra.

    O diagnóstico é o que torna a lista acionável · "pendente" sozinho não diz
    se falta esperar, re-sincronizar a estatística ou olhar o pick na mão:

      sem folha do jogo   o provedor não publicou match_statistics · é o caso
                          que a invariante protege, e o que resolve é o
                          collector, não mexer no pick
      folha incompleta    a folha existe mas o contador daquele mercado veio
                          nulo · mesma origem, só que parcial
      folha completa      o dado está lá e o pick continua pendente · aqui o
                          suspeito é a liquidação, não a fonte
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        itens: list[dict] = []
        for pt in _PICK_TABLES_UMA_FIXTURE:
            table, home_col, away_col = _PICK_TABLES[pt]
            try:
                cur.execute(f"""
                    SELECT p.id, p.{home_col} AS home_team, p.{away_col} AS away_team,
                           p.match_date, p.market, p.line, p.fixture_id,
                           (ms.fixture_id IS NOT NULL) AS tem_folha,
                           ms.home_corners, ms.away_corners,
                           ms.home_yellow_cards, ms.away_yellow_cards,
                           ms.home_fouls, ms.away_fouls,
                           ms.home_total_shots, ms.away_total_shots,
                           ms.home_shots_on, ms.away_shots_on
                      FROM {table} p
                      LEFT JOIN match_statistics ms ON ms.fixture_id = p.fixture_id
                     WHERE p.result IS NULL
                       AND p.match_date <= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
                     ORDER BY p.match_date ASC, p.id ASC
                     LIMIT 200
                """)
            except Exception:
                # Instância sem a migração de alguma tabela: pula em vez de
                # derrubar o painel inteiro (mesma escolha de /picks/search).
                conn.rollback()
                continue
            for r in cur.fetchall():
                d = dict(r)
                contadores = [d.get(k) for k in (
                    "home_corners", "away_corners", "home_yellow_cards", "away_yellow_cards",
                    "home_fouls", "away_fouls", "home_total_shots", "away_total_shots",
                    "home_shots_on", "away_shots_on",
                )]
                if not d["tem_folha"]:
                    motivo = "sem folha do jogo"
                elif any(c is None for c in contadores):
                    motivo = "folha incompleta"
                else:
                    motivo = "folha completa"
                itens.append({
                    "pick_type":  pt,
                    "id":         d["id"],
                    # Preenchido depois, quando o corte de horas ja e conhecido.
                    "travado":    False,
                    "home_team":  d["home_team"],
                    "away_team":  d["away_team"],
                    "match_date": str(d["match_date"]) if d["match_date"] else None,
                    "market":     d["market"],
                    "line":       d["line"],
                    "fixture_id": d["fixture_id"],
                    "motivo":     motivo,
                })

        # Múltipla e alavancagem têm várias fixtures por bilhete · não dá pra
        # apontar UMA folha faltando, então entram só na contagem.
        bilhetes = {}
        for pt in ("multipla", "alavancagem"):
            table, _h, _a = _PICK_TABLES[pt]
            try:
                cur.execute(f"""
                    SELECT COUNT(*) AS n FROM {table}
                     WHERE result IS NULL
                       AND match_date <= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
                """)
                bilhetes[pt] = int((cur.fetchone() or {}).get("n") or 0)
            except Exception:
                conn.rollback()
                bilhetes[pt] = 0

        # "Travado" = passou da janela em que a folha normalmente já chegou. É o
        # corte que separa "o jogo acabou agora" de "isto não vai resolver
        # sozinho", e é ajustável porque a janela boa depende do provedor.
        from datetime import timedelta as _td
        from zoneinfo import ZoneInfo

        limite = (datetime.now(ZoneInfo("America/Sao_Paulo")) - _td(hours=horas)).date()
        for i in itens:
            i["travado"] = bool(i["match_date"] and i["match_date"] < limite.isoformat())
        travados = [i for i in itens if i["travado"]]
        # Jogo de HOJE que ainda nao terminou nao e pendencia, e o estado normal
        # de um pick recem-publicado. Misturar os dois na mesma lista fazia o
        # painel gritar todo dia de manha sobre a rodada da noite.
        aguardando = len(itens) - len(travados)

        return {
            "total":            len(itens) + sum(bilhetes.values()),
            "simples":          len(itens),
            "aguardando_jogo":  aguardando,
            "bilhetes":         bilhetes,
            "travados":         len(travados),
            "horas_de_corte":   horas,
            "por_motivo": {
                "sem folha do jogo": sum(1 for i in itens if i["motivo"] == "sem folha do jogo"),
                "folha incompleta":  sum(1 for i in itens if i["motivo"] == "folha incompleta"),
                "folha completa":    sum(1 for i in itens if i["motivo"] == "folha completa"),
            },
            # Travado primeiro: e o que pede acao. O resto vai junto pra
            # conferencia, marcado, mas nunca na frente.
            "itens": (travados + [i for i in itens if not i["travado"]])[:100],
        }
    finally:
        cur.close()
        conn.close()


@router.post("/picks/reparar-pernas")
def admin_reparar_pernas(
    limit: int = Query(20, ge=1, le=100),
    dry_run: bool = Query(True),
    current_user: dict = Depends(require_admin),
):
    """Recalcula o resultado de CADA perna das múltiplas já liquidadas.

    Conserta o estrago do bug corrigido em fae4ccc: quatro call sites fechavam
    o bilhete com `["RED"] * len(legs)` e esse carimbo era gravado no JSONB
    `games`, marcando RED até em perna que ganhou ou que nem tinha jogado. A
    correção de lá vale só pra bilhete novo · linha já gravada continua errada,
    e é isso que esta rota alcança.

    DUAS COISAS QUE ELA NÃO FAZ, de propósito:

    · não toca em `result` nem em `profit` do bilhete. O bilhete estava certo
      (uma perna RED mata a múltipla) e o dinheiro dele já entrou na banca de
      quem seguiu. Reescrever isso mexeria em saldo por causa de um bug de
      exibição.
    · não alcança alavancagem, porque lá nunca houve o que corromper:
      `_save_alavancagem_result` nunca gravou resultado por perna.

    Custa chamada de API (uma fixture por perna), então tem `limit` e começa em
    `dry_run` · quem repara histórico sem ver antes o que vai mudar acaba
    descobrindo o alcance depois.
    """
    from routers.live import _enrich_leg, _fetch_fixtures_bulk, _locked_leg_result

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, games, result, match_date
              FROM picks_multiplas
             WHERE result IS NOT NULL AND games IS NOT NULL
             ORDER BY match_date DESC, id DESC
             LIMIT %s
        """, (limit,))
        bilhetes = [dict(r) for r in cur.fetchall()]

        # Aquece o cache de fixtures de uma vez só · uma chamada por perna, em
        # série, é o que transforma um reparo de 20 bilhetes em minutos.
        fids = []
        for b in bilhetes:
            pernas = b["games"]
            if isinstance(pernas, str):
                try: pernas = json.loads(pernas)
                except Exception: continue
            if isinstance(pernas, list):
                fids += [p.get("fixture_id") for p in pernas
                         if isinstance(p, dict) and p.get("fixture_id")]
        if fids:
            _fetch_fixtures_bulk(fids)

        mudancas, corrigidos = [], 0
        for b in bilhetes:
            pernas = b["games"]
            if isinstance(pernas, str):
                try: pernas = json.loads(pernas)
                except Exception: continue
            if not isinstance(pernas, list) or not pernas:
                continue

            antes  = [p.get("result") if isinstance(p, dict) else None for p in pernas]
            depois = []
            for p in pernas:
                if not isinstance(p, dict) or not p.get("fixture_id"):
                    depois.append(p.get("result") if isinstance(p, dict) else None)
                    continue
                try:
                    leg = _enrich_leg(
                        p["fixture_id"], p.get("market", ""), p.get("line", ""),
                        p.get("home") or p.get("home_team") or "",
                        p.get("away") or p.get("away_team") or "",
                        p.get("home_team_id"), p.get("away_team_id"),
                        float(p.get("odd", 1)), market_type=p.get("market_type"),
                    )
                    depois.append(_locked_leg_result(leg))
                except Exception as e:
                    logger.warning("[REPARO] perna do bilhete %s falhou: %s", b["id"], e)
                    depois.append(p.get("result"))

            if antes == depois:
                continue
            mudancas.append({
                "pick_id":    b["id"],
                "match_date": str(b["match_date"]) if b["match_date"] else None,
                "bilhete":    b["result"],
                "antes":      antes,
                "depois":     depois,
            })
            if not dry_run:
                for p, r in zip(pernas, depois):
                    if isinstance(p, dict):
                        p["result"] = r
                cur.execute("UPDATE picks_multiplas SET games = %s WHERE id = %s",
                            (json.dumps(pernas, default=str), b["id"]))
                corrigidos += 1

        if not dry_run:
            conn.commit()
        return {
            "dry_run":     dry_run,
            "analisados":  len(bilhetes),
            "divergentes": len(mudancas),
            "corrigidos":  corrigidos,
            "mudancas":    mudancas[:50],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.get("/picks/search")
def admin_search_picks(
    q:          Optional[str] = None,
    date_from:  Optional[str] = None,
    date_to:    Optional[str] = None,
    pick_type:  Optional[str] = None,
    current_user: dict = Depends(require_admin),
):
    conn = get_connection()
    cur = conn.cursor()
    try:
        results = []
        types_to_search = [pick_type] if pick_type and pick_type in _PICK_TABLES else list(_PICK_TABLES.keys())
        for pt in types_to_search:
            table, home_col, away_col = _PICK_TABLES[pt]
            conds, params = [], []
            if q:
                # MULTIPLA NAO TEM COLUNA DE TIME (2026-08-27).
                #
                # `picks_multiplas` guarda as pernas em `games` (JSONB) e nao
                # tem `home_team_name`/`away_team_name` -- essas colunas so'
                # existem em picks_vip. O SELECT abaixo as pedia mesmo assim, a
                # consulta estourava, o `except` engolia e a MULTIPLA SUMIA da
                # busca inteira. Ela nunca apareceu no /admin por isso.
                #
                # Procurar time numa multipla e' procurar dentro do JSON, que e'
                # onde os times de fato estao.
                if pt == "multipla":
                    conds.append("games::text ILIKE %s")
                    params.append(f"%{q}%")
                else:
                    conds.append(f"(LOWER({home_col}) LIKE %s OR LOWER({away_col}) LIKE %s)")
                    params += [f"%{q.lower()}%", f"%{q.lower()}%"]
            if date_from:
                conds.append("match_date >= %s"); params.append(date_from)
            if date_to:
                conds.append("match_date <= %s"); params.append(date_to)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            # Multipla e alavancagem nao tem coluna `market`/`line` unica (sao
            # varias pernas), entao vao com rotulo fixo -- sem isso a query
            # quebra e some do resultado inteiro.
            if pt == "multipla":
                mercado = "'Múltipla' AS market, NULL AS line, total_odd AS odd"
            elif pt == "alavancagem":
                mercado = "market_1 AS market, line_1 AS line, odd_combined AS odd"
            else:
                mercado = "market, line, odd"

            # As colunas de time, pelo mesmo motivo. A multipla mostra quantas
            # pernas tem: e' o que identifica o bilhete, ja' que nao ha' UM
            # confronto pra nomear.
            if pt == "multipla":
                times = ("multipla_name AS home_team, "
                         "(jsonb_array_length(games::jsonb) || ' jogos') AS away_team")
            else:
                times = f"{home_col} AS home_team, {away_col} AS away_team"
            try:
                cur.execute(f"""
                    SELECT id, {times},
                           match_date, result, profit, {mercado}
                    FROM {table}
                    {where}
                    ORDER BY match_date DESC, id DESC
                    LIMIT 50
                """, params)
            except Exception as e:
                # Instancia sem a migracao das tabelas novas: pula esse tipo em
                # vez de derrubar a busca inteira.
                #
                # O LOG entrou em 27/08: este `except` escondeu por meses o fato
                # de a multipla pedir colunas que nao existem. "Pula o tipo" e'
                # a decisao certa; fazer isso em SILENCIO nao era.
                conn.rollback()
                logging.getLogger(__name__).warning(
                    "[ADMIN/PICKS] busca pulou %s: %s", pt, str(e)[:200])
                continue
            for r in cur.fetchall():
                results.append({**dict(r), "pick_type": pt})
        results.sort(key=lambda x: (str(x.get("match_date") or ""), x["id"]), reverse=True)
        return results[:100]
    finally:
        cur.close()
        conn.close()


class SetResultBody(BaseModel):
    pick_type: str
    pick_id:   int
    result:    Optional[str] = None  # None = limpar (voltar a pendente)

    @field_validator("pick_type")
    @classmethod
    def validate_pick_type(cls, v):
        if v not in _PICK_TABLES:
            raise ValueError(f"pick_type inválido. Use: {list(_PICK_TABLES)}")
        return v

    @field_validator("result")
    @classmethod
    def validate_result(cls, v):
        if v not in _VALID_RESULTS:
            raise ValueError(f"Resultado inválido. Use: GREEN, RED, PUSH, HALF-WIN, HALF-LOSS ou null")
        return v


@router.post("/picks/set-result")
def admin_set_pick_result(body: SetResultBody, current_user: dict = Depends(require_admin)):
    table = _PICK_TABLES[body.pick_type][0]
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Profit em unidades, a partir da odd da tabela certa (ver _ODD_COL).
        odd_col = _ODD_COL[body.pick_type]
        cur.execute(f"SELECT {odd_col} AS odd, result FROM {table} WHERE id = %s", (body.pick_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pick não encontrado")
        resultado_anterior = row.get("result")

        odd = float(row["odd"]) if row.get("odd") else None
        profit = None
        if body.result == "GREEN" and odd:
            profit = round(odd - 1, 4)
        elif body.result == "RED":
            profit = -1.0
        elif body.result == "PUSH":
            profit = 0.0
        elif body.result == "HALF-WIN" and odd:
            profit = round((odd - 1) / 2, 4)
        elif body.result == "HALF-LOSS":
            profit = -0.5

        cur.execute(
            f"UPDATE {table} SET result = %s, profit = %s WHERE id = %s RETURNING id, result, profit",
            (body.result, profit, body.pick_id),
        )
        updated = cur.fetchone()
        # Propaga resultado para todos os usuários que seguiram este pick
        result_val = None if body.result == "pending" else body.result
        cur.execute(
            "UPDATE user_followed_picks SET result=%s WHERE pick_id=%s AND pick_type=%s",
            (result_val, body.pick_id, body.pick_type),
        )

        # Sino de quem seguiu o pick · faltava exatamente aqui.
        #
        # A resolução automática avisa por um ponto único
        # (routers.live::_sync_followed_result, que chama notify_pick_result),
        # mas o carimbo manual desta rota escrevia direto no banco e pulava
        # esse ponto. O efeito pro usuário era o pior possível: o dinheiro
        # mudava na banca dele sem nenhum aviso de que o pick tinha sido
        # resolvido -- e como o /admin é justamente onde se resolve o que a
        # automação não deu conta, era o caso mais comum de todos.
        #
        # Voltar pra "pending" não avisa nada: não há resultado a anunciar.
        if result_val is not None:
            from routers.notifications import notify_pick_result

            notify_pick_result(cur, body.pick_id, body.pick_type, result_val)

            # CORREÇÃO de um resultado já anunciado precisa piscar de novo.
            # create_notification preserva `read_at` de propósito (resultado
            # revisado pelo provedor não deve reaparecer como não lido pra quem
            # já viu), mas aqui a premissa é outra: alguém trocou GREEN por RED
            # na mão, o saldo de quem seguiu mudou junto, e deixar isso passar
            # em silêncio é esconder a única parte que importa.
            if resultado_anterior and resultado_anterior != result_val:
                cur.execute(
                    "UPDATE notifications SET read_at = NULL WHERE dedupe_key = %s",
                    (f"pick_result:{body.pick_type}:{body.pick_id}",),
                )

        conn.commit()
        return dict(updated)
    finally:
        cur.close()
        conn.close()


class DescartarBody(BaseModel):
    pick_type: str
    pick_id:   int

    @field_validator("pick_type")
    @classmethod
    def _tipo(cls, v):
        if v not in _PICK_TABLES:
            raise ValueError(f"pick_type inválido. Use: {list(_PICK_TABLES)}")
        return v


@router.post("/picks/descartar")
def admin_descartar_pick(body: DescartarBody, current_user: dict = Depends(require_admin)):
    """Apaga um pick que NUNCA vai resolver.

    Existe por um caso concreto: um pick de picks_vip com fixture_id 9000001,
    id sintético que não existe na API-Football. O collector pedia a folha dele
    a cada rodada do checker, a API respondia "não encontrado", e o pick ficava
    pendente pra sempre -- poluindo o painel de pendências e gastando uma
    chamada por rodada, sem chance nenhuma de fechar.

    DUAS CERCAS, porque isto apaga dado:

    1. Só pick SEM resultado. Pick já liquidado tem lucro contado na banca de
       quem seguiu; apagá-lo mudaria saldo de usuário pelas costas. Aqui o
       404 é proposital -- se tem resultado, o caminho é corrigir o resultado,
       não sumir com a linha.

    2. Os follows vão junto, no mesmo commit. Deixar `user_followed_picks`
       apontando pra um pick que não existe mais é como nasce card fantasma na
       tela de Meus Picks.
    """
    tabela = _PICK_TABLES[body.pick_type][0]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT result FROM {tabela} WHERE id = %s", (body.pick_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pick não encontrado.")
        if row["result"] is not None:
            raise HTTPException(400,
                "Este pick já tem resultado. Descartar é só pra pick que nunca vai "
                "resolver. Pra corrigir um resultado errado, use Alterar resultado.")

        cur.execute(
            "DELETE FROM user_followed_picks WHERE pick_id = %s AND pick_type = %s",
            (body.pick_id, body.pick_type))
        follows = cur.rowcount or 0
        cur.execute(f"DELETE FROM {tabela} WHERE id = %s", (body.pick_id,))
        conn.commit()
        logger.info("[ADMIN] Pick %s #%s descartado por %s (%d follow(s) junto)",
                    body.pick_type, body.pick_id, current_user.get("email"), follows)
        return {"ok": True, "follows_removidos": follows}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.post("/picks/descartar-sinteticos")
def admin_descartar_sinteticos(
    dry_run: bool = Query(True),
    current_user: dict = Depends(require_admin),
):
    """Descarta de uma vez todo pick pendente com fixture SINTETICA.

    Fixture na faixa >= 9000000 nao existe na API-Football · e' semente de teste
    que vazou pra tabela. O checker pede a folha dela a cada rodada, a API
    responde "nao encontrado", e o pick fica pendente pra sempre. Nao ha cenario
    em que ele resolva, entao nao ha o que esperar.

    Mesmas duas cercas do descarte individual, pelos mesmos motivos: so' pick
    SEM resultado, e os follows saem no mesmo commit. Comeca em dry_run porque
    apagar em lote sem ver a lista antes e como se descobre o alcance tarde.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        alvos: list[dict] = []
        for pt in _PICK_TABLES_UMA_FIXTURE:
            tabela, home_col, away_col = _PICK_TABLES[pt]
            try:
                cur.execute(f"""
                    SELECT id, fixture_id, {home_col} AS home_team, {away_col} AS away_team,
                           match_date
                      FROM {tabela}
                     WHERE result IS NULL AND fixture_id >= 9000000
                     ORDER BY id
                """)
            except Exception:
                conn.rollback()
                continue
            for r in cur.fetchall():
                d = dict(r)
                alvos.append({
                    "pick_type":  pt,
                    "id":         d["id"],
                    "fixture_id": d["fixture_id"],
                    "jogo":       f"{d['home_team']} x {d['away_team']}",
                    "match_date": str(d["match_date"]) if d["match_date"] else None,
                })

        removidos = follows = 0
        if not dry_run and alvos:
            for a in alvos:
                tabela = _PICK_TABLES[a["pick_type"]][0]
                cur.execute(
                    "DELETE FROM user_followed_picks WHERE pick_id = %s AND pick_type = %s",
                    (a["id"], a["pick_type"]))
                follows += cur.rowcount or 0
                cur.execute(f"DELETE FROM {tabela} WHERE id = %s AND result IS NULL", (a["id"],))
                removidos += cur.rowcount or 0
            conn.commit()
            logger.info("[ADMIN] %d pick(s) sintetico(s) descartado(s) por %s",
                        removidos, current_user.get("email"))

        return {
            "dry_run":  dry_run,
            "encontrados": len(alvos),
            "removidos": removidos,
            "follows_removidos": follows,
            "picks": alvos[:50],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.get("/stats")
def admin_stats(current_user: dict = Depends(require_admin)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                COUNT(*)                                        AS total,
                COUNT(*) FILTER (WHERE plan = 'vip')           AS vip,
                COUNT(*) FILTER (WHERE plan = 'trial')         AS trial,
                COUNT(*) FILTER (WHERE plan = 'free')          AS free,
                COUNT(*) FILTER (WHERE active = true)          AS ativos,
                COUNT(*) FILTER (WHERE plan = 'vip'
                    AND expires_at IS NOT NULL
                    AND expires_at < NOW() + INTERVAL '7 days'
                    AND expires_at > NOW())                     AS vip_expirando,
                COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '1 day')  AS ativos_hoje,
                COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '7 days') AS ativos_semana
            FROM users
        """)
        users_row = dict(cur.fetchone())

        cur.execute(f"""
            SELECT
                (SELECT COUNT(*) FROM picks_vip
                 WHERE match_date = {HOJE_BR})                               AS vip_picks,
                (SELECT COUNT(*) FROM picks_alavancagem
                 WHERE match_date = {HOJE_BR})                               AS alavancagem,
                (SELECT COUNT(*) FROM picks_free
                 WHERE match_date = {HOJE_BR})                               AS dica,
                (SELECT COUNT(*) FROM picks_multiplas
                 WHERE DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE)  AS multiplas
        """)
        picks_row = dict(cur.fetchone())

        return {**users_row, "picks_hoje": picks_row}
    finally:
        cur.close()
        conn.close()


@router.post("/resolve-picks")
def admin_resolve_picks(current_user: dict = Depends(require_admin)):
    """Resolve os picks pendentes. Unica forma de resolver em lote desde que o
    scheduler foi removido (2026-08-01) -- fora daqui, o resultado so' e' salvo
    de forma oportunista quando alguem abre a aba de picks ao vivo."""
    from routers.live import resolve_all_pending
    result = resolve_all_pending()
    return {"ok": True, "resolved": result}


@router.post("/reverify-stats-results")
def admin_reverify_stats_results(
    days: int | None = None,
    all_markets: bool = False,
    current_user: dict = Depends(require_admin),
):
    """Dispara manualmente a reconferência de picks já resolvidos
    (ver routers.live.reverify_recent_stats_results). Rodava de 3 em 3h no
    scheduler, removido em 2026-08-01 -- agora so' por aqui.

    Sem parametro: janela curta, so' escanteios/cartoes (uso do dia a dia).
    `?days=365&all_markets=true`: auditoria completa -- reconfere TODOS os
    mercados de TODO o historico contra a estatistica oficial de agora, e
    corrige o que nao bater. Custa cota da API (uma consulta por fixture),
    entao nao e' o padrao."""
    from routers.live import reverify_recent_stats_results
    result = reverify_recent_stats_results(days=days, all_markets=all_markets)
    return {"ok": True, **result}


# ─── Console de operação ────────────────────────────────────────────────────
# O /admin e' o painel de quem opera o site, nao so' do desenvolvedor. Os
# endpoints abaixo existem pra que dar uma olhada no estado do sistema nao
# dependa de abrir o banco ou ler log.

_API_FOOTBALL_STATUS_CACHE: dict = {"ts": 0.0, "data": None}


def _api_football_status() -> dict | None:
    """Cota da API-Football (plano, usado hoje, limite diario).

    O endpoint /status NAO consome cota -- e' o unico que responde com a cota
    ja zerada, e e' justamente ai' que a informacao mais importa. Ainda assim
    vai com cache de 60s: o dashboard recarrega sozinho e nao ha' motivo pra
    bater na API a cada render.

    Devolve None em qualquer falha. O painel inteiro nao pode cair porque um
    provedor externo esta fora do ar.
    """
    import time

    import requests

    agora = time.time()
    if _API_FOOTBALL_STATUS_CACHE["data"] and agora - _API_FOOTBALL_STATUS_CACHE["ts"] < 60:
        return _API_FOOTBALL_STATUS_CACHE["data"]

    key = os.getenv("API_FOOTBALL_KEY", "")
    if not key:
        return None
    try:
        r = requests.get("https://v3.football.api-sports.io/status",
                         headers={"x-apisports-key": key}, timeout=8)
        corpo = r.json().get("response") or {}
        assinatura = corpo.get("subscription") or {}
        requisicoes = corpo.get("requests") or {}
        usado = requisicoes.get("current")
        limite = requisicoes.get("limit_day")
        dados = {
            "plano": assinatura.get("plan"),
            "ativo": assinatura.get("active"),
            "expira_em": assinatura.get("end"),
            "usado": usado,
            "limite": limite,
            "pct": round(usado / limite * 100, 1) if usado is not None and limite else None,
        }
    except Exception:
        return None

    _API_FOOTBALL_STATUS_CACHE.update({"ts": agora, "data": dados})
    return dados


@router.get("/overview")
def admin_overview(current_user: dict = Depends(require_admin)):
    """Retrato do sistema numa chamada so'.

    Cada bloco tem fallback proprio: instancia sem alguma tabela nova (ou
    provedor externo fora) mostra aquele bloco vazio em vez de derrubar o
    painel -- que e' exatamente quando alguem mais precisa dele.
    """
    conn = get_connection()
    cur = conn.cursor()

    def uma(sql, default=None):
        try:
            cur.execute(sql)
            row = cur.fetchone()
            return dict(row) if row else default
        except Exception:
            conn.rollback()
            return default

    try:
        usuarios = uma("""
            SELECT COUNT(*)                                                    AS total,
                   COUNT(*) FILTER (WHERE plan = 'vip')                        AS vip,
                   COUNT(*) FILTER (WHERE plan = 'trial')                      AS trial,
                   COUNT(*) FILTER (WHERE plan = 'free')                       AS free,
                   COUNT(*) FILTER (WHERE active)                              AS ativos,
                   COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '1 day')  AS ativos_hoje,
                   COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '7 days') AS ativos_semana,
                   COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')    AS novos_semana,
                   COUNT(*) FILTER (WHERE plan = 'vip' AND expires_at IS NOT NULL
                                      AND expires_at BETWEEN NOW() AND NOW() + INTERVAL '7 days')
                                                                               AS vip_expirando
            FROM users
        """, {})

        # Picks de hoje por tipo, ja com faltas e goleiros. Uma subquery por
        # tabela pra que uma tabela faltando nao zere o bloco inteiro.
        picks = {}
        for rotulo, tabela in (("vip", "picks_vip"), ("free", "picks_free"),
                               ("multiplas", "picks_multiplas"),
                               ("alavancagem", "picks_alavancagem"),
                               ("faltas", "picks_faltas"), ("goleiros", "picks_goleiros")):
            picks[rotulo] = uma(
                f"SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE result IS NULL) AS pendentes "
                f"FROM {tabela} WHERE match_date = {HOJE_BR}",
                {"n": 0, "pendentes": 0},
            )

        # Saude da coleta. Sem isso, "nao saiu pick hoje" fica indistinguivel
        # de "a coleta nem rodou" -- que sao problemas completamente
        # diferentes pra quem esta operando.
        coleta = uma(f"""
            SELECT (SELECT COUNT(*) FROM fixtures
                     WHERE {data_br('match_datetime')} = {HOJE_BR})            AS jogos_hoje,
                   (SELECT COUNT(*) FROM fixtures
                     WHERE {data_br('match_datetime')} = {HOJE_BR}
                       AND status IN ('NS','TBD'))                          AS jogos_por_comecar,
                   (SELECT COUNT(DISTINCT fixture_id) FROM odds_values)        AS jogos_com_odds,
                   (SELECT MAX(match_date) FROM match_statistics)              AS ultimo_jogo_coletado,
                   (SELECT COUNT(*) FROM leagues)                              AS ligas,
                   (SELECT COUNT(*) FROM teams)                                AS times,
                   (SELECT COUNT(*) FROM player_match_stats)                   AS estatisticas_jogador
        """, {})

        financeiro = uma("""
            SELECT COALESCE(SUM(amount), 0)                                    AS receita_mes,
                   COUNT(*)                                                    AS pagamentos_mes
            FROM payments
            WHERE status = 'approved'
              AND created_at >= date_trunc('month', NOW())
        """, {})

        return {
            "usuarios": usuarios,
            "picks_hoje": picks,
            "coleta": coleta,
            "financeiro": financeiro,
            "api_football": _api_football_status(),
            "pipeline": _pipeline_status.get("tudo", {}),
        }
    finally:
        cur.close()
        conn.close()


# ─── Ligas ──────────────────────────────────────────────────────────────────

class LigaBody(BaseModel):
    league_id: int
    season: int
    name: Optional[str] = None
    # None = nao marcado. Ver a migration de `temporada_iniciada`: e' o estado
    # que faz a coleta rodar completa, que e' o seguro.
    temporada_iniciada: Optional[bool] = None


@router.get("/leagues")
def listar_ligas(current_user: dict = Depends(require_admin)):
    """Ligas cadastradas, com o volume de dado que cada uma ja acumulou.

    A contagem existe pra deixar visivel o custo de remover: liga com muito
    jogo coletado e' base de calibracao do motor (ai_performance_service faz
    JOIN em match_statistics).
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT l.league_id, l.name, l.season, l.temporada_iniciada, l.ativa,
                   (SELECT COUNT(*) FROM teams t
                     WHERE t.league_id = l.league_id)                AS times,
                   (SELECT COUNT(*) FROM match_statistics ms
                     WHERE ms.league_id = l.league_id)               AS jogos_coletados,
                   (SELECT COUNT(*) FROM fixtures f
                     WHERE f.league_id = l.league_id)                AS jogos_agendados
            FROM leagues l
            ORDER BY l.league_id
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


@router.post("/leagues")
def adicionar_liga(body: LigaBody, current_user: dict = Depends(require_admin)):
    """Cadastra uma liga, validando o id contra a API-Football.

    A validacao custa 1 requisicao e evita o modo de falha silencioso que essa
    tabela permite hoje: id digitado errado entra no banco sem reclamar e so'
    aparece dias depois, como uma liga que nunca coleta jogo nenhum. De
    quebra, o nome vem da propria API em vez de digitado na mao.
    """
    import requests

    key = os.getenv("API_FOOTBALL_KEY", "")
    nome = (body.name or "").strip()

    if key:
        try:
            r = requests.get("https://v3.football.api-sports.io/leagues",
                             headers={"x-apisports-key": key},
                             params={"id": body.league_id}, timeout=10)
            itens = r.json().get("response") or []
            if not itens:
                raise HTTPException(400, f"Liga {body.league_id} nao existe na API-Football.")
            info = itens[0]
            nome = nome or (info.get("league") or {}).get("name") or ""
            temporadas = {s.get("year") for s in (info.get("seasons") or []) if s.get("year")}
            if temporadas and body.season not in temporadas:
                disponiveis = ", ".join(str(a) for a in sorted(temporadas)[-6:])
                raise HTTPException(
                    400,
                    f"A liga {nome} nao tem a temporada {body.season}. "
                    f"Temporadas disponiveis: {disponiveis}.",
                )
        except HTTPException:
            raise
        except Exception as e:
            # Cota estourada ou provedor fora do ar nao pode impedir o
            # cadastro -- so' custa a validacao.
            logging.getLogger(__name__).warning("[LIGAS] Validacao indisponivel: %s", e)

    if not nome:
        raise HTTPException(
            400, "Informe o nome da liga (a validacao automatica nao esta disponivel agora).")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT league_id FROM leagues WHERE league_id = %s", (body.league_id,))
        if cur.fetchone():
            cur.execute(
                "UPDATE leagues SET name = %s, season = %s, temporada_iniciada = %s "
                "WHERE league_id = %s",
                (nome, body.season, body.temporada_iniciada, body.league_id))
            acao = "atualizada"
        else:
            cur.execute(
                "INSERT INTO leagues (league_id, name, season, temporada_iniciada) "
                "VALUES (%s, %s, %s, %s)",
                (body.league_id, nome, body.season, body.temporada_iniciada))
            acao = "cadastrada"
        conn.commit()
        return {
            "ok": True, "acao": acao,
            "league_id": body.league_id, "name": nome, "season": body.season,
            "aviso": "Rode 'Atualizar Jogos' pra coletar times e jogos desta liga.",
        }
    finally:
        cur.close()
        conn.close()


@router.get("/leagues/{league_id}/verificar")
def verificar_liga(league_id: int, season: int, current_user: dict = Depends(require_admin)):
    """A temporada dessa liga ja comecou? Tem jogo pra coletar?

    Pergunta que a tela nao sabia responder antes de gastar cota: cadastrar uma
    liga cuja temporada ainda nao abriu, ou cujo `season` esta errado, resulta
    numa coleta que roda inteira e traz zero jogo -- e o unico sintoma e' a
    linha continuar com "0 times, 0 jogos", que se confunde com falha.

    UMA requisicao (`/fixtures?league&season`) responde tudo: total de jogos da
    temporada, quantos ja terminaram (o que o backfill vai buscar), quantos
    faltam, o periodo e em que rodada a competicao esta.
    """
    import requests
    from collections import Counter

    key = os.getenv("API_FOOTBALL_KEY", "")
    if not key:
        raise HTTPException(503, "API_FOOTBALL_KEY nao configurada nesta instancia.")

    try:
        r = requests.get("https://v3.football.api-sports.io/fixtures",
                         headers={"x-apisports-key": key},
                         params={"league": league_id, "season": season}, timeout=15)
        r.raise_for_status()
        corpo = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"API-Football nao respondeu: {e}")

    if corpo.get("errors"):
        raise HTTPException(400, f"API-Football recusou a consulta: {corpo['errors']}")

    jogos = corpo.get("response") or []
    if not jogos:
        return {
            "existe": False, "iniciada": False, "total": 0, "finalizados": 0, "agendados": 0,
            "aviso": f"A API nao tem jogo nenhum para a liga {league_id} na temporada {season}. "
                     f"Confira o id e o ano da temporada antes de cadastrar.",
        }

    _FINAL = {"FT", "AET", "PEN"}
    status = Counter((j.get("fixture", {}).get("status") or {}).get("short") for j in jogos)
    finalizados = sum(n for s, n in status.items() if s in _FINAL)
    agendados = status.get("NS", 0)

    datas = sorted(j["fixture"]["date"][:10] for j in jogos if j.get("fixture", {}).get("date"))
    # Rodada do proximo jogo que ainda nao aconteceu -- e' o "onde a competicao
    # esta" que interessa pra quem vai cadastrar.
    proximos = [j for j in jogos
                if (j.get("fixture", {}).get("status") or {}).get("short") == "NS"]
    rodada_atual = ((proximos[0].get("league") or {}).get("round") if proximos else None)

    return {
        "existe": True,
        "iniciada": finalizados > 0,
        "total": len(jogos),
        "finalizados": finalizados,
        "agendados": agendados,
        "inicio": datas[0] if datas else None,
        "fim": datas[-1] if datas else None,
        "rodada_atual": rodada_atual,
        "nome": (jogos[0].get("league") or {}).get("name"),
    }


@router.post("/leagues/{league_id}/coletar")
async def coletar_liga(league_id: int, current_user: dict = Depends(require_admin)):
    """Coleta completa DESTA liga: times, jogos da janela e estatistica da
    temporada inteira. Upsert, sem apagar nada.

    Existe porque cadastrar a liga NAO coleta nada sozinho, e a dependencia que
    faz isso doer e' invisivel na tela: FixtureCollectorService filtra por
    `SELECT team_id FROM teams`, entao liga sem time cadastrado nunca salva
    jogo, por mais que a API tenha. Estado real em 2026-08-11: Sul-Americana
    cadastrada havia dias, 56 times e as oitavas em andamento na API, zero
    linha no banco -- e nada na tela dizia isso.

    Dispara em segundo plano (mesmo padrao de /run-pipeline): o backfill de
    temporada faz uma requisicao por jogo finalizado e nao cabe num request
    HTTP. O andamento sai em /admin/pipeline-status como "coletar_liga".

    Liga marcada como "temporada nao comecou" (leagues.temporada_iniciada =
    false) pula o backfill de estatistica: nao ha jogo finalizado pra buscar, e
    a varredura so' gastaria a listagem pra voltar de maos vazias. NULL roda
    completo -- pular por engano deixaria o motor sem base, e o unico sintoma
    seria "essa liga nunca gera pick".

    NAO e' o `new_league` do script: aquele faz TRUNCATE em match_statistics/
    teams/fixtures/standings e recoleta tudo do zero.
    """
    # A consulta vai pro threadpool porque esta rota e' `async` e psycopg2 e'
    # bloqueante: rodando no event loop com WEB_CONCURRENCY=1, ela segurava o
    # processo inteiro. Ver a nota longa em
    # suggestions.get_standings_for_fixture. A rota CONTINUA async por causa do
    # asyncio.create_task() la' embaixo, que precisa de um loop rodando --
    # transformar isto em `def` moveria a funcao pro threadpool, onde nao ha
    # loop, e a coleta morreria com RuntimeError em vez de comecar.
    def _ler_liga():
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT name, temporada_iniciada FROM leagues WHERE league_id = %s",
                        (league_id,))
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    row = await run_in_threadpool(_ler_liga)
    if not row:
        raise HTTPException(404, "Liga nao cadastrada. Cadastre antes de coletar.")
    nome = row["name"]
    # So' pula o historico quando alguem marcou EXPLICITAMENTE que a temporada
    # nao comecou. NULL (ninguem marcou) roda completo, que e' o seguro: pular
    # por engano deixa o motor sem base pra analisar a liga, e o unico sintoma
    # seria "essa liga nunca gera pick".
    com_historico = row["temporada_iniciada"] is not False

    if _pipeline_status.get("coletar_liga", {}).get("status") == "running":
        raise HTTPException(409, "Ja ha uma coleta de liga em andamento.")

    script = os.path.join(_PIPELINE_DIR, "atualizar_jogos.py")
    if not os.path.exists(script):
        raise HTTPException(500, detail=f"Script nao encontrado: {script}")

    # `extra` viaja junto no status: e' como a tela sabe EM QUAL linha mostrar
    # "Coletando..." enquanto roda.
    args = ["liga", str(league_id)] + ([] if com_historico else ["leve"])
    asyncio.create_task(_run_and_track(
        "coletar_liga", script, args,
        extra={"league_id": league_id, "liga": nome},
    ))
    return {
        "ok": True, "status": "iniciado", "liga": nome, "league_id": league_id,
        "com_historico": com_historico,
    }


@router.post("/leagues/{league_id}/reativar")
def reativar_liga(league_id: int, current_user: dict = Depends(require_admin)):
    """Volta a coletar uma liga que estava so' como historico."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE leagues SET ativa = TRUE WHERE league_id = %s RETURNING name",
                    (league_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Liga nao encontrada.")
        conn.commit()
        return {"ok": True, "liga": row["name"]}
    finally:
        cur.close()
        conn.close()


@router.delete("/leagues/{league_id}")
def remover_liga(league_id: int, current_user: dict = Depends(require_admin)):
    """Tira a liga da coleta MARCANDO ativa=false. Nao apaga a linha.

    Regra do usuario (2026-08-01): historico nao se apaga. Ate' 2026-08-11 isto
    fazia DELETE, e o efeito colateral so' apareceu quando a Copa do Mundo 2026
    saiu (competicao encerrada, so' volta em 2030): TODO lugar que resolve o
    nome da liga por JOIN em `leagues` passou a cair no fallback, e os picks
    dela viraram "LIGA 1" nos Resultados da IA. Os 104 jogos continuavam em
    match_statistics sustentando 77% do ledger de calibracao -- o que sumiu foi
    so' o nome, e nao ha de onde recupera-lo depois do DELETE.

    Marcar em vez de apagar resolve os dois lados: os coletores leem
    `WHERE COALESCE(ativa, TRUE)` e param na hora, e a linha continua ali pra
    quem so' quer escrever o nome na tela.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE leagues SET ativa = FALSE WHERE league_id = %s RETURNING name",
                    (league_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Liga nao encontrada.")
        conn.commit()
        return {
            "ok": True, "removida": row["name"],
            "aviso": "Parou de coletar. Jogos, times, picks e o NOME da liga "
                     "continuam, entao o historico segue legivel no site.",
        }
    finally:
        cur.close()
        conn.close()


# ─── Casas de aposta ─────────────────────────────────────────────────────────


class BookmakerBody(BaseModel):
    bookmaker_id: int
    bookmaker_name: str
    ativo: bool = True


@router.get("/dados")
def dados_do_banco(current_user: dict = Depends(require_admin)):
    """O que o motor tem pra ler, e onde estao os buracos.

    O /overview responde "o sistema esta de pe". Esta rota responde outra
    coisa: "o motor esta enxergando?". Sao perguntas diferentes e a segunda nao
    tinha tela -- jogo encerrado sem estatistica nao quebra nada, so' deixa a
    media velha, e media velha nao parece defeito de coisa nenhuma.

    Tres blocos:
      contagem  quanto tem em cada tabela que o motor le'
      buracos   jogo encerrado sem estatistica, e ha quantos dias
      varredura o estado da coleta automatica (stats_sweep)
    """
    conn = get_connection()
    cur = conn.cursor()

    def um(sql: str, params: tuple = ()):
        # Uma consulta que falha nao pode levar a tela junto: o painel serve
        # justamente pra quando alguma coisa esta errada.
        try:
            cur.execute(sql, params)
            linha = cur.fetchone()
            return dict(linha) if linha else {}
        except Exception as e:
            logging.getLogger(__name__).warning("[ADMIN/DADOS] %s", e)
            conn.rollback()
            return {}

    try:
        contagem = {}
        for rotulo, tabela in (
            ("fixtures", "fixtures"), ("match_statistics", "match_statistics"),
            ("team_statistics", "team_statistics"), ("teams", "teams"),
            ("leagues", "leagues"), ("league_standings", "league_standings"),
            ("picks_vip", "picks_vip"), ("picks_free", "picks_free"),
        ):
            contagem[rotulo] = (um(f"SELECT COUNT(*) AS n FROM {tabela}") or {}).get("n")

        frescor = um("""
            SELECT MAX(match_date)::text                       AS ultima_partida,
                   COUNT(*) FILTER (WHERE match_date >= CURRENT_DATE - 7) AS ultimos_7_dias
              FROM match_statistics
        """)

        # Quando a MEDIA foi recalculada, nao quando a PARTIDA entrou.
        #
        # Sao dois relogios diferentes e o motor le' o segundo: `match_statistics`
        # pode estar em dia e `team_statistics` parada em semana passada, que e'
        # media velha sem nenhum sintoma na tela. A distancia entre as duas datas
        # e' o defeito.
        frescor["medias_atualizadas_em"] = um("""
            SELECT MAX(last_updated)::text AS em FROM team_statistics
        """).get("em")

        # O buraco que importa: encerrado no banco de jogos e ausente no de
        # estatistica. E' exatamente o que a varredura automatica persegue.
        buracos = um("""
            SELECT COUNT(*)                                        AS total,
                   MIN(f.match_datetime)::text                     AS mais_antigo
              FROM fixtures f
         LEFT JOIN match_statistics ms ON ms.fixture_id = f.fixture_id
             WHERE f.status IN ('FT','AET','PEN')
               AND ms.fixture_id IS NULL
        """)

    finally:
        cur.close()
        conn.close()

    try:
        from stats_sweep import estado_da_varredura
        varredura = estado_da_varredura()
    except Exception as e:
        varredura = {"erro": str(e)[:200]}

    return {
        "contagem": contagem,
        "frescor": frescor,
        "buracos": buracos,
        "varredura": varredura,
    }


# Historico POR PARTIDA -- 40 e' teto do banco, nao tamanho de pagina.
#
# A tela listava LIGA, com "partidas com estatistica" agregado. Agregado nao
# responde a pergunta que se faz olhando esta aba ("o motor enxergou o jogo de
# ontem?"): uma liga com 3.000 jogos e uma com 4 apareciam iguais, uma linha
# cada, e nenhuma das duas dizia QUAL jogo entrou.
#
# O corte de 40 acontece no SQL, antes do OFFSET. E' o que mantem a pagina 4 do
# mesmo custo da pagina 1 e deixa `match_statistics` crescer sem que esta rota
# fique mais cara -- o contrario (paginar a tabela inteira e cortar na tela)
# ficaria mais lento a cada coleta.
HISTORICO_TETO = 40
HISTORICO_POR_PAGINA_MAX = 20

# Tudo que `match_statistics` guarda por partida, na ordem em que faz sentido
# ler. Uma fonte so' pra tres coisas: as colunas do SELECT, os rotulos da tela
# e as contas do resumo -- adicionar familia nova e' mexer aqui e mais nada.
#
#   modo "soma"  o numero da PARTIDA e' casa + fora (escanteio, falta, chute)
#   modo "lado"  somar nao significa nada (posse da 100% sempre), entao a media
#                e' por lado. E' um detector: posse media por lado longe de 50
#                ou precisao de passe longe de ~80 e' coleta torta, nao jogo
#                estranho.
STATS_DA_PARTIDA = [
    ("gols",         "Gols",                  "home_goals",             "away_goals",             "soma"),
    ("gols_ht",      "Gols no 1ºT",           "home_goals_ht",          "away_goals_ht",          "soma"),
    ("gols_90",      "Gols nos 90",           "home_goals_90",          "away_goals_90",          "soma"),
    ("escanteios",   "Escanteios",            "home_corners",           "away_corners",           "soma"),
    ("chutes",       "Chutes",                "home_total_shots",       "away_total_shots",       "soma"),
    ("chutes_gol",   "Chutes a gol",          "home_shots_on",          "away_shots_on",          "soma"),
    ("chutes_fora",  "Chutes para fora",      "home_shots_off",         "away_shots_off",         "soma"),
    ("bloqueados",   "Chutes bloqueados",     "home_blocked_shots",     "away_blocked_shots",     "soma"),
    ("defesas",      "Defesas do goleiro",    "home_goalkeeper_saves",  "away_goalkeeper_saves",  "soma"),
    ("faltas",       "Faltas",                "home_fouls",             "away_fouls",             "soma"),
    ("amarelos",     "Cartões amarelos",      "home_yellow_cards",      "away_yellow_cards",      "soma"),
    ("vermelhos",    "Cartões vermelhos",     "home_red_cards",         "away_red_cards",         "soma"),
    ("impedimentos", "Impedimentos",          "home_offsides",          "away_offsides",          "soma"),
    ("posse",        "Posse de bola (%)",     "home_possession",        "away_possession",        "lado"),
    ("passes",       "Passes",                "home_passes",            "away_passes",            "soma"),
    ("precisao",     "Precisão de passe (%)", "home_passes_accuracy",   "away_passes_accuracy",   "lado"),
]

# A assinatura do jogo "coletado vazio": FT com escanteio, chute e falta todos
# em ZERO. Nao e' hipotese -- `extract_stat` devolvia 0 pra ausencia ate' ser
# corrigido, e o banco ficou com 99 partidas assim, 94 delas COM GOL (ver o
# docstring de collectors/match_statistics_sync_service.py::extract_stat).
#
# Zero nao e' NULL, entao a contagem de "quantas vieram preenchidas" passa
# batido nessas linhas. So' olhando o valor da' pra ver.
_SQL_SUSPEITA = """
    COALESCE(home_corners, 0) + COALESCE(away_corners, 0) = 0
AND COALESCE(home_total_shots, 0) + COALESCE(away_total_shots, 0) = 0
AND COALESCE(home_fouls, 0) + COALESCE(away_fouls, 0) = 0
"""


@router.get("/dados/partidas")
def partidas_coletadas(
    pagina: int = 0,
    por_pagina: int = 10,
    filtro: str | None = None,
    meses: int = 24,
    current_user: dict = Depends(require_admin),
):
    """As ultimas partidas que entraram em `match_statistics`, paginadas.

    Sem filtro de status de proposito: "coletada" aqui e' literalmente ter
    linha na tabela. Jogo adiado ou interrompido que tenha estatistica gravada
    PRECISA aparecer -- ele conta nas medias do motor igual aos outros, e
    esconder da tela justo a linha esquisita e' esconder o problema.

    O `filtro` E' A SAIDA DO DIAGNOSTICO (2026-08-27)
    ------------------------------------------------
    Ate' aqui o diagnostico era um beco: ele dizia "45 jogos sem falta" e o
    unico caminho de conserto -- `Rodar` e `Preencher a mao` -- morava nesta
    lista, que so' mostra as 40 mais recentes. Se a API nao publica a folha
    daquele jogo (e ela nao publica folha velha), nao havia NENHUMA forma de
    chegar naquelas 45 partidas pela tela.

    Com `filtro`, o numero do diagnostico vira a propria lista: cada cartao de
    familia manda pra ca' com a chave dele, e as partidas que faltam aparecem
    com os mesmos tres botoes de sempre. E' o que fecha o ciclo
    "vejo o buraco -> chego na partida -> escrevo o numero".

    Valores aceitos: uma chave de STATS_DA_PARTIDA (a familia que falta),
    `folha_incompleta`, ou `zeradas`. Sem filtro, o comportamento e' o de antes.

    O TETO DE 40 SO' VALE SEM FILTRO. Ele existe pra a lista "ultimas
    coletadas" nao virar varredura; filtrando, o teto seria justamente o que
    esconderia a partida antiga que precisa de conserto -- entao ai' o recorte
    passa a ser a janela de meses, a mesma do diagnostico.
    """
    pagina     = max(0, pagina)
    por_pagina = min(max(1, por_pagina), HISTORICO_POR_PAGINA_MAX)
    offset     = pagina * por_pagina
    limite     = max(0, min(por_pagina, HISTORICO_TETO - offset))
    meses      = min(max(1, meses), 60)

    # Traduz o filtro em predicado. Chave desconhecida vira "sem filtro" em vez
    # de erro: o filtro chega da URL da tela, e um typo nao pode virar 500.
    por_familia = {chave: (casa, fora) for chave, _r, casa, fora, _m in STATS_DA_PARTIDA}
    onde_filtro = ""
    if filtro == "folha_incompleta":
        onde_filtro = _FOLHA_INCOMPLETA
    elif filtro == "zeradas":
        onde_filtro = f"({_SQL_SUSPEITA})"
    elif filtro in por_familia:
        casa, fora = por_familia[filtro]
        onde_filtro = f"({casa} IS NULL OR {fora} IS NULL)"

    conn = get_connection()
    cur  = conn.cursor()
    try:
        if onde_filtro:
            # Filtrando, o universo e' a janela inteira, nao as 40 ultimas ·
            # ver a docstring. O COUNT aqui e' de verdade, e por isso a janela
            # existe.
            cur.execute(f"""
                SELECT COUNT(*) AS n FROM match_statistics
                 WHERE {onde_filtro}
                   AND match_date >= (CURRENT_DATE - (%s || ' months')::interval)
            """, (meses,))
            total = (cur.fetchone() or {}).get("n") or 0
            limite = por_pagina
        else:
            # COUNT na tabela inteira seria varredura completa a cada troca de
            # pagina pra devolver, no maximo, 40. O LIMIT no subselect faz o
            # Postgres parar de contar no quadragesimo.
            cur.execute(
                f"SELECT COUNT(*) AS n FROM (SELECT 1 FROM match_statistics LIMIT {HISTORICO_TETO}) t"
            )
            total = (cur.fetchone() or {}).get("n") or 0

        # Cobertura e media das MESMAS 40 que a lista pagina, num passe so'.
        #
        # As duas juntas e' que acham erro. Cobertura sozinha nao ve' o jogo
        # coletado zerado (zero nao e' NULL); media sozinha nao diz se o numero
        # saiu de 40 partidas ou de 3. Defesa de goleiro, por exemplo, aparece
        # em menos de 1% dos jogos -- media alta ali com n=2 nao e' tendencia,
        # e' amostra.
        colunas_resumo = []
        for chave, _rot, casa, fora, modo in STATS_DA_PARTIDA:
            valor = f"({casa} + {fora})" if modo == "soma" else f"(({casa} + {fora}) / 2.0)"
            colunas_resumo.append(f"COUNT({valor}) AS {chave}_n")
            colunas_resumo.append(f"ROUND(AVG({valor})::numeric, 2) AS {chave}_m")
        cur.execute(f"""
            SELECT {', '.join(colunas_resumo)},
                   COUNT(*) FILTER (WHERE {_SQL_SUSPEITA}) AS zeradas
              FROM (SELECT * FROM match_statistics
                     ORDER BY match_date DESC, fixture_id DESC
                     LIMIT {HISTORICO_TETO}) t
        """)
        bruto = dict(cur.fetchone() or {})
        resumo = [
            {"chave": chave, "rotulo": rotulo, "modo": modo,
             "com_dado": bruto.get(f"{chave}_n") or 0,
             "media": float(bruto[f"{chave}_m"]) if bruto.get(f"{chave}_m") is not None else None}
            for chave, rotulo, _c, _f, modo in STATS_DA_PARTIDA
        ]
        zeradas = bruto.get("zeradas") or 0

        partidas = []
        # Montado fora da f-string: expressao condicional com aspas dentro de
        # f-string triplo funciona, mas e' exatamente o tipo de linha que
        # ninguem revisa direito depois.
        onde_sql = ""
        if onde_filtro:
            onde_sql = (f"WHERE {onde_filtro} AND ms.match_date >= "
                        "(CURRENT_DATE - (%s || ' months')::interval)")
        if limite:
            colunas = ", ".join(
                f"ms.{casa}, ms.{fora}" for _k, _r, casa, fora, _m in STATS_DA_PARTIDA
            )
            # LATERAL, e nao JOIN direto em `teams`: a tabela tem UMA LINHA POR
            # TEMPORADA por time, entao o join simples multiplicaria a partida
            # por quantas temporadas o time tiver cadastradas.
            cur.execute(f"""
                SELECT ms.fixture_id,
                       ms.match_date::text                  AS data,
                       ms.status,
                       ms.referee,
                       ms.last_updated::text                AS coletada_em,
                       -- Quais numeros desta linha foram digitados a mao, e
                       -- por quem. Numero manual e' indistinguivel do coletado
                       -- depois que entra na coluna; a tela marca a diferenca.
                       ms.manual_stats,
                       l.name                               AS liga,
                       casa.name                            AS mandante,
                       fora.name                            AS visitante,
                       ({_SQL_SUSPEITA})                    AS zerada,
                       {colunas}
                  FROM match_statistics ms
             LEFT JOIN leagues l ON l.league_id = ms.league_id
             LEFT JOIN LATERAL (
                       SELECT name FROM teams
                        WHERE team_id = ms.home_team_id
                        ORDER BY season DESC LIMIT 1
                   ) casa ON TRUE
             LEFT JOIN LATERAL (
                       SELECT name FROM teams
                        WHERE team_id = ms.away_team_id
                        ORDER BY season DESC LIMIT 1
                   ) fora ON TRUE
                 {onde_sql}
              ORDER BY ms.match_date DESC, ms.fixture_id DESC
                 LIMIT %s OFFSET %s
            """, ((meses,) if onde_filtro else ()) + (limite, offset))
            for r in cur.fetchall():
                linha = dict(r)
                # Achatar os 32 campos crus em par por familia: a tela desenha
                # "casa | fora" e nao precisa conhecer nome de coluna.
                stats = {
                    chave: [linha.pop(casa, None), linha.pop(fora, None)]
                    for chave, _rot, casa, fora, _modo in STATS_DA_PARTIDA
                }
                linha["stats"] = stats
                linha["completas"] = sum(
                    1 for par in stats.values() if par[0] is not None and par[1] is not None
                )
                partidas.append(linha)
    except Exception as e:
        # Mesma postura do /dados: consulta que falha nao pode levar a aba
        # junto, ela serve justamente pra quando algo esta errado.
        logging.getLogger(__name__).warning("[ADMIN/DADOS] partidas: %s", e)
        conn.rollback()
        return {"total": 0, "pagina": pagina, "por_pagina": por_pagina,
                "teto": HISTORICO_TETO, "partidas": [], "resumo": [],
                "zeradas": 0, "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "teto": HISTORICO_TETO,
        "familias": len(STATS_DA_PARTIDA),
        "resumo": resumo,
        "zeradas": zeradas,
        "partidas": partidas,
        # Ecoados pra a tela poder desenhar o estado do filtro sem guardar
        # duas verdades · o servidor descarta chave desconhecida, e a tela
        # precisa saber disso.
        "filtro": filtro if onde_filtro else None,
        "meses": meses if onde_filtro else None,
    }



# ─── O buraco de estatistica, e as tres saidas dele ─────────────────────────
#
# A aba Dados mostrava o buraco e parava ai'. "12 partidas encerradas sem
# estatistica" sem nada pra clicar e' um alarme sem botao: ate' aqui a unica
# saida era esperar a varredura automatica -- que so' enxerga 3 dias e so' roda
# em producao -- ou rodar o pipeline inteiro por causa de uma partida.
#
# Sao tres saidas, em ordem de preferencia:
#
#   1. RODAR       repergunta a folha pra API. Resolve o caso normal (a coleta
#                  passou antes de a API publicar) e custa 2 requisicoes.
#   2. LINHA OCA   a API respondeu sem folha e nao vai mudar de ideia (jogo
#                  antigo, liga sem cobertura de estatistica). Cria a linha com
#                  placar/status/arbitro vindos de /fixtures e os contadores em
#                  NULL, pra o passo 3 ter onde escrever.
#   3. A MAO       digitar o numero olhando a sumula. Fica marcado em
#                  `manual_stats`, com quem digitou e quando.
#
# A ordem importa: numero digitado a mao e' o ultimo recurso, nao o primeiro.
# Ele entra na mesma coluna que o coletado e o motor le' os dois igual.

#: chave da familia -> (coluna casa, coluna fora, modo). Mesma fonte que a tela
#: e o resumo usam -- adicionar familia continua sendo mexer so' em
#: STATS_DA_PARTIDA.
_STATS_POR_CHAVE = {
    chave: (casa, fora, modo) for chave, _rot, casa, fora, modo in STATS_DA_PARTIDA
}

#: Familias que TAMBEM tem coluna de total no banco. Gravar o lado sem refazer
#: o total deixa a linha incoerente consigo mesma, e o motor le' as duas: o
#: pool de cartoes sai de `total_yellow_cards`, a media de escanteio da liga
#: sai de `total_corners`.
_TOTAL_DA_FAMILIA = {
    "gols":       "total_goals",
    "escanteios": "total_corners",
    "amarelos":   "total_yellow_cards",
    "vermelhos":  "total_red_cards",
}

#: Teto por familia. Nao e' regra de futebol, e' peneira de digito trocado --
#: 55 escanteios num jogo e' tecla presa, e numero torto no banco nao para na
#: partida: vira baseline torto da liga inteira, media torta do time e do
#: arbitro, e o sintoma aparece semanas depois como "o motor nao pega mais
#: escanteio nessa liga".
_TETO_DA_FAMILIA = {"posse": 100, "precisao": 100, "passes": 1500, "gols": 30}
_TETO_PADRAO = 60


class EstatisticaManualBody(BaseModel):
    """{"valores": {"escanteios": [7, 4], "faltas": [12, 15]}}

    O par e' [casa, fora], na mesma forma que /dados/partidas devolve. `null`
    num lado apaga o numero de volta pra ausencia -- que e' a forma de desfazer
    um valor digitado errado sem inventar zero no lugar.
    """
    valores: dict[str, list[Optional[float]]]

    @field_validator("valores")
    @classmethod
    def validar_valores(cls, v):
        if not v:
            raise ValueError("Nenhum valor enviado.")
        for chave, par in v.items():
            if chave not in _STATS_POR_CHAVE:
                raise ValueError(f"Estatistica desconhecida: {chave}")
            if not isinstance(par, list) or len(par) != 2:
                raise ValueError(f"{chave}: esperado [casa, fora].")
            teto = _TETO_DA_FAMILIA.get(chave, _TETO_PADRAO)
            for lado in par:
                if lado is None:
                    continue
                if lado < 0 or lado > teto:
                    raise ValueError(f"{chave}: fora da faixa 0 a {teto}.")
        return v


def _no_path() -> None:
    """Poe o motor no sys.path · mesmo caminho que o settlement_bridge usa."""
    if _PIPELINE_DIR and _PIPELINE_DIR not in sys.path:
        sys.path.insert(0, _PIPELINE_DIR)


def _recalcular_medias(home_team_id, away_team_id, league_id, season) -> bool:
    """`team_statistics` dos dois times da partida.

    Escrever em `match_statistics` e nao refazer a media deixa o motor lendo a
    media de ontem sobre um historico de hoje -- o pior dos dois mundos, porque
    parece atualizado. E' a mesma razao pela qual a varredura automatica chama
    o agregador na mesma passada (stats_sweep._coletar).

    Best-effort de proposito: a estatistica ja' esta gravada quando isto roda,
    e falhar aqui nao pode desfazer a gravacao. O proximo pipeline recalcula.
    """
    try:
        _no_path()
        from services.team_stats_aggregator_service import TeamStatsAggregatorService
        agregador = TeamStatsAggregatorService()
        for team_id in (home_team_id, away_team_id):
            if team_id and league_id and season:
                agregador.process_single_team(team_id, league_id, season)
        return True
    except Exception as e:
        logging.getLogger(__name__).warning("[ADMIN/DADOS] recalculo de medias: %s", e)
        return False


def _linha_da_partida(fixture_id: int) -> dict | None:
    """A linha de `match_statistics` na mesma forma que a lista da tela usa."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        colunas = ", ".join(f"{casa}, {fora}" for _k, _r, casa, fora, _m in STATS_DA_PARTIDA)
        cur.execute(f"""
            SELECT fixture_id, match_date::text AS data, status, referee,
                   last_updated::text AS coletada_em, manual_stats,
                   home_team_id, away_team_id, league_id, season,
                   {colunas}
              FROM match_statistics WHERE fixture_id = %s
        """, (fixture_id,))
        linha = cur.fetchone()
        if not linha:
            return None
        linha = dict(linha)
        stats = {
            chave: [linha.pop(casa, None), linha.pop(fora, None)]
            for chave, _rot, casa, fora, _modo in STATS_DA_PARTIDA
        }
        linha["stats"] = stats
        linha["completas"] = sum(
            1 for par in stats.values() if par[0] is not None and par[1] is not None
        )
        return linha
    finally:
        cur.close()
        conn.close()


@router.get("/dados/buracos")
def buracos_de_estatistica(limite: int = 30, current_user: dict = Depends(require_admin)):
    """As partidas que o painel CONTA em "encerradas sem estatistica", nomeadas.

    O numero sozinho nao da' pra agir: pra ir atras de uma delas era preciso
    abrir o banco. Aqui elas viram linha com nome de time e botao.

    Le' `fixtures.home_team`/`away_team` (texto, gravado pelo coletor) em vez de
    juntar com `teams`: a partida orfa e' justamente a que pode ter time nao
    cadastrado, e o LEFT JOIN devolveria "Time ?" bem no caso que interessa.
    """
    limite = min(max(1, limite), 100)
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT f.fixture_id,
                   f.match_datetime::text AS data,
                   f.status,
                   f.home_team            AS mandante,
                   f.away_team            AS visitante,
                   l.name                 AS liga
              FROM fixtures f
         LEFT JOIN match_statistics ms ON ms.fixture_id = f.fixture_id
         LEFT JOIN leagues l           ON l.league_id  = f.league_id
             WHERE f.status IN ('FT','AET','PEN')
               AND ms.fixture_id IS NULL
          ORDER BY f.match_datetime DESC
             LIMIT %s
        """, (limite,))
        partidas = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logging.getLogger(__name__).warning("[ADMIN/DADOS] buracos: %s", e)
        conn.rollback()
        return {"partidas": [], "limite": limite, "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()
    return {"partidas": partidas, "limite": limite}


@router.post("/dados/partidas/{fixture_id}/coletar")
async def coletar_partida(
    fixture_id: int,
    criar_sem_folha: bool = False,
    current_user: dict = Depends(require_admin),
):
    """Repergunta a folha desta partida pra API-Football, agora.

    Reusa `MatchStatisticsSyncService.sync_one_fixture`, que e' o MESMO caminho
    do lote -- nao existe um segundo jeito de escrever em `match_statistics`.
    Custa 2 requisicoes (a partida e a folha), entao roda em qualquer ambiente:
    o freio de cota que existe na varredura automatica esta' la' porque ela
    dispara sozinha, e este botao so' dispara por clique.

    `criar_sem_folha=true` e' a segunda saida: grava a linha com placar e
    arbitro de /fixtures e os contadores em NULL, pra a partida que a API nunca
    vai publicar poder ser preenchida a mao. So' por clique explicito -- linha
    oca criada sozinha esconderia a partida da varredura pra sempre.

    Sincrono de proposito, ao contrario de /leagues/{id}/coletar: sao duas
    requisicoes e a tela precisa do resultado pra dizer o que fazer em seguida.
    """
    def _rodar():
        _no_path()
        from collectors.match_statistics_sync_service import MatchStatisticsSyncService
        return MatchStatisticsSyncService().sync_one_fixture(
            fixture_id, criar_sem_folha=criar_sem_folha)

    try:
        saida = await run_in_threadpool(_rodar)
    except Exception as e:
        logging.getLogger(__name__).warning("[ADMIN/DADOS] coletar %s: %s", fixture_id, e)
        raise HTTPException(502, f"A coleta falhou: {str(e)[:200]}")

    situacao = saida.get("situacao")
    mensagem = {
        "gravada":         "Folha coletada e gravada.",
        "linha_sem_folha": "A API não tem a folha desta partida. A linha foi criada com o "
                           "placar · os contadores ficam para preencher à mão.",
        "sem_folha":       "A API respondeu sem folha de estatística para esta partida.",
        "nao_encontrada":  "A API não conhece esta partida.",
        "nao_finalizada":  "A partida ainda não terminou para a API · nada a coletar.",
    }.get(situacao, "Coleta concluída.")

    partida = None
    medias = False
    if situacao in ("gravada", "linha_sem_folha"):
        partida = await run_in_threadpool(_linha_da_partida, fixture_id)
        if partida:
            medias = await run_in_threadpool(
                _recalcular_medias, partida["home_team_id"], partida["away_team_id"],
                partida["league_id"], partida["season"])

    return {"ok": situacao in ("gravada", "linha_sem_folha"),
            "situacao": situacao, "mensagem": mensagem,
            "medias_recalculadas": medias, "partida": partida,
            "familias": len(STATS_DA_PARTIDA)}


@router.put("/dados/partidas/{fixture_id}/estatisticas")
def editar_estatistica_manual(
    fixture_id: int,
    body: EstatisticaManualBody,
    current_user: dict = Depends(require_admin),
):
    """Preenche a mao a estatistica que a API nao entregou.

    So' edita linha que ja' existe: criar a linha e' trabalho do botao Rodar,
    porque placar, status, arbitro e ids de time tem que vir de /fixtures. Sem
    isso a linha nasceria com placar inventado, e placar inventado liquida pick.

    Tres coisas acontecem juntas, e as tres sao necessarias:
      · o par casa/fora vai pra coluna
      · o total da familia e' refeito (NULL se faltar um lado -- parcela
        desconhecida, total desconhecido, igual ao `_sum_stats` do coletor)
      · `manual_stats` guarda o que foi digitado, por quem e quando

    `last_updated` sobe junto, e isso e' proposital: e' o que faz o coletor
    parar de voltar nesta partida (ver o predicado de "estabilizado" em
    _load_fixtures). Se a folha for completada a mao, a proxima coleta em lote
    nao gasta requisicao com ela. O botao Rodar continua passando por cima --
    numero da API vence numero digitado, sempre.
    """
    valores = body.valores
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT home_team_id, away_team_id, league_id, season
              FROM match_statistics WHERE fixture_id = %s
        """, (fixture_id,))
        linha = cur.fetchone()
        if not linha:
            raise HTTPException(
                404, "Esta partida não tem linha em match_statistics. Use o botão "
                     "Rodar primeiro · o placar e os times precisam vir da API.")
        linha = dict(linha)

        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        quem = current_user.get("email") or current_user.get("name") or "admin"

        sets, params, marca = [], [], {}
        for chave, par in valores.items():
            casa_col, fora_col, _modo = _STATS_POR_CHAVE[chave]
            casa, fora = par
            sets += [f"{casa_col} = %s", f"{fora_col} = %s"]
            params += [casa, fora]

            total_col = _TOTAL_DA_FAMILIA.get(chave)
            if total_col:
                sets.append(f"{total_col} = %s")
                params.append(None if casa is None or fora is None else casa + fora)

            marca[chave] = {"casa": casa, "fora": fora, "por": quem, "em": agora}

        sets.append("manual_stats = COALESCE(manual_stats, '{}'::jsonb) || %s::jsonb")
        params.append(json.dumps(marca))
        sets.append("last_updated = NOW()")
        params.append(fixture_id)

        cur.execute(
            f"UPDATE match_statistics SET {', '.join(sets)} WHERE fixture_id = %s",
            tuple(params))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/DADOS] editar %s: %s", fixture_id, e)
        raise HTTPException(500, f"Não deu pra gravar: {str(e)[:200]}")
    finally:
        cur.close()
        conn.close()

    medias = _recalcular_medias(linha["home_team_id"], linha["away_team_id"],
                                linha["league_id"], linha["season"])
    return {"ok": True, "gravadas": sorted(valores), "medias_recalculadas": medias,
            "partida": _linha_da_partida(fixture_id),
            "familias": len(STATS_DA_PARTIDA)}


# ─── Cartao vermelho que a API mandou vazio ────────────────────────────────
#
# A API-Football publica zero explicito em todo contador da folha, MENOS em
# "Red Cards": esse ela manda `null` no caso normal, quando ninguem foi expulso.
# Entre 2026-07-25 e 2026-08-26 o coletor leu esse null como ausencia e gravou
# NULL -- ver o cabecalho de utils/stat_sheet.py, com a medicao.
#
# O estrago nao para no vermelho. `stats_model` derruba do pool de cartoes todo
# jogo sem os dois contadores, entao 87% da amostra evaporou; e a media de
# vermelho do arbitro saia tirada SO' dos jogos com expulsao (AVG ignora NULL),
# o que da' 1,00 pra quem tem 1 expulsao em 10 jogos.
#
# O coletor ja' foi corrigido, mas coletor corrigido nao mexe no passado: a
# coleta so' volta em folha incompleta, e a janela e' de dias. O conserto do
# historico e' este, e ele mora aqui porque e' operacao de painel -- o script
# de linha de comando continua sendo a fonte da regra.


def _alvo_vermelho() -> str:
    """O predicado do backfill, importado do script · nao copiado.

    A regra e' estreita: so' entra a linha com a folha COMPLETA no resto e o
    buraco unicamente no vermelho. Essa combinacao so' pode ter sido produzida
    pelo coletor lendo uma folha publicada -- ou seja, a API respondeu e disse
    que nao houve expulsao. Folha de fato incompleta nao e' tocada: continua
    NULL, e a coleta volta nela sozinha.
    """
    _no_path()
    from scripts.backfill_cartao_vermelho import _ALVO
    return _ALVO


@router.get("/dados/vermelho-legado")
def vermelho_legado(current_user: dict = Depends(require_admin)):
    """Quantas linhas ainda tem o vermelho apagado pelo bug · so' leitura."""
    try:
        alvo_sql = _alvo_vermelho()
    except Exception as e:
        return {"disponivel": False, "erro": str(e)[:200]}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) AS n FROM match_statistics WHERE {alvo_sql}")
        alvo = (cur.fetchone() or {}).get("n") or 0
        cur.execute("""
            SELECT COUNT(*) AS n FROM match_statistics
             WHERE status IN ('FT','AET','PEN')
               AND (home_red_cards IS NULL OR away_red_cards IS NULL
                    OR total_red_cards IS NULL)
        """)
        sem_vermelho = (cur.fetchone() or {}).get("n") or 0
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/DADOS] vermelho: %s", e)
        return {"disponivel": False, "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {
        "disponivel": True,
        "alvo": alvo,
        "sem_vermelho": sem_vermelho,
        # A diferenca e' a folha de fato incompleta: nao entra no conserto, e
        # mostrar as duas juntas e' o que evita a leitura de que o backfill
        # "deixou linha pra tras".
        "folha_incompleta": max(0, sem_vermelho - alvo),
    }


@router.post("/dados/vermelho-legado")
def corrigir_vermelho_legado(current_user: dict = Depends(require_admin)):
    """Grava 0 no vermelho das linhas-alvo e refaz a media dos arbitros.

    Usa `_aplicar` e `_recalcular_arbitros` do proprio script: e' um UPDATE de
    predicado estreito, e a media do arbitro TEM que ser refeita na mesma
    transacao -- corrigir o vermelho e deixar `referee_stats.avg_red` inflado
    trocaria um numero errado por outro.
    """
    try:
        _no_path()
        from scripts.backfill_cartao_vermelho import _aplicar, _recalcular_arbitros
    except Exception as e:
        raise HTTPException(500, f"Script de backfill indisponível: {str(e)[:200]}")

    conn = get_connection()
    cur = conn.cursor()
    try:
        corrigidas = _aplicar(cur)
        arbitros = _recalcular_arbitros(cur)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/DADOS] backfill vermelho: %s", e)
        raise HTTPException(500, f"Não deu pra corrigir: {str(e)[:200]}")
    finally:
        cur.close()
        conn.close()

    return {"ok": True, "corrigidas": corrigidas, "arbitros": arbitros}




# ─── Diagnóstico da folha inteira, e a recoleta em lote ─────────────────────
#
# O bloco do vermelho conserta UM defeito conhecido, e ele é a exceção da casa:
# vermelho é o único contador em que `null` numa folha publicada significa zero,
# então é o único que dá pra corrigir com SQL, sem perguntar nada pra API. Em
# qualquer outra família, inventar o número seria fabricar estatística · e zero
# fabricado vira pick errado (invariante 1 de services/settlement.py).
#
# Pras outras só existem dois caminhos honestos: pedir de novo pra API, ou
# digitar olhando a súmula. O que faltava era enxergar ONDE estão os buracos,
# porque o resumo da tela olha as últimas 40 partidas e defeito de coleta não
# mora só ali · e um jeito de rodar a recoleta em cima de todas de uma vez, sem
# clicar partida por partida.
#
# As médias do resumo saem das últimas 40. Este diagnóstico varre a tabela
# inteira dentro de uma janela de meses. São perguntas diferentes: uma é "o
# motor está lendo bem AGORA", a outra é "o que o histórico tem de furado".

#: A definição de "folha completa" do projeto, em colunas.
#:
#: É a MESMA lista do predicado de "estabilizado" em
#: collectors/match_statistics_sync_service.py::_load_fixtures e do corte de
#: sync_pending_fixtures. Repetir a lista aqui é o preço de o coletor guardá-la
#: dentro de string de SQL, sem constante pra importar · o teste
#: test_estatistica_a_mao_2026_08 lê o arquivo do coletor e trava as duas
#: juntas, pra a definição não se abrir em duas.
#:
#: Não são as 16 famílias de propósito: defesa de goleiro aparece em menos de
#: 1% das folhas, e exigir as 16 marcaria a tabela inteira como incompleta e
#: mandaria recoletar 3.000 partidas pra nada.
_COLUNAS_DA_FOLHA = ("total_corners", "total_yellow_cards", "total_red_cards",
                     "home_fouls", "home_total_shots")
_FOLHA_INCOMPLETA = "(" + " OR ".join(f"{c} IS NULL" for c in _COLUNAS_DA_FOLHA) + ")"


# ─── Placar 0x0 que não aconteceu ───────────────────────────────────────────
#
# Até 27/08 os três leitores de /fixtures montavam a linha com
# `goals["home"] or 0`, e `or 0` não distingue "a API disse zero" de "a API não
# disse nada". Campo nulo virava jogo terminado 0x0 dentro de
# `match_statistics`.
#
# É o mesmo defeito do cartão vermelho, com dois agravantes: gol é a família
# que mais mercado gera (baseline de liga, média de time, confronto direto), e
# zero não é NULL · o 0x0 falso passa por "preenchido" em toda contagem de
# cobertura desta aba e some da varredura, que procura jogo ENCERRADO SEM
# LINHA. Foi assim que ele apareceu: um 0-0 na amostra do motor, num jogo que
# não terminou 0x0.
#
# O coletor já foi corrigido (placar ausente agora recusa a linha), mas coletor
# corrigido não mexe no passado.
#
# A DETECÇÃO NÃO É PALPITE. `home_goals_90`/`away_goals_90` (score.fulltime da
# API) e `home_goals_ht`/`away_goals_ht` são colunas independentes, gravadas na
# mesma passada e sem o `or 0`. Placar final 0x0 com qualquer uma delas acima
# de zero é aritmeticamente impossível: gol não se desmarca, e prorrogação só
# soma. Onde as três concordam em zero, o 0x0 é real e a linha não é tocada.
_SQL_PLACAR_FALSO = """
    status IN ('FT','AET','PEN')
AND COALESCE(home_goals, 0) + COALESCE(away_goals, 0) = 0
AND (COALESCE(home_goals_90, 0) + COALESCE(away_goals_90, 0) > 0
     OR COALESCE(home_goals_ht, 0) + COALESCE(away_goals_ht, 0) > 0)
"""

# O conserto só vale onde a referência RESOLVE o placar, e ela só resolve em
# FT: aí `score.fulltime` é, por definição, o placar final. Em AET/PEN ele é o
# placar dos 90 minutos, e o jogo continuou depois -- copiar aquele número
# gravaria outro placar errado no lugar do primeiro. Esses voltam pela recoleta,
# que é uma requisição por partida, e ficam contados à parte pra a tela não
# dizer que sobrou linha por descuido.
_SQL_PLACAR_CORRIGIVEL = f"""
    ({_SQL_PLACAR_FALSO})
AND status = 'FT'
AND home_goals_90 IS NOT NULL AND away_goals_90 IS NOT NULL
"""


@router.get("/dados/placar-falso")
def placar_falso(current_user: dict = Depends(require_admin)):
    """Quantas linhas têm 0x0 gravado num jogo que não terminou 0x0."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT COUNT(*) FILTER (WHERE {_SQL_PLACAR_FALSO})     AS total,
                   COUNT(*) FILTER (WHERE {_SQL_PLACAR_CORRIGIVEL}) AS corrigiveis
              FROM match_statistics
        """)
        bruto = dict(cur.fetchone() or {})
        total = bruto.get("total") or 0

        partidas = []
        if total:
            cur.execute(f"""
                SELECT ms.fixture_id, ms.match_date::text AS data, ms.status,
                       ms.home_goals_90, ms.away_goals_90,
                       ms.home_goals_ht, ms.away_goals_ht,
                       casa.name AS mandante, fora.name AS visitante,
                       l.name AS liga
                  FROM match_statistics ms
             LEFT JOIN leagues l ON l.league_id = ms.league_id
             -- Mesmo LATERAL da lista de partidas: `teams` tem uma linha por
             -- temporada, e um JOIN direto multiplicaria a partida.
             LEFT JOIN LATERAL (
                       SELECT name FROM teams
                        WHERE team_id = ms.home_team_id
                        ORDER BY season DESC LIMIT 1
                   ) casa ON TRUE
             LEFT JOIN LATERAL (
                       SELECT name FROM teams
                        WHERE team_id = ms.away_team_id
                        ORDER BY season DESC LIMIT 1
                   ) fora ON TRUE
                 WHERE {_SQL_PLACAR_FALSO}
              ORDER BY ms.match_date DESC
                 LIMIT 20
            """)
            partidas = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/DADOS] placar falso: %s", e)
        return {"disponivel": False, "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    corrigiveis = bruto.get("corrigiveis") or 0
    return {
        "disponivel": True,
        "total": total,
        "corrigiveis": corrigiveis,
        # A diferença são os AET/PEN: o placar de 90' não responde por eles.
        "so_recoleta": max(0, total - corrigiveis),
        "partidas": partidas,
    }


@router.post("/dados/placar-falso")
def corrigir_placar_falso(current_user: dict = Depends(require_admin)):
    """Reescreve o placar a partir do de 90 minutos e refaz as médias.

    Não inventa número nenhum: copia uma coluna que já estava no banco, gravada
    na mesma passada e livre do `or 0`. Refazer `team_statistics` na sequência
    é obrigatório pelo mesmo motivo do backfill de vermelho -- corrigir o jogo
    e deixar a média velha troca um número errado por outro, com a agravante de
    parecer atualizado.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT home_team_id, away_team_id, league_id, season
              FROM match_statistics WHERE {_SQL_PLACAR_CORRIGIVEL}
        """)
        afetados = [dict(r) for r in cur.fetchall()]

        cur.execute(f"""
            UPDATE match_statistics
               SET home_goals  = home_goals_90,
                   away_goals  = away_goals_90,
                   total_goals = home_goals_90 + away_goals_90,
                   last_updated = NOW()
             WHERE {_SQL_PLACAR_CORRIGIVEL}
        """)
        corrigidas = cur.rowcount or 0
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/DADOS] conserto de placar: %s", e)
        raise HTTPException(500, f"Não deu pra corrigir: {str(e)[:200]}")
    finally:
        cur.close()
        conn.close()

    # Uma passada por (liga, temporada) distinta em vez de uma por partida: o
    # agregador lê a temporada inteira do time, então repetir por jogo refaria
    # a mesma conta N vezes.
    grupos = {(r["home_team_id"], r["away_team_id"], r["league_id"], r["season"])
              for r in afetados}
    medias = sum(1 for g in grupos if _recalcular_medias(*g))

    return {"ok": True, "corrigidas": corrigidas, "medias": medias}


@router.get("/dados/diagnostico")
def diagnostico_da_folha(meses: int = 12, current_user: dict = Depends(require_admin)):
    """Onde estão os buracos da tabela inteira, família por família.

    A janela existe porque isto é varredura: sem recorte, cada abertura da aba
    passaria por toda a história de `match_statistics` pra contar coisa que
    ninguém vai recoletar (jogo de 2023 não volta · a API não guarda folha
    velha, e recoletar custaria uma requisição por partida pra receber vazio).
    """
    meses = min(max(1, meses), 60)
    conn = get_connection()
    cur = conn.cursor()
    try:
        colunas = []
        for chave, _rot, casa, fora, _modo in STATS_DA_PARTIDA:
            colunas.append(f"COUNT({casa} + {fora}) AS {chave}_n")
            # A data do buraco MAIS ANTIGO da família. É o que separa "defeito
            # que voltou agora" de "cicatriz de julho": os dois aparecem como
            # cobertura baixa, e só um deles pede ação.
            colunas.append(
                f"MIN(match_date) FILTER (WHERE {casa} IS NULL OR {fora} IS NULL)::text "
                f"AS {chave}_desde")
        cur.execute(f"""
            SELECT COUNT(*)                                        AS ft,
                   COUNT(*) FILTER (WHERE {_FOLHA_INCOMPLETA})     AS incompletas,
                   COUNT(*) FILTER (WHERE {_SQL_SUSPEITA})         AS zeradas,
                   MIN(match_date) FILTER (WHERE {_FOLHA_INCOMPLETA})::text AS incompleta_mais_antiga,
                   {', '.join(colunas)}
              FROM match_statistics
             WHERE status IN ('FT','AET','PEN')
               AND match_date >= (CURRENT_DATE - (%s || ' months')::interval)
        """, (meses,))
        bruto = dict(cur.fetchone() or {})

        ft = bruto.get("ft") or 0
        familias = [
            {"chave": chave, "rotulo": rotulo,
             "com_dado": bruto.get(f"{chave}_n") or 0,
             "sem_dado": max(0, ft - (bruto.get(f"{chave}_n") or 0)),
             "desde": bruto.get(f"{chave}_desde")}
            for chave, rotulo, _c, _f, _m in STATS_DA_PARTIDA
        ]

        # Partida encerrada que nunca chegou a ter linha. O diagnóstico e a
        # recoleta tratam as duas coisas juntas de propósito: pra quem opera,
        # "o motor não viu esse jogo" é o mesmo problema, tenha a linha nascido
        # incompleta ou não tenha nascido.
        cur.execute("""
            SELECT COUNT(*) AS n
              FROM fixtures f
         LEFT JOIN match_statistics ms ON ms.fixture_id = f.fixture_id
             WHERE f.status IN ('FT','AET','PEN') AND ms.fixture_id IS NULL
        """)
        sem_linha = (cur.fetchone() or {}).get("n") or 0
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/DADOS] diagnostico: %s", e)
        return {"erro": str(e)[:200], "familias": [], "ft": 0,
                "incompletas": 0, "zeradas": 0, "sem_linha": 0, "meses": meses}
    finally:
        cur.close()
        conn.close()

    return {
        "meses": meses,
        "ft": ft,
        "incompletas": bruto.get("incompletas") or 0,
        "incompleta_mais_antiga": bruto.get("incompleta_mais_antiga"),
        "zeradas": bruto.get("zeradas") or 0,
        "sem_linha": sem_linha,
        "familias": familias,
        # A tela precisa dizer o que ela considera folha completa · senão
        # "incompleta" vira um número sem definição.
        "colunas_da_folha": list(_COLUNAS_DA_FOLHA),
    }


#: Estado da recoleta em lote. Mora na MEMÓRIA do processo, igual ao status do
#: pipeline: é acompanhamento de execução, não histórico · e um deploy no meio
#: da recoleta interrompe o trabalho de qualquer jeito.
_recoleta: dict = {
    "rodando": False, "total": 0, "feitas": 0, "gravadas": 0, "falhas": 0,
    "iniciada_em": None, "terminada_em": None, "ultimo": None, "erro": None,
    "medias": 0,
}
_recoleta_lock = threading.Lock()

#: Teto de partidas por lote. Cada uma custa DUAS requisições da API (a partida
#: e a folha), e a chave é uma conta só pros três ambientes · foi assim que a
#: cota estourou em 2026-08-01 e o agendador foi removido. 100 partidas são 200
#: requisições, o suficiente pra doer sem clique nenhum de aviso.
_RECOLETA_TETO = 100


def _ids_para_recoletar(limite: int, meses: int) -> list:
    """As partidas que valem uma requisição, mais recentes primeiro.

    Duas fontes na mesma lista: linha existente com a folha incompleta, e
    partida encerrada sem linha nenhuma. Mais recente primeiro porque a API
    publica folha de jogo velho cada vez menos · gastar as 20 requisições do
    lote em agosto rende mais que gastá-las em março.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT fixture_id, match_date FROM (
                SELECT ms.fixture_id, ms.match_date
                  FROM match_statistics ms
                 WHERE ms.status IN ('FT','AET','PEN')
                   AND {_FOLHA_INCOMPLETA}
                   AND ms.match_date >= (CURRENT_DATE - (%s || ' months')::interval)
                 UNION
                SELECT f.fixture_id, f.match_datetime::date
                  FROM fixtures f
             LEFT JOIN match_statistics m2 ON m2.fixture_id = f.fixture_id
                 WHERE f.status IN ('FT','AET','PEN')
                   AND m2.fixture_id IS NULL
                   AND f.match_datetime >= (CURRENT_DATE - (%s || ' months')::interval)
            ) alvo
             ORDER BY match_date DESC
             LIMIT %s
        """, (meses, meses, limite))
        return [r["fixture_id"] for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def _recoletar_em_lote(ids: list) -> None:
    """Uma partida por vez, pelo mesmo caminho do botão Rodar.

    Sequencial de propósito: paralelizar aqui multiplicaria o consumo de cota
    por segundo sem reduzir o total, e a API-Football tem limite por minuto.
    """
    times = set()
    try:
        _no_path()
        from collectors.match_statistics_sync_service import MatchStatisticsSyncService

        for fixture_id in ids:
            try:
                saida = MatchStatisticsSyncService().sync_one_fixture(fixture_id)
                situacao = saida.get("situacao")
                with _recoleta_lock:
                    _recoleta["feitas"] += 1
                    _recoleta["ultimo"] = {"fixture_id": fixture_id, "situacao": situacao}
                    if situacao == "gravada":
                        _recoleta["gravadas"] += 1
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "[ADMIN/RECOLETA] fixture %s: %s", fixture_id, e)
                with _recoleta_lock:
                    _recoleta["feitas"] += 1
                    _recoleta["falhas"] += 1
                    _recoleta["ultimo"] = {"fixture_id": fixture_id, "situacao": "erro"}

        # As médias no fim, uma vez por time · não a cada partida. Um lote de
        # 20 jogos costuma tocar menos de 40 times, e recalcular por partida
        # refaria a mesma média várias vezes contra a tabela inteira.
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT DISTINCT home_team_id, away_team_id, league_id, season
                  FROM match_statistics WHERE fixture_id = ANY(%s)
            """, (ids,))
            for r in cur.fetchall():
                times.add((r["home_team_id"], r["league_id"], r["season"]))
                times.add((r["away_team_id"], r["league_id"], r["season"]))
        finally:
            cur.close()
            conn.close()

        from services.team_stats_aggregator_service import TeamStatsAggregatorService
        agregador = TeamStatsAggregatorService()
        for team_id, league_id, season in times:
            if not (team_id and league_id and season):
                continue
            try:
                agregador.process_single_team(team_id, league_id, season)
                with _recoleta_lock:
                    _recoleta["medias"] += 1
            except Exception as e:
                logging.getLogger(__name__).warning("[ADMIN/RECOLETA] media %s: %s", team_id, e)
    except Exception as e:
        logging.getLogger(__name__).error("[ADMIN/RECOLETA] lote: %s", e, exc_info=True)
        with _recoleta_lock:
            _recoleta["erro"] = str(e)[:200]
    finally:
        with _recoleta_lock:
            _recoleta["rodando"] = False
            _recoleta["terminada_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.post("/dados/recoletar")
async def recoletar_em_lote(
    limite: int = 20,
    meses: int = 3,
    current_user: dict = Depends(require_admin),
):
    """Roda a coleta em cima de todas as partidas furadas da janela, de uma vez.

    É o botão Rodar aplicado a uma lista · não um caminho novo de gravação. Vai
    pra thread de fundo porque são duas requisições por partida: um lote de 20
    leva minutos, e nenhum request HTTP espera isso.

    A janela padrão é curta (3 meses) pelo mesmo motivo que a varredura
    automática só olha 3 dias: folha que não apareceu há muito tempo quase
    nunca aparece, e cada tentativa custa cota.
    """
    limite = min(max(1, limite), _RECOLETA_TETO)
    meses = min(max(1, meses), 24)

    with _recoleta_lock:
        if _recoleta["rodando"]:
            raise HTTPException(409, "Já há uma recoleta em andamento.")

    ids = await run_in_threadpool(_ids_para_recoletar, limite, meses)
    if not ids:
        return {"ok": True, "total": 0,
                "mensagem": "Nenhuma partida furada na janela · nada a recoletar."}

    with _recoleta_lock:
        _recoleta.update({
            "rodando": True, "total": len(ids), "feitas": 0, "gravadas": 0,
            "falhas": 0, "medias": 0, "erro": None, "ultimo": None,
            "terminada_em": None,
            "iniciada_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    threading.Thread(target=_recoletar_em_lote, args=(ids,),
                     name="admin-recoleta", daemon=True).start()

    return {"ok": True, "total": len(ids),
            "mensagem": f"{len(ids)} partida(s) na fila · {len(ids) * 2} requisições da API."}


@router.get("/dados/recoleta-status")
def recoleta_status(current_user: dict = Depends(require_admin)):
    """Só leitura. A tela pesquisa isto enquanto o lote roda."""
    with _recoleta_lock:
        return dict(_recoleta)



# ─── A amostra por trás da média ────────────────────────────────────────────
#
# `team_statistics` é UM número por contexto, e é dele que o motor decide. A
# pergunta que não tinha tela é a de trás: QUE jogos entraram nessa média.
#
# Sem a lista, "média de escanteios 9,4" é indistinguível em três casos que
# pedem reações opostas:
#
#   · 18 jogos coletados inteiros              -> o número é o número
#   · 3 jogos                                  -> é amostra, não tendência
#   · 18 jogos, 7 deles com escanteio ausente  -> é média puxada pra baixo por
#                                                 buraco de coleta
#
# O terceiro é o que morde, e ele é invisível em qualquer contagem de
# cobertura. O agregador soma `g.get(campo) or 0` e incrementa o contador do
# mesmo jeito (ver services/match_stats_service_media.py::_aggregate_games):
# jogo com o contador NULL entra na média COMO ZERO. Não é bug do agregador --
# é o preço de somar em Python -- mas significa que folha furada não some da
# média, ela a distorce. A tela marca exatamente esses jogos.
#
# A média mostrada aqui NÃO é recalculada por conta própria: vem de
# `calculate_team_season_averages`, o mesmo método que o pipeline chama. Uma
# segunda implementação aqui poderia discordar do motor justamente na tela
# feita pra conferir o motor.


def _servico_de_medias():
    """MatchStatsServiceMedia do motor · a fonte da média que o pipeline usa."""
    _no_path()
    from services.match_stats_service_media import MatchStatsServiceMedia
    return MatchStatsServiceMedia()


@router.get("/dados/times/{team_id}/amostra")
def amostra_do_time(
    team_id: int,
    league_id: int | None = None,
    season: int | None = None,
    current_user: dict = Depends(require_admin),
):
    """Os jogos que entraram na média deste time, e a média que saiu deles.

    Sem `league_id`/`season`, o recorte com mais jogos na temporada mais
    recente · que é o que o motor usa pra decidir o jogo de hoje.

    O recorte é por LIGA e TEMPORADA porque é assim que o motor lê: o mesmo
    time tem uma média no Brasileirão e outra na Sul-Americana, e misturar as
    duas é comparar competições diferentes.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT name FROM teams WHERE team_id = %s ORDER BY season DESC LIMIT 1
        """, (team_id,))
        nome = (cur.fetchone() or {}).get("name")

        # Onde este time tem amostra. Sem isto a tela não teria como oferecer
        # a troca de competição, e o recorte errado parece "média estranha".
        cur.execute("""
            SELECT ms.league_id, ms.season, l.name AS liga, COUNT(*) AS jogos
              FROM match_statistics ms
         LEFT JOIN leagues l ON l.league_id = ms.league_id
             WHERE ms.status = 'FT'
               AND (ms.home_team_id = %s OR ms.away_team_id = %s)
             GROUP BY ms.league_id, ms.season, l.name
             ORDER BY ms.season DESC, COUNT(*) DESC
        """, (team_id, team_id))
        contextos = [dict(r) for r in cur.fetchall()]

        if league_id is None or season is None:
            if not contextos:
                return {"time": {"team_id": team_id, "nome": nome}, "contextos": [],
                        "jogos": [], "media_salva": {}, "media_do_motor": {},
                        "league_id": None, "season": None, "jogos_com_buraco": 0}
            league_id = contextos[0]["league_id"]
            season = contextos[0]["season"]

        # O que está GRAVADO. A distância entre isto e a média recalculada é a
        # medida de "média velha": `match_statistics` em dia com
        # `team_statistics` parada não tem sintoma nenhum na tela do site.
        cur.execute("""
            SELECT * FROM team_statistics
             WHERE team_id = %s AND league_id = %s AND season = %s
        """, (team_id, league_id, season))
        salvas = {r["context_type"]: dict(r) for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()

    try:
        servico = _servico_de_medias()
        # As duas chamadas públicas do serviço do motor, de propósito: a média
        # sai do MESMO método que o pipeline chama, não de uma conta feita
        # aqui. Tela feita pra conferir o motor não pode ter a sua própria
        # aritmética.
        jogos_crus = servico.get_team_games_stats_in_season(team_id, league_id, season)
        do_motor = {m["context_type"]: m
                    for m in servico.calculate_team_season_averages(team_id, league_id, season)}
    except Exception as e:
        logging.getLogger(__name__).warning("[ADMIN/AMOSTRA] %s", e)
        return {"time": {"team_id": team_id, "nome": nome}, "contextos": contextos,
                "league_id": league_id, "season": season, "jogos": [],
                "media_salva": salvas, "media_do_motor": {}, "jogos_com_buraco": 0,
                "erro": str(e)[:200]}

    jogos = []
    com_buraco = 0
    for g in sorted(jogos_crus, key=lambda x: (str(x.get("match_date")), x.get("fixture_id") or 0),
                    reverse=True):
        em_casa = g.get("home_team_id") == team_id
        pre_favor, pre_contra = ("home", "away") if em_casa else ("away", "home")

        stats, buracos = {}, []
        for chave, _rot, casa_col, fora_col, _modo in STATS_DA_PARTIDA:
            # As colunas de STATS_DA_PARTIDA são home_*/away_*; aqui o par vira
            # "a favor / contra", que é como o agregador lê e como se lê a
            # média depois.
            a_favor = g.get(casa_col if em_casa else fora_col)
            contra = g.get(fora_col if em_casa else casa_col)
            stats[chave] = [a_favor, contra]
            if a_favor is None or contra is None:
                buracos.append(chave)
        if buracos:
            com_buraco += 1

        jogos.append({
            "fixture_id": g.get("fixture_id"),
            "data": str(g.get("match_date")) if g.get("match_date") else None,
            "em_casa": em_casa,
            "adversario_id": g.get("away_team_id") if em_casa else g.get("home_team_id"),
            "gols_pro": g.get(f"{pre_favor}_goals"),
            "gols_contra": g.get(f"{pre_contra}_goals"),
            "status": g.get("status"),
            "stats": stats,
            # As famílias que entraram na soma valendo ZERO. É o número que
            # explica média baixa sem jogo ruim nenhum.
            "buracos": buracos,
        })

    # Nome do adversário sem N+1: uma consulta pra todos os ids da lista.
    ids = {j["adversario_id"] for j in jogos if j["adversario_id"]}
    nomes: dict = {}
    if ids:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT DISTINCT ON (team_id) team_id, name
                  FROM teams WHERE team_id = ANY(%s)
                 ORDER BY team_id, season DESC
            """, (list(ids),))
            nomes = {r["team_id"]: r["name"] for r in cur.fetchall()}
        except Exception:
            conn.rollback()
        finally:
            cur.close()
            conn.close()
    for j in jogos:
        j["adversario"] = nomes.get(j["adversario_id"])

    return {
        "time": {"team_id": team_id, "nome": nome},
        "contextos": contextos,
        "league_id": league_id,
        "season": season,
        "jogos": jogos,
        "jogos_com_buraco": com_buraco,
        "media_salva": salvas,
        "media_do_motor": do_motor,
        # O agregador soma NULL como zero e conta o jogo do mesmo jeito. A tela
        # precisa dizer isso em algum lugar, senão a coluna "buracos" parece
        # decoração.
        "nulo_entra_como_zero": True,
    }


@router.get("/dados/partidas/{fixture_id}/times")
def times_da_partida(fixture_id: int, current_user: dict = Depends(require_admin)):
    """Os dois times de uma partida, com liga e temporada · atalho pra amostra.

    A lista de decisões do motor guarda o NOME do time, não o id (o log é do
    motor, e lá o nome basta). Pra abrir a amostra a partir dela é preciso
    resolver o id, e o fixture é a única chave que as duas pontas têm.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ms.home_team_id, ms.away_team_id, ms.league_id, ms.season,
                   casa.name AS mandante, fora.name AS visitante
              FROM match_statistics ms
         LEFT JOIN LATERAL (SELECT name FROM teams WHERE team_id = ms.home_team_id
                             ORDER BY season DESC LIMIT 1) casa ON TRUE
         LEFT JOIN LATERAL (SELECT name FROM teams WHERE team_id = ms.away_team_id
                             ORDER BY season DESC LIMIT 1) fora ON TRUE
             WHERE ms.fixture_id = %s
        """, (fixture_id,))
        linha = cur.fetchone()
        if not linha:
            # Jogo de hoje ainda não tem linha em match_statistics · o registro
            # dele vive em `fixtures`, que é de onde o motor leu pra decidir.
            cur.execute("""
                SELECT home_team_id, away_team_id, league_id, season,
                       home_team AS mandante, away_team AS visitante
                  FROM fixtures WHERE fixture_id = %s
            """, (fixture_id,))
            linha = cur.fetchone()
        if not linha:
            raise HTTPException(404, "Partida não encontrada no banco.")
        return dict(linha)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/AMOSTRA] times %s: %s", fixture_id, e)
        raise HTTPException(500, f"Não deu pra ler a partida: {str(e)[:200]}")
    finally:
        cur.close()
        conn.close()



# ─── Árbitro · a mesma régua que os times ───────────────────────────────────
#
# A média do árbitro tinha dois defeitos que só apareciam de dentro do SQL:
#
#   1. `games` era COUNT(*) da temporada e as médias eram AVG, que ignora NULL.
#      Os dois números saíam de conjuntos diferentes · árbitro com 5 jogos
#      apitados e 2 folhas de cartão passava no gate de amostra mínima
#      (`cards_referee_min_games`, 3) com uma média tirada de 2 jogos.
#   2. Não havia filtro de status. Jogo adiado ou interrompido com linha
#      gravada entrava na média com o placar parcial · e o backfill de cartão
#      já filtrava por status, então as duas contas do mesmo número discordavam.
#
# Os dois foram corrigidos no coletor (é lá que a média nasce). O que mora aqui
# é o resto: enxergar a amostra e poder refazer a conta sem esperar o próximo
# jogo daquele árbitro.
#
# Refazer não custa cota: a média do árbitro sai inteira de `match_statistics`,
# que já está no banco. É a diferença entre este botão e a recoleta.


@router.get("/dados/arbitros")
def lista_de_arbitros(
    season: int | None = None,
    busca: str | None = None,
    pagina: int = 0,
    por_pagina: int = 15,
    current_user: dict = Depends(require_admin),
):
    """Os árbitros com média na temporada, do mais visto pro menos.

    `games` é a amostra que sustenta a média de cartões; `games_total` é quanto
    ele apitou. A distância entre os dois é quanta folha falta coletar daquele
    árbitro · e é ela que explica média estranha sem jogo estranho nenhum.

    PAGINADO desde 27/08. Vinha com `limite=60` e a tela desenhava os 60 de uma
    vez: numa temporada com 14 ligas isso é uma tabela que não acaba no celular,
    e o árbitro que interessa quase nunca é um dos primeiros. A busca por nome
    existe pelo mesmo motivo · paginar sem poder procurar só troca a rolagem
    por cliques.
    """
    pagina = max(0, pagina)
    por_pagina = min(max(1, por_pagina), 100)
    conn = get_connection()
    cur = conn.cursor()
    try:
        if season is None:
            cur.execute("SELECT MAX(season) AS s FROM referee_stats")
            season = (cur.fetchone() or {}).get("s")
        if season is None:
            return {"season": None, "arbitros": [], "temporadas": [], "total": 0}

        cur.execute("SELECT DISTINCT season FROM referee_stats ORDER BY season DESC")
        temporadas = [r["season"] for r in cur.fetchall()]

        filtro, params = "", [season]
        if busca and busca.strip():
            filtro = "AND r.name ILIKE %s"
            params.append(f"%{busca.strip()}%")

        cur.execute(f"""
            SELECT COUNT(*) AS n
              FROM referee_stats rs
              JOIN referees r ON r.referee_id = rs.referee_id
             WHERE rs.season = %s {filtro}
        """, tuple(params))
        total = (cur.fetchone() or {}).get("n") or 0

        cur.execute(f"""
            SELECT r.referee_id, r.name, rs.season,
                   rs.games, rs.games_total,
                   rs.avg_yellow, rs.avg_red, rs.avg_fouls,
                   rs.avg_corners, rs.avg_goals,
                   rs.max_yellow, rs.min_yellow,
                   rs.last_updated::text AS atualizado_em
              FROM referee_stats rs
              JOIN referees r ON r.referee_id = rs.referee_id
             WHERE rs.season = %s {filtro}
             ORDER BY rs.games DESC NULLS LAST, r.name
             LIMIT %s OFFSET %s
        """, tuple(params) + (por_pagina, pagina * por_pagina))
        arbitros = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/ARBITROS] lista: %s", e)
        return {"season": season, "arbitros": [], "temporadas": [], "total": 0,
                "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {"season": season, "temporadas": temporadas, "arbitros": arbitros,
            "total": total, "pagina": pagina, "por_pagina": por_pagina,
            # O gate de cartões do motor. A tela marca quem está abaixo dele ·
            # árbitro com amostra curta não bloqueia o mercado, cai no fallback
            # da média da liga, e isso é uma decisão diferente.
            "amostra_minima": 3}


# ─── Médias desatualizadas ──────────────────────────────────────────────────
#
# `team_statistics` é o que o motor lê. Ela é derivada de `match_statistics`, e
# derivada não se atualiza sozinha: coletar a partida e não refazer a média
# deixa o motor lendo a média de ontem sobre um histórico de hoje · o pior dos
# dois mundos, porque parece atualizado.
#
# As duas formas que existiam eram grossas demais nas duas pontas:
#
#   update_full_season_statistics()     APAGA a tabela inteira e reprocessa
#                                       todo time do banco;
#   update_recent_teams_statistics(3)   reprocessa todo time que TEVE JOGO nos
#                                       últimos três dias, tenha algo mudado
#                                       nele ou não.
#
# A segunda era a da varredura automática, e ela refaz a conta de dezenas de
# times para produzir exatamente o mesmo número que já estava lá · no caminho
# de uma visita ao site.
#
# `update_stale_teams_statistics` faz a pergunta exata: existe partida deste
# time gravada DEPOIS da última vez que a média dele foi escrita? É comparação
# de `last_updated` entre duas tabelas, custa zero requisição de API, e quando
# nada mudou a resposta é uma lista vazia.
#
# Este botão é essa mesma operação na mão · serve pra quando alguém acabou de
# preencher estatística à mão, ou rodou a recoleta em lote, e quer o motor
# lendo o número novo sem esperar a próxima visita disparar a varredura.

#: Estado do recálculo. Memória do processo, igual à recoleta: é acompanhamento
#: de execução, não histórico.
_medias: dict = {
    "rodando": False, "total": 0, "feitas": 0, "falhas": 0,
    "iniciada_em": None, "terminada_em": None, "erro": None,
}
_medias_lock = threading.Lock()


def _contar_medias_velhas() -> dict:
    """Quantos times têm a média mais velha que a última partida deles."""
    try:
        _no_path()
        from services.team_stats_reader import TeamStatsReader
        alvos = TeamStatsReader().get_teams_with_stale_statistics()
        return {"disponivel": True, "total": len(alvos)}
    except Exception as e:
        logging.getLogger(__name__).warning("[ADMIN/MEDIAS] contagem: %s", e)
        return {"disponivel": False, "total": 0, "erro": str(e)[:200]}


@router.get("/dados/medias-velhas")
def medias_velhas(current_user: dict = Depends(require_admin)):
    estado = dict(_medias)
    estado.update(_contar_medias_velhas())
    return estado


def _rodar_medias(limite: int) -> None:
    try:
        _no_path()
        from services.team_stats_aggregator_service import TeamStatsAggregatorService

        def progresso(feitos, total):
            with _medias_lock:
                _medias["feitas"] = feitos
                _medias["total"] = total

        resultado = TeamStatsAggregatorService().update_stale_teams_statistics(
            limite=limite, progresso=progresso)
        with _medias_lock:
            _medias["total"] = resultado.get("total", 0)
            _medias["feitas"] = resultado.get("feitos", 0)
            _medias["falhas"] = resultado.get("falhas", 0)
    except Exception as e:
        logging.getLogger(__name__).error("[ADMIN/MEDIAS] lote: %s", e, exc_info=True)
        with _medias_lock:
            _medias["erro"] = str(e)[:200]
    finally:
        with _medias_lock:
            _medias["rodando"] = False
            _medias["terminada_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.post("/dados/medias-velhas")
def recalcular_medias_velhas(limite: int = 0, current_user: dict = Depends(require_admin)):
    """Dispara o recálculo em segundo plano. `limite=0` = todos.

    Em thread pelo mesmo motivo da recoleta: são duas leituras da temporada e
    dois upserts POR TIME, e quem clicou não pode ficar segurando a requisição
    até o fim. Diferente da recoleta, aqui não há cota de API envolvida.
    """
    with _medias_lock:
        if _medias["rodando"]:
            raise HTTPException(409, "Já há um recálculo em andamento.")
        _medias.update({
            "rodando": True, "total": 0, "feitas": 0, "falhas": 0, "erro": None,
            "iniciada_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "terminada_em": None,
        })
    threading.Thread(target=_rodar_medias, args=(max(0, limite),), daemon=True).start()
    return {"ok": True, "mensagem": "Recálculo iniciado."}


# ─── Jogadores ──────────────────────────────────────────────────────────────
#
# A régua dos times e dos árbitros, aplicada ao jogador. `player_match_stats`
# existe desde 01/08 e alimenta o Player Stats (chutes, chutes no alvo, faltas,
# desarmes, passes e defesas de goleiro), mas nenhuma tela mostrava o que há
# dentro dela · a única forma de conferir a média de um jogador era abrir o
# banco.
#
# DUAS REGRAS SÃO COPIADAS DO MOTOR, E NÃO INVENTADAS AQUI
# -------------------------------------------------------
#   1. atuação abaixo de 60 minutos não entra (player_history.MIN_MINUTOS). Uma
#      entrada de 12 minutos e um jogo inteiro não são a mesma observação, e
#      misturar as duas subestima todo contador. É a regra principal daquele
#      módulo, então uma tela que a ignorasse mostraria uma média que o motor
#      nunca viu;
#   2. a contagem é POR COLUNA. Defesa aparece em 0.86% das atuações e passe em
#      todas · dizer "12 jogos" ao lado das seis médias esconderia que uma
#      delas saiu de dois.
#
# O MANDO É O RECORTE QUE O USUÁRIO PEDIU, e ele não é enfeite: `volume_do_
# adversario` do próprio motor já separa casa de fora com a justificativa de
# que "mandante e visitante produzem chute no alvo em taxas diferentes, e a
# média misturada não descreve nem um caso nem o outro". Vale igual pro
# jogador. `player_match_stats` não guarda mando, então ele sai do JOIN com
# `match_statistics`: casa é o time do jogador ser o home_team_id da partida.
#
# A COMPETIÇÃO É O SEGUNDO RECORTE, e pela mesma razão (2026-08-27). Um jogador
# atua em duas competições na mesma temporada · Brasileirão e Libertadores, por
# exemplo · e chute no Brasileirão e chute na Libertadores não são a mesma
# população. Somados numa linha só, o número não descreve nenhum dos dois.
#
# Aqui a tela faz as DUAS coisas que o pedido admite: dá um filtro de liga (a
# estatística separada) e, quando não há filtro, marca a linha que mistura (a
# diferenciação). O motor foi corrigido junto, em
# player_stats_engine/player_history.carregar: ele lia as 15 últimas atuações em
# qualquer competição e qualquer temporada, enquanto o volume do adversário do
# MESMO pick já era filtrado por liga e temporada.

#: Espelha player_history.MIN_MINUTOS. Importado de lá quando o motor está no
#: path (é o caso em produção, via _no_path); a constante local é o fallback
#: pra o site subir sozinho, sem o pipeline montado.
_MIN_MINUTOS_JOGADOR = 60


def _min_minutos_do_motor() -> int:
    try:
        _no_path()
        from services.player_stats_engine.player_history import MIN_MINUTOS
        return int(MIN_MINUTOS)
    except Exception:
        return _MIN_MINUTOS_JOGADOR


#: (chave, rótulo, coluna de player_match_stats). A ordem é a da tela.
#:
#: São as colunas que viram MERCADO -- as mesmas de
#: player_stats_engine.methods.METODOS, mais gols, que não é método (o motor
#: não publica prop de gol de jogador) mas é o número que se procura primeiro
#: ao olhar um atacante.
STATS_DO_JOGADOR = [
    ("chutes",     "Chutes",           "shots_total"),
    ("chutes_alvo", "Chutes no alvo",  "shots_on"),
    ("gols",       "Gols",             "goals_total"),
    ("defesas",    "Defesas",          "saves"),
    ("faltas",     "Faltas cometidas", "fouls_committed"),
    ("desarmes",   "Desarmes",         "tackles_total"),
    ("passes",     "Passes",           "passes_total"),
    ("amarelos",   "Amarelos",         "cards_yellow"),
]

#: Mando -> pedaço de SQL que o resolve. O jogador está em casa quando o time
#: dele é o mandante da partida.
_MANDO_SQL = {
    "casa": "AND ms.home_team_id = p.team_id",
    "fora": "AND ms.away_team_id = p.team_id",
    "todos": "",
}


@router.get("/dados/jogadores")
def lista_de_jogadores(
    season: int | None = None,
    mando: str = "todos",
    league_id: int | None = None,
    ordenar: str = "chutes",
    busca: str | None = None,
    pagina: int = 0,
    por_pagina: int = 15,
    current_user: dict = Depends(require_admin),
):
    """As médias por jogador que o Player Stats lê, por mando e competição."""
    pagina = max(0, pagina)
    por_pagina = min(max(1, por_pagina), 100)
    mando = mando if mando in _MANDO_SQL else "todos"
    colunas_validas = {chave: coluna for chave, _rot, coluna in STATS_DO_JOGADOR}
    ordenar = ordenar if ordenar in colunas_validas else "chutes"
    min_minutos = _min_minutos_do_motor()

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT season FROM player_match_stats ORDER BY season DESC")
        temporadas = [r["season"] for r in cur.fetchall() if r["season"] is not None]
        if season is None:
            season = temporadas[0] if temporadas else None
        if season is None:
            return {"season": None, "temporadas": [], "jogadores": [], "total": 0,
                    "mando": mando, "min_minutos": min_minutos, "ligas": [],
                    "colunas": [{"chave": c, "rotulo": r} for c, r, _x in STATS_DO_JOGADOR]}

        # As competições que existem nesta temporada, com quantas atuações
        # cada uma tem · é o que enche o seletor, e o número ao lado evita
        # escolher uma liga que tem três jogos.
        cur.execute("""
            SELECT p.league_id, l.name AS liga, COUNT(*) AS atuacoes
              FROM player_match_stats p
         LEFT JOIN leagues l ON l.league_id = p.league_id
             WHERE p.season = %s AND COALESCE(p.minutes, 0) >= %s
          GROUP BY p.league_id, l.name
          ORDER BY COUNT(*) DESC
        """, (season, min_minutos))
        ligas = [dict(r) for r in cur.fetchall()]

        filtro_busca, params_busca = "", []
        if busca and busca.strip():
            filtro_busca = "AND (p.player_name ILIKE %s OR p.team_name ILIKE %s)"
            alvo = f"%{busca.strip()}%"
            params_busca = [alvo, alvo]

        filtro_liga, params_liga = "", []
        if league_id is not None:
            filtro_liga = "AND p.league_id = %s"
            params_liga = [league_id]

        # O JOIN com match_statistics só é necessário pro mando · sem recorte
        # ele sairia caro à toa numa tabela que cresce por jogador por jogo.
        junta = ("JOIN match_statistics ms ON ms.fixture_id = p.fixture_id"
                 if mando != "todos" else "")
        onde_mando = _MANDO_SQL[mando]

        agregados = ",\n                   ".join(
            # Prefixo `p.` obrigatorio: com mando o JOIN traz `match_statistics`
            # junto, e coluna sem qualificar num SELECT de duas tabelas e' erro
            # esperando acontecer na proxima coluna que existir dos dois lados.
            f"ROUND(AVG(p.{coluna})::numeric, 2) AS {chave}_m, COUNT(p.{coluna}) AS {chave}_n"
            for chave, _rot, coluna in STATS_DO_JOGADOR
        )
        base = f"""
              FROM player_match_stats p
              {junta}
             WHERE p.season = %s
               AND COALESCE(p.minutes, 0) >= %s
               {onde_mando}
               {filtro_liga}
               {filtro_busca}
        """
        params = tuple([season, min_minutos] + params_liga + params_busca)

        cur.execute(f"""
            SELECT COUNT(*) AS n FROM (
                SELECT p.player_id {base} GROUP BY p.player_id
            ) t
        """, params)
        total = (cur.fetchone() or {}).get("n") or 0

        cur.execute(f"""
            SELECT p.player_id,
                   MAX(p.player_name) AS nome,
                   -- O time e a posição do jogo MAIS RECENTE, não o mais
                   -- frequente: jogador transferido no meio da temporada só
                   -- pode representar o time em que está agora. Mesma escolha
                   -- de player_history.jogadores_dos_times.
                   (ARRAY_AGG(p.team_name ORDER BY p.match_date DESC))[1] AS time,
                   (ARRAY_AGG(p.position  ORDER BY p.match_date DESC))[1] AS posicao,
                   COUNT(*) AS atuacoes,
                   -- Quantas competições esta linha está somando. Sem filtro
                   -- de liga, é o que separa "média de 12 jogos" de "média de
                   -- 12 jogos de duas competições diferentes" · a segunda não
                   -- descreve nenhuma das duas.
                   COUNT(DISTINCT p.league_id) AS competicoes,
                   ROUND(AVG(p.minutes)::numeric, 0) AS minutos,
                   MAX(p.match_date)::text AS ultima,
                   {agregados}
            {base}
          GROUP BY p.player_id
          ORDER BY AVG(p.{colunas_validas[ordenar]}) DESC NULLS LAST, COUNT(*) DESC
             LIMIT %s OFFSET %s
        """, params + (por_pagina, pagina * por_pagina))
        jogadores = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        conn.rollback()
        # `player_match_stats` nasce em `main.py setup`, do motor · banco de
        # site que nunca rodou o pipeline não tem a tabela, e isso não é
        # defeito do painel (mesma razão de _sem_tabela, com outro nome).
        if "player_match_stats" in str(e) and "exist" in str(e).lower():
            return {"season": season, "temporadas": [], "jogadores": [], "total": 0,
                    "mando": mando, "min_minutos": min_minutos, "ligas": [],
                    "colunas": [{"chave": c, "rotulo": r} for c, r, _x in STATS_DO_JOGADOR],
                    "erro": "Nenhuma estatística de jogador coletada neste banco ainda."}
        logging.getLogger(__name__).warning("[ADMIN/JOGADORES] lista: %s", e)
        return {"season": season, "temporadas": [], "jogadores": [], "total": 0,
                "mando": mando, "min_minutos": min_minutos, "ligas": [],
                "colunas": [{"chave": c, "rotulo": r} for c, r, _x in STATS_DO_JOGADOR],
                "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {
        "season": season,
        "temporadas": temporadas,
        "mando": mando,
        "league_id": league_id,
        "ligas": ligas,
        "ordenar": ordenar,
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "jogadores": jogadores,
        # A tela precisa dizer o corte, senão "12 atuações" vira um número sem
        # definição · e o corte é a razão de a média não bater com a soma bruta
        # que alguém faria olhando a folha.
        "min_minutos": min_minutos,
        "colunas": [{"chave": c, "rotulo": r} for c, r, _x in STATS_DO_JOGADOR],
    }


@router.get("/dados/jogadores/{player_id}/amostra")
def amostra_do_jogador(
    player_id: int,
    season: int | None = None,
    mando: str = "todos",
    league_id: int | None = None,
    current_user: dict = Depends(require_admin),
):
    """As atuações que entraram na média deste jogador, uma a uma.

    Mesma razão da amostra do time e da do árbitro: "média de 2,4 chutes" é
    indistinguível entre doze jogos parecidos e dois jogos de cinco chutes
    seguidos de dez sem nenhum. Só a lista separa os dois · e em prop de
    jogador a diferença entre os dois casos é o produto inteiro.
    """
    mando = mando if mando in _MANDO_SQL else "todos"
    min_minutos = _min_minutos_do_motor()
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT season FROM player_match_stats
             WHERE player_id = %s AND season IS NOT NULL
             ORDER BY season DESC
        """, (player_id,))
        temporadas = [r["season"] for r in cur.fetchall()]
        if season is None:
            season = temporadas[0] if temporadas else None
        if season is None:
            raise HTTPException(404, "Jogador sem atuação coletada.")

        colunas = ", ".join(f"p.{coluna} AS {chave}"
                            for chave, _rot, coluna in STATS_DO_JOGADOR)
        cur.execute(f"""
            SELECT p.fixture_id, p.match_date::text AS data, p.minutes, p.position,
                   -- `AS time` seria alias com nome de tipo do SQL · o
                   -- resultado sai com outro nome e a resposta o renomeia.
                   p.player_name AS nome, p.team_name AS time_nome, p.rating,
                   p.is_substitute,
                   (ms.home_team_id = p.team_id) AS em_casa,
                   casa.name AS mandante, fora.name AS visitante,
                   ms.home_goals, ms.away_goals,
                   -- A competição de CADA atuação. É o que responde "essa
                   -- média está somando Brasileirão com Libertadores?" sem
                   -- reproduzir a consulta.
                   p.league_id, lg.name AS liga,
                   {colunas}
              FROM player_match_stats p
              LEFT JOIN leagues lg ON lg.league_id = p.league_id
              LEFT JOIN match_statistics ms ON ms.fixture_id = p.fixture_id
              LEFT JOIN LATERAL (
                        SELECT name FROM teams
                         WHERE team_id = ms.home_team_id
                         ORDER BY season DESC LIMIT 1
                    ) casa ON TRUE
              LEFT JOIN LATERAL (
                        SELECT name FROM teams
                         WHERE team_id = ms.away_team_id
                         ORDER BY season DESC LIMIT 1
                    ) fora ON TRUE
             WHERE p.player_id = %s AND p.season = %s
               {_MANDO_SQL[mando]}
               {"AND p.league_id = %s" if league_id is not None else ""}
          ORDER BY p.match_date DESC
             LIMIT 40
        """, (player_id, season) + ((league_id,) if league_id is not None else ()))
        atuacoes = [dict(r) for r in cur.fetchall()]
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/JOGADORES] amostra: %s", e)
        raise HTTPException(500, f"Não deu pra ler a amostra: {str(e)[:200]}")
    finally:
        cur.close()
        conn.close()

    # A média sai das atuações QUE O MOTOR LERIA (>= min_minutos), e a lista
    # mostra todas · é essa diferença que explica por que a média não bate com
    # a conta feita a olho sobre a tabela inteira.
    lidas = [a for a in atuacoes if (a.get("minutes") or 0) >= min_minutos]
    medias = {}
    for chave, _rot, _col in STATS_DO_JOGADOR:
        valores = [a[chave] for a in lidas if a.get(chave) is not None]
        medias[chave] = {
            "media": round(sum(valores) / len(valores), 2) if valores else None,
            "n": len(valores),
        }

    return {
        "jogador": {
            "player_id": player_id,
            "nome": atuacoes[0]["nome"] if atuacoes else None,
            "time": atuacoes[0]["time_nome"] if atuacoes else None,
            "posicao": atuacoes[0]["position"] if atuacoes else None,
        },
        "season": season,
        "temporadas": temporadas,
        "mando": mando,
        "league_id": league_id,
        "min_minutos": min_minutos,
        "atuacoes": atuacoes,
        "lidas": len(lidas),
        # Quantas competições estas atuações somam · a tela avisa quando é mais
        # de uma, do mesmo jeito que a amostra do time avisa multi_competicao.
        "competicoes": sorted({a["league_id"] for a in lidas if a.get("league_id")}),
        "medias": medias,
        "colunas": [{"chave": c, "rotulo": r} for c, r, _x in STATS_DO_JOGADOR],
    }


@router.get("/dados/arbitros/{referee_id}/amostra")
def amostra_do_arbitro(
    referee_id: int,
    season: int | None = None,
    current_user: dict = Depends(require_admin),
):
    """Os jogos que entraram na média deste árbitro, um a um.

    Mesma ideia da amostra do time, e pela mesma razão: "média de 4,8 amarelos"
    é indistinguível entre 18 jogos coletados inteiros, 3 jogos, e 18 jogos com
    7 folhas faltando. Só a lista separa os três.

    A diferença pro time é o vínculo: árbitro se liga à partida pelo NOME
    (`match_statistics.referee`), não por id · é o que a API-Football entrega, e
    é por isso que `referees` existe só pra dar id a um nome.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM referees WHERE referee_id = %s", (referee_id,))
        linha = cur.fetchone()
        if not linha:
            raise HTTPException(404, "Árbitro não cadastrado.")
        nome = linha["name"]

        cur.execute("""
            SELECT DISTINCT season FROM match_statistics
             WHERE referee = %s AND status IN ('FT','AET','PEN')
             ORDER BY season DESC
        """, (nome,))
        temporadas = [r["season"] for r in cur.fetchall()]
        if season is None:
            season = temporadas[0] if temporadas else None
        if season is None:
            return {"arbitro": {"referee_id": referee_id, "nome": nome},
                    "temporadas": [], "season": None, "jogos": [],
                    "media_salva": None, "jogos_com_buraco": 0}

        cur.execute("""
            SELECT rs.*, rs.last_updated::text AS atualizado_em
              FROM referee_stats rs
             WHERE rs.referee_id = %s AND rs.season = %s
        """, (referee_id, season))
        salva = cur.fetchone()
        salva = dict(salva) if salva else None

        # Os mesmos jogos que a média agrega · mesmo filtro, mesma tabela.
        cur.execute("""
            SELECT ms.fixture_id,
                   ms.match_date::text AS data,
                   ms.status,
                   l.name              AS liga,
                   casa.name           AS mandante,
                   fora.name           AS visitante,
                   ms.home_goals, ms.away_goals, ms.total_goals,
                   ms.total_yellow_cards, ms.total_red_cards,
                   ms.total_corners,
                   ms.home_fouls, ms.away_fouls
              FROM match_statistics ms
         LEFT JOIN leagues l ON l.league_id = ms.league_id
         LEFT JOIN LATERAL (SELECT name FROM teams WHERE team_id = ms.home_team_id
                             ORDER BY season DESC LIMIT 1) casa ON TRUE
         LEFT JOIN LATERAL (SELECT name FROM teams WHERE team_id = ms.away_team_id
                             ORDER BY season DESC LIMIT 1) fora ON TRUE
             WHERE ms.referee = %s AND ms.season = %s
               AND ms.status IN ('FT','AET','PEN')
             ORDER BY ms.match_date DESC, ms.fixture_id DESC
        """, (nome, season))
        jogos = []
        com_buraco = 0
        for r in cur.fetchall():
            j = dict(r)
            faltas = (None if j["home_fouls"] is None or j["away_fouls"] is None
                      else j["home_fouls"] + j["away_fouls"])
            j["total_fouls"] = faltas
            # Um jogo pode faltar em UMA média e entrar em outra: AVG ignora a
            # linha por coluna, não por jogo. Marcar qual faltou é o que impede
            # de ler "18 jogos" como 18 jogos em todas as colunas.
            j["buracos"] = [nome_col for nome_col, valor in (
                ("amarelos", j["total_yellow_cards"]),
                ("vermelhos", j["total_red_cards"]),
                ("escanteios", j["total_corners"]),
                ("faltas", faltas),
                ("gols", j["total_goals"]),
            ) if valor is None]
            if j["buracos"]:
                com_buraco += 1
            jogos.append(j)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/ARBITROS] amostra %s: %s", referee_id, e)
        raise HTTPException(500, f"Não deu pra ler a amostra: {str(e)[:200]}")
    finally:
        cur.close()
        conn.close()

    return {
        "arbitro": {"referee_id": referee_id, "nome": nome},
        "season": season,
        "temporadas": temporadas,
        "jogos": jogos,
        "jogos_com_buraco": com_buraco,
        "media_salva": salva,
    }


@router.post("/dados/arbitros/recalcular")
async def recalcular_arbitros(
    season: int | None = None,
    current_user: dict = Depends(require_admin),
):
    """Refaz a média de TODO árbitro que apitou na temporada.

    O coletor só recalcula quem apareceu no lote coletado · árbitro cujo último
    jogo já estava no banco nunca era revisitado, e foi por isso que a correção
    de `games`/status não chegaria sozinha ao histórico.

    Não gasta cota: sai inteiro de `match_statistics`. E chama
    `_sync_referee_stats` do próprio coletor em vez de repetir o SQL aqui · a
    regra da média do árbitro tem que ter um dono só, senão o painel e o
    pipeline calculam números diferentes com o mesmo nome.
    """
    def _rodar():
        _no_path()
        from collectors.match_statistics_sync_service import MatchStatisticsSyncService

        servico = MatchStatisticsSyncService()
        servico._open()
        try:
            filtro = "AND season = %s" if season is not None else ""
            params = (season,) if season is not None else ()
            servico.cur.execute(f"""
                SELECT DISTINCT referee, season
                  FROM match_statistics
                 WHERE referee IS NOT NULL AND referee <> ''
                   AND status IN ('FT','AET','PEN')
                   {filtro}
            """, params)
            pares = {(r[0], r[1]) for r in servico.cur.fetchall()}
            servico._sync_referee_stats(pares)
            return len(pares)
        finally:
            servico._close()

    try:
        quantos = await run_in_threadpool(_rodar)
    except Exception as e:
        logging.getLogger(__name__).warning("[ADMIN/ARBITROS] recalcular: %s", e)
        raise HTTPException(500, f"Não deu pra recalcular: {str(e)[:200]}")

    return {"ok": True, "arbitros": quantos,
            "mensagem": f"{quantos} árbitro(s) recalculado(s) · sem custo de API."}


# ─── Motor · o que ele olhou antes de escolher ──────────────────────────────
#
# O pick publicado é a ponta. A pergunta que não tinha tela é a de baixo dela:
# QUE jogos o motor considerou, que mercados ele pontuou em cada um, e por que
# os outros não venceram.
#
# O dado já existe desde 07/08 e nunca foi lido pelo site:
# `engine_decisions`, gravada por engine_pipelines/decision_log.py. Uma linha
# por fixture processado, em três formas:
#
#   avaliado    o motor rodou · `candidates` traz TODOS os mercados pontuados,
#               não só o escolhido, com odd, taxa real, amostra, EV e score
#   descartado  o jogo caiu ANTES do motor · `reason` diz qual das quatro
#               portas fechou (sem odds, sem histórico, histórico reprovado)
#   sem_pick    o pipeline terminou o dia sem candidato nenhum, sem fixture
#
# Até aqui isso só era legível abrindo o banco. Em produção o arquivo
# .jsonl nem existe: o Railway não tem volume, então LOGS_DIR some a cada
# deploy · o Postgres é a única cópia que sobrevive.
#
# Nada aqui escreve. É leitura de log, e log de decisão que a tela pode
# alterar deixa de ser log.

#: Os pipelines que gravam em `engine_decisions`, na ordem em que o painel
#: pergunta por eles. O nome é o mesmo que o motor escreve na coluna.
_PIPELINES_DO_MOTOR = [
    ("VIP_ENGINE",         "VIP"),
    ("DICA_ENGINE",        "Free"),
    ("MULTIPLA_ENGINE",    "Múltipla"),
    ("ALAVANCAGEM_ENGINE", "Alavancagem"),
    ("FALTAS_ENGINE",      "Faltas"),
    ("GOLEIROS_ENGINE",    "Goleiros"),
    ("LIVE_ENGINE",        "Ao vivo"),
]

#: Onde o pick daquele pipeline foi parar, pra a tela poder dizer "este virou
#: pick". Só as tabelas que guardam UM fixture por linha: alavancagem tem três
#: colunas de fixture e múltipla guarda as pernas em JSON · marcar a partida
#: nessas duas exigiria abrir o bilhete, e o que a tela precisa aqui é do
#: candidato, não do bilhete.
_TABELA_DO_PIPELINE = {
    "VIP_ENGINE":      "picks_vip",
    "DICA_ENGINE":     "picks_free",
    "FALTAS_ENGINE":   "picks_faltas",
    "GOLEIROS_ENGINE": "picks_goleiros",
}

_DECISOES_POR_PAGINA_MAX = 25


def _sem_tabela(e: Exception) -> bool:
    """`engine_decisions` é criada pelo MOTOR, não pelas migrações do site.

    Ambiente que nunca rodou pipeline não tem a tabela, e isso não é defeito
    do painel: a aba responde "ainda não há decisão registrada" em vez de
    devolver 500 e parecer que o site quebrou.
    """
    return "engine_decisions" in str(e) and "exist" in str(e).lower()


@router.get("/motor/decisoes")
def motor_decisoes(data: str | None = None, current_user: dict = Depends(require_admin)):
    """Retrato de um dia: quanto cada pipeline avaliou, e onde os jogos morreram.

    Sem `data`, o dia de Brasília · a mesma data que os pipelines gravam
    (`HOJE_BR`), não `CURRENT_DATE`, que já virou o dia entre 21h e meia-noite.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # As datas que existem, pra a tela oferecer só dia com log. Um dia sem
        # linha nenhuma não é um dia vazio: é um dia em que o pipeline não rodou.
        cur.execute("""
            SELECT match_date::text AS dia, COUNT(*) AS n
              FROM engine_decisions
             GROUP BY match_date
             ORDER BY match_date DESC
             LIMIT 30
        """)
        dias = [dict(r) for r in cur.fetchall()]

        dia = data or (dias[0]["dia"] if dias else None)
        if dia is None:
            return {"disponivel": True, "data": None, "dias": [], "pipelines": [], "motivos": []}

        cur.execute("""
            SELECT pipeline,
                   COUNT(*) FILTER (WHERE status = 'avaliado')    AS avaliados,
                   COUNT(*) FILTER (WHERE status = 'descartado')  AS descartados,
                   COUNT(*) FILTER (WHERE status = 'sem_pick')    AS sem_pick,
                   -- Avaliado com pelo menos um candidato APROVADO. É a
                   -- distância entre "o motor olhou" e "o motor teve o que
                   -- escolher", e as duas juntas explicam o dia vazio.
                   COUNT(*) FILTER (
                       WHERE status = 'avaliado'
                         AND EXISTS (SELECT 1 FROM jsonb_array_elements(candidates) c
                                      WHERE (c->>'eligible')::boolean)
                   ) AS com_aprovado
              FROM engine_decisions
             WHERE match_date = %s
             GROUP BY pipeline
        """, (dia,))
        por_pipeline = {r["pipeline"]: dict(r) for r in cur.fetchall()}

        # Onde os jogos morreram, agrupado. Motivo é texto curto e estável
        # justamente pra isto (ver as constantes MOTIVO_* do decision_log):
        # frase escrita à mão em cada pipeline não agruparia.
        cur.execute("""
            SELECT pipeline, reason, COUNT(*) AS n
              FROM engine_decisions
             WHERE match_date = %s AND status <> 'avaliado' AND reason IS NOT NULL
             GROUP BY pipeline, reason
             ORDER BY n DESC
        """, (dia,))
        motivos = [dict(r) for r in cur.fetchall()]

        pipelines = []
        for chave, rotulo in _PIPELINES_DO_MOTOR:
            linha = por_pipeline.pop(chave, {})
            pipelines.append({
                "pipeline": chave, "rotulo": rotulo,
                "avaliados": linha.get("avaliados") or 0,
                "descartados": linha.get("descartados") or 0,
                "sem_pick": linha.get("sem_pick") or 0,
                "com_aprovado": linha.get("com_aprovado") or 0,
                "picks": _picks_do_dia(conn, cur, chave, dia),
            })
        # Pipeline que o motor gravou e esta lista não conhece ainda: aparece
        # mesmo assim. Sumir com a linha seria esconder justamente a novidade.
        for chave, linha in por_pipeline.items():
            pipelines.append({
                "pipeline": chave, "rotulo": chave,
                "avaliados": linha.get("avaliados") or 0,
                "descartados": linha.get("descartados") or 0,
                "sem_pick": linha.get("sem_pick") or 0,
                "com_aprovado": linha.get("com_aprovado") or 0,
                "picks": None,
            })
    except Exception as e:
        conn.rollback()
        if _sem_tabela(e):
            return {"disponivel": False, "data": data, "dias": [], "pipelines": [],
                    "motivos": [], "erro": "Nenhum pipeline gravou decisão neste banco ainda."}
        logging.getLogger(__name__).warning("[ADMIN/MOTOR] decisoes: %s", e)
        return {"disponivel": False, "data": data, "dias": [], "pipelines": [],
                "motivos": [], "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {"disponivel": True, "data": dia, "dias": dias,
            "pipelines": pipelines, "motivos": motivos}


def _picks_do_dia(conn, cur, pipeline: str, dia: str) -> int | None:
    """Quantos picks daquele pipeline foram publicados naquele dia.

    É o fecho da conta: avaliados, com candidato aprovado, e quantos viraram
    pick de verdade. Sem esta terceira coluna, "12 avaliados e 4 com aprovado"
    ainda não diz se saiu alguma coisa.
    """
    tabela = _TABELA_DO_PIPELINE.get(pipeline)
    if pipeline == "ALAVANCAGEM_ENGINE":
        tabela = "picks_alavancagem"
    if not tabela:
        return None
    try:
        cur.execute(f"SELECT COUNT(*) AS n FROM {tabela} WHERE match_date = %s", (dia,))
        return (cur.fetchone() or {}).get("n") or 0
    except Exception:
        # Tabela ausente neste ambiente não pode derrubar o resumo inteiro. O
        # rollback é obrigatório: no Postgres, erro deixa a transação abortada
        # e a PRÓXIMA consulta falharia junto, arrastando o resumo inteiro
        # por causa de uma tabela que nem existe aqui.
        conn.rollback()
        return None


@router.get("/motor/decisoes/linhas")
def motor_decisoes_linhas(
    pipeline: str,
    data: str | None = None,
    status: str | None = None,
    pagina: int = 0,
    por_pagina: int = 10,
    current_user: dict = Depends(require_admin),
):
    """Partida a partida: o que o motor viu naquele jogo, e o que pontuou.

    `candidates` vem inteiro, porque é ele que responde a pergunta. O peso da
    resposta é a razão de isto ser paginado curto: são até 16 mercados por
    partida, cada um com odd, taxa real, amostra, EV, edge e os scores
    parciais · trazer o dia inteiro de uma vez seria alguns MB de JSON pra ler
    uma partida.
    """
    pagina = max(0, pagina)
    por_pagina = min(max(1, por_pagina), _DECISOES_POR_PAGINA_MAX)

    filtros = ["pipeline = %s"]
    params: list = [pipeline]
    if data:
        filtros.append("match_date = %s")
        params.append(data)
    if status:
        filtros.append("status = %s")
        params.append(status)
    onde = " AND ".join(filtros)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) AS n FROM engine_decisions WHERE {onde}", tuple(params))
        total = (cur.fetchone() or {}).get("n") or 0

        cur.execute(f"""
            SELECT id, match_date::text AS dia, pipeline, fixture_id,
                   home_team, away_team, status, reason,
                   candidates, matchup, context,
                   created_at::text AS gravada_em
              FROM engine_decisions
             WHERE {onde}
             -- Avaliado primeiro: é a linha que tem conteúdo. Descarte é
             -- contexto, e ler 30 descartes antes do primeiro jogo avaliado
             -- é o mesmo que não ter a tela.
             ORDER BY (status = 'avaliado') DESC, id DESC
             LIMIT %s OFFSET %s
        """, tuple(params) + (por_pagina, pagina * por_pagina))
        linhas = [dict(r) for r in cur.fetchall()]

        # Quais dessas partidas viraram pick de verdade. O candidato aprovado
        # não é o pick: ele ainda passa pelo gate de IA, pela exclusividade de
        # partida e pelo teto do dia.
        virou_pick: list = []
        tabela = _TABELA_DO_PIPELINE.get(pipeline)
        ids = [l["fixture_id"] for l in linhas if l.get("fixture_id")]
        if tabela and ids:
            try:
                cur.execute(
                    f"SELECT DISTINCT fixture_id FROM {tabela} WHERE fixture_id = ANY(%s)",
                    (ids,))
                virou_pick = [r["fixture_id"] for r in cur.fetchall()]
            except Exception:
                conn.rollback()
    except Exception as e:
        conn.rollback()
        if _sem_tabela(e):
            return {"total": 0, "linhas": [], "virou_pick": [],
                    "erro": "Nenhum pipeline gravou decisão neste banco ainda."}
        logging.getLogger(__name__).warning("[ADMIN/MOTOR] linhas: %s", e)
        return {"total": 0, "linhas": [], "virou_pick": [], "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {"total": total, "pagina": pagina, "por_pagina": por_pagina,
            "linhas": linhas, "virou_pick": virou_pick}


# ─── Auditoria dos Motores ──────────────────────────────────────────────────
#
# A aba Motor respondia "o que o motor olhou HOJE". Faltava a camada de cima:
# QUAIS EXECUÇÕES aconteceram, de qual motor, em que versão, com que status, e
# o que cada uma decidiu.
#
# A diferença entre as duas é a pergunta que cada uma responde. "Por que não
# saiu pick de faltas hoje?" tem três respostas possíveis e só a execução as
# separa: o motor não rodou · rodou e falhou · rodou, olhou 14 jogos e nenhum
# passou. Sem `engine_runs`, as três eram indistinguíveis de fora, porque as
# três produzem a mesma coisa: nenhuma linha em picks_faltas.
#
# A fonte é o Engine Audit (ApostaEsportivas/src/services/engine_audit), que
# grava DURANTE a execução do motor. Nada aqui recalcula nada: se um número
# desta tela discordasse do motor, a tela estaria errada por construção.
#
# Nada aqui escreve. Auditoria que a tela altera deixa de ser auditoria.

_EXECUCOES_POR_PAGINA_MAX = 50

#: Ordem em que os motores aparecem. Sai do registro do motor quando ele está
#: no caminho (ver settlement_bridge.engine_registry) · a lista literal é só o
#: fallback de ambiente sem o pipeline montado.
_ORDEM_MOTORES = ("PRE_LIVE", "LIVE", "PICK_BOOST", "PLAYER_STATS")


def _catalogo_de_motores() -> list:
    """[{slug, label, prefixo, metodos:[{slug,label,versao}]}] pro painel.

    Vem do registro do MOTOR, não de uma cópia aqui. Foi manter uma cópia à
    mão (`_PIPELINES_DO_MOTOR`, logo acima) que fez esta tela precisar de um
    ramo "pipeline que a lista não conhece".
    """
    if engine_registry is None:
        return [{"slug": s, "label": s, "prefixo": s[:2], "metodos": []}
                for s in _ORDEM_MOTORES]
    return [
        {"slug": m.slug, "label": m.label, "prefixo": m.prefixo,
         "metodos": [{"slug": met.slug, "label": met.label, "versao": met.versao,
                      "tabela_picks": met.tabela_picks}
                     for met in m.metodos]}
        for m in engine_registry.MOTORES
    ]


def _rotulo_do_metodo(motor: str | None, metodo: str | None) -> str:
    if engine_registry is None or not motor or not metodo:
        return metodo or motor or "?"
    met = engine_registry.metodo(motor, metodo)
    return met.label if met else (metodo or "?")


def _sem_auditoria(e: Exception) -> bool:
    """`engine_runs` ausente não é defeito do painel · ver `_sem_tabela`."""
    texto = str(e).lower()
    return ("engine_runs" in texto or "engine_errors" in texto) and "exist" in texto


@router.get("/motor/execucoes")
def motor_execucoes(
    motor: str | None = None,
    metodo: str | None = None,
    status: str | None = None,
    data: str | None = None,
    pagina: int = 0,
    por_pagina: int = 20,
    current_user: dict = Depends(require_admin),
):
    """Execuções recentes dos motores · a lista de cima da aba.

    Ordenada por início decrescente, não por data do jogo: a pergunta desta
    tela é sempre "o que rodou por último", e o motor ao vivo roda várias vezes
    pelo mesmo `match_date`.
    """
    pagina = max(0, pagina)
    por_pagina = min(max(1, por_pagina), _EXECUCOES_POR_PAGINA_MAX)

    filtros, params = [], []
    if motor:
        filtros.append("engine = %s")
        params.append(motor)
    if metodo:
        filtros.append("method = %s")
        params.append(metodo)
    if status:
        filtros.append("status = %s")
        params.append(status)
    if data:
        filtros.append("match_date = %s")
        params.append(data)
    onde = ("WHERE " + " AND ".join(filtros)) if filtros else ""

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) AS n FROM engine_runs {onde}", tuple(params))
        total = (cur.fetchone() or {}).get("n") or 0

        cur.execute(f"""
            SELECT r.run_id, r.engine, r.method, r.engine_version,
                   r.match_date::text AS dia,
                   r.started_at::text  AS iniciada_em,
                   r.finished_at::text AS terminada_em,
                   -- Duração em segundos. Execução aberta (RUNNING) mede
                   -- contra AGORA: é assim que se vê uma que travou, em vez
                   -- de ela aparecer sem duração e parecer instantânea.
                   EXTRACT(EPOCH FROM (COALESCE(r.finished_at, NOW()) - r.started_at))::int AS duracao_s,
                   r.status, r.analisados, r.selecionados, r.descartados, r.erros,
                   r.resumo
              FROM engine_runs r
              {onde}
             ORDER BY r.started_at DESC
             LIMIT %s OFFSET %s
        """, tuple(params) + (por_pagina, pagina * por_pagina))
        execucoes = [dict(r) for r in cur.fetchall()]
        for e in execucoes:
            e["metodo_label"] = _rotulo_do_metodo(e.get("engine"), e.get("method"))

        # Retrato do dia por motor+método, pra a tela ter o topo antes da
        # lista. Últimas 24h e não `match_date`: execução é evento de relógio.
        cur.execute("""
            SELECT engine, method,
                   COUNT(*)                                   AS execucoes,
                   COUNT(*) FILTER (WHERE status = 'FAILED')   AS falhas,
                   COUNT(*) FILTER (WHERE status = 'PARTIAL')  AS parciais,
                   COUNT(*) FILTER (WHERE status = 'RUNNING')  AS rodando,
                   SUM(analisados)                             AS analisados,
                   SUM(selecionados)                           AS selecionados,
                   SUM(erros)                                  AS erros,
                   MAX(started_at)::text                       AS ultima
              FROM engine_runs
             WHERE started_at >= NOW() - INTERVAL '24 hours'
             GROUP BY engine, method
        """)
        resumo_24h = [dict(r) for r in cur.fetchall()]
        for r in resumo_24h:
            r["metodo_label"] = _rotulo_do_metodo(r.get("engine"), r.get("method"))
    except Exception as e:
        conn.rollback()
        if _sem_auditoria(e) or _sem_tabela(e):
            return {"disponivel": False, "total": 0, "execucoes": [],
                    "resumo_24h": [], "motores": _catalogo_de_motores(),
                    "erro": "Nenhum motor registrou execução neste banco ainda."}
        logging.getLogger(__name__).warning("[ADMIN/MOTOR] execucoes: %s", e)
        return {"disponivel": False, "total": 0, "execucoes": [], "resumo_24h": [],
                "motores": _catalogo_de_motores(), "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {"disponivel": True, "total": total, "pagina": pagina,
            "por_pagina": por_pagina, "execucoes": execucoes,
            "resumo_24h": resumo_24h, "motores": _catalogo_de_motores()}


@router.get("/motor/execucoes/{run_id}")
def motor_execucao(
    run_id: str,
    filtro: str = "todos",
    pagina: int = 0,
    por_pagina: int = 20,
    current_user: dict = Depends(require_admin),
):
    """Uma execução por dentro: os jogos analisados e os erros.

    `filtro` é `todos` | `selecionados` | `descartados` | `erros`. Selecionado
    primeiro na ordenação padrão porque é a linha com conteúdo · ler trinta
    descartes antes do primeiro jogo escolhido é o mesmo que não ter a tela
    (mesma decisão de `motor_decisoes_linhas`).
    """
    pagina = max(0, pagina)
    por_pagina = min(max(1, por_pagina), _DECISOES_POR_PAGINA_MAX)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT run_id, engine, method, engine_version,
                   match_date::text AS dia,
                   started_at::text AS iniciada_em, finished_at::text AS terminada_em,
                   status, analisados, selecionados, descartados, erros, resumo
              FROM engine_runs WHERE run_id = %s
        """, (run_id,))
        execucao = cur.fetchone()
        if not execucao:
            raise HTTPException(404, "Execução não encontrada")
        execucao = dict(execucao)
        execucao["metodo_label"] = _rotulo_do_metodo(execucao.get("engine"),
                                                     execucao.get("method"))

        erros = []
        if filtro in ("todos", "erros"):
            cur.execute("""
                SELECT id, fixture_id, contexto, erro, traceback,
                       created_at::text AS quando
                  FROM engine_errors WHERE run_id = %s
                 ORDER BY created_at
                 LIMIT 50
            """, (run_id,))
            erros = [dict(r) for r in cur.fetchall()]

        jogos, total = [], 0
        if filtro != "erros":
            filtros, params = ["run_id = %s"], [run_id]
            if filtro == "selecionados":
                filtros.append("status = 'selecionado'")
            elif filtro == "descartados":
                filtros.append("status <> 'selecionado'")
            onde = " AND ".join(filtros)

            cur.execute(f"SELECT COUNT(*) AS n FROM engine_decisions WHERE {onde}",
                        tuple(params))
            total = (cur.fetchone() or {}).get("n") or 0

            cur.execute(f"""
                SELECT id, fixture_id, home_team, away_team, status, reason,
                       score, probability, odd, pick_table, pick_id,
                       candidates, context, created_at::text AS gravada_em
                  FROM engine_decisions
                 WHERE {onde}
                 ORDER BY (status = 'selecionado') DESC,
                          score DESC NULLS LAST, id
                 LIMIT %s OFFSET %s
            """, tuple(params) + (por_pagina, pagina * por_pagina))
            jogos = [dict(r) for r in cur.fetchall()]
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        if _sem_auditoria(e) or _sem_tabela(e):
            return {"disponivel": False, "erro": "Auditoria ainda não existe neste banco."}
        logging.getLogger(__name__).warning("[ADMIN/MOTOR] execucao %s: %s", run_id, e)
        return {"disponivel": False, "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    return {"disponivel": True, "execucao": execucao, "jogos": jogos,
            "total": total, "pagina": pagina, "por_pagina": por_pagina,
            "erros": erros, "filtro": filtro}


#: Tabelas de pick que a tela "Por que essa pick?" sabe abrir, e a coluna que
#: identifica o autor da linha. Lista fechada de propósito: `tabela` vem da
#: query string e entra em SQL por f-string · aceitar qualquer nome seria
#: injeção. Mesma trava que `_PICK_FONTE` usa em suggestions.py.
_TABELAS_EXPLICAVEIS = {
    "picks_vip":          "VIP",
    "picks_free":         "Free",
    "picks_faltas":       "Faltas",
    "picks_goleiros":     "Defesas (histórico)",
    "picks_player_stats": "Player Stats",
    "picks_boost":        "Pick Boost",
    "picks_live":         "Ao vivo",
}


@router.get("/motor/pick/porque")
def motor_pick_porque(
    tabela: str,
    pick_id: int,
    current_user: dict = Depends(require_admin),
):
    """"Por que essa pick?" · os indicadores que sustentaram a decisão.

    Monta a resposta de duas fontes, e nenhuma delas é um recálculo:

      · `engine_debug` do próprio pick · o retrato do candidato no instante da
        escolha, incluindo a AMOSTRA (quais jogos o motor leu);
      · a linha de `engine_decisions` daquela partida · o run_id, a versão do
        motor, o score, e o resumo estruturado que o motor gravou.

    A segunda é o que amarra o pick à execução: com ela, "qual versão do motor
    gerou este pick" e "quais outros jogos ele olhou naquele momento" deixam de
    exigir arqueologia de log.
    """
    if tabela not in _TABELAS_EXPLICAVEIS:
        raise HTTPException(400, "Tabela de pick desconhecida")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT id, fixture_id, match_date::text AS dia,
                   home_team, away_team, market, line, odd,
                   reasoning, engine_debug, result,
                   created_at::text AS criada_em
              FROM {tabela} WHERE id = %s
        """, (pick_id,))
        pick = cur.fetchone()
        if not pick:
            raise HTTPException(404, "Pick não encontrado")
        pick = dict(pick)

        # A decisão que gerou ESTE pick. Primeiro pelo vínculo direto
        # (pick_table + pick_id, gravado pelos motores novos); depois pela
        # partida, que é o que existe para os picks anteriores à auditoria.
        cur.execute("""
            SELECT run_id, engine, method, engine_version, status, reason,
                   score, probability, odd, context, candidates,
                   created_at::text AS gravada_em
              FROM engine_decisions
             WHERE (pick_table = %s AND pick_id = %s)
                OR (fixture_id = %s AND match_date = %s::date
                    AND status IN ('selecionado', 'avaliado'))
             ORDER BY (pick_table = %s AND pick_id = %s) DESC, id DESC
             LIMIT 1
        """, (tabela, pick_id, pick.get("fixture_id"), pick.get("dia"),
              tabela, pick_id))
        decisao = cur.fetchone()
        decisao = dict(decisao) if decisao else None

        execucao = None
        if decisao and decisao.get("run_id"):
            cur.execute("""
                SELECT run_id, engine, method, engine_version,
                       started_at::text AS iniciada_em, status,
                       analisados, selecionados, descartados, erros
                  FROM engine_runs WHERE run_id = %s
            """, (decisao["run_id"],))
            linha = cur.fetchone()
            execucao = dict(linha) if linha else None
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[ADMIN/MOTOR] porque %s#%s: %s",
                                            tabela, pick_id, e)
        return {"disponivel": False, "erro": str(e)[:200]}
    finally:
        cur.close()
        conn.close()

    debug = pick.get("engine_debug") or {}
    if isinstance(debug, str):
        try:
            debug = json.loads(debug)
        except Exception:
            debug = {}

    contexto = (decisao or {}).get("context") or {}
    if isinstance(contexto, str):
        try:
            contexto = json.loads(contexto)
        except Exception:
            contexto = {}

    return {
        "disponivel": True,
        "fonte": _TABELAS_EXPLICAVEIS[tabela],
        "pick": {k: v for k, v in pick.items() if k != "engine_debug"},
        # O resumo estruturado que o motor gravou · é ele que a tela lista
        # ("Over 1.5: 9 de 10 jogos"). Vem pronto do motor de propósito:
        # montá-lo aqui seria escrever a explicação uma segunda vez, e as duas
        # versões acabariam divergindo.
        "resumo": contexto.get("resumo"),
        "conclusao": contexto.get("conclusao"),
        "parcelas": contexto.get("parcelas") or debug.get("parcelas"),
        "pontos_fracos": contexto.get("pontos_fracos") or debug.get("pontos_fracos"),
        # A AMOSTRA · quais jogos entraram na conta. `engine_debug` primeiro
        # porque é o retrato do pick; o contexto da decisão é a reserva para
        # picks gravados antes de a amostra existir no engine_debug.
        "amostra": debug.get("amostra") or contexto.get("amostra"),
        "engine_debug": debug,
        "decisao": {k: v for k, v in (decisao or {}).items()
                    if k not in ("context",)} if decisao else None,
        "execucao": execucao,
    }


@router.get("/bookmakers")
def listar_bookmakers(current_user: dict = Depends(require_admin)):
    """Casas de aposta cadastradas e seus volumes de coleta."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT b.bookmaker_id,
                   b.bookmaker_name,
                   b.ativo,
                   b.created_at,
                   COUNT(ov.id)              AS n_odds,
                   COUNT(DISTINCT ov.fixture_id) AS n_fixtures
            FROM bookmakers b
            LEFT JOIN odds_values ov ON ov.bookmaker_id = b.bookmaker_id
            GROUP BY b.bookmaker_id, b.bookmaker_name, b.ativo, b.created_at
            ORDER BY b.bookmaker_id
        """)
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        # Tabela bookmakers pode nao existir ainda (pre-migracao).
        conn.rollback()
        # Fallback: lê direto das odds coletadas
        cur.execute("""
            SELECT bookmaker_id,
                   bookmaker_name,
                   TRUE           AS ativo,
                   NULL           AS created_at,
                   COUNT(*)       AS n_odds,
                   COUNT(DISTINCT fixture_id) AS n_fixtures
            FROM odds_values
            WHERE bookmaker_id IS NOT NULL
            GROUP BY bookmaker_id, bookmaker_name
            ORDER BY bookmaker_id
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


@router.put("/bookmakers/{bookmaker_id}")
def atualizar_bookmaker(
    bookmaker_id: int,
    body: BookmakerBody,
    current_user: dict = Depends(require_admin),
):
    """Cria ou atualiza uma casa de aposta na tabela bookmakers.

    Criar: permite cadastrar uma casa nova com o ID que a API-Football usa,
    antes que a primeira odd seja coletada (útil pra pré-autorizar).
    Atualizar: renomeia ou ativa/desativa sem apagar o histórico de odds.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO bookmakers (bookmaker_id, bookmaker_name, ativo)
            VALUES (%s, %s, %s)
            ON CONFLICT (bookmaker_id) DO UPDATE
                SET bookmaker_name = EXCLUDED.bookmaker_name,
                    ativo          = EXCLUDED.ativo
            RETURNING bookmaker_id, bookmaker_name, ativo
        """, (bookmaker_id, body.bookmaker_name.strip(), body.ativo))
        row = cur.fetchone()
        conn.commit()
        return dict(row)
    finally:
        cur.close()
        conn.close()


@router.delete("/bookmakers/{bookmaker_id}")
def desativar_bookmaker(bookmaker_id: int, current_user: dict = Depends(require_admin)):
    """Marca a casa como inativa (não apaga — o histórico de odds fica intacto)."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE bookmakers SET ativo = FALSE WHERE bookmaker_id = %s "
            "RETURNING bookmaker_id, bookmaker_name",
            (bookmaker_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Casa de aposta não encontrada.")
        conn.commit()
        return {
            "ok": True,
            "desativada": row["bookmaker_name"],
            "aviso": "Odds já coletadas não são afetadas. Só a coleta futura ignora esta casa.",
        }
    finally:
        cur.close()
        conn.close()
