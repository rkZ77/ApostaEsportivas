import os
import json
import struct
import time
import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Any
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


# ── Notificações in-app (o sino da navbar) ────────────────────────────────────
# Push é entrega, isto é histórico: o push some da bandeja do sistema e não
# volta, então tudo que importa também vira linha em `notifications` pra o
# usuário reencontrar depois. Foi exatamente o buraco do fechamento mensal,
# que vivia só num localStorage e sumia pra sempre ao fechar o popup.

TYPE_MONTHLY_CLOSE = "monthly_close"
TYPE_NEW_PICKS     = "new_picks"
TYPE_PICK_LIVE     = "pick_live"
TYPE_PICK_RESULT   = "pick_result"

LIST_LIMIT   = 40
PURGE_DAYS   = 60   # notificações lidas mais velhas que isso são descartadas


def fmt_brl(value: float) -> str:
    """R$ 1.234,56 · pt-BR sem depender de locale instalado no container."""
    s = f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{'-' if value < 0 else ''}R$ {s}"


def create_notification(cur, user_id: int, ntype: str, title: str, dedupe_key: str,
                        body: Optional[str] = None, url: Optional[str] = None,
                        payload: Optional[dict] = None) -> None:
    """
    Cria (ou atualiza) uma notificação usando o cursor/transação do chamador.

    `dedupe_key` é obrigatório: todos os geradores rodam mais de uma vez sobre
    o mesmo evento (poll de 60s, revisão tardia de resultado pelo provedor,
    recálculo do fechamento a cada request) e sem ele o sino viraria uma pilha
    de repetições. Em conflito o conteúdo é atualizado mas `read_at` é
    preservado: um resultado corrigido não volta a piscar como não lido pra
    quem já tinha visto o item.
    """
    cur.execute("""
        INSERT INTO notifications (user_id, type, title, body, url, payload, dedupe_key)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (user_id, dedupe_key) DO UPDATE
           SET title   = EXCLUDED.title,
               body    = EXCLUDED.body,
               url     = EXCLUDED.url,
               payload = EXCLUDED.payload
    """, (user_id, ntype, title[:160], body, url,
          json.dumps(payload) if payload is not None else None, dedupe_key))


def notify_all_users(ntype: str, title: str, dedupe_key: str,
                     body: Optional[str] = None, url: Optional[str] = None,
                     payload: Optional[dict] = None) -> int:
    """Cria a mesma notificação pra toda a base, numa query só. Abre conexão própria."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO notifications (user_id, type, title, body, url, payload, dedupe_key)
            SELECT u.id, %s, %s, %s, %s, %s::jsonb, %s FROM users u
            ON CONFLICT (user_id, dedupe_key) DO NOTHING
        """, (ntype, title[:160], body, url,
              json.dumps(payload) if payload is not None else None, dedupe_key))
        count = cur.rowcount
        conn.commit()
        return count
    finally:
        cur.close()
        conn.close()


def notify_pick_result(cur, pick_id: int, pick_type: str, result: str) -> None:
    """
    Avisa todo mundo que seguiu o pick que ele foi resolvido, com o P&L real da
    entrada de cada um (odd declarada e cashout entram na conta, então dois
    usuários no mesmo pick podem receber números diferentes · é por design,
    ver _compute_follow_pnl).

    Roda dentro da transação que grava o resultado. Nunca propaga exceção: o
    caminho crítico aqui é salvar o resultado do pick, notificação é acessório.
    """
    try:
        from routers.banca import _resolve_pick, _compute_follow_pnl

        pick = _resolve_pick(cur, pick_id, pick_type)
        if not pick:
            return
        # Fallback pro resultado recém-gravado: alguns call sites usam
        # "UPDATE ... WHERE result IS NULL", então a leitura pode vir vazia.
        if not pick.get("result"):
            pick["result"] = result

        cur.execute("""
            SELECT uf.user_id, uf.stake_units, uf.actual_odd, uf.cashout_amount,
                   COALESCE(ub.unit_value, 1) AS unit_value
            FROM user_followed_picks uf
            LEFT JOIN user_banca ub ON ub.user_id = uf.user_id
            WHERE uf.pick_id = %s AND uf.pick_type = %s
        """, (pick_id, pick_type))
        followers = [dict(r) for r in cur.fetchall()]
        if not followers:
            return

        home, away = pick.get("home_team_name"), pick.get("away_team_name")
        if pick_type == "multipla":
            match_label = "Múltipla do dia"
        elif pick_type == "alavancagem":
            match_label = "Alavancagem"
        elif home and away:
            match_label = f"{home} x {away}"
        else:
            match_label = "Pick seguido"

        market = " ".join(str(p) for p in (pick.get("market"), pick.get("line")) if p).strip()

        for f in followers:
            unit_value = float(f["unit_value"] or 1)
            label, profit_u, pnl_r = _compute_follow_pnl(pick, f, unit_value)
            if label is None:
                continue
            parts = [p for p in (market,) if p]
            if pnl_r is not None:
                sign = "+" if pnl_r >= 0 else ""
                parts.append(f"{sign}{fmt_brl(pnl_r)} ({sign}{profit_u:.2f}u)")
            create_notification(
                cur, f["user_id"], TYPE_PICK_RESULT,
                title=f"{label} · {match_label}",
                dedupe_key=f"pick_result:{pick_type}:{pick_id}",
                body=" · ".join(parts) or None,
                url="/banca",
                payload={
                    "pick_id":      pick_id,
                    "pick_type":    pick_type,
                    "result":       label,
                    "profit_units": round(profit_u, 4) if profit_u is not None else None,
                    "pnl":          round(pnl_r, 2) if pnl_r is not None else None,
                },
            )
    except Exception as e:
        logger.warning("[NOTIF] Falha ao notificar resultado de %s #%s: %s", pick_type, pick_id, e)


