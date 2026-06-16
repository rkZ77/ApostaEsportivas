import os
import hmac
import hashlib
import logging
import resend
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import mercadopago
from auth_utils import get_current_user
from database import get_connection

logger = logging.getLogger(__name__)

PLAN_LABELS = {
    "mensal":     "Mensal",
    "trimestral": "Trimestral",
    "semestral":  "Semestral",
    "anual":      "Anual",
}


def _send_vip_email(to: str, name: str, plan_key: str, expires_at) -> None:
    api_key   = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("SMTP_FROM", "noreply@pickia.com.br")
    site_url  = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")

    if not api_key:
        return

    first_name  = name.strip().split()[0]
    plan_label  = PLAN_LABELS.get(plan_key, plan_key.capitalize())
    expires_str = expires_at.strftime("%d/%m/%Y") if hasattr(expires_at, "strftime") else str(expires_at)[:10]

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111;border:1px solid #222;border-radius:16px;overflow:hidden;max-width:560px;width:100%;">
        <tr><td style="background:linear-gradient(135deg,#16a34a,#15803d);padding:36px 40px;text-align:center;">
          <h1 style="margin:0;color:#fff;font-size:28px;font-weight:900;letter-spacing:-0.5px;">Pick<span style="color:#bbf7d0;">IA</span></h1>
          <p style="margin:6px 0 0;color:#dcfce7;font-size:14px;">Tips esportivas por Inteligência Artificial</p>
        </td></tr>
        <tr><td style="padding:36px 40px;text-align:center;">
          <div style="width:64px;height:64px;background:#16a34a22;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;">
            <span style="font-size:32px;">&#127942;</span>
          </div>
          <h2 style="margin:0 0 8px;color:#fff;font-size:22px;font-weight:800;">Acesso ativado, {first_name}!</h2>
          <p style="margin:0 0 24px;color:#a1a1aa;font-size:15px;line-height:1.6;">
            Seu pagamento foi confirmado. Você agora tem acesso completo ao Pick IA.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border:1px solid #262626;border-radius:12px;margin-bottom:28px;">
            <tr>
              <td style="padding:16px 20px;border-bottom:1px solid #262626;">
                <span style="color:#71717a;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Plano</span>
                <div style="color:#fff;font-size:15px;font-weight:700;margin-top:4px;">{plan_label}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 20px;">
                <span style="color:#71717a;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Acesso até</span>
                <div style="color:#22c55e;font-size:15px;font-weight:700;margin-top:4px;">{expires_str}</div>
              </td>
            </tr>
          </table>
          <a href="{site_url}/picks"
             style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;font-weight:800;font-size:15px;padding:14px 40px;border-radius:10px;">
            Acessar meus picks
          </a>
        </td></tr>
        <tr><td style="border-top:1px solid #1f1f1f;padding:20px 40px;text-align:center;">
          <p style="margin:0;color:#3f3f46;font-size:11px;">Pick IA &mdash; Tips por Inteligência Artificial</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        resend.api_key = api_key
        resend.Emails.send({
            "from":    from_addr,
            "to":      [to],
            "subject": "Acesso ativado — Pick IA",
            "text":    f"Olá {first_name}, seu acesso foi ativado! Plano {plan_label} válido até {expires_str}. Acesse: {site_url}/picks",
            "html":    html,
        })
        logger.info("[EMAIL] VIP email enviado para %s", to)
    except Exception as e:
        logger.warning("[EMAIL] Falha ao enviar VIP email para %s: %s", to, e)


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
    "mensal":     {"price": 39.90,  "title": "Plano Picks — Mensal",     "days": 30},
    "trimestral": {"price": 99.90,  "title": "Plano Picks — Trimestral", "days": 90},
    "semestral":  {"price": 199.90, "title": "Plano Picks — Semestral",  "days": 180},
    "anual":      {"price": 359.90, "title": "Plano Picks — Anual",      "days": 365},
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
            "title":       plan_info["title"],
            "description": f"Acesso VIP ao Pick IA — picks esportivos por IA por {plan_info['days']} dias",
            "quantity":    1,
            "unit_price":  plan_info["price"],
            "currency_id": "BRL",
            "category_id": "services",
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
        "statement_descriptor": "PICK IA",
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

    # Verificação de assinatura HMAC do MercadoPago
    webhook_secret = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "")
    if webhook_secret:
        x_signature  = request.headers.get("x-signature", "")
        x_request_id = request.headers.get("x-request-id", "")
        data_id      = str(data.get("data", {}).get("id", ""))
        if not x_signature or not _verify_mp_signature(body, x_signature, x_request_id, data_id, webhook_secret):
            logger.warning("[WEBHOOK] Assinatura inválida de %s — processando mesmo assim (verificar secret)",
                           request.client.host if request.client else "unknown")

    event_type = data.get("type")
    logger.info("[WEBHOOK] Evento recebido: type=%s data=%s", event_type, data.get("data"))

    if event_type != "payment":
        logger.info("[WEBHOOK] Ignorado (type=%s)", event_type)
        return {"status": "ignored"}

    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        logger.error("[WEBHOOK] MERCADOPAGO_ACCESS_TOKEN não configurado")
        return {"status": "error", "detail": "token missing"}

    payment_id = data.get("data", {}).get("id")
    if not payment_id:
        logger.warning("[WEBHOOK] payment_id ausente no payload")
        return {"status": "ignored"}

    logger.info("[WEBHOOK] Consultando pagamento id=%s", payment_id)
    sdk = mercadopago.SDK(access_token)
    payment_info = sdk.payment().get(payment_id)
    payment = payment_info.get("response", {})

    status = payment.get("status")
    logger.info("[WEBHOOK] Pagamento id=%s status=%s external_ref=%s", payment_id, status, payment.get("external_reference"))

    if status != "approved":
        logger.info("[WEBHOOK] Pagamento não aprovado (status=%s), ignorando", status)
        return {"status": "pending"}

    external_ref = payment.get("external_reference", "")
    parts = external_ref.split(":", 1)
    if len(parts) != 2:
        logger.error("[WEBHOOK] external_reference inválido: %s", external_ref)
        return {"status": "error", "detail": "external_reference inválido"}

    user_id, plan_key = parts
    plan_info = PLANS.get(plan_key)
    if not plan_info:
        logger.error("[WEBHOOK] Plano inválido: %s", plan_key)
        return {"status": "error", "detail": "plano inválido"}

    expires_at = datetime.now(timezone.utc) + timedelta(days=plan_info["days"])
    logger.info("[WEBHOOK] Ativando VIP para user_id=%s plano=%s expires=%s", user_id, plan_key, expires_at)

    amount        = float(payment.get("transaction_amount") or plan_info["price"])
    payment_method = payment.get("payment_type_id") or payment.get("payment_method_id") or "unknown"

    conn = get_connection()
    cur = conn.cursor()
    user_name  = None
    user_email = None
    try:
        cur.execute(
            "UPDATE users SET plan='vip', expires_at=%s, subscription_type=%s WHERE id=%s RETURNING name, email",
            (expires_at, plan_key, int(user_id)),
        )
        row = cur.fetchone()
        if not row:
            logger.error("[WEBHOOK] user_id=%s não encontrado no banco — pagamento %s ignorado", user_id, payment_id)
            return {"status": "error", "detail": "user not found"}
        user_name  = row["name"]
        user_email = row["email"]

        # Registra pagamento (ignora se já existe — idempotente)
        cur.execute(
            """
            INSERT INTO payments (user_id, mp_payment_id, plan_key, amount, status, expires_at, payment_method)
            VALUES (%s, %s, %s, %s, 'approved', %s, %s)
            ON CONFLICT (mp_payment_id) DO NOTHING
            """,
            (int(user_id), str(payment_id), plan_key, amount, expires_at, payment_method),
        )

        # Crédito de indicação: +2 dias VIP para o referrer quando indicado assina VIP
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
                SET plan       = CASE WHEN plan IN ('free', 'trial') THEN 'vip' ELSE plan END,
                    expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '2 days'
                WHERE id = %s
                """,
                (referrer_id,),
            )

        conn.commit()
        logger.info("[WEBHOOK] VIP ativado com sucesso para user_id=%s email=%s", user_id, user_email)
    finally:
        cur.close()
        conn.close()

    # Email de confirmação de VIP (em thread separada para não atrasar a resposta)
    if user_email and user_name:
        import threading
        threading.Thread(
            target=_send_vip_email,
            args=(user_email, user_name, plan_key, expires_at),
            daemon=True,
        ).start()

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
