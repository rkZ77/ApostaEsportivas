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
        conn2 = get_connection()
        try:
            cur2 = conn2.cursor()
            cur2.execute("DELETE FROM user_push_subscriptions WHERE endpoint = ANY(%s)", (expired,))
            conn2.commit()
            cur2.close()
        except Exception:
            pass
        finally:
            conn2.close()

    logger.info("[PUSH] %d enviados, %d expirados removidos.", ok_count, len(expired))


# ── Notificações in-app (o sino da navbar) ────────────────────────────────────
# Push é entrega, isto é histórico: o push some da bandeja do sistema e não
# volta, então tudo que importa também vira linha em `notifications` pra o
# usuário reencontrar depois. Foi exatamente o buraco do fechamento mensal,
# que vivia só num localStorage e sumia pra sempre ao fechar o popup.

# O PONTO DO MEIO SAIU DOS TEXTOS DE AVISO (2026-09-12). Ele e' proibido no
# texto de tela do site (ver CLAUDE.md) e estes titulos e corpos vao pro sino,
# pro toast e pra bandeja do sistema -- sao texto de tela como qualquer outro.
TYPE_MONTHLY_CLOSE = "monthly_close"
TYPE_NEW_PICKS     = "new_picks"
TYPE_PICK_LIVE     = "pick_live"
#: Pick NOVO publicado pelo Motor Live · é outra coisa que `pick_live`.
#:
#: `pick_live` é "o pick QUE VOCÊ SEGUIU entrou em jogo" -- pessoal, e só existe
#: pra quem apostou. Este é "o motor achou uma oportunidade agora" -- vale pra
#: toda a base que tem acesso, e é o único aviso possível de um produto cuja
#: janela de odd dura minutos. Dois nomes porque são dois eventos: juntá-los
#: faria o sino dizer "começou" pra um pick que ninguém pegou ainda.
TYPE_LIVE_NOVO     = "live_novo"
TYPE_PICK_RESULT   = "pick_result"
TYPE_PLAN_EXPIRING = "plan_expiring"
TYPE_TRIAL_ENDED   = "trial_ended"
# Um tipo por plano encerrado, e não um "access_ended" só: o ícone e a
# cópia do popup mudam (assinar x renovar), e o sino escolhe pelo tipo.
TYPE_VIP_ENDED     = "vip_ended"

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


#: QUEM TEM ACESSO VIP, em SQL.
#:
#: E' a traducao de `auth_utils.is_vip_active` pra dentro do INSERT em lote --
#: mesma lista de planos, mesma leitura de vencimento, e `admin` nunca expira.
#: Existe porque o aviso em massa nao passa por usuario nenhum: ele nasce de um
#: SELECT sobre `users`, e sem esta clausula o sino entrega pra base inteira o
#: que a tela cobra pra mostrar.
SQL_VIP_ATIVO = """
    u.plan IN ('vip', 'trial', 'admin')
    AND (u.plan = 'admin' OR u.expires_at IS NULL OR u.expires_at > NOW())
"""


#: QUEM TEM O PICK IA PRO, em SQL.
#:
#: Traducao de `auth_utils.tem_tier_pro` pro INSERT em lote, pelo mesmo motivo
#: que SQL_VIP_ATIVO existe. `plan_tier` so' e' lido de quem paga em `vip`:
#: admin e trial veem o produto inteiro, e a coluna nasceu com DEFAULT 'pro'
#: justamente pra base antiga nao perder nada.
SQL_PRO_ATIVO = """
    u.plan IN ('vip', 'trial', 'admin')
    AND (u.plan = 'admin' OR u.expires_at IS NULL OR u.expires_at > NOW())
    AND (u.plan <> 'vip' OR COALESCE(u.plan_tier, 'pro') = 'pro')
"""


