from fastapi import APIRouter, Query
from typing import Optional
from database import get_connection

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
                    f"https://media.api-sports.io/football/leagues/{r['league_id']}.png"
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
    except Exception:
        cur.connection.rollback()
        return []


def _q1(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except Exception:
        cur.connection.rollback()
        return None


def _build_union(date_cond: str, source: Optional[str]) -> str:
    """Monta UNION ALL das 4 tabelas de picks com colunas normalizadas."""
    vip = f"""
        SELECT match_date,
               home_team_name, away_team_name,
               home_team_id,   away_team_id,
               market, line, odd,
               result, profit,
               COALESCE(stake, 1) AS stake,
               'vip' AS source
        FROM picks_vip
        WHERE result IS NOT NULL {date_cond}
    """
    free = f"""
        SELECT match_date,
               home_team AS home_team_name, away_team AS away_team_name,
               home_team_id, away_team_id,
               market, line, odd,
               result, profit,
               1 AS stake,
               'free' AS source
        FROM picks_free
        WHERE result IS NOT NULL {date_cond}
    """
    mult = f"""
        SELECT match_date,
               multipla_name AS home_team_name, NULL AS away_team_name,
               NULL::INTEGER AS home_team_id, NULL::INTEGER AS away_team_id,
               'Múltipla' AS market, NULL AS line, total_odd AS odd,
               result, profit,
               COALESCE(stake, 1) AS stake,
               'multiplas' AS source
        FROM picks_multiplas
        WHERE result IS NOT NULL {date_cond}
    """
    alav = f"""
        SELECT match_date,
               home_team_1 AS home_team_name, away_team_1 AS away_team_name,
               NULL::INTEGER AS home_team_id, NULL::INTEGER AS away_team_id,
               market_1 AS market, line_1 AS line, odd_combined AS odd,
               result, profit,
               COALESCE(stake, 0) AS stake,
               'alavancagem' AS source
        FROM picks_alavancagem
        WHERE result IS NOT NULL {date_cond}
    """

    parts = {"vip": vip, "free": free, "multiplas": mult, "alavancagem": alav}

    if source and source in parts:
        return parts[source]
    return " UNION ALL ".join(parts.values())


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
            date_cond   = "AND match_date >= CURRENT_DATE - INTERVAL '30 days'"
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

        # ── Recentes ──────────────────────────────────────────────────────────
        recent = _q(cur, f"""
            SELECT match_date, home_team_name, away_team_name,
                   home_team_id, away_team_id,
                   market, line, odd, result, profit, source
            FROM ({union_sql}) AS t
            ORDER BY match_date DESC, result
            LIMIT 30
        """, p)

        return {
            "available_months": available_months,
            "summary": dict(summary) if summary else {},
            "by_day":  [dict(r) for r in by_day],
            "recent":  [dict(r) for r in recent],
        }
    finally:
        cur.close()
        conn.close()
