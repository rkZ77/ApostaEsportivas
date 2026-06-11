from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from database import get_connection
from auth_utils import get_current_user

router = APIRouter(prefix="/api/banca", tags=["banca"])


class BancaSetup(BaseModel):
    bankroll_start: float
    bankroll_goal: Optional[float] = None
    unit_value: Optional[float] = None  # R$ por unidade; None = manter atual


class FollowPick(BaseModel):
    pick_id: int
    pick_type: str
    stake_units: float = 1.0


def _resolve_pick(cur, pick_id: int, pick_type: str) -> Optional[dict]:
    if pick_type == "vip":
        cur.execute("SELECT result, profit, COALESCE(stake, 1) AS stake, home_team_name, market FROM picks_vip WHERE id = %s", (pick_id,))
    elif pick_type == "free":
        cur.execute("SELECT result, profit, 1 AS stake, home_team AS home_team_name, market FROM picks_free WHERE id = %s", (pick_id,))
    elif pick_type == "multipla":
        cur.execute("SELECT result, profit, 1 AS stake, NULL AS home_team_name, NULL AS market FROM picks_multiplas WHERE id = %s", (pick_id,))
    elif pick_type == "alavancagem":
        cur.execute("SELECT result, profit, COALESCE(stake, 1) AS stake, home_team_1 AS home_team_name, market_1 AS market FROM picks_alavancagem WHERE id = %s", (pick_id,))
    else:
        return None
    row = cur.fetchone()
    return dict(row) if row else None


def _compute_streak(resolved: list) -> dict:
    """Calcula streak atual e melhor streak."""
    streak = 0
    streak_type = None
    for e in reversed(resolved):
        r = e.get("result")
        if r not in ("GREEN", "RED"):
            continue
        t = "green" if r == "GREEN" else "red"
        if streak_type is None:
            streak_type = t; streak = 1
        elif streak_type == t:
            streak += 1
        else:
            break

    best = 0
    temp = 0
    for e in resolved:
        r = e.get("result")
        if r == "GREEN":
            temp += 1
            if temp > best: best = temp
        else:
            temp = 0

    return {"streak": streak, "streak_type": streak_type, "best_streak": best}


