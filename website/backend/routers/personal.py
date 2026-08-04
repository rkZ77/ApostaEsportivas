"""Coisas do usuário: favoritos, alertas e conquistas.

Os três moram no mesmo router porque compartilham a mesma forma (tabela pequena
com user_id + chave, sempre lida inteira pela tela) e porque a tela de perfil
mostra os três juntos. Separar em três arquivos daria três imports pro mesmo
lugar sem ganhar nada.

Regra de segurança que vale pros três: TODA query filtra por user_id vindo do
token, nunca de parâmetro. Sem isso um id na URL vira leitura da conta alheia.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/personal", tags=["personal"])

FAVORITE_KINDS = {"league", "team", "market", "pick"}

# Teto por usuário. Não é regra de negócio, é freio: sem isso um script guarda
# favorito em laço e a listagem do perfil vira uma resposta de megabytes.
MAX_FAVORITES_PER_KIND = 100


# ─────────────────────────── Favoritos ────────────────────────────────


class FavoriteBody(BaseModel):
    kind: str
    ref_id: str = Field(min_length=1, max_length=60)
    label: str | None = Field(default=None, max_length=120)


@router.get("/favorites")
def list_favorites(
    kind: str | None = Query(None, description="league|team|market|pick"),
    current_user: dict = Depends(get_current_user),
):
    """Favoritos do usuário, opcionalmente de um tipo só."""
    if kind and kind not in FAVORITE_KINDS:
        raise HTTPException(400, "Tipo de favorito inválido")

    conn = get_connection()
    cur = conn.cursor()
    try:
        sql = """
            SELECT id, kind, ref_id, label, created_at
              FROM user_favorites
             WHERE user_id = %s
        """
        params: list = [current_user["id"]]
        if kind:
            sql += " AND kind = %s"
            params.append(kind)
        sql += " ORDER BY created_at DESC"

        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return [
        {
            "id": r["id"],
            "kind": r["kind"],
            "ref_id": r["ref_id"],
            "label": r["label"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.post("/favorites")
def add_favorite(body: FavoriteBody, current_user: dict = Depends(get_current_user)):
    """Marca um favorito. Repetir a chamada não duplica nem dá erro."""
    if body.kind not in FAVORITE_KINDS:
        raise HTTPException(400, "Tipo de favorito inválido")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) AS n FROM user_favorites WHERE user_id = %s AND kind = %s",
            (current_user["id"], body.kind),
        )
        if cur.fetchone()["n"] >= MAX_FAVORITES_PER_KIND:
            raise HTTPException(400, f"Limite de {MAX_FAVORITES_PER_KIND} favoritos por tipo atingido")

        # ON CONFLICT em vez de checar antes: o botão de favoritar é clicável
        # duas vezes em sequência e select-then-insert perde essa corrida.
        cur.execute(
            """
            INSERT INTO user_favorites (user_id, kind, ref_id, label)
                 VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, kind, ref_id)
              DO UPDATE SET label = COALESCE(EXCLUDED.label, user_favorites.label)
              RETURNING id, kind, ref_id, label
            """,
            (current_user["id"], body.kind, body.ref_id, body.label),
        )
        row = cur.fetchone()
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error("[FAVORITES] erro ao salvar: %s", e)
        raise HTTPException(500, "Não foi possível salvar o favorito")
    finally:
        cur.close()
        conn.close()

    return {"id": row["id"], "kind": row["kind"], "ref_id": row["ref_id"], "label": row["label"]}


@router.delete("/favorites/{kind}/{ref_id}")
def remove_favorite(kind: str, ref_id: str, current_user: dict = Depends(get_current_user)):
    """Desmarca. Idempotente: remover o que não existe devolve ok."""
    if kind not in FAVORITE_KINDS:
        raise HTTPException(400, "Tipo de favorito inválido")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM user_favorites WHERE user_id = %s AND kind = %s AND ref_id = %s",
            (current_user["id"], kind, ref_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"ok": True}


# ──────────────────────────── Alertas ─────────────────────────────────

ALERT_KINDS = {
    "new_value_bet": "Nova value bet publicada",
    "confidence": "Pick acima da confiança que eu escolher",
    "favorite_team": "Pick de um time que eu favoritei",
}


class AlertBody(BaseModel):
    kind: str
    enabled: bool = True
    # 0..1, mesma escala de `confidence` no banco de picks
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    # em pontos percentuais, mesma escala do campo `ev`
    min_ev: float | None = Field(default=None, ge=-100, le=100)


@router.get("/alerts")
def list_alerts(current_user: dict = Depends(get_current_user)):
    """Alertas do usuário, já preenchidos com os tipos que ele ainda não configurou.

    A tela precisa listar todos os tipos possíveis (com um botão de ligar), não
    só os que já existem no banco. Montar isso aqui evita o front ter que
    conhecer o catálogo por conta própria e sair do ar de sincronia.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT kind, enabled, min_confidence, min_ev
              FROM user_alerts
             WHERE user_id = %s
            """,
            (current_user["id"],),
        )
        saved = {r["kind"]: r for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()

    out = []
    for kind, label in ALERT_KINDS.items():
        r = saved.get(kind)
        out.append({
            "kind": kind,
            "label": label,
            "enabled": bool(r["enabled"]) if r else False,
            "min_confidence": float(r["min_confidence"]) if r and r["min_confidence"] is not None else None,
            "min_ev": float(r["min_ev"]) if r and r["min_ev"] is not None else None,
            "configured": r is not None,
        })
    return out


@router.put("/alerts")
def upsert_alert(body: AlertBody, current_user: dict = Depends(get_current_user)):
    """Liga, desliga ou ajusta o limiar de um alerta."""
    if body.kind not in ALERT_KINDS:
        raise HTTPException(400, "Tipo de alerta inválido")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO user_alerts (user_id, kind, enabled, min_confidence, min_ev)
                 VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, kind)
              DO UPDATE SET enabled        = EXCLUDED.enabled,
                            min_confidence = EXCLUDED.min_confidence,
                            min_ev         = EXCLUDED.min_ev,
                            updated_at     = NOW()
              RETURNING kind, enabled, min_confidence, min_ev
            """,
            (current_user["id"], body.kind, body.enabled, body.min_confidence, body.min_ev),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("[ALERTS] erro ao salvar: %s", e)
        raise HTTPException(500, "Não foi possível salvar o alerta")
    finally:
        cur.close()
        conn.close()

    return {
        "kind": row["kind"],
        "label": ALERT_KINDS[row["kind"]],
        "enabled": bool(row["enabled"]),
        "min_confidence": float(row["min_confidence"]) if row["min_confidence"] is not None else None,
        "min_ev": float(row["min_ev"]) if row["min_ev"] is not None else None,
        "configured": True,
    }


