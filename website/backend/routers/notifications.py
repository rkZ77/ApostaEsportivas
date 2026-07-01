import os
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import get_connection
from auth_utils import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_MAILTO      = os.getenv("VAPID_MAILTO", "mailto:contato@pickia.com.br")


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict
    expirationTime: Optional[float] = None


@router.get("/vapid-public-key")
def get_vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(503, "Push notifications não configuradas.")
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
def subscribe(sub: PushSubscription, current_user: dict = Depends(get_current_user)):
    if not VAPID_PRIVATE_KEY:
        raise HTTPException(503, "Push notifications não configuradas.")
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO user_push_subscriptions (user_id, endpoint, p256dh, auth)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, endpoint) DO UPDATE
                SET p256dh = EXCLUDED.p256dh,
                    auth   = EXCLUDED.auth,
                    updated_at = NOW()
        """, (user_id, sub.endpoint, sub.keys.get("p256dh"), sub.keys.get("auth")))
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


@router.delete("/subscribe")
def unsubscribe(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM user_push_subscriptions WHERE user_id = %s", (user_id,))
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


def send_push_to_all_vip(title: str, body: str, url: str = "/picks"):
    """Envia push notification para todos os usuários VIP com subscription ativa."""
    if not VAPID_PRIVATE_KEY:
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("[PUSH] pywebpush não instalado — push desabilitado.")
        return

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ps.endpoint, ps.p256dh, ps.auth
            FROM user_push_subscriptions ps
            JOIN users u ON u.id = ps.user_id
            WHERE u.plan IN ('vip', 'admin')
              AND (u.expires_at IS NULL OR u.expires_at > NOW() OR u.plan = 'admin')
        """)
        subs = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not subs:
        return

    data = json.dumps({"title": title, "body": body, "url": url})
    expired = []
    ok_count = 0

    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s["endpoint"],
                    "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
                },
                data=data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_MAILTO},
            )
            ok_count += 1
        except Exception as e:
            err_str = str(e)
            # 404/410 = subscription expirada, limpar do banco
            if "404" in err_str or "410" in err_str:
                expired.append(s["endpoint"])
            else:
                logger.debug("[PUSH] Falha ao enviar: %s", e)

    if expired:
        try:
            conn2 = get_connection()
            cur2 = conn2.cursor()
            cur2.execute("DELETE FROM user_push_subscriptions WHERE endpoint = ANY(%s)", (expired,))
            conn2.commit()
            cur2.close()
            conn2.close()
        except Exception:
            pass

    logger.info("[PUSH] %d enviados, %d expirados removidos.", ok_count, len(expired))
