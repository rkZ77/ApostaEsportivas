import os
import sys
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from database import get_connection
from auth_utils import require_admin, hash_password

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
            SELECT u.id, u.name, u.email, u.plan, u.subscription_type,
                   u.active, u.expires_at, u.created_at,
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
            (body.name, body.email, hash_password(body.password), body.plan),
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
        if body.plan is not None:
            fields.append("plan = %s"); values.append(body.plan)
        if body.subscription_type is not None:
            fields.append("subscription_type = %s"); values.append(body.subscription_type or None)
        if body.active is not None:
            fields.append("active = %s"); values.append(body.active)
        if body.expires_at is not None:
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
    import glob as _glob
    dunder_file = os.path.abspath(__file__)
    cwd = os.getcwd()
    candidate1 = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ApostaEsportivas/src"))
    candidate2 = os.path.abspath(os.path.join(cwd, "ApostaEsportivas/src"))
    # lista raiz e /app se existir
    root_ls = os.listdir("/") if os.path.isdir("/") else []
    app_ls = os.listdir("/app") if os.path.isdir("/app") else []
    return {
        "__file__": dunder_file,
        "cwd": cwd,
        "PIPELINE_SRC_PATH_env": os.getenv("PIPELINE_SRC_PATH"),
        "_PIPELINE_DIR": _PIPELINE_DIR,
        "candidate1_exists": os.path.isdir(candidate1),
        "candidate2_exists": os.path.isdir(candidate2),
        "root_ls": root_ls,
        "app_ls": app_ls,
    }


_PIPELINE_SCRIPTS = {
    "atualizar_jogos":      "atualizar_jogos.py",
    "capturar_odds":        "capturar_odds.py",
    "gerar_vip":            "gerar_sugestao_vip.py",
    "gerar_free":           os.path.join("ai", "dica_do_dia_pipeline.py"),
    "gerar_multipla":       "gerar_sugestao_multiplas.py",
    "gerar_alavancagem":    os.path.join("ai", "alavancagem_pipeline.py"),
    "atualizar_resultados": "atualizar_resultados_sugestoes.py",
}


class PipelineCommandBody(BaseModel):
    command: str


async def _run_and_track(command: str, script: str):
    now = lambda: datetime.now(timezone.utc).strftime("%H:%M:%S")
    started = now()
    _pipeline_status[command] = {"status": "running", "started_at": started, "finished_at": None, "returncode": None, "error": None}
    try:
        env = {**os.environ, "PYTHONPATH": _PIPELINE_DIR}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_PIPELINE_DIR,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("Script excedeu o limite de 5 minutos e foi encerrado")
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


@router.get("/pipeline-status")
def pipeline_status(current_user: dict = Depends(require_admin)):
    return _pipeline_status


@router.post("/run-pipeline")
async def run_pipeline(body: PipelineCommandBody, current_user: dict = Depends(require_admin)):
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
    """Reprocessa um pagamento do MercadoPago pelo ID — ativa VIP manualmente se aprovado."""
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

    expires_at     = datetime.now(timezone.utc) + timedelta(days=days)
    amount         = float(payment.get("transaction_amount") or 0)
    payment_method = payment.get("payment_type_id") or "unknown"

    conn = get_connection()
    cur = conn.cursor()
    try:
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
                    AND expires_at > NOW())                     AS vip_expirando
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