def notify_pro_users(ntype: str, title: str, dedupe_key: str,
                     body: Optional[str] = None, url: Optional[str] = None,
                     payload: Optional[dict] = None) -> int:
    """Igual a `notify_vip_users`, mas so' pra quem tem o Pick IA Pro.

    Existe pelo motivo exato que criou a `notify_vip_users` em 10/09: o sino
    entrega o CORPO da notificacao, e o corpo do aviso de pick ao vivo tem
    mercado, linha e odd dentro. Com dois planos, mandar pelo gate de VIP faria
    o assinante Pick IA -- que ve' teaser na aba -- ler a analise completa no
    sino. Seria o mesmo furo de antes, so' que uma camada acima.
    """
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(f"""
            INSERT INTO notifications (user_id, type, title, body, url, payload, dedupe_key)
            SELECT u.id, %s, %s, %s, %s, %s::jsonb, %s FROM users u
            WHERE {SQL_PRO_ATIVO}
            ON CONFLICT (user_id, dedupe_key) DO NOTHING
        """, (ntype, title[:160], body, url,
              json.dumps(payload) if payload is not None else None, dedupe_key))
        count = cur.rowcount
        conn.commit()
        return count
    finally:
        cur.close()
        conn.close()


def notify_vip_users(ntype: str, title: str, dedupe_key: str,
                     body: Optional[str] = None, url: Optional[str] = None,
                     payload: Optional[dict] = None) -> int:
    """Igual a `notify_all_users`, mas so' pra quem assina.

    A DIFERENCA E' DE CONTEUDO, NAO DE VOLUME (2026-09-10).

    Um aviso de produto VIP carrega o produto dentro: mercado, linha e odd
    cabem no corpo da notificacao, e o corpo chega inteiro pra quem recebe. Com
    `notify_all_users` o sino virava a porta dos fundos do paywall -- o free
    nao via o pick na aba e lia a analise no sino, que e' pior do que nunca ter
    trancado.

    Quem nao assina nao fica sem nada: o teaser da propria aba continua
    mostrando jogo, liga e odd. O que nao sai daqui e' o que se paga.
    """
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(f"""
            INSERT INTO notifications (user_id, type, title, body, url, payload, dedupe_key)
            SELECT u.id, %s, %s, %s, %s, %s::jsonb, %s FROM users u
            WHERE {SQL_VIP_ATIVO}
            ON CONFLICT (user_id, dedupe_key) DO NOTHING
        """, (ntype, title[:160], body, url,
              json.dumps(payload) if payload is not None else None, dedupe_key))
        count = cur.rowcount
        conn.commit()
        return count
    finally:
        cur.close()
        conn.close()


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
            match_label = "Múltipla do Dia"
        elif pick_type == "bingo":
            match_label = "Bingo do Dia"
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
                title=f"{label}: {match_label}",
                dedupe_key=f"pick_result:{pick_type}:{pick_id}",
                body=" ".join(parts) or None,
                url="/banca",
                payload={
                    "pick_id":      pick_id,
                    "pick_type":    pick_type,
                    "result":       label,
                    "profit_units": round(profit_u, 4) if profit_u is not None else None,
                    "pnl":          round(pnl_r, 2) if pnl_r is not None else None,
                },
            )
            # O mesmo resultado no WhatsApp, pra quem ligou. Depois do sino
            # pelo motivo de sempre: o item do sino é a fonte da verdade e não
            # pode depender de a Meta responder.
            avisar_resultado_no_whatsapp(
                f["user_id"], pick_type, pick_id, label, match_label,
                " ".join(parts) or market or "",
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
            # PICK AO VIVO NAO GANHA "COMECOU" (2026-09-06, pedido do usuario).
            #
            # O aviso existe pra quem pegou um pick de PRE-JOGO horas antes e
            # precisa saber que a partida entrou em campo. No ao vivo isso e'
            # premissa: a pessoa pegou o bilhete com o jogo correndo, olhando o
            # minuto e o placar na tela. Avisar "comecou" ali e' contar uma
            # novidade que ela acabou de ver -- e o sino perde valor quando
            # entrega o que o usuario ja' sabe.
            if pick_type == "live":
                continue
            if pick_type == "multipla":
                label = "Múltipla do Dia"
            elif pick_type == "bingo":
                label = "Bingo do Dia"
            elif pick_type == "alavancagem":
                label = "Alavancagem"
            else:
                home, away = item.get("home_team"), item.get("away_team")
                label = f"{home} x {away}" if home and away else "Pick seguido"
            create_notification(
                cur, user_id, TYPE_PICK_LIVE,
                title=f"Começou: {label}",
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


def notificar_pick_live_novo(picks: list) -> int:
    """Avisa quem tem acesso de que o Motor Live publicou pick novo.

    POR QUE ISTO É BROADCAST E NÃO POR USUÁRIO

    Um pick ao vivo vale enquanto a odd vale · minutos. Não existe "abrir o
    site mais tarde e aproveitar", que é o que o sino resolve pros picks de
    pré-jogo. Então o item precisa nascer pra todo mundo no instante em que o
    motor publica, e não quando cada um passa por aqui.

    O DEDUPE É POR PICK, e é ele que permite chamar isto de dentro de um poll
    sem encher o sino: o primeiro visitante que vir o pick novo cria o item pra
    base inteira, e as próximas passadas caem no ON CONFLICT DO NOTHING.

    Devolve quantas linhas foram criadas (0 quando já existiam).
    """
    if not picks:
        return 0
    criadas = 0
    for p in picks:
        pick_id = p.get("id")
        if pick_id is None:
            continue
        home, away = p.get("home_team_name"), p.get("away_team_name")
        jogo = f"{home} x {away}" if home and away else "Jogo ao vivo"
        minuto = p.get("minute_at_creation")
        # SO' QUEM TEM O PRO (2026-09-10, estreitado em 12/09). O Ao Vivo
        # virou VIP puro, e este corpo carrega mercado, linha e odd -- era o
        # unico lugar do site que ainda entregava a analise do produto pra base
        # inteira. Com dois planos o gate subiu junto com o produto: o Ao Vivo
        # e' do Pick IA Pro, entao o aviso dele tambem e'.
        criadas += notify_pro_users(
            TYPE_LIVE_NOVO,
            title=f"Pick ao vivo: {jogo}",
            dedupe_key=f"live_novo:{pick_id}",
            body=(f"{p.get('market') or 'Mercado'} {p.get('line') or ''} @ "
                  f"{p.get('odd')}"
                  + (f" (criado aos {minuto}')" if minuto is not None else "")).strip(),
            url="/picks#ao_vivo",
            payload={"pick_id": pick_id, "pick_type": "live"},
        )
        # O MESMO AVISO NO WHATSAPP, pra quem ligou (2026-09-14).
        #
        # Depois do sino de proposito: o item do sino e' a fonte da verdade e
        # nao pode depender da Meta responder. Se o WhatsApp falhar, o aviso
        # continua existindo no site.
        avisar_ao_vivo_no_whatsapp(p)
    return criadas


# ── WhatsApp · o mesmo aviso do sino, saindo por outra porta ────────────────
#
# TRES AVISOS, E CADA UM TEM UM MOTIVO PRA EXISTIR NESTE CANAL
#
#   AO VIVO      · o sino resolve o pick de pre-jogo: a pessoa abre o site
#                  quando puder e o pick ainda esta la'. O ao vivo nao tem esse
#                  conforto -- a odd vence em minutos, e quem nao esta com a
#                  aba aberta perde. E' o aviso que mais justifica tocar o
#                  celular de alguem.
#   PICKS DO DIA · uma por dia, no fim do pipeline. Nao e' urgente, e' ancora:
#                  e' o que faz a pessoa lembrar de abrir.
#   RESULTADO    · so' pra quem SEGUIU o pick. E' o mais barato dos tres e o
#                  menos sujeito a reclamacao, porque responde uma coisa que a
#                  propria pessoa comecou.
#
# AS TRAVAS, e nenhuma e' zelo abstrato: o numero do WhatsApp e' UM so', e a
# politica da Meta pra vertical de aposta trata denuncia no nivel da CONTA.
#   1. opt-in explicito no perfil, com telefone verificado por SMS;
#   2. cada aviso tem a propria coluna de preferencia, entao desligar um nao
#      desliga os outros;
#   3. dedupe por chave, que e' o que deixa isto ser chamado de dentro de um
#      poll sem virar metralhadora;
#   4. teto diario no ao vivo, que e' o unico que dispara em rajada.

#: Teto de avisos de pick ao vivo por pessoa, por dia.
#:
#: Quatro porque o motor ao vivo publica em rajada: dia cheio de jogo produz
#: mais pick numa tarde do que qualquer um entra pra apostar. Sem teto, o
#: produto que a pessoa PEDIU vira o motivo de ela bloquear o numero -- e
#: bloqueio em massa e' exatamente o sinal que a Meta usa pra derrubar conta.
TETO_WHATSAPP_AO_VIVO_DIA = 4

#: (coluna de preferencia, teto diario) de cada tipo de aviso.
#:
#: Declarado numa tabela so' porque o SQL de quem recebe e' identico nos tres:
#: escrito a mao em cada lugar, viraria o mesmo defeito do `pick_sources` --
#: uma copia esquecendo de checar o opt-in e mandando mensagem pra quem nao
#: pediu, sem dar erro nenhum.
_AVISOS_WA = {
    "ao_vivo":      ("whatsapp_ao_vivo",      TETO_WHATSAPP_AO_VIVO_DIA),
    "picks_do_dia": ("whatsapp_picks_do_dia", 1),
    "resultado":    ("whatsapp_resultado",    8),
}


def _primeiro_nome(destino: dict) -> str:
    """O nome como ele entra no template. "tudo bem" no lugar do vazio porque
    "Ola , sua entrada" e' pior do que uma saudacao generica."""
    partes = (destino.get("name") or "").strip().split()
    return partes[0] if partes else "tudo bem"


def _destinos_whatsapp(cur, tipo: str, dedupe_key: str,
                       gate: str = "", user_id: int | None = None) -> list:
    """Quem pode receber ESTE aviso agora. Uma consulta pros tres tipos.

    `gate` e' a clausula de plano (SQL_PRO_ATIVO no ao vivo, vazio nos outros):
    o corpo do aviso de ao vivo carrega mercado, linha e odd, que e' a analise
    que a aba cobra, entao ele nao pode sair pra quem nao assina o Pro.
    """
    coluna, teto = _AVISOS_WA[tipo]
    cur.execute(f"""
        SELECT u.id, u.name, u.phone
          FROM users u
         WHERE u.active AND u.deleted_at IS NULL
           {"AND " + gate if gate else ""}
           {"AND u.id = %(user_id)s" if user_id is not None else ""}
           AND COALESCE(u.whatsapp_opt_in, FALSE)
           AND COALESCE(u.{coluna}, TRUE)
           AND COALESCE(u.phone_verified, FALSE)
           AND u.phone IS NOT NULL AND u.phone <> ''
           AND NOT EXISTS (
                 SELECT 1 FROM whatsapp_envios e
                  WHERE e.user_id = u.id AND e.dedupe_key = %(dedupe)s
               )
           AND (
                 SELECT COUNT(*) FROM whatsapp_envios e
                  WHERE e.user_id = u.id
                    AND e.tipo = %(tipo)s
                    AND e.enviado_em >= DATE_TRUNC('day', NOW())
               ) < {teto}
    """, {"dedupe": dedupe_key, "tipo": tipo, "user_id": user_id})
    return [dict(r) for r in cur.fetchall()]


def _disparar_whatsapp(tipo: str, dedupe_key: str, template: str,
                       variaveis, gate: str = "",
                       user_id: int | None = None) -> int:
    """Manda `template` pra quem pode receber. Devolve quantos sairam.

    NUNCA levanta: isto e' chamado de dentro do poll do sino e do fim do
    pipeline, e uma falha da Meta nao pode derrubar a requisicao de quem so'
    queria ver a bolinha vermelha, nem fazer o pipeline (que ja gravou os
    picks) parecer que falhou. Falha vira linha de log e nada mais.

    `variaveis` pode ser uma lista (igual pra todo mundo) ou uma funcao que
    recebe o destinatario e devolve a lista dele.
    """
    from runtime_env import side_effects_enabled
    import whatsapp as wa

    # O noprod aponta pro banco de PRODUCAO. Sem este freio, uma aba aberta no
    # staging tocaria o celular do assinante real -- e pior: gravaria o dedupe,
    # entao o aviso de verdade nao sairia depois.
    if not side_effects_enabled():
        return 0
    if not wa.whatsapp_configurado():
        return 0

    conn = get_connection()
    cur = conn.cursor()
    enviados = 0
    try:
        destinos = _destinos_whatsapp(cur, tipo, dedupe_key, gate, user_id)
        for d in destinos:
            # O INSERT vem ANTES do envio. Se a Meta demorar e a requisicao
            # cair no meio, o pior caso vira "aviso que nao saiu" em vez de
            # "mesmo aviso tres vezes" -- e o segundo e' o que faz bloquear.
            try:
                cur.execute("""
                    INSERT INTO whatsapp_envios (user_id, tipo, dedupe_key)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, dedupe_key) DO NOTHING
                """, (d["id"], tipo, dedupe_key))
                if cur.rowcount == 0:
                    continue
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning("[WA] Nao registrou envio do user %s: %s", d["id"], e)
                continue

            try:
                vars_dele = variaveis(d) if callable(variaveis) else variaveis
                wa.enviar_template(d["phone"], template, vars_dele)
                enviados += 1
            except Exception as e:
                cur.execute("""
                    UPDATE whatsapp_envios SET status = 'falhou', erro = %s
                     WHERE user_id = %s AND dedupe_key = %s
                """, (str(e)[:300], d["id"], dedupe_key))
                conn.commit()
                logger.warning("[WA] Falha no aviso %s do user %s: %s", tipo, d["id"], e)
        return enviados
    except Exception as e:
        conn.rollback()
        logger.warning("[WA] Aviso %s (%s) nao saiu: %s", tipo, dedupe_key, e)
        return 0
    finally:
        cur.close()
        conn.close()


def avisar_ao_vivo_no_whatsapp(pick: dict) -> int:
    """O pick ao vivo pra quem tem o Pro e ligou o aviso."""
    import whatsapp as wa

    pick_id = pick.get("id")
    if pick_id is None:
        return 0
    home, away = pick.get("home_team_name"), pick.get("away_team_name")
    jogo = f"{home} x {away}" if home and away else "Jogo ao vivo"
    mercado = (f"{pick.get('market') or 'Mercado'} "
               f"{pick.get('line') or ''}").strip()
    return _disparar_whatsapp(
        "ao_vivo", f"ao_vivo:{pick_id}", wa.TEMPLATE_AO_VIVO,
        # A ORDEM E' A DO TEMPLATE APROVADO NA META (ver
        # website/scripts/whatsapp/README.md). Trocar aqui sem trocar la' manda
        # o nome do jogo pro lugar da odd, e a mensagem sai errada sem dar erro
        # nenhum -- a Meta so' confere a QUANTIDADE de variaveis.
        lambda d: [_primeiro_nome(d), jogo, mercado, str(pick.get("odd"))],
        gate=SQL_PRO_ATIVO,
    )


def avisar_picks_do_dia_no_whatsapp(data_iso: str) -> int:
    """Uma mensagem por dia, no fim do pipeline · a mesma chave do sino.

    Sem gate de plano de propósito: o corpo não carrega pick nenhum, só diz que
    a leva do dia saiu, e o free tem a Dica do dia pra abrir.

    SEM CONTAGEM no texto, e isso é decisão. O número de picks que vale pra
    cada pessoa depende do plano dela (o free vê os abertos pra ele, não o
    total), e um número só pra base toda estaria errado pra metade dela · o
    tipo de erro que a pessoa confere em dois cliques e não esquece.
    """
    import whatsapp as wa

    return _disparar_whatsapp(
        "picks_do_dia", f"picks_do_dia:{data_iso}", wa.TEMPLATE_PICKS_DO_DIA,
        lambda d: [_primeiro_nome(d)],
    )


def avisar_resultado_no_whatsapp(user_id: int, pick_type: str, pick_id,
                                 rotulo: str, jogo: str, resumo: str) -> int:
    """O resultado da entrada, pra quem seguiu aquele pick.

    Por usuário e não em lote porque o resultado É por usuário: o mesmo pick
    encerra GREEN pra um e RED pra quem fez cashout no vermelho, e o valor em
    reais depende da odd declarada e da unidade de cada um.

    ANULADA NÃO SAI DAQUI. A régua do canal é "se não muda uma decisão sua, não
    é enviada", e PUSH é exatamente o caso: ninguém ganhou nem perdeu, a banca
    não mexeu. O item continua no sino, que é onde histórico mora.
    """
    import whatsapp as wa

    if rotulo == "PUSH":
        return 0
    template = (wa.TEMPLATE_RESULTADO_GREEN if rotulo in ("GREEN", "HALF-WIN")
                else wa.TEMPLATE_RESULTADO_RED)
    return _disparar_whatsapp(
        "resultado", f"resultado:{pick_type}:{pick_id}", template,
        # A ordem é a do template aprovado: nome, jogo e mercado, P&L.
        lambda d: [_primeiro_nome(d), jogo, resumo], user_id=user_id,
    )


#: Idade máxima de um pick ao vivo pra ainda valer aviso.
#:
#: A odd ao vivo vence em minutos, mas o PICK continua de pé até o apito (ver
#: routers/live_picks.py). O aviso, porém, é sobre a oportunidade: passados 25
#: minutos, mandar alguém correr atrás de um preço da criação é convidar a
#: entrar num número que a casa já não mostra. É folgado o bastante pra cobrir
#: dois ciclos do motor (8 min) mais o poll do sino (60s).
LIVE_NOVO_JANELA_MIN = 25


def sync_live_pick_notifications() -> int:
    """Cria no sino o aviso de pick ao vivo que o motor acabou de publicar.

    POR QUE ISTO NÃO PODE MORAR SÓ NO FEED (2026-08-29, pedido do usuário)

    `routers/live_picks.py::feed` já chamava `notificar_pick_live_novo`, e
    funcionava · para quem estivesse com a aba "Ao Vivo" ABERTA. O gatilho era
    a visita àquele endpoint, então quem estava na Home, na Banca ou em Meus
    Picks não criava o item e, o que é pior, não recebia: se ninguém abrisse a
    aba, o sino não tocava para ninguém. O aviso existia justamente para quem
    NÃO está olhando a aba.

    Aqui o gatilho passa a ser o poll do sino, que roda em toda página para
    todo usuário logado. Continua sem agendador e sem laço: quem passar
    primeiro cria o item para a base inteira, e as próximas passadas caem no
    dedupe por pick_id (ON CONFLICT DO NOTHING).

    O CUSTO É UM SELECT, e é por isso que ele pode entrar no caminho do poll:
    lê só `picks_live`, sem tocar na API-Football. O feed precisa do
    enriquecimento (placar, minuto corrente, estatística) porque desenha o
    card; o sino só precisa saber que o pick existe.

    Só o que está DE PÉ: pick liquidado ou já expirado não é oportunidade.
    """
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT to_regclass('public.picks_live') IS NOT NULL AS existe")
        row = cur.fetchone()
        if not row or not row["existe"]:
            return 0

        cur.execute(f"""
            SELECT id, home_team_name, away_team_name, market, line, odd,
                   minute_at_creation
            FROM picks_live
            WHERE result IS NULL
              AND status = 'ACTIVE'
              AND created_at >= NOW() - INTERVAL '{LIVE_NOVO_JANELA_MIN} minutes'
            ORDER BY created_at DESC
            LIMIT 10
        """)
        picks = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning("[NOTIF] Falha ao ler picks ao vivo pendentes: %s", e)
        return 0
    finally:
        cur.close()
        conn.close()

    return notificar_pick_live_novo(picks)


def purge_old_notifications() -> int:
    """Descarta notificações já lidas com mais de PURGE_DAYS. Chamado no fim do
    pipeline manual (routers.admin::_notificar_picks_publicados)."""
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

        # Pick ao vivo publicado agora · mesmo padrão do fechamento acima: o
        # poll do sino é o gatilho. Antes o item só nascia quando alguém abria
        # a aba Ao Vivo, e o aviso serve exatamente pra quem não está nela.
        # Conexão própria (ver a função), então roda fora desta transação e
        # nunca derruba a listagem.
        try:
            sync_live_pick_notifications()
        except Exception as e:
            logger.warning("[NOTIF] Falha no sync de pick ao vivo: %s", e)

        cur.execute("""
            SELECT id, type, title, body, url, payload, read_at, created_at,
                   -- IDADE CALCULADA NO BANCO (2026-09-10).
                   --
                   -- `created_at` e' TIMESTAMP sem fuso, gravado pelo relogio
                   -- do servidor. Mandar so' ele obriga a tela a chutar de que
                   -- fuso veio, e o chute erra por horas -- que e' exatamente
                   -- a ordem de grandeza que decide se um aviso de pick ao
                   -- vivo ainda vale. A subtracao acontece aqui, do lado de
                   -- quem gravou, e o que viaja e' um numero sem fuso nenhum.
                   GREATEST(0, EXTRACT(EPOCH FROM (NOW() - created_at)))::int
                       AS idade_seg
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
                "idade_seg":  d.get("idade_seg"),
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


# ── Avisos no WhatsApp · a tela onde o usuário autoriza ──────────────────────
#
# A coluna `whatsapp_opt_in` existe desde 08/2026 e nunca teve interruptor:
# era um campo que ninguém podia ligar, e por isso a audiência de WhatsApp no
# /admin era zero permanente. Estas duas rotas são o que faltava.
#
# O TELEFONE VERIFICADO É PRÉ-REQUISITO, e a rota recusa sem ele. Telefone não
# verificado pode ser o do vizinho · foi por isso que o SMS entrou quando o CPF
# saiu do cadastro (18/08/2026), e mandar aviso pro número errado é denúncia na
# certa. A denúncia custa o número inteiro, não uma mensagem.

class PrefsWhatsApp(BaseModel):
    opt_in: bool
    ao_vivo: bool = True
    picks_do_dia: bool = True
    resultado: bool = True


@router.get("/whatsapp")
def get_prefs_whatsapp(current_user: dict = Depends(get_current_user)):
    """O que a pessoa escolheu, mais o que o ambiente consegue entregar.

    `disponivel` vem junto de propósito: sem provedor configurado a tela tem
    que dizer isso, em vez de aceitar o toggle e prometer um aviso que nunca
    vai sair. Mesmo raciocínio do `sms_configurado`.
    """
    import whatsapp as wa

    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT phone, COALESCE(phone_verified, FALSE) AS phone_verified,
                   COALESCE(whatsapp_opt_in, FALSE)      AS opt_in,
                   whatsapp_opt_in_at,
                   COALESCE(whatsapp_ao_vivo, TRUE)      AS ao_vivo,
                   COALESCE(whatsapp_picks_do_dia, TRUE) AS picks_do_dia,
                   COALESCE(whatsapp_resultado, TRUE)    AS resultado
              FROM users WHERE id = %s
        """, (current_user["id"],))
        u = dict(cur.fetchone() or {})
        # O telefone volta MASCARADO: a tela só precisa confirmar qual número
        # é, e o corpo da resposta acaba em log de proxy com mais frequência do
        # que se imagina.
        tel = (u.get("phone") or "")
        return {
            "disponivel":     wa.whatsapp_configurado(),
            "telefone":       (f"{tel[:-4].replace(tel[3:-4], '*' * len(tel[3:-4]))}{tel[-4:]}"
                               if len(tel) > 7 else ""),
            "phone_verified": bool(u.get("phone_verified")),
            "opt_in":         bool(u.get("opt_in")),
            "opt_in_at":      u.get("whatsapp_opt_in_at"),
            "ao_vivo":        bool(u.get("ao_vivo")),
            "picks_do_dia":   bool(u.get("picks_do_dia")),
            "resultado":      bool(u.get("resultado")),
            # Só quem tem o Pro recebe aviso de ao vivo, porque só ele vê o
            # produto. Dizer isso na tela evita o toggle ligado que não toca.
            "ao_vivo_no_plano": bool(current_user.get("plan") in ("admin", "trial")
                                     or (current_user.get("plan") == "vip"
                                         and (current_user.get("plan_tier") or "pro") == "pro")),
            "teto_dia":       TETO_WHATSAPP_AO_VIVO_DIA,
        }
    finally:
        cur.close()
        conn.close()


@router.put("/whatsapp")
def put_prefs_whatsapp(body: PrefsWhatsApp,
                       current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(phone_verified, FALSE) AS ok, phone FROM users WHERE id = %s",
                    (current_user["id"],))
        row = dict(cur.fetchone() or {})
        if body.opt_in and not (row.get("ok") and row.get("phone")):
            raise HTTPException(
                400,
                "Confirme seu telefone antes de ligar os avisos no WhatsApp.",
            )
        # `opt_in_at` só é carimbado quando LIGA, e nunca é apagado ao
        # desligar: é a prova de consentimento, e ela precisa sobreviver ao
        # desligamento pra responder "quando essa pessoa autorizou".
        cur.execute("""
            UPDATE users
               SET whatsapp_opt_in = %s,
                   whatsapp_opt_in_at = CASE
                       WHEN %s AND NOT COALESCE(whatsapp_opt_in, FALSE) THEN NOW()
                       ELSE whatsapp_opt_in_at END,
                   whatsapp_ao_vivo = %s,
                   whatsapp_picks_do_dia = %s,
                   whatsapp_resultado = %s
             WHERE id = %s
        """, (body.opt_in, body.opt_in, body.ao_vivo, body.picks_do_dia,
              body.resultado, current_user["id"]))
        conn.commit()
        return {"ok": True, "opt_in": body.opt_in}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
