import time
import logging
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import psycopg2.extras
from database import get_connection
from auth_utils import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/social", tags=["social"])

VALID_REACTIONS = {"fire", "money", "like", "doubt"}
VALID_PICK_TYPES = {"vip", "free", "multiplas", "alavancagem"}

# Rate limit: máx 5 comentários + 5 msgs de chat por usuário por 60s
_comment_rate: dict[str, list[float]] = defaultdict(list)
_COMMENT_LIMIT  = 5
_COMMENT_WINDOW = 60


def _check_comment_rate(user_id: int) -> None:
    uid = str(user_id)
    now = time.time()
    _comment_rate[uid] = [t for t in _comment_rate[uid] if now - t < _COMMENT_WINDOW]
    if len(_comment_rate[uid]) >= _COMMENT_LIMIT:
        raise HTTPException(429, f"Limite de {_COMMENT_LIMIT} mensagens por minuto atingido.")
    _comment_rate[uid].append(now)


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn():
    return get_connection()


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ── models ────────────────────────────────────────────────────────────────────

class ReactBody(BaseModel):
    reaction: str

class CommentBody(BaseModel):
    content: str

class ChatBody(BaseModel):
    content: str


# ── chat ao vivo (deve vir antes das rotas dinâmicas /{pick_type}/{pick_id}) ──

@router.get("/chat/messages")
def get_chat(after_id: int = 0, limit: int = 60, current_user: dict = Depends(get_current_user)):
    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("""
            SELECT id, user_id, user_name, user_plan, user_avatar_url, content, created_at
            FROM chat_messages
            WHERE id > %s
              AND deleted_at IS NULL
              AND created_at >= NOW() - INTERVAL '48 hours'
            ORDER BY id ASC
            LIMIT %s
        """, (after_id, min(limit, 100)))
        messages = [dict(m) for m in cur.fetchall()]
        return messages
    finally:
        cur.close(); conn.close()


@router.post("/chat/messages")
def post_chat(body: ChatBody, current_user: dict = Depends(get_current_user)):
    _check_comment_rate(current_user["id"])
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "Mensagem vazia")
    if len(content) > 500:
        raise HTTPException(400, "Máximo 500 caracteres")

    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("""
            INSERT INTO chat_messages
              (user_id, user_name, user_plan, user_avatar_url, content)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, user_id, user_name, user_plan, user_avatar_url, content, created_at
        """, (
            current_user["id"], current_user.get("name", ""),
            current_user.get("plan", "free"), current_user.get("avatar_url"),
            content,
        ))
        msg = dict(cur.fetchone())
        conn.commit()
        return msg
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        import logging; logging.getLogger(__name__).error("social error: %s", e, exc_info=True)
        raise HTTPException(500, "Erro interno. Tente novamente.")
    finally:
        cur.close(); conn.close()


