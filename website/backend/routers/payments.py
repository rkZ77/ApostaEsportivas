import os
import hmac
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import mercadopago
from auth_utils import get_current_user
from database import get_connection

logger = logging.getLogger(__name__)


def _verify_mp_signature(body: bytes, x_signature: str, x_request_id: str, data_id: str, secret: str) -> bool:
    """Verifica assinatura HMAC-SHA256 do MercadoPago conforme documentação oficial."""
    try:
        # O MercadoPago envia: x-signature = ts=<timestamp>,v1=<hash>
        parts = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
        ts = parts.get("ts", "")
        v1 = parts.get("v1", "")
        if not ts or not v1:
            return False
        # Template: id:<data.id>;request-id:<x-request-id>;ts:<ts>
        signed_template = f"id:{data_id};request-id:{x_request_id};ts:{ts}"
        expected = hmac.new(secret.encode(), signed_template.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False

router = APIRouter(prefix="/api/payments", tags=["payments"])

PLANS = {
    "mensal":     {"price": 29.90,  "title": "Plano Picks — Mensal",     "days": 30},
    "trimestral": {"price": 79.90,  "title": "Plano Picks — Trimestral", "days": 90},
    "semestral":  {"price": 149.90, "title": "Plano Picks — Semestral",  "days": 180},
    "anual":      {"price": 269.90, "title": "Plano Picks — Anual",      "days": 365},
}


class CreatePreferenceBody(BaseModel):
    plan: str


@router.post("/create")
def create_preference(body: CreatePreferenceBody, current_user: dict = Depends(get_current_user)):
    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        raise HTTPException(500, "MERCADOPAGO_ACCESS_TOKEN não configurado")

    plan_info = PLANS.get(body.plan)
    if not plan_info:
        raise HTTPException(400, "Plano inválido. Use: mensal, trimestral, semestral ou anual")

    sdk = mercadopago.SDK(access_token)
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    backend_url  = os.getenv("BACKEND_URL",  "http://localhost:8000")

    preference_data = {
        "items": [{
            "title":      plan_info["title"],
            "quantity":   1,
            "unit_price": plan_info["price"],
            "currency_id": "BRL",
        }],
        "payer": {"email": current_user.get("email", "")},
        "back_urls": {
            "success": f"{frontend_url}/checkout/sucesso",
            "failure": f"{frontend_url}/checkout/falha",
            "pending": f"{frontend_url}/checkout/pendente",
        },
        "auto_return": "approved",
        "external_reference": f"{current_user['sub']}:{body.plan}",
        "notification_url": f"{backend_url}/api/payments/webhook",
        "statement_descriptor": "HPS PICKS",
    }

    result = sdk.preference().create(preference_data)
    if result.get("status", 0) >= 400:
        logger.error("Erro MercadoPago ao criar preferência: %s", result.get("response"))
        raise HTTPException(500, "Erro ao processar pagamento. Tente novamente.")

    preference = result["response"]
    sandbox = os.getenv("MERCADOPAGO_SANDBOX", "true").lower() == "true"

    return {
        "init_point": preference.get("sandbox_init_point") if sandbox else preference.get("init_point"),
        "id": preference.get("id"),
    }


@router.post("/webhook")
async def webhook(request: Request):
    body = await request.body()

    try:
        data = __import__("json").loads(body)
    except Exception:
        raise HTTPException(400, "Payload inválido")

    # Verificação de assinatura HMAC do MercadoPago (após parsear body para obter data.id)
    webhook_secret = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "")
    if webhook_secret:
        x_signature  = request.headers.get("x-signature", "")
        x_request_id = request.headers.get("x-request-id", "")
        data_id      = str(data.get("data", {}).get("id", ""))
        if not x_signature or not _verify_mp_signature(body, x_signature, x_request_id, data_id, webhook_secret):
            logger.warning("Webhook recebido com assinatura inválida de %s", request.client.host if request.client else "unknown")
            raise HTTPException(403, "Assinatura inválida")

    if data.get("type") != "payment":
        return {"status": "ignored"}

    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        return {"status": "error", "detail": "token missing"}

    payment_id = data.get("data", {}).get("id")
    if not payment_id:
        return {"status": "ignored"}

    sdk = mercadopago.SDK(access_token)
    payment_info = sdk.payment().get(payment_id)
    payment = payment_info.get("response", {})

    if payment.get("status") != "approved":
        return {"status": "pending"}

    external_ref = payment.get("external_reference", "")
    parts = external_ref.split(":", 1)
    if len(parts) != 2:
        return {"status": "error", "detail": "external_reference inválido"}

    user_id, plan_key = parts
    plan_info = PLANS.get(plan_key)
    if not plan_info:
        return {"status": "error", "detail": "plano inválido"}

    expires_at = datetime.now(timezone.utc) + timedelta(days=plan_info["days"])

    amount        = float(payment.get("transaction_amount") or plan_info["price"])
    payment_method = payment.get("payment_type_id") or payment.get("payment_method_id") or "unknown"

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE users SET plan='vip', expires_at=%s, subscription_type=%s WHERE id=%s",
            (expires_at, plan_key, int(user_id)),
        )

        # Registra pagamento (ignora se já existe — idempotente)
        cur.execute(
            """
            INSERT INTO payments (user_id, mp_payment_id, plan_key, amount, status, expires_at, payment_method)
            VALUES (%s, %s, %s, %s, 'approved', %s, %s)
            ON CONFLICT (mp_payment_id) DO NOTHING
            """,
            (int(user_id), str(payment_id), plan_key, amount, expires_at, payment_method),
        )

        # Crédito de indicação: +1 dia VIP para o referrer na primeira compra
        cur.execute(
            "SELECT referred_by FROM users WHERE id = %s AND referred_by IS NOT NULL",
            (int(user_id),),
        )
        ref_row = cur.fetchone()
        if ref_row:
            referrer_id = ref_row["referred_by"]
            cur.execute(
                """
                UPDATE users
                SET plan = 'vip',
                    expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '1 day'
                WHERE id = %s AND plan IN ('free', 'trial', 'vip', 'admin')
                """,
                (referrer_id,),
            )

        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"status": "ok"}


@router.get("/history")
def payment_history(current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT mp_payment_id, plan_key, amount, status, payment_method, expires_at, created_at
            FROM payments
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (current_user["sub"],),
        )
        rows = cur.fetchall()
        return [
            {
                "id":             r["mp_payment_id"],
                "plan":           r["plan_key"],
                "amount":         float(r["amount"]),
                "status":         r["status"],
                "payment_method": r["payment_method"],
                "expires_at":     r["expires_at"].isoformat() if r["expires_at"] else None,
                "created_at":     r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()