# ─────────────────────────── Conquistas ───────────────────────────────

# Catálogo no código, não no banco: é copy de produto. `goal` é o alvo e
# `metric` diz de onde sai o número atual (ver _achievement_progress).
ACHIEVEMENTS = [
    {"code": "first_follow",   "title": "Primeira aposta registrada", "desc": "Registre um pick na sua banca.",                 "goal": 1,   "metric": "follows"},
    {"code": "ten_follows",    "title": "Dez apostas",                "desc": "Registre 10 picks na sua banca.",                "goal": 10,  "metric": "follows"},
    {"code": "first_green",    "title": "Primeiro green",             "desc": "Acerte o seu primeiro pick registrado.",         "goal": 1,   "metric": "greens"},
    {"code": "ten_greens",     "title": "Dez greens",                 "desc": "Acumule 10 greens na sua banca.",                "goal": 10,  "metric": "greens"},
    {"code": "banca_set",      "title": "Banca configurada",          "desc": "Defina banca inicial e valor da unidade.",       "goal": 1,   "metric": "banca"},
    {"code": "week_active",    "title": "Uma semana na plataforma",   "desc": "Complete 7 dias desde o cadastro.",              "goal": 7,   "metric": "days"},
    {"code": "month_active",   "title": "Um mês na plataforma",       "desc": "Complete 30 dias desde o cadastro.",             "goal": 30,  "metric": "days"},
]


# Onde mora o resultado de cada tipo de pick. `user_followed_picks` guarda só a
# referência (pick_id + pick_type); o GREEN/RED fica na tabela do pick.
PICK_TABLES = {
    "vip":         "picks_vip",
    "free":        "picks_free",
    "multipla":    "picks_multiplas",
    "alavancagem": "picks_alavancagem",
    "faltas":      "picks_faltas",
    "goleiros":    "picks_goleiros",
}