@router.delete("/chat/{msg_id}")
def delete_chat(msg_id: int, current_user: dict = Depends(get_current_user)):
    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("SELECT user_id FROM chat_messages WHERE id = %s AND deleted_at IS NULL", (msg_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Mensagem não encontrada")

        is_admin = current_user.get("plan") == "admin"
        is_owner = row["user_id"] == current_user.get("id")
        if not is_admin and not is_owner:
            raise HTTPException(403, "Sem permissão para apagar esta mensagem")

        # Soft delete — mantém no banco, oculta para todos
        cur.execute("UPDATE chat_messages SET deleted_at = NOW() WHERE id = %s", (msg_id,))
        conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        import logging; logging.getLogger(__name__).error("social error: %s", e, exc_info=True)
        raise HTTPException(500, "Erro interno. Tente novamente.")
    finally:
        cur.close(); conn.close()


# ── reactions + comentários ───────────────────────────────────────────────────

@router.get("/{pick_type}/{pick_id}")
def get_social(pick_type: str, pick_id: int, current_user: dict = Depends(get_current_user)):
    if pick_type not in VALID_PICK_TYPES:
        raise HTTPException(400, "Tipo inválido")

    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("""
            SELECT reaction, COUNT(*) AS count
            FROM pick_reactions
            WHERE pick_id = %s AND pick_type = %s
            GROUP BY reaction
        """, (pick_id, pick_type))
        reactions = {r["reaction"]: int(r["count"]) for r in cur.fetchall()}

        cur.execute("""
            SELECT reaction FROM pick_reactions
            WHERE user_id = %s AND pick_id = %s AND pick_type = %s
        """, (current_user["id"], pick_id, pick_type))
        user_reactions = [r["reaction"] for r in cur.fetchall()]

        cur.execute("""
            SELECT id, user_id, user_name, user_plan, user_avatar_url, content, created_at
            FROM pick_comments
            WHERE pick_id = %s AND pick_type = %s
            ORDER BY created_at ASC
            LIMIT 200
        """, (pick_id, pick_type))
        comments = [dict(c) for c in cur.fetchall()]

        return {"reactions": reactions, "user_reactions": user_reactions, "comments": comments}
    finally:
        cur.close(); conn.close()


@router.post("/{pick_type}/{pick_id}/react")
def toggle_reaction(pick_type: str, pick_id: int, body: ReactBody,
                    current_user: dict = Depends(get_current_user)):
    if pick_type not in VALID_PICK_TYPES:
        raise HTTPException(400, "Tipo inválido")
    if body.reaction not in VALID_REACTIONS:
        raise HTTPException(400, "Reação inválida")

    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("""
            SELECT id FROM pick_reactions
            WHERE user_id = %s AND pick_id = %s AND pick_type = %s AND reaction = %s
        """, (current_user["id"], pick_id, pick_type, body.reaction))
        existing = cur.fetchone()

        if existing:
            cur.execute("DELETE FROM pick_reactions WHERE id = %s", (existing["id"],))
            active = False
        else:
            cur.execute("""
                INSERT INTO pick_reactions (user_id, pick_id, pick_type, reaction)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, pick_id, pick_type, reaction) DO NOTHING
            """, (current_user["id"], pick_id, pick_type, body.reaction))
            active = True

        conn.commit()

        cur.execute("""
            SELECT COUNT(*) AS count FROM pick_reactions
            WHERE pick_id = %s AND pick_type = %s AND reaction = %s
        """, (pick_id, pick_type, body.reaction))
        count = int(cur.fetchone()["count"])

        return {"reaction": body.reaction, "active": active, "count": count}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        import logging; logging.getLogger(__name__).error("social error: %s", e, exc_info=True)
        raise HTTPException(500, "Erro interno. Tente novamente.")
    finally:
        cur.close(); conn.close()


@router.post("/{pick_type}/{pick_id}/comment")
def add_comment(pick_type: str, pick_id: int, body: CommentBody,
                current_user: dict = Depends(get_current_user)):
    if pick_type not in VALID_PICK_TYPES:
        raise HTTPException(400, "Tipo inválido")
    _check_comment_rate(current_user["id"])

    content = body.content.strip()
    if not content:
        raise HTTPException(400, "Comentário vazio")
    if len(content) > 300:
        raise HTTPException(400, "Máximo 300 caracteres")

    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("""
            INSERT INTO pick_comments
              (user_id, user_name, user_plan, user_avatar_url, pick_id, pick_type, content)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, user_name, user_plan, user_avatar_url, content, created_at
        """, (
            current_user["id"], current_user["name"],
            current_user.get("plan", "free"), current_user.get("avatar_url"),
            pick_id, pick_type, content,
        ))
        comment = dict(cur.fetchone())
        conn.commit()
        return comment
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        import logging; logging.getLogger(__name__).error("social error: %s", e, exc_info=True)
        raise HTTPException(500, "Erro interno. Tente novamente.")
    finally:
        cur.close(); conn.close()


@router.delete("/comment/{comment_id}")
def delete_comment(comment_id: int, current_user: dict = Depends(get_current_user)):
    conn = _conn(); cur = _cur(conn)
    try:
        cur.execute("SELECT user_id FROM pick_comments WHERE id = %s", (comment_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Comentário não encontrado")
        if row["user_id"] != current_user.get("id") and current_user.get("plan") != "admin":
            raise HTTPException(403, "Sem permissão")

        cur.execute("DELETE FROM pick_comments WHERE id = %s", (comment_id,))
        conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        import logging; logging.getLogger(__name__).error("social error: %s", e, exc_info=True)
        raise HTTPException(500, "Erro interno. Tente novamente.")
    finally:
        cur.close(); conn.close()


