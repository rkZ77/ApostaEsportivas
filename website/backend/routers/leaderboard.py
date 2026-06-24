from fastapi import APIRouter, Depends, Query
from auth_utils import get_current_user
from database import get_connection

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])

SORT_OPTIONS = {"roi", "yield_roi", "win_rate", "picks", "streak"}


def _mask_name(full_name: str) -> str:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


def _compute_streak(results: list[str]) -> dict:
    """results: lista de 'GREEN'/'RED'/... em ordem DESC de data."""
    streak = 0
    streak_type = None
    for r in results:
        if r not in ("GREEN", "RED"):
            continue
        t = "green" if r == "GREEN" else "red"
        if streak_type is None:
            streak_type = t
            streak = 1
        elif streak_type == t:
            streak += 1
        else:
            break
    return {"streak": streak, "streak_type": streak_type}


@router.get("")
def get_leaderboard(
    current_user: dict = Depends(get_current_user),
    sort: str = Query("roi", pattern="^(roi|yield_roi|win_rate|picks|streak)$"),
    days: int = Query(0, ge=0),
):
    conn = get_connection()
    cur = conn.cursor()
    try:
        date_cond = ""
        date_params_extra: list = []
        if days > 0:
            date_cond = "AND uf.followed_at >= NOW() - (%s * INTERVAL '1 day')"
            date_params_extra = [days, days]

        cur.execute(f"""
            WITH resolved AS (
                SELECT
                    uf.user_id,
                    uf.stake_units,
                    uf.followed_at,
                    CASE
                        WHEN uf.cashout_amount IS NOT NULL THEN 'CASHOUT'
                        WHEN uf.pick_type = 'vip'         THEN pv.result
                        WHEN uf.pick_type = 'free'        THEN pf.result
                        WHEN uf.pick_type = 'multipla'    THEN pm.result
                        WHEN uf.pick_type = 'alavancagem' THEN pa.result
                    END AS result,
                    CASE
                        WHEN uf.cashout_amount IS NOT NULL
                            THEN (uf.cashout_amount / COALESCE(ub.unit_value, 1)) - uf.stake_units
                        WHEN uf.pick_type = 'vip'         THEN COALESCE(pv.profit, 0) * uf.stake_units
                        WHEN uf.pick_type = 'free'        THEN COALESCE(pf.profit, 0) * uf.stake_units
                        WHEN uf.pick_type = 'multipla'    THEN COALESCE(pm.profit, 0) * uf.stake_units
                        WHEN uf.pick_type = 'alavancagem' THEN COALESCE(pa.profit, 0) * uf.stake_units
                        ELSE 0
                    END AS profit_weighted
                FROM user_followed_picks uf
                LEFT JOIN picks_vip pv         ON pv.id = uf.pick_id AND uf.pick_type = 'vip'
                LEFT JOIN picks_free pf        ON pf.id = uf.pick_id AND uf.pick_type = 'free'
                LEFT JOIN picks_multiplas pm   ON pm.id = uf.pick_id AND uf.pick_type = 'multipla'
                LEFT JOIN picks_alavancagem pa ON pa.id = uf.pick_id AND uf.pick_type = 'alavancagem'
                LEFT JOIN user_banca ub        ON ub.user_id = uf.user_id
                WHERE 1=1 {date_cond}
            ),
            user_stats AS (
                SELECT
                    user_id,
                    COUNT(*)         FILTER (WHERE result IS NOT NULL)  AS total_resolved,
                    COUNT(*)         FILTER (WHERE result = 'GREEN')    AS greens,
                    COALESCE(SUM(profit_weighted) FILTER (WHERE result IS NOT NULL), 0) AS total_profit_units,
                    COALESCE(SUM(stake_units)     FILTER (WHERE result IS NOT NULL), 0) AS total_staked_units
                FROM resolved
                GROUP BY user_id
                HAVING COUNT(*) FILTER (WHERE result IS NOT NULL) >= 3
            )
            SELECT
                u.id,
                u.name,
                u.avatar_url,
                COALESCE(ub.bankroll_start, 100)                    AS bankroll_start,
                COALESCE(ub.unit_value, 1)                          AS unit_value,
                us.total_resolved,
                us.greens,
                ROUND(us.greens::numeric / us.total_resolved * 100) AS win_rate,
                ROUND(us.total_profit_units * COALESCE(ub.unit_value,1)
                      / COALESCE(ub.bankroll_start, 100) * 100, 1)  AS roi,
                CASE WHEN us.total_staked_units > 0
                     THEN ROUND(us.total_profit_units / us.total_staked_units * 100, 1)
                     ELSE 0 END                                      AS yield_roi,
                us.total_profit_units * COALESCE(ub.unit_value, 1)  AS total_pnl
            FROM user_stats us
            JOIN users u ON u.id = us.user_id
            LEFT JOIN user_banca ub ON ub.user_id = us.user_id
            LIMIT 50
        """, date_params_extra + date_params_extra)

        rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return []

        # Busca as últimas 20 entradas resolvidas de cada usuário para calcular streak
        user_ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(user_ids))
        streak_date_cond = ""
        if days > 0:
            streak_date_cond = f"AND uf.followed_at >= NOW() - ({days} * INTERVAL '1 day')"
        cur.execute(f"""
            SELECT t.user_id, t.result
            FROM (
                SELECT
                    uf.user_id,
                    CASE uf.pick_type
                        WHEN 'vip'         THEN pv.result
                        WHEN 'free'        THEN pf.result
                        WHEN 'multipla'    THEN pm.result
                        WHEN 'alavancagem' THEN pa.result
                    END AS result,
                    ROW_NUMBER() OVER (
                        PARTITION BY uf.user_id
                        ORDER BY uf.followed_at DESC
                    ) AS rn
                FROM user_followed_picks uf
                LEFT JOIN picks_vip pv         ON pv.id = uf.pick_id AND uf.pick_type = 'vip'
                LEFT JOIN picks_free pf        ON pf.id = uf.pick_id AND uf.pick_type = 'free'
                LEFT JOIN picks_multiplas pm   ON pm.id = uf.pick_id AND uf.pick_type = 'multipla'
                LEFT JOIN picks_alavancagem pa ON pa.id = uf.pick_id AND uf.pick_type = 'alavancagem'
                WHERE uf.user_id IN ({placeholders}) {streak_date_cond}
            ) t
            WHERE t.result IS NOT NULL AND t.rn <= 20
            ORDER BY t.user_id, t.rn
        """, user_ids)

        from collections import defaultdict
        streak_map: dict[int, list[str]] = defaultdict(list)
        for r in cur.fetchall():
            streak_map[r["user_id"]].append(r["result"])

        result = []
        for r in rows:
            uid = r["id"]
            streak_info = _compute_streak(streak_map[uid])
            result.append({
                "id":               uid,
                "name":             _mask_name(r["name"]),
                "avatar_url":       r["avatar_url"],
                "bankroll_start":   float(r["bankroll_start"]),
                "unit_value":       float(r["unit_value"]),
                "total_pnl":        round(float(r["total_pnl"]), 2),
                "total_resolved":   int(r["total_resolved"]),
                "greens":           int(r["greens"]),
                "win_rate":         int(r["win_rate"]),
                "roi":              float(r["roi"]),
                "yield_roi":        float(r["yield_roi"]),
                "streak":           streak_info["streak"],
                "streak_type":      streak_info["streak_type"],
                "is_hot":           streak_info["streak_type"] == "green" and streak_info["streak"] >= 3,
                "is_me":            uid == current_user["id"],
            })

        sort_key = {
            "roi":      lambda e: e["roi"],
            "yield_roi": lambda e: e["yield_roi"],
            "win_rate": lambda e: (e["win_rate"], e["total_resolved"]),
            "picks":    lambda e: e["total_resolved"],
            "streak":   lambda e: (e["streak"] if e["streak_type"] == "green" else -e["streak"]),
        }[sort]
        result.sort(key=sort_key, reverse=True)
        result = result[:20]

        for i, e in enumerate(result):
            e["rank"] = i + 1

        return result
    finally:
        cur.close()
        conn.close()
