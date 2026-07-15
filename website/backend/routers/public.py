import logging
import traceback
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])

LOCAL_LOGOS: dict[int, str] = {
    1: "/logo-copa-mundo.png",
}


@router.get("/leagues")
def public_leagues():
    """Ligas ativas cadastradas no sistema — sem autenticação."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(
            "SELECT league_id, name, season FROM leagues ORDER BY league_id"
        )
        rows = cur.fetchall()
        return [
            {
                "league_id": r["league_id"],
                "name":      r["name"],
                "season":    r["season"],
                "logo_url":  LOCAL_LOGOS.get(
                    r["league_id"],
                    # Proxy do backend (main.py:/api/proxy/league) baixa e cacheia em disco --
                    # hotlink direto pro CDN da API-Sports no browser costuma cair no fallback
                    # genérico (hotlink protection/rate limit do lado deles).
                    f"/api/proxy/league/{r['league_id']}.png"
                ),
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


def _q(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as e:
        logger.error("[PUBLIC] _q error: %s", e)
        traceback.print_exc()
        cur.connection.rollback()
        return []


def _q1(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except Exception as e:
        logger.error("[PUBLIC] _q1 error: %s", e)
        traceback.print_exc()
        cur.connection.rollback()
        return None


def _sub_vip(date_cond: str) -> str:
    return f"""
        SELECT match_date,
               home_team_name, away_team_name,
               home_team_id,   away_team_id,
               market, line, odd,
               result, profit,
               1::numeric AS stake,
               'vip' AS source
        FROM picks_vip
        WHERE result IS NOT NULL {date_cond}
    """

def _sub_free(date_cond: str) -> str:
    return f"""
        SELECT pf.match_date,
               pf.home_team AS home_team_name, pf.away_team AS away_team_name,
               COALESCE(pf.home_team_id, f.home_team_id,
                   (SELECT fx.home_team_id FROM fixtures fx
                    WHERE fx.home_team = pf.home_team AND fx.home_team_id IS NOT NULL LIMIT 1)
               ) AS home_team_id,
               COALESCE(pf.away_team_id, f.away_team_id,
                   (SELECT fx.away_team_id FROM fixtures fx
                    WHERE fx.away_team = pf.away_team AND fx.away_team_id IS NOT NULL LIMIT 1)
               ) AS away_team_id,
               pf.market, pf.line, pf.odd,
               pf.result, pf.profit,
               1 AS stake,
               'free' AS source
        FROM picks_free pf
        LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
        WHERE pf.result IS NOT NULL {date_cond}
    """

def _sub_mult(date_cond: str) -> str:
    return f"""
        SELECT match_date,
               CONCAT('Múltipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' sel.') AS home_team_name,
               NULL AS away_team_name,
               NULL::INTEGER AS home_team_id, NULL::INTEGER AS away_team_id,
               'Múltipla' AS market, NULL AS line, total_odd AS odd,
               result, profit,
               1::numeric AS stake,
               'multiplas' AS source
        FROM picks_multiplas
        WHERE result IS NOT NULL {date_cond}
    """

def _sub_alav(date_cond: str) -> str:
    return f"""
        SELECT match_date,
               home_team_1 AS home_team_name, away_team_1 AS away_team_name,
               NULL::INTEGER AS home_team_id, NULL::INTEGER AS away_team_id,
               market_1 AS market, line_1 AS line, odd_combined AS odd,
               result, profit,
               1::numeric AS stake,
               'alavancagem' AS source
        FROM picks_alavancagem
        WHERE result IS NOT NULL {date_cond}
    """

_SUB_BUILDERS = {
    "vip":        _sub_vip,
    "free":       _sub_free,
    "multiplas":  _sub_mult,
    "alavancagem":_sub_alav,
}

def _build_union(date_cond: str, source: Optional[str]) -> str:
    """Monta UNION ALL das 4 tabelas de picks com colunas normalizadas."""
    if source and source in _SUB_BUILDERS:
        return _SUB_BUILDERS[source](date_cond)
    return " UNION ALL ".join(fn(date_cond) for fn in _SUB_BUILDERS.values())


def _collect_results(cur, date_cond: str, date_params: tuple, source: Optional[str], limit: int = 30) -> list:
    """Corre cada sub-query separada, assim uma falha não apaga as outras."""
    builders = [_SUB_BUILDERS[source]] if (source and source in _SUB_BUILDERS) else list(_SUB_BUILDERS.values())
    rows: list = []
    for fn in builders:
        sub = fn(date_cond)
        batch = _q(cur, f"SELECT * FROM ({sub}) t ORDER BY match_date DESC, result LIMIT %s", date_params + (limit,))
        rows.extend(batch)
    rows.sort(key=lambda r: (str(r["match_date"]), str(r.get("result",""))), reverse=True)
    return rows[:limit]


@router.get("/results")
def public_results(
    month:  Optional[str] = Query(None, description="YYYY-MM — filtra por mês"),
    source: Optional[str] = Query(None, description="all | vip | free | multiplas | alavancagem"),
):
    """Resultados públicos consolidados para a Landing page."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        # ── Meses disponíveis (todas as tabelas) ─────────────────────────────
        months_rows = _q(cur, """
            SELECT month, SUM(cnt) AS total FROM (
                SELECT TO_CHAR(match_date, 'YYYY-MM') AS month, COUNT(*) AS cnt
                FROM picks_vip WHERE result IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT TO_CHAR(match_date, 'YYYY-MM'), COUNT(*)
                FROM picks_free WHERE result IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT TO_CHAR(match_date, 'YYYY-MM'), COUNT(*)
                FROM picks_multiplas WHERE result IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT TO_CHAR(match_date, 'YYYY-MM'), COUNT(*)
                FROM picks_alavancagem WHERE result IS NOT NULL GROUP BY 1
            ) t
            GROUP BY month
            HAVING SUM(cnt) > 0
            ORDER BY month DESC
            LIMIT 24
        """)
        available_months = [r["month"] for r in months_rows]

        # ── Filtro de data ────────────────────────────────────────────────────
        if month:
            date_cond   = "AND TO_CHAR(match_date, 'YYYY-MM') = %s"
            date_params = (month,)
        else:
            date_cond   = ""
            date_params = ()

        single = source in ("vip", "free", "multiplas", "alavancagem")
        union_sql = _build_union(date_cond, source if single else None)
        # cada sub-query tem 1 placeholder; UNION de 4 precisa 4x
        p = date_params if single else date_params * 4

        # ── Sumário ───────────────────────────────────────────────────────────
        summary = _q1(cur, f"""
            SELECT
                COUNT(*)                                          AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')         AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')           AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')          AS push,
                COUNT(*) FILTER (WHERE result = 'HALF-WIN')      AS half_wins,
                COUNT(*) FILTER (WHERE result = 'HALF-LOSS')     AS half_losses,
                COALESCE(SUM(profit), 0)                         AS profit,
                COALESCE(SUM(stake),  0)                         AS stake_total,
                ROUND(
                    COALESCE(SUM(profit), 0) /
                    NULLIF(COALESCE(SUM(stake), 0), 0) * 100, 1
                )                                                 AS roi
            FROM ({union_sql}) AS t
        """, p)

        # ── Por dia (gráfico) ─────────────────────────────────────────────────
        by_day = _q(cur, f"""
            SELECT
                match_date,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN') AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')   AS reds,
                COALESCE(SUM(profit), 0)                 AS profit
            FROM ({union_sql}) AS t
            GROUP BY match_date
            ORDER BY match_date
        """, p)

        # ── Recentes (por sub-query para não quebrar tudo se uma coluna faltar) ──
        single_source = source if source in _SUB_BUILDERS else None
        recent = _collect_results(cur, date_cond, date_params, single_source, limit=30)

        # ── Contagem por tipo ─────────────────────────────────────────────────
        counts_row = _q1(cur, f"""
            SELECT
                COUNT(*) FILTER (WHERE source = 'vip')        AS vip_total,
                COUNT(*) FILTER (WHERE source = 'free')       AS free_total,
                COUNT(*) FILTER (WHERE source = 'multipla')   AS multipla_total,
                COUNT(*) FILTER (WHERE source = 'alavancagem') AS alavancagem_total
            FROM (
                SELECT 'vip'        AS source FROM picks_vip        WHERE result IS NOT NULL
                UNION ALL
                SELECT 'free'       AS source FROM picks_free       WHERE result IS NOT NULL
                UNION ALL
                SELECT 'multipla'   AS source FROM picks_multiplas  WHERE result IS NOT NULL
                UNION ALL
                SELECT 'alavancagem' AS source FROM picks_alavancagem WHERE result IS NOT NULL
            ) AS t
        """)

        return {
            "available_months": available_months,
            "summary": dict(summary) if summary else {},
            "by_day":  [dict(r) for r in by_day],
            "recent":  [dict(r) for r in recent],
            "counts":  dict(counts_row) if counts_row else {},
        }
    finally:
        cur.close()
        conn.close()


def _mask_first(full_name: str) -> str:
    """'João da Silva' → 'João S.'"""
    parts = (full_name or "").strip().split()
    if not parts:
        return "Usuário"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


_ACTIVITY_VERBS = [
    "ativou o teste VIP",
    "criou uma conta",
    "entrou agora",
    "seguiu o pick VIP de hoje",
    "está acompanhando ao vivo",
]


@router.get("/activity")
def public_activity():
    """Últimas ações de usuários reais — anonimizadas — para o ticker da landing."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        # Usuários mais recentes (últimos 30 dias, sem expor email)
        cur.execute("""
            SELECT name, created_at, plan
            FROM users
            WHERE active = TRUE
              AND created_at >= NOW() - INTERVAL '30 days'
            ORDER BY created_at DESC
            LIMIT 15
        """)
        rows = cur.fetchall()
        if not rows:
            # Fallback: últimos usuários ativos qualquer data
            cur.execute("SELECT name, created_at, plan FROM users WHERE active = TRUE ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
        total = _q1(cur, "SELECT COUNT(*) AS cnt FROM users WHERE active = TRUE")
        events = []
        for i, r in enumerate(rows):
            verb = "ativou o teste VIP" if r.get("plan") in ("trial", "vip") else _ACTIVITY_VERBS[i % len(_ACTIVITY_VERBS)]
            events.append({"name": _mask_first(r["name"]), "verb": verb})
        return {
            "events": events,
            "total_users": int(total["cnt"]) if total else 0,
        }
    finally:
        cur.close()
        conn.close()


@router.get("/pick/{pick_type}/{pick_id}")
def public_pick(pick_type: str, pick_id: int):
    """Teaser público de pick para compartilhamento. Nao expoe market/reasoning."""
    valid = {"vip", "free", "multipla", "alavancagem"}
    if pick_type not in valid:
        raise HTTPException(400, "Tipo inválido")

    conn = get_connection()
    cur  = conn.cursor()
    try:
        if pick_type == "vip":
            cur.execute("""
                SELECT pv.id, pv.match_date,
                       pv.home_team_name, pv.away_team_name,
                       pv.home_team_id,  pv.away_team_id,
                       COALESCE(l.name, '') AS league_name,
                       f.league_id,
                       pv.odd, pv.result, pv.profit
                FROM picks_vip pv
                LEFT JOIN fixtures f ON f.fixture_id = pv.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = f.league_id
                WHERE pv.id = %s
            """, (pick_id,))
        elif pick_type == "free":
            cur.execute("""
                SELECT pf.id, pf.match_date,
                       pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                       COALESCE(pf.home_team_id, fx.home_team_id) AS home_team_id,
                       COALESCE(pf.away_team_id, fx.away_team_id) AS away_team_id,
                       COALESCE(l.name, '') AS league_name,
                       fx.league_id,
                       pf.odd, pf.result, pf.profit
                FROM picks_free pf
                LEFT JOIN fixtures fx ON fx.fixture_id = pf.fixture_id
                LEFT JOIN leagues   l ON l.league_id   = fx.league_id
                WHERE pf.id = %s
            """, (pick_id,))
        elif pick_type == "multipla":
            cur.execute("""
                SELECT id, match_date, games, total_odd AS odd, result, profit
                FROM picks_multiplas WHERE id = %s
            """, (pick_id,))
        else:  # alavancagem
            cur.execute("""
                SELECT id, match_date,
                       home_team_1 AS home_team_name, away_team_1 AS away_team_name,
                       odd_combined AS odd, result, profit
                FROM picks_alavancagem WHERE id = %s
            """, (pick_id,))

        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pick não encontrado")

        d = dict(row)
        if d.get("match_date") and hasattr(d["match_date"], "isoformat"):
            d["match_date"] = d["match_date"].isoformat()

        # Para múltipla: extrai preview dos times sem expor markets
        if pick_type == "multipla" and d.get("games"):
            import json as _json
            games = d["games"] if isinstance(d["games"], list) else _json.loads(d["games"])
            d["teams_preview"] = [
                f"{g.get('home_team', '?')} x {g.get('away_team', '?')}"
                for g in games[:4]
            ]
            d.pop("games", None)

        d["pick_type"] = pick_type
        return d
    finally:
        cur.close()
        conn.close()


@router.get("/leaderboard")
def public_leaderboard():
    """Top 5 usuarios por yield ROI — anonimizados para landing page (min 5 picks resolvidos)."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            WITH resolved AS (
                SELECT
                    uf.user_id,
                    uf.stake_units,
                    CASE uf.pick_type
                        WHEN 'vip'         THEN pv.result
                        WHEN 'free'        THEN pf.result
                        WHEN 'multipla'    THEN pm.result
                        WHEN 'alavancagem' THEN pa.result
                    END AS result,
                    CASE uf.pick_type
                        WHEN 'vip'         THEN COALESCE(pv.profit, 0)
                        WHEN 'free'        THEN COALESCE(pf.profit, 0)
                        WHEN 'multipla'    THEN COALESCE(pm.profit, 0)
                        WHEN 'alavancagem' THEN COALESCE(pa.profit, 0)
                        ELSE 0
                    END AS profit
                FROM user_followed_picks uf
                LEFT JOIN picks_vip pv         ON pv.id = uf.pick_id AND uf.pick_type = 'vip'
                LEFT JOIN picks_free pf        ON pf.id = uf.pick_id AND uf.pick_type = 'free'
                LEFT JOIN picks_multiplas pm   ON pm.id = uf.pick_id AND uf.pick_type = 'multipla'
                LEFT JOIN picks_alavancagem pa ON pa.id = uf.pick_id AND uf.pick_type = 'alavancagem'
            ),
            user_stats AS (
                SELECT
                    user_id,
                    COUNT(*) FILTER (WHERE result IS NOT NULL)  AS total,
                    COUNT(*) FILTER (WHERE result = 'GREEN')    AS greens,
                    ROUND(
                        COUNT(*) FILTER (WHERE result = 'GREEN')::numeric /
                        NULLIF(COUNT(*) FILTER (WHERE result IS NOT NULL), 0) * 100
                    ) AS win_rate,
                    ROUND(
                        COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) /
                        NULLIF(COALESCE(SUM(stake_units) FILTER (WHERE result IS NOT NULL), 0), 0) * 100,
                        1
                    ) AS yield_roi
                FROM resolved
                GROUP BY user_id
                HAVING COUNT(*) FILTER (WHERE result IS NOT NULL) >= 5
            )
            SELECT u.name, u.avatar_url, us.total, us.greens, us.win_rate, us.yield_roi
            FROM user_stats us
            JOIN users u ON u.id = us.user_id
            ORDER BY us.yield_roi DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        return [
            {
                "name":      _mask_first(r["name"]),
                "avatar_url": r["avatar_url"],
                "total":     int(r["total"]),
                "greens":    int(r["greens"]),
                "win_rate":  int(r["win_rate"]),
                "yield_roi": float(r["yield_roi"]),
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()
