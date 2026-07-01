import os
import json
import struct
import time
import base64
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


# ── Helpers base64url ─────────────────────────────────────────────────────────

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ── Web Push encryption (RFC 8291 / aesgcm) sem dependências externas ─────────
# Usa apenas `cryptography` e `requests`, já presentes em requirements.txt.

def _encrypt_payload(p256dh: str, auth_secret: str, plaintext: bytes):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    p256dh_bytes = _b64d(p256dh)
    auth_bytes   = _b64d(auth_secret)

    # Carrega chave pública do cliente (ponto não-comprimido: 0x04 || x || y)
    x = int.from_bytes(p256dh_bytes[1:33], "big")
    y = int.from_bytes(p256dh_bytes[33:65], "big")
    client_pub = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()

    # Par efêmero do servidor
    server_priv = ec.generate_private_key(ec.SECP256R1())
    server_pub_bytes = server_priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    # ECDH
    shared = server_priv.exchange(ec.ECDH(), client_pub)

    # Salt aleatório
    salt = os.urandom(16)

    # Contexto (RFC 8291 aesgcm draft)
    context = (
        b"P-256\x00"
        + struct.pack(">H", len(p256dh_bytes)) + p256dh_bytes
        + struct.pack(">H", len(server_pub_bytes)) + server_pub_bytes
    )

    # PRK baseado no auth_secret
    prk = HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=auth_bytes, info=b"Content-Encoding: auth\x00"
    ).derive(shared)

    # Chave de cifração (16 bytes) e nonce (12 bytes)
    enc_key = HKDF(
        algorithm=hashes.SHA256(), length=16,
        salt=salt, info=b"Content-Encoding: aesgcm\x00" + context
    ).derive(prk)

    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12,
        salt=salt, info=b"Content-Encoding: nonce\x00" + context
    ).derive(prk)

    # AES-128-GCM (2 bytes de padding + payload)
    ciphertext = AESGCM(enc_key).encrypt(nonce, b"\x00\x00" + plaintext, None)

    return salt, server_pub_bytes, ciphertext


def _vapid_jwt(private_b64: str, audience: str) -> tuple[str, str]:
    """Retorna (jwt, public_key_b64url)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    priv_bytes  = _b64d(private_b64)
    private_key = ec.derive_private_key(int.from_bytes(priv_bytes, "big"), ec.SECP256R1())
    pub_bytes   = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    header  = _b64e(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    payload = _b64e(json.dumps({
        "aud": audience,
        "exp": int(time.time()) + 86400,
        "sub": VAPID_MAILTO,
    }).encode())

    signing_input = f"{header}.{payload}".encode()
    der_sig = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    jwt = f"{header}.{payload}.{_b64e(raw_sig)}"
    return jwt, _b64e(pub_bytes)


def _send_push(endpoint: str, p256dh: str, auth: str, data: str):
    """Envia push para um endpoint específico. Lança exceção em caso de falha."""
    import requests as _req
    from urllib.parse import urlparse

    audience = f"{urlparse(endpoint).scheme}://{urlparse(endpoint).netloc}"
    jwt, pub_b64 = _vapid_jwt(VAPID_PRIVATE_KEY, audience)

    salt, server_pub, ciphertext = _encrypt_payload(p256dh, auth, data.encode())

    headers = {
        "Content-Type":     "application/octet-stream",
        "Content-Encoding": "aesgcm",
        "Encryption":       f"salt={_b64e(salt)}",
        "Crypto-Key":       f"dh={_b64e(server_pub)};p256ecdsa={pub_b64}",
        "Authorization":    f"WebPush {jwt}",
        "TTL":              "86400",
    }

    resp = _req.post(endpoint, data=ciphertext, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.status_code


# ── Endpoints ─────────────────────────────────────────────────────────────────

class PushSubscription(BaseModel):
    endpoint: str
    keys: dict
    expirationTime: Optional[float] = None


@router.get("/vapid-public-key")
def get_vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(503, "Push notifications nao configuradas.")
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
def subscribe(sub: PushSubscription, current_user: dict = Depends(get_current_user)):
    if not VAPID_PRIVATE_KEY:
        raise HTTPException(503, "Push notifications nao configuradas.")
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
    """Envia push para todos os usuarios VIP com subscription ativa."""
    if not VAPID_PRIVATE_KEY:
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

    data    = json.dumps({"title": title, "body": body, "url": url})
    expired = []
    ok_count = 0

    for s in subs:
        try:
            _send_push(s["endpoint"], s["p256dh"], s["auth"], data)
            ok_count += 1
        except Exception as e:
            err = str(e)
            if "404" in err or "410" in err or "Gone" in err:
                expired.append(s["endpoint"])
            else:
                logger.debug("[PUSH] Falha: %s", e)

    if expired:
        try:
            conn2 = get_connection()
            cur2  = conn2.cursor()
            cur2.execute("DELETE FROM user_push_subscriptions WHERE endpoint = ANY(%s)", (expired,))
            conn2.commit()
            cur2.close()
            conn2.close()
        except Exception:
            pass

    logger.info("[PUSH] %d enviados, %d expirados removidos.", ok_count, len(expired))
