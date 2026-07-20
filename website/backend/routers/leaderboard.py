from fastapi import APIRouter, Depends, Query
from auth_utils import get_current_user
from database import get_connection
from routers.banca import _compute_follow_pnl

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
        date_params: list = []
        if days > 0:
            date_cond = "AND uf.followed_at >= NOW() - (%s * INTERVAL '1 day')"
            date_params = [days]

        # Busca cru (sem calcular resultado/profit em SQL) e resolve por pick em
        # Python via _compute_follow_pnl -- mesma funcao usada em GET /banca e no
        # fechamento mensal. A query antiga usava pv.profit/pf.profit/etc direto
        # (pre-calculado com a odd OFICIAL do pick), ignorando uf.actual_odd (a
        # odd que o usuario realmente registrou) -- bug real: 84% dos follows no
        # banco tem actual_odd preenchido, entao o ranking (ROI/yield/total_pnl)
        # estava errado pra maioria das entradas sempre que a odd real divergia
        # da oficial.
        cur.execute(f"""
            SELECT
                uf.user_id, uf.stake_units, uf.actual_odd, uf.cashout_amount,
                CASE uf.pick_type
                    WHEN 'vip'         THEN pv.result
                    WHEN 'free'        THEN pf.result
                    WHEN 'multipla'    THEN pm.result
                    WHEN 'alavancagem' THEN pa.result
                    WHEN 'bingo'       THEN pb.result
                END AS result,
                CASE uf.pick_type
                    WHEN 'vip'         THEN pv.odd
                    WHEN 'free'        THEN pf.odd
                    WHEN 'multipla'    THEN pm.total_odd
                    WHEN 'alavancagem' THEN pa.odd_combined
                    WHEN 'bingo'       THEN pb.odd_final
                END AS odd,
                COALESCE(ub.unit_value, 1)       AS unit_value,
                COALESCE(ub.bankroll_start, 100) AS bankroll_start
            FROM user_followed_picks uf
            LEFT JOIN picks_vip pv         ON pv.id = uf.pick_id AND uf.pick_type = 'vip'
            LEFT JOIN picks_free pf        ON pf.id = uf.pick_id AND uf.pick_type = 'free'
            LEFT JOIN picks_multiplas pm   ON pm.id = uf.pick_id AND uf.pick_type = 'multipla'
            LEFT JOIN picks_alavancagem pa ON pa.id = uf.pick_id AND uf.pick_type = 'alavancagem'
            LEFT JOIN picks_bingo pb       ON pb.id = uf.pick_id AND uf.pick_type = 'bingo'
            LEFT JOIN user_banca ub        ON ub.user_id = uf.user_id
            WHERE 1=1 {date_cond}
        """, date_params)

        per_user: dict[int, dict] = {}
        for raw in cur.fetchall():
            raw = dict(raw)
            uid = raw["user_id"]
            unit_value = float(raw["unit_value"] or 1)
            pick = {"result": raw["result"], "odd": raw["odd"]}
            follow = {"stake_units": raw["stake_units"], "actual_odd": raw["actual_odd"], "cashout_amount": raw["cashout_amount"]}
            result, _profit_u, pnl_r = _compute_follow_pnl(pick, follow, unit_value)
            if result is None:
                continue
            st = per_user.setdefault(uid, {
                "total_resolved": 0, "greens": 0,
                "total_profit_units": 0.0, "total_staked_units": 0.0,
                "unit_value": unit_value, "bankroll_start": float(raw["bankroll_start"] or 100),
            })
            st["total_resolved"] += 1
            if result == "GREEN":
                st["greens"] += 1
            # pnl_r vem em R$ (jah multiplicado por unit_value); volta pra
            # "unidades" pra agregar igual a query antiga fazia, e so converte
            # pra R$ de novo no final (evita contaminar a soma entre usuarios
            # com unit_value diferentes).
            st["total_profit_units"] += (pnl_r / unit_value) if unit_value else 0.0
            st["total_staked_units"] += float(raw["stake_units"])

        qualifying = {uid: st for uid, st in per_user.items() if st["total_resolved"] >= 3}
        if not qualifying:
            return []

        user_ids_q = list(qualifying.keys())
        placeholders_q = ",".join(["%s"] * len(user_ids_q))
        cur.execute(f"SELECT id, name, avatar_url FROM users WHERE id IN ({placeholders_q})", user_ids_q)
        user_info = {r["id"]: dict(r) for r in cur.fetchall()}

        rows = []
        for uid, st in qualifying.items():
            info = user_info.get(uid)
            if not info:
                continue
            win_rate = round(st["greens"] / st["total_resolved"] * 100) if st["total_resolved"] else 0
            roi = round(st["total_profit_units"] * st["unit_value"] / st["bankroll_start"] * 100, 1) if st["bankroll_start"] else 0
            yield_roi = round(st["total_profit_units"] / st["total_staked_units"] * 100, 1) if st["total_staked_units"] > 0 else 0
            rows.append({
                "id": uid, "name": info["name"], "avatar_url": info["avatar_url"],
                "bankroll_start": st["bankroll_start"], "unit_value": st["unit_value"],
                "total_resolved": st["total_resolved"], "greens": st["greens"],
                "win_rate": win_rate, "roi": roi, "yield_roi": yield_roi,
                "total_pnl": round(st["total_profit_units"] * st["unit_value"], 2),
            })

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
                        WHEN 'bingo'       THEN pb.result
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
                LEFT JOIN picks_bingo pb       ON pb.id = uf.pick_id AND uf.pick_type = 'bingo'
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
