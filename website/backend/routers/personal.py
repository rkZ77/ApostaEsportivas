"""Coisas do usuário: alertas e conquistas.

Favoritos moravam aqui e saíram em 2026-08-07, por decisão do usuário. O
coração aparecia no card de pick, no cabeçalho das seções de mercado e na
agenda, e servia de filtro em dois lugares · muita superfície para uma
preferência que ninguém usava. A TABELA `user_favorites` continua no banco,
sem DROP: coluna e tabela paradas não custam nada, e apagar não tem volta.

Os dois que ficaram moram no mesmo router porque compartilham a mesma forma
(tabela pequena com user_id + chave, sempre lida inteira pela tela) e porque a
tela de perfil mostra os dois juntos.

Regra de segurança que vale pros dois: TODA query filtra por user_id vindo do
token, nunca de parâmetro. Sem isso um id na URL vira leitura da conta alheia.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/personal", tags=["personal"])

# ──────────────────────────── Alertas ─────────────────────────────────

ALERT_KINDS = {
    "new_value_bet": "Nova value bet publicada",
    "confidence": "Pick acima da confiança que eu escolher",
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
    # Player Stats (27/08). Sem esta linha o GREEN de um pick de jogador nao
    # conta pra conquista · o laco abaixo so' visita o que esta' neste mapa.
    "player_stats": "picks_player_stats",
    "boost":        "picks_boost",
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


# ──────────────────────── Tours guiados ───────────────────────────────
#
# Onde mora o "esta pessoa ja' viu este tour?". No BANCO, e nao no localStorage,
# porque a pergunta e' sobre a CONTA e nao sobre o navegador: sair e entrar de
# novo, trocar de aparelho ou abrir numa aba anonima nao pode fazer o tour
# reaparecer pra quem ja' passou por ele.
#
# `step` guarda o passo em aberto. Sem ele, recarregar a pagina no meio do tour
# recomecava do primeiro passo.

# Teto do roteiro de boas-vindas: 7 passos fixos + o de confirmar e-mail, que
# so' entra pra quem ainda tem os 2 dias de VIP esperando. O total que a TELA
# mostra varia entre 7 e 8, entao o que o backend valida e' o maximo.
TUTORIAL_TOTAL_STEPS = 8
# Roteiro do VIP: o que a assinatura abriu.
#
# 8 desde 2026-08-28. Eram 6 ate' o passo de "Mercados" (aba que deixou de
# existir) virar tres: picks de jogador, Pick Boost e Picks Ao Vivo.
#
# O numero vive nos DOIS lados e ha' teste comparando os arquivos, e a
# duplicacao e' deliberada: o backend valida o `step` que a tela manda, entao
# ele precisa saber o teto sem baixar o roteiro (que e' TSX). Sem o teste, subir
# um lado e esquecer o outro faria o backend recusar o ultimo passo do tour --
# e o tour reabriria do zero na visita seguinte, que foi um bug real aqui.
VIP_TOUR_TOTAL_STEPS = 8

TUTORIAL_STATUS = ("pending", "completed", "skipped")

# Os roteiros, e onde cada um guarda o estado.
#
# Duas colunas por roteiro na propria `users`, e nao uma tabela `user_tours`.
# Com DOIS tours a tabela seria mais cerimonia do que ajuda: uma linha por
# usuario por tour, um JOIN a mais em toda leitura, e uma migration movendo
# estado que ja esta em producao. Aparecendo um terceiro roteiro a conta vira,
# e aí este dicionario e' o unico lugar que precisa mudar.
#
# Os nomes espelham TOURS em components/onboarding/constantes.ts. Ha teste
# travando os dois lados.
TOURS: dict[str, dict] = {
    "boas-vindas": {
        "status": "tutorial_status",
        "step":   "tutorial_step",
        "fim":    "tutorial_finished_at",
        "total":  TUTORIAL_TOTAL_STEPS,
    },
    "vip": {
        "status": "vip_tour_status",
        "step":   "vip_tour_step",
        "fim":    "vip_tour_finished_at",
        "total":  VIP_TOUR_TOTAL_STEPS,
    },
}

# O que responder quando o banco nao coopera. Ver a docstring de get_tutorial.
TOUR_PADRAO = "boas-vindas"


class TutorialBody(BaseModel):
    status: str | None = None
    # `le` e' o maior teto entre os roteiros; o clamp por roteiro acontece
    # depois, ja com o `tour` em maos.
    step: int | None = Field(default=None, ge=0, le=max(t["total"] for t in TOURS.values()))


def _colunas_do_tour(tour: str) -> dict:
    cfg = TOURS.get(tour)
    if not cfg:
        raise HTTPException(400, "Tour desconhecido")
    return cfg


def _tutorial_payload(status: str, step: int, total: int, tour: str) -> dict:
    return {
        "tour": tour,
        "status": status,
        "step": max(0, min(step, total - 1)),
        "total_steps": total,
        # Quem decide abrir sozinho e' o servidor, nao a tela. Assim a regra
        # ("so' quem nunca viu") vive num lugar so'.
        "should_start": status == "pending",
    }


@router.get("/tutorial")
def get_tutorial(
    # Escalar com default simples, e nao `Query(...)`: o FastAPI infere query
    # param do mesmo jeito, e assim a funcao continua CHAMAVEL direto pelos
    # testes. Com `Query(...)` no default, quem chama fora do framework recebe
    # o objeto Query no lugar da string e cai no 400 de tour desconhecido.
    tour: str = TOUR_PADRAO,
    current_user: dict = Depends(get_current_user),
):
    """Estado de um tour na conta. `tour` e' "boas-vindas" ou "vip".

    Falha para o lado de NAO mostrar. Se as colunas ainda nao existirem no
    banco (deploy novo antes da migration de startup rodar, que ja aconteceu
    aqui), responder 500 quebraria a tela e responder 'pending' abriria o tour
    na cara da base inteira. 'completed' e' o unico erro barato dos tres.
    """
    cfg = _colunas_do_tour(tour)

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Nomes de coluna vem do dicionario acima, nunca da query string: o
        # `tour` ja foi validado em _colunas_do_tour e o que entra no SQL sao
        # constantes deste modulo.
        cur.execute(
            f"SELECT {cfg['status']} AS status, {cfg['step']} AS step FROM users WHERE id = %s",
            (current_user["id"],),
        )
        row = cur.fetchone()
    except Exception as e:
        conn.rollback()
        logger.warning("[TOUR] leitura indisponivel (%s, user %s): %s", tour, current_user["id"], e)
        return _tutorial_payload("completed", 0, cfg["total"], tour)
    finally:
        cur.close()
        conn.close()

    if not row:
        raise HTTPException(404, "Usuário não encontrado")

    status = row["status"] or "pending"
    if status not in TUTORIAL_STATUS:
        status = "completed"
    return _tutorial_payload(status, int(row["step"] or 0), cfg["total"], tour)


@router.put("/tutorial")
def save_tutorial(
    body: TutorialBody,
    tour: str = TOUR_PADRAO,  # ver o comentario em get_tutorial
    current_user: dict = Depends(get_current_user),
):
    """Avanca o passo, conclui ou pula.

    Um PUT so' pros tres casos porque eles gravam nas mesmas duas colunas e a
    tela chama sempre no mesmo momento (mudou de passo). `status=None` e'
    "so' guardei onde parei" -- o passo anda sem tirar a conta de 'pending'.
    """
    cfg = _colunas_do_tour(tour)

    if body.status is not None and body.status not in TUTORIAL_STATUS:
        raise HTTPException(400, "Estado de tutorial inválido")
    if body.status is None and body.step is None:
        raise HTTPException(400, "Nada para salvar")

    campos, valores = [], []
    if body.status is not None:
        campos.append(f"{cfg['status']} = %s")
        valores.append(body.status)
        # Carimba o fim so' quando ele acontece, e so' na primeira vez: reabrir
        # o tour pelo menu e concluir de novo nao deve reescrever a data em que
        # a pessoa aprendeu a usar o site.
        if body.status in ("completed", "skipped"):
            campos.append(f"{cfg['fim']} = COALESCE({cfg['fim']}, NOW())")
    if body.step is not None:
        campos.append(f"{cfg['step']} = %s")
        valores.append(min(body.step, cfg["total"] - 1))

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"UPDATE users SET {', '.join(campos)} WHERE id = %s "
            f"RETURNING {cfg['status']} AS status, {cfg['step']} AS step",
            (*valores, current_user["id"]),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("[TOUR] erro ao salvar (%s, user %s): %s", tour, current_user["id"], e)
        raise HTTPException(500, "Não foi possível salvar o tutorial")
    finally:
        cur.close()
        conn.close()

    if not row:
        raise HTTPException(404, "Usuário não encontrado")

    return _tutorial_payload(row["status"] or "pending", int(row["step"] or 0), cfg["total"], tour)