def notify_picks_went_live(user_id: int, live_items: list[dict]) -> None:
    """
    Marca no sino os picks seguidos que entraram em jogo. Chamado pelo próprio
    GET /live/my-picks (que o front já consulta a cada 60s) em vez de um job
    dedicado: o dado de "está ao vivo agora" só existe depois do enrich, e
    duplicar isso num scheduler significaria pagar as mesmas chamadas de API
    de novo. O dedupe_key por pick garante um aviso só por pick.
    """
    if not live_items:
        return
    conn = get_connection()
    cur  = conn.cursor()
    try:
        for item in live_items:
            pick_type = item.get("pick_type")
            pick_id   = item.get("pick_id")
            if pick_id is None:
                continue
            if pick_type == "multipla":
                label = "Múltipla do dia"
            elif pick_type == "alavancagem":
                label = "Alavancagem"
            else:
                home, away = item.get("home_team"), item.get("away_team")
                label = f"{home} x {away}" if home and away else "Pick seguido"
            create_notification(
                cur, user_id, TYPE_PICK_LIVE,
                title=f"Começou · {label}",
                dedupe_key=f"pick_live:{pick_type}:{pick_id}",
                body="Seu pick está em jogo. Acompanhe ao vivo.",
                url="/picks?tab=ao-vivo",
                payload={"pick_id": pick_id, "pick_type": pick_type},
            )
        conn.commit()
    except Exception as e:
        logger.warning("[NOTIF] Falha ao notificar picks ao vivo do user %s: %s", user_id, e)
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def purge_old_notifications() -> int:
    """Descarta notificações já lidas com mais de PURGE_DAYS. Chamado pelo scheduler."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM notifications WHERE read_at IS NOT NULL "
            f"AND created_at < NOW() - INTERVAL '{PURGE_DAYS} days'"
        )
        removed = cur.rowcount
        conn.commit()
        return removed
    finally:
        cur.close()
        conn.close()


# ── Endpoints do sino ─────────────────────────────────────────────────────────

@router.get("")
def list_notifications(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(LIST_LIMIT, ge=1, le=LIST_LIMIT),
):
    """Lista do sino + contagem de não lidas."""
    user_id = current_user["id"]
    conn = get_connection()
    cur  = conn.cursor()
    try:
        # O fechamento do mês anterior é gerado sob demanda aqui (não por job):
        # depende do histórico de picks seguidos de cada usuário e a checagem
        # sai barata quando já existe (dois SELECTs por índice único).
        try:
            from routers.banca import sync_monthly_close_notification
            sync_monthly_close_notification(cur, user_id)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning("[NOTIF] Falha no sync do fechamento mensal (user %s): %s", user_id, e)

        cur.execute("""
            SELECT id, type, title, body, url, payload, read_at, created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
        """, (user_id, limit))
        items: list[dict[str, Any]] = []
        for r in cur.fetchall():
            d = dict(r)
            payload = d.get("payload")
            if isinstance(payload, str):
                try:    payload = json.loads(payload)
                except Exception: payload = None
            items.append({
                "id":         d["id"],
                "type":       d["type"],
                "title":      d["title"],
                "body":       d["body"],
                "url":        d["url"],
                "payload":    payload or {},
                "read":       d["read_at"] is not None,
                "created_at": d["created_at"].isoformat() if d["created_at"] else None,
            })

        cur.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = %s AND read_at IS NULL",
            (user_id,),
        )
        unread = cur.fetchone()["c"]
        return {"items": items, "unread_count": unread}
    finally:
        cur.close()
        conn.close()


@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur  = conn.cursor()
    try:
        # user_id no WHERE: sem ele, um id chutado marcaria a notificação de outro.
        cur.execute(
            "UPDATE notifications SET read_at = NOW() "
            "WHERE id = %s AND user_id = %s AND read_at IS NULL",
            (notification_id, current_user["id"]),
        )
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


@router.post("/read-all")
def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(
            "UPDATE notifications SET read_at = NOW() WHERE user_id = %s AND read_at IS NULL",
            (current_user["id"],),
        )
        count = cur.rowcount
        conn.commit()
        return {"ok": True, "marked": count}
    finally:
        cur.close()
        conn.close()