@router.get("")
def get_banca(
    current_user: dict = Depends(get_current_user),
    days: int = Query(0, ge=0),  # 0 = tudo
):
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT bankroll_start, bankroll_goal, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        bankroll_start = float(row["bankroll_start"]) if row else 100.0
        bankroll_goal  = float(row["bankroll_goal"]) if row and row["bankroll_goal"] else None
        # unit_value: R$ por unidade. Default = 1 (pnl em unidades ≈ R$1/u)
        unit_value = float(row["unit_value"]) if row and row["unit_value"] else 1.0

        date_cond = ""
        date_params: list = [user_id]
        if days > 0:
            date_cond = " AND uf.followed_at >= NOW() - (%s * INTERVAL '1 day')"
            date_params.append(days)

        cur.execute(f"""
            SELECT uf.id, uf.pick_id, uf.pick_type, uf.stake_units, uf.followed_at
            FROM user_followed_picks uf
            WHERE uf.user_id = %s {date_cond}
            ORDER BY uf.followed_at ASC
        """, date_params)
        followed = [dict(r) for r in cur.fetchall()]

        entries = []
        running = bankroll_start
        for f in followed:
            pick = _resolve_pick(cur, f["pick_id"], f["pick_type"])
            if not pick:
                continue
            result   = pick.get("result")
            profit_u = float(pick.get("profit") or 0) if result else None
            # pnl em R$ = lucro_por_unidade × unidades_apostadas × valor_da_unidade
            pnl_r    = profit_u * float(f["stake_units"]) * unit_value if profit_u is not None else None
            if pnl_r is not None:
                running += pnl_r

            entries.append({
                "id":             f["id"],
                "pick_id":        f["pick_id"],
                "pick_type":      f["pick_type"],
                "stake_units":    float(f["stake_units"]),
                "followed_at":    f["followed_at"].isoformat() if f["followed_at"] else None,
                "home_team_name": pick.get("home_team_name"),
                "market":         pick.get("market"),
                "result":         result,
                "profit_units":   profit_u,
                "pnl":            round(pnl_r, 2) if pnl_r is not None else None,
                "bankroll_after": round(running, 2) if pnl_r is not None else None,
            })

        resolved  = [e for e in entries if e["result"]]
        greens    = sum(1 for e in resolved if e["result"] == "GREEN")
        reds      = sum(1 for e in resolved if e["result"] == "RED")
        push      = sum(1 for e in resolved if e["result"] == "PUSH")
        half_wins = sum(1 for e in resolved if e["result"] == "HALF-WIN")
        half_loss = sum(1 for e in resolved if e["result"] == "HALF-LOSS")
        total_pnl = sum(e["pnl"] for e in resolved if e["pnl"] is not None)
        win_rate  = round(greens / len(resolved) * 100) if resolved else 0
        # ROI de crescimento: ganho sobre banca inicial em R$
        roi = round(total_pnl / bankroll_start * 100, 1) if bankroll_start else 0
        # Yield tipster: lucro em unidades / unidades apostadas × 100
        total_profit_units  = sum(e["pnl"] / unit_value for e in resolved if e["pnl"] is not None)
        total_staked_units  = sum(e["stake_units"] for e in resolved)
        yield_roi = round(total_profit_units / total_staked_units * 100, 1) if total_staked_units > 0 else 0

        # Streak pessoal
        streak_info = _compute_streak(resolved)

        # Melhor e pior pick
        pnl_entries = [e for e in resolved if e["pnl"] is not None]
        best_pick  = max(pnl_entries, key=lambda e: e["pnl"]) if pnl_entries else None
        worst_pick = min(pnl_entries, key=lambda e: e["pnl"]) if pnl_entries else None

        # ROI geral da IA para comparação
        ia_roi = None
        try:
            cur.execute("""
                SELECT COALESCE(SUM(profit), 0) AS p, COALESCE(SUM(COALESCE(stake,1)), 0) AS s
                FROM picks_vip WHERE result IS NOT NULL
            """)
            ia_row = cur.fetchone()
            if ia_row and float(ia_row["s"]) > 0:
                ia_roi = round(float(ia_row["p"]) / float(ia_row["s"]) * 100, 1)
        except Exception:
            pass

        # Gráfico (usa running que já acumula com unit_value)
        chart: list[dict] = []
        running2 = bankroll_start
        for e in entries:
            if e["pnl"] is not None:
                running2 += e["pnl"]
                chart.append({
                    "date": (e["followed_at"] or "")[:10],
                    "bankroll": round(running2, 2),
                })

        return {
            "bankroll_start":       bankroll_start,
            "bankroll_goal":        bankroll_goal,
            "bankroll_current":     round(running, 2),
            "unit_value":           unit_value,
            "total_followed":       len(followed),
            "total_resolved":       len(resolved),
            "greens":               greens,
            "reds":                 reds,
            "push":                 push,
            "half_wins":            half_wins,
            "half_loss":            half_loss,
            "win_rate":             win_rate,
            "roi":                  roi,
            "yield_roi":            yield_roi,
            "ia_roi":               ia_roi,
            "total_pnl":            round(total_pnl, 2),
            "streak":               streak_info["streak"],
            "streak_type":          streak_info["streak_type"],
            "best_streak":          streak_info["best_streak"],
            "best_pick":            best_pick,
            "worst_pick":           worst_pick,
            "entries":              entries,
            "chart":                chart,
        }
    finally:
        cur.close()
        conn.close()


