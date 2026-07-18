import os
import sys
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from database import get_connection
from auth_utils import require_admin, hash_password, get_current_user

_pipeline_status: dict = {}  # command -> {status, started_at, finished_at, returncode}

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
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


@router.get("/debug-paths")
def debug_paths(current_user: dict = Depends(require_admin)):
    dunder_file = os.path.abspath(__file__)
    cwd = os.getcwd()
    candidate1 = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ApostaEsportivas/src"))
    candidate2 = os.path.abspath(os.path.join(cwd, "ApostaEsportivas/src"))
    return {
        "__file__": dunder_file,
        "cwd": cwd,
        "PIPELINE_SRC_PATH_env": os.getenv("PIPELINE_SRC_PATH"),
        "_PIPELINE_DIR": _PIPELINE_DIR,
        "candidate1_exists": os.path.isdir(candidate1),
        "candidate2_exists": os.path.isdir(candidate2),
    }


_PIPELINE_SCRIPTS = {
    "atualizar_jogos":      "atualizar_jogos.py",
    "capturar_odds":        "capturar_odds.py",
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
    "atualizar_resultados": "atualizar_resultados_sugestoes.py",
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
    "atualizar_jogos", "capturar_odds",
    "dev_gerar_vip", "dev_gerar_dica", "dev_gerar_multipla", "dev_gerar_alavancagem",
    "dev_homolog_vip", "dev_homolog_dica", "dev_homolog_multipla", "dev_homolog_alavancagem",
]

# Timeouts por comando (segundos). atualizar_jogos roda 6 stages + API externa → precisa de mais tempo.
_PIPELINE_TIMEOUTS = {
    "atualizar_jogos": 900.0,   # 15 min
    "gerar_vip":       600.0,   # 10 min · múltiplos fixtures com chamadas IA
    "gerar_multipla":  600.0,   # 10 min · IA + carregamento de contexto
    "gerar_alavancagem": 600.0, # 10 min
    "default":         300.0,   # 5 min para os demais
}

_TUDO_STEPS = ["atualizar_jogos", "capturar_odds", "gerar_vip", "gerar_free", "gerar_multipla", "gerar_alavancagem"]

