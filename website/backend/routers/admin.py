from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from database import get_connection
from auth_utils import require_admin, hash_password

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
                   ub.bankroll_current, ub.unit_value
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
                (SELECT COUNT(*) FROM ai_suggestions
                 WHERE DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE)  AS vip_picks,
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
