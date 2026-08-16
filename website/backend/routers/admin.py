import os
import sys
import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from typing import Optional
from database import get_connection
from data_br import HOJE_BR, data_br
from auth_utils import require_admin, hash_password, get_current_user, invalidar_cache_usuario

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
    "gerar_goleiros":       os.path.join("engine_pipelines", "goleiros_pipeline.py"),
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
        await _run_and_track(cmd, script, espelhar_em="tudo")
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
        await _run_and_track(cmd, script)
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
        falhas_por_status: dict = {}
        cobertura = {"pernas": len(legs), "com_parecer": 0, "sem_parecer": 0,
                     "autor_gravado": 0, "autor_inferido": 0, "autor_desconhecido": 0}

        for leg in legs:
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

        return {
            "days": days,
            "cobertura": cobertura,
            "modelos": modelos,
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

    asyncio.create_task(_run_and_track(body.command, script))
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
    "multipla": "total_odd", "alavancagem": "odd_combined",
}


#: Tabelas com UMA fixture por pick · só nelas dá pra cruzar com
#: match_statistics e dizer se o provedor publicou a folha do jogo.
_PICK_TABLES_UMA_FIXTURE = ("vip", "free", "faltas", "goleiros")


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
            try:
                cur.execute(f"""
                    SELECT id, {home_col} AS home_team, {away_col} AS away_team,
                           match_date, result, profit, {mercado}
                    FROM {table}
                    {where}
                    ORDER BY match_date DESC, id DESC
                    LIMIT 50
                """, params)
            except Exception:
                # Instancia sem a migracao das tabelas novas: pula esse tipo em
                # vez de derrubar a busca inteira.
                conn.rollback()
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
        cur.execute(f"SELECT {odd_col} AS odd FROM {table} WHERE id = %s", (body.pick_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pick não encontrado")

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
                "resolver · pra corrigir um resultado errado, use Alterar resultado.")

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
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name, temporada_iniciada FROM leagues WHERE league_id = %s",
                    (league_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Liga nao cadastrada. Cadastre antes de coletar.")
        nome = row["name"]
        # So' pula o historico quando alguem marcou EXPLICITAMENTE que a
        # temporada nao comecou. NULL (ninguem marcou) roda completo, que e' o
        # seguro: pular por engano deixa o motor sem base pra analisar a liga,
        # e o unico sintoma seria "essa liga nunca gera pick".
        com_historico = row["temporada_iniciada"] is not False
    finally:
        cur.close()
        conn.close()

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