_STEP_LABELS = {
    "atualizar_jogos":   "Atualizando jogos",
    "capturar_odds":     "Capturando odds",
    "gerar_vip":         "Gerando picks VIP",
    "gerar_free":        "Gerando pick gratuito",
    "gerar_multipla":    "Gerando múltipla",
    "gerar_alavancagem": "Gerando alavancagem",
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


async def _run_and_track(command: str, script: str):
    now = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    started = now()
    _pipeline_status[command] = {"status": "running", "started_at": started, "finished_at": None, "returncode": None, "error": None}
    timeout = _PIPELINE_TIMEOUTS.get(command, _PIPELINE_TIMEOUTS["default"])
    try:
        env = {**os.environ, "PYTHONPATH": _PIPELINE_DIR}
        if command.startswith("dev_"):
            env = _dev_env(env)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_PIPELINE_DIR,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Script excedeu o limite de {int(timeout // 60)} minutos e foi encerrado")
        returncode = proc.returncode
        out = stdout.decode(errors="replace")[-1500:]
        err = stderr.decode(errors="replace")[-1500:]
        _pipeline_status[command] = {
            "status": "ok" if returncode == 0 else "error",
            "started_at": started,
            "finished_at": now(),
            "returncode": returncode,
            "log": out,
            "error": err if returncode != 0 else (err or None),
        }
    except Exception as e:
        _pipeline_status[command] = {"status": "error", "started_at": started, "finished_at": now(), "returncode": -1, "error": str(e)}


async def _run_tudo():
    now = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    started = now()
    _pipeline_status["tudo"] = {"status": "running", "started_at": started, "finished_at": None, "returncode": None, "error": None, "log": "Iniciando..."}
    for cmd in _TUDO_STEPS:
        script = os.path.join(_PIPELINE_DIR, _PIPELINE_SCRIPTS[cmd])
        _pipeline_status["tudo"]["log"] = f"Rodando {cmd}..."
        await _run_and_track(cmd, script)
        if _pipeline_status[cmd]["status"] == "error":
            err = _pipeline_status[cmd].get("error") or _pipeline_status[cmd].get("log") or ""
            _pipeline_status["tudo"] = {"status": "error", "started_at": started, "finished_at": now(), "returncode": -1, "error": f"Falhou em '{cmd}': {err[:300]}"}
            return
    _pipeline_status["tudo"] = {"status": "ok", "started_at": started, "finished_at": now(), "returncode": 0, "log": "Pipeline completo!", "error": None}


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


@router.get("/pipeline-status")
def pipeline_status(current_user: dict = Depends(require_admin)):
    return _pipeline_status


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
    """Reprocessa um pagamento do MercadoPago pelo ID · ativa VIP manualmente se aprovado."""
    import mercadopago as _mp
    from datetime import timedelta, timezone
    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        raise HTTPException(500, "MERCADOPAGO_ACCESS_TOKEN não configurado")

    sdk = _mp.SDK(access_token)
    info = sdk.payment().get(body.mp_payment_id)
    payment = info.get("response", {})

    status = payment.get("status")
    if status != "approved":
        raise HTTPException(400, f"Pagamento não aprovado (status={status})")

    external_ref = payment.get("external_reference", "")
    parts = external_ref.split(":", 1)
    if len(parts) != 2:
        raise HTTPException(400, f"external_reference inválido: {external_ref}")

    user_id, plan_key = parts
    PLANS_DAYS = {"mensal": 30, "trimestral": 90, "semestral": 180, "anual": 365}
    days = PLANS_DAYS.get(plan_key)
    if not days:
        raise HTTPException(400, f"Plano inválido: {plan_key}")

    amount         = float(payment.get("transaction_amount") or 0)
    payment_method = payment.get("payment_type_id") or "unknown"

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Mesmo criterio de GET /payments/webhook: estende a partir do maior
        # entre "agora" e o expires_at atual, nao sobrescreve (perderia dias
        # restantes se o usuario ja tiver VIP ativo).
        cur.execute("SELECT expires_at FROM users WHERE id = %s", (int(user_id),))
        row_exp = cur.fetchone()
        current_expires = row_exp["expires_at"] if row_exp else None  # naive UTC
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        base = current_expires if (current_expires and current_expires > now_naive) else now_naive
        expires_at = base + timedelta(days=days)

        cur.execute(
            "UPDATE users SET plan='vip', expires_at=%s, subscription_type=%s WHERE id=%s RETURNING id, name, email",
            (expires_at, plan_key, int(user_id)),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"Usuário {user_id} não encontrado")

        cur.execute(
            """INSERT INTO payments (user_id, mp_payment_id, plan_key, amount, status, expires_at, payment_method)
               VALUES (%s, %s, %s, %s, 'approved', %s, %s)
               ON CONFLICT (mp_payment_id) DO NOTHING""",
            (int(user_id), str(body.mp_payment_id), plan_key, amount, expires_at, payment_method),
        )
        conn.commit()
        return {"ok": True, "user": dict(row), "plan": plan_key, "expires_at": expires_at.isoformat()}
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

        cur.execute("""
            SELECT
                TO_CHAR(created_at AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM') AS month,
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
}
_VALID_RESULTS = {"GREEN", "RED", "PUSH", "HALF-WIN", "HALF-LOSS", None}


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
            date_col = "match_date" if pt != "multipla" else "DATE(created_at AT TIME ZONE 'UTC')"
            cur.execute(f"""
                SELECT id, {home_col} AS home_team, {away_col} AS away_team,
                       match_date, result
                FROM {table}
                {where}
                ORDER BY match_date DESC, id DESC
                LIMIT 50
            """, params)
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
        # Calcula profit simples quando resultado é definido (apenas para picks com odd)
        cur.execute(f"SELECT odd FROM {table} WHERE id = %s", (body.pick_id,))
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

        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM picks_vip
                 WHERE match_date = CURRENT_DATE)                            AS vip_picks,
                (SELECT COUNT(*) FROM picks_alavancagem
                 WHERE match_date = CURRENT_DATE)                            AS alavancagem,
                (SELECT COUNT(*) FROM picks_free
                 WHERE match_date = CURRENT_DATE)                            AS dica,
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
    """Dispara manualmente o resolver de picks pendentes (mesmo job do scheduler)."""
    from routers.live import resolve_all_pending
    result = resolve_all_pending()
    return {"ok": True, "resolved": result}