@router.post("/setup")
def setup_banca(body: BancaSetup, current_user: dict = Depends(get_current_user)):
    if body.bankroll_start <= 0:
        raise HTTPException(400, "Banca deve ser maior que zero.")
    if body.bankroll_goal is not None and body.bankroll_goal <= body.bankroll_start:
        raise HTTPException(400, "Meta deve ser maior que a banca inicial.")
    if body.unit_value is not None and body.unit_value <= 0:
        raise HTTPException(400, "Valor da unidade deve ser maior que zero.")
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO user_banca (user_id, bankroll_start, bankroll_goal, unit_value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET bankroll_start = EXCLUDED.bankroll_start,
                    bankroll_goal  = EXCLUDED.bankroll_goal,
                    unit_value     = COALESCE(EXCLUDED.unit_value, user_banca.unit_value),
                    updated_at     = NOW()
        """, (user_id, body.bankroll_start, body.bankroll_goal, body.unit_value))
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


@router.post("/follow")
def follow_pick(body: FollowPick, current_user: dict = Depends(get_current_user)):
    if body.pick_type not in ("vip", "free", "multipla", "alavancagem"):
        raise HTTPException(400, "Tipo inválido.")
    if body.stake_units <= 0:
        raise HTTPException(400, "Stake deve ser maior que zero.")
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not _resolve_pick(cur, body.pick_id, body.pick_type):
            raise HTTPException(404, "Pick não encontrado.")
        cur.execute(
            "SELECT id FROM user_followed_picks WHERE user_id=%s AND pick_id=%s AND pick_type=%s",
            (user_id, body.pick_id, body.pick_type),
        )
        if cur.fetchone():
            return {"ok": True, "already_followed": True}
        cur.execute("""
            INSERT INTO user_followed_picks (user_id, pick_id, pick_type, stake_units)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, pick_id, pick_type) DO NOTHING
        """, (user_id, body.pick_id, body.pick_type, body.stake_units))
        conn.commit()
        return {"ok": True, "already_followed": False}
    finally:
        cur.close()
        conn.close()


@router.get("/alavancagem-serie")
def get_alavancagem_serie(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT bankroll_start FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"has_banca": False, "current_bankroll": 0.0, "initial_bankroll": 0.0}

        initial = float(row["bankroll_start"])
        bankroll = initial

        cur.execute("""
            SELECT pa.result, pa.odd_combined
            FROM user_followed_picks uf
            JOIN picks_alavancagem pa ON pa.id = uf.pick_id
            WHERE uf.user_id = %s AND uf.pick_type = 'alavancagem' AND pa.result IS NOT NULL
            ORDER BY pa.match_date ASC
        """, (user_id,))

        for pick in cur.fetchall():
            result = pick["result"]
            odd = float(pick["odd_combined"] or 1)
            if result == "GREEN":
                bankroll = round(bankroll + bankroll * (odd - 1), 2)
            elif result == "RED":
                bankroll = initial

        return {
            "has_banca": True,
            "current_bankroll": round(bankroll, 2),
            "initial_bankroll": initial,
        }
    finally:
        cur.close()
        conn.close()


@router.get("/summary")
def get_banca_summary(current_user: dict = Depends(get_current_user)):
    """Retorna dados mínimos da banca para sugestão de stake nos picks."""
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"has_banca": False, "bankroll_current": 0.0, "unit_value": 1.0}

        bankroll_start = float(row["bankroll_start"])
        unit_value = float(row["unit_value"]) if row["unit_value"] else 1.0

        # P&L acumulado de picks seguidos com resultado
        cur.execute("""
            SELECT COALESCE(SUM(
                CASE uf.pick_type
                    WHEN 'vip'      THEN COALESCE(pv.profit, 0) * %s
                    WHEN 'free'     THEN COALESCE(pf.profit, 0) * %s
                    WHEN 'multipla' THEN COALESCE(pm.profit, 0) * %s
                    ELSE 0
                END
            ), 0) AS total_pnl
            FROM user_followed_picks uf
            LEFT JOIN picks_vip pv       ON uf.pick_type='vip'      AND pv.id=uf.pick_id AND pv.result IS NOT NULL
            LEFT JOIN picks_free pf      ON uf.pick_type='free'      AND pf.id=uf.pick_id AND pf.result IS NOT NULL
            LEFT JOIN picks_multiplas pm ON uf.pick_type='multipla'  AND pm.id=uf.pick_id AND pm.result IS NOT NULL
            WHERE uf.user_id = %s
        """, (unit_value, unit_value, unit_value, user_id))
        pnl_row = cur.fetchone()
        pnl = float(pnl_row["total_pnl"]) if pnl_row else 0.0

        return {
            "has_banca": True,
            "bankroll_current": round(bankroll_start + pnl, 2),
            "unit_value": unit_value,
        }
    finally:
        cur.close()
        conn.close()


@router.delete("/follow/{pick_id}/{pick_type}")
def unfollow_pick(pick_id: int, pick_type: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM user_followed_picks WHERE user_id=%s AND pick_id=%s AND pick_type=%s",
            (user_id, pick_id, pick_type),
        )
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()