def _achievement_progress(cur, user_id: int) -> dict[str, int]:
    """Número atual de cada métrica. Contagens simples, uma por métrica."""
    progress = {"follows": 0, "greens": 0, "banca": 0, "days": 0}

    cur.execute(
        "SELECT COUNT(*) AS n FROM user_followed_picks WHERE user_id = %s",
        (user_id,),
    )
    progress["follows"] = cur.fetchone()["n"] or 0

    # Greens: um COUNT por tabela de pick, somando.
    #
    # Poderia ser um UNION ALL só, mas aí uma tabela que ainda não exista em
    # algum ambiente (faltas e goleiros são recentes) derrubaria a query
    # inteira e a tela de conquistas junto. Em laço, uma tabela ausente custa
    # só aquela métrica.
    greens = 0
    for pick_type, table in PICK_TABLES.items():
        try:
            cur.execute(
                f"""
                SELECT COUNT(*) AS n
                  FROM user_followed_picks uf
                  JOIN {table} p ON p.id = uf.pick_id
                 WHERE uf.user_id = %s AND uf.pick_type = %s AND p.result = 'GREEN'
                """,
                (user_id, pick_type),
            )
            greens += cur.fetchone()["n"] or 0
        except Exception as e:
            # savepoint implícito perdido: a transação fica abortada e as
            # queries seguintes falhariam em cascata sem este rollback.
            cur.connection.rollback()
            logger.warning("[ACHIEVEMENTS] pulei %s: %s", table, e)
    progress["greens"] = greens

    cur.execute(
        "SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s",
        (user_id,),
    )
    b = cur.fetchone()
    progress["banca"] = 1 if b and b["bankroll_start"] and b["unit_value"] else 0

    cur.execute("SELECT created_at FROM users WHERE id = %s", (user_id,))
    u = cur.fetchone()
    if u and u["created_at"]:
        created = u["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        progress["days"] = max(0, (datetime.now(timezone.utc) - created).days)

    return progress


@router.get("/achievements")
def list_achievements(current_user: dict = Depends(get_current_user)):
    """Conquistas com progresso, gravando as que acabaram de ser atingidas.

    O desbloqueio é calculado na leitura em vez de por gatilho: são contagens
    baratas e assim uma conquista nova no catálogo já vale para quem cumpriu o
    requisito antes de ela existir, sem script de retroação.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        progress = _achievement_progress(cur, current_user["id"])

        cur.execute(
            "SELECT code, unlocked_at FROM user_achievements WHERE user_id = %s",
            (current_user["id"],),
        )
        unlocked = {r["code"]: r["unlocked_at"] for r in cur.fetchall()}

        newly = [
            a["code"] for a in ACHIEVEMENTS
            if a["code"] not in unlocked and progress.get(a["metric"], 0) >= a["goal"]
        ]
        if newly:
            cur.executemany(
                """
                INSERT INTO user_achievements (user_id, code) VALUES (%s, %s)
                ON CONFLICT (user_id, code) DO NOTHING
                """,
                [(current_user["id"], code) for code in newly],
            )
            conn.commit()
            now = datetime.now(timezone.utc)
            for code in newly:
                unlocked[code] = now
    except Exception as e:
        conn.rollback()
        logger.error("[ACHIEVEMENTS] erro: %s", e)
        raise HTTPException(500, "Não foi possível carregar as conquistas")
    finally:
        cur.close()
        conn.close()

    out = []
    for a in ACHIEVEMENTS:
        current = progress.get(a["metric"], 0)
        at = unlocked.get(a["code"])
        out.append({
            "code": a["code"],
            "title": a["title"],
            "desc": a["desc"],
            "goal": a["goal"],
            "current": min(current, a["goal"]),
            "unlocked": a["code"] in unlocked,
            "unlocked_at": at.isoformat() if hasattr(at, "isoformat") else None,
            "just_unlocked": a["code"] in newly,
        })

    return {
        "total": len(ACHIEVEMENTS),
        "unlocked": sum(1 for a in out if a["unlocked"]),
        "achievements": out,
    }
