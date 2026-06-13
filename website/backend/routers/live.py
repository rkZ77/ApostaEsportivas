import os
import json
import time
import requests
from fastapi import APIRouter, Depends
from database import get_connection
from auth_utils import get_current_user

router = APIRouter(prefix="/api/live", tags=["live"])

API_BASE      = "https://v3.football.api-sports.io"
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"}
FT_STATUSES   = {"FT", "AET", "PEN"}
CACHE_TTL     = 60  # seconds

_fix_cache:   dict[int, tuple[float, dict]] = {}
_stats_cache: dict[int, tuple[float, list]] = {}


def _headers():
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _fetch_fixture(fid: int) -> dict:
    now = time.time()
    if fid in _fix_cache and now - _fix_cache[fid][0] < CACHE_TTL:
        return _fix_cache[fid][1]
    try:
        r = requests.get(f"{API_BASE}/fixtures", headers=_headers(),
                         params={"id": fid, "timezone": "America/Sao_Paulo"}, timeout=10)
        items = r.json().get("response", [])
        data  = items[0] if items else {}
    except Exception as e:
        print(f"[LIVE] fixture {fid}: {e}")
        data = {}
    _fix_cache[fid] = (now, data)
    return data


def _fetch_stats(fid: int) -> list:
    now = time.time()
    if fid in _stats_cache and now - _stats_cache[fid][0] < CACHE_TTL:
        return _stats_cache[fid][1]
    try:
        r = requests.get(f"{API_BASE}/fixtures/statistics", headers=_headers(),
                         params={"fixture": fid}, timeout=10)
        data = r.json().get("response", [])
    except Exception as e:
        print(f"[LIVE STATS] fixture {fid}: {e}")
        data = []
    _stats_cache[fid] = (now, data)
    return data


def _parse_stats(raw: list) -> tuple[dict, dict]:
    home, away = {}, {}
    for i, team in enumerate(raw):
        d = {}
        for s in team.get("statistics", []):
            val = s.get("value")
            try:
                val = int(val) if val is not None else 0
            except Exception:
                val = 0
            d[s["type"]] = val
        if i == 0:
            home = d
        else:
            away = d
    return home, away


def _extract_line(line_str: str | None) -> tuple[str | None, float | None]:
    """Returns (direction, numeric_value). direction: 'over'|'under'|'result'|raw."""
    if not line_str:
        return None, None
    l = line_str.strip().lower()
    for prefix in ("over ", "mais de "):
        if l.startswith(prefix):
            try:
                return "over", float(l[len(prefix):])
            except Exception:
                pass
    for prefix in ("under ", "menos de "):
        if l.startswith(prefix):
            try:
                return "under", float(l[len(prefix):])
            except Exception:
                pass
    return l, None


def _stat_for_market(market: str, line: str, home_stats: dict, away_stats: dict,
                     home_goals: int, away_goals: int) -> tuple[float | None, str, str | None]:
    """Returns (current_value, stat_label, direction_for_bar)."""
    m   = (market or "").lower()
    direction, _ = _extract_line(line)

    # ── Corners ──
    if any(k in m for k in ["escanteio", "corner"]):
        hc = home_stats.get("Corner Kicks", 0)
        ac = away_stats.get("Corner Kicks", 0)
        if "casa" in m or "home" in m:
            return float(hc), "Escanteios Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(ac), "Escanteios Fora", direction
        return float(hc + ac), "Escanteios", direction

    # ── Cards ──
    if any(k in m for k in ["cart", "card"]):
        hy = home_stats.get("Yellow Cards", 0)
        hr = home_stats.get("Red Cards", 0)
        ay = away_stats.get("Yellow Cards", 0)
        ar = away_stats.get("Red Cards", 0)
        if "casa" in m or "home" in m:
            return float(hy + hr), "Cartões Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(ay + ar), "Cartões Fora", direction
        return float(hy + hr + ay + ar), "Cartões", direction

    # ── Fouls ──
    if any(k in m for k in ["falta", "foul"]):
        hf = home_stats.get("Fouls", 0)
        af = away_stats.get("Fouls", 0)
        return float(hf + af), "Faltas", direction

    # ── Saves ──
    if any(k in m for k in ["defesa", "save", "goleiro"]):
        hs = home_stats.get("Goalkeeper Saves", 0)
        as_ = away_stats.get("Goalkeeper Saves", 0)
        return float(hs + as_), "Defesas do Goleiro", direction

    # ── Shots ──
    if any(k in m for k in ["chute", "shot", "finaliza"]):
        hs = home_stats.get("Shots on Goal", 0) + home_stats.get("Shots off Goal", 0)
        as_ = away_stats.get("Shots on Goal", 0) + away_stats.get("Shots off Goal", 0)
        return float(hs + as_), "Chutes", direction

    # ── BTTS ──
    if any(k in m for k in ["ambas", "btts", "ambos"]):
        both = int(home_goals or 0) > 0 and int(away_goals or 0) > 0
        return (1.0 if both else 0.0), "Ambas Marcam", None

    # ── Goals ──
    if any(k in m for k in ["gol", "goal"]):
        if "casa" in m or "home" in m:
            return float(home_goals or 0), "Gols Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(away_goals or 0), "Gols Fora", direction
        return float((home_goals or 0) + (away_goals or 0)), "Gols", direction

    # ── Result / Dupla Chance ──
    if any(k in m for k in ["resultado", "dupla chance", "1x2", "vencedor"]):
        return None, "Placar", "result"

    return None, market or "—", direction


def _pick_status(current: float | None, line_str: str | None,
                 home_goals: int = 0, away_goals: int = 0) -> str:
    if current is None:
        return "neutral"
    direction, line_val = _extract_line(line_str)
    if direction == "over" and line_val is not None:
        return "winning" if current > line_val else "losing"
    if direction == "under" and line_val is not None:
        return "winning" if current < line_val else "losing"
    if direction == "result":
        return _result_pick_status(line_str or "", home_goals, away_goals)
    return "neutral"


def _result_pick_status(line_str: str, home_goals: int, away_goals: int) -> str:
    hg, ag = int(home_goals or 0), int(away_goals or 0)
    cur = "1" if hg > ag else "2" if ag > hg else "x"
    l   = line_str.lower().strip()
    if l in ("1", "2", "x"):
        return "winning" if cur == l else "losing"
    if l in ("1 ou x", "1 ou empate"):
        return "winning" if cur in ("1", "x") else "losing"
    if l in ("x ou 2", "empate ou 2"):
        return "winning" if cur in ("x", "2") else "losing"
    if l == "1 ou 2":
        return "winning" if cur in ("1", "2") else "losing"
    return "neutral"


def _calc_result(market: str, line: str, cur_val: float | None,
                 home_goals: int, away_goals: int) -> str | None:
    """Resultado definitivo de um pick com jogo encerrado."""
    if cur_val is None:
        return None
    direction, line_val = _extract_line(line)
    if direction == "over" and line_val is not None:
        if cur_val > line_val:  return "GREEN"
        if cur_val < line_val:  return "RED"
        return "PUSH"
    if direction == "under" and line_val is not None:
        if cur_val < line_val:  return "GREEN"
        if cur_val > line_val:  return "RED"
        return "PUSH"
    if direction == "result":
        pst = _result_pick_status(line, home_goals, away_goals)
        return "GREEN" if pst == "winning" else "RED"
    return None


def _save_single_result(pick_id: int, pick_type: str, result: str, odd: float, conn) -> None:
    profit = round(float(odd) - 1, 4) if result == "GREEN" \
             else (-1.0 if result == "RED" else 0.0)
    tbl = "picks_vip" if pick_type == "vip" else "picks_free"
    c = conn.cursor()
    c.execute(f"UPDATE {tbl} SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    conn.commit()
    c.close()
    print(f"[AUTO-RESULT] {pick_type} #{pick_id} → {result} ({profit:+.2f}u)")


def _save_multipla_result(pick_id: int, legs_results: list[str | None],
                          total_odd: float, conn) -> None:
    if any(r is None for r in legs_results):
        return  # nem todas as pernas encerradas ainda
    if any(r == "RED" for r in legs_results):
        result = "RED"
    elif all(r == "GREEN" for r in legs_results):
        result = "GREEN"
    else:
        result = "PUSH"
    profit = round(float(total_odd) - 1, 4) if result == "GREEN" \
             else (-1.0 if result == "RED" else 0.0)
    c = conn.cursor()
    c.execute("UPDATE picks_multiplas SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    conn.commit()
    c.close()
    print(f"[AUTO-RESULT] multipla #{pick_id} → {result} ({profit:+.2f}u)")


def _save_alavancagem_result(pick_id: int, legs_results: list[str | None],
                             odd_combined: float, conn) -> None:
    _save_multipla_result.__wrapped__ = True  # reuse same logic
    if any(r is None for r in legs_results):
        return
    if any(r == "RED" for r in legs_results):
        result = "RED"
    elif all(r == "GREEN" for r in legs_results):
        result = "GREEN"
    else:
        result = "PUSH"
    profit = round(float(odd_combined) - 1, 4) if result == "GREEN" \
             else (-1.0 if result == "RED" else 0.0)
    c = conn.cursor()
    c.execute("UPDATE picks_alavancagem SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    conn.commit()
    c.close()
    print(f"[AUTO-RESULT] alavancagem #{pick_id} → {result} ({profit:+.2f}u)")


def _enrich_leg(fid: int, market: str, line: str,
                home_team: str, away_team: str,
                home_team_id: int | None, away_team_id: int | None,
                odd: float) -> dict:
    fix_data   = _fetch_fixture(fid)
    fix        = fix_data.get("fixture", {})
    goals      = fix_data.get("goals", {})
    status     = fix.get("status", {}).get("short", "NS")
    elapsed    = fix.get("status", {}).get("elapsed")
    home_goals = int(goals.get("home") or 0)
    away_goals = int(goals.get("away") or 0)

    home_stats, away_stats = {}, {}
    if status in LIVE_STATUSES or status in FT_STATUSES:
        home_stats, away_stats = _parse_stats(_fetch_stats(fid))

    cur_val, stat_label, direction = _stat_for_market(
        market, line, home_stats, away_stats, home_goals, away_goals
    )
    _, line_val = _extract_line(line)
    pst = _pick_status(cur_val, line, home_goals, away_goals) if cur_val is not None \
          else _result_pick_status(line, home_goals, away_goals) if direction == "result" \
          else "neutral"

    # Locked: resultado já determinado e irreversível
    is_ft     = status in FT_STATUSES
    is_locked = is_ft
    if not is_ft and cur_val is not None and line_val is not None:
        if direction == "over"  and cur_val > line_val:  is_locked = True  # stats só sobem
        if direction == "under" and cur_val >= line_val: is_locked = True  # já estourou o limite

    return {
        "fixture_id":   fid,
        "home_team":    home_team,
        "away_team":    away_team,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "market":       market,
        "line":         line,
        "odd":          odd,
        "status":       status,
        "elapsed":      elapsed,
        "home_goals":   home_goals,
        "away_goals":   away_goals,
        "stat_label":   stat_label,
        "current_val":  cur_val,
        "line_val":     line_val,
        "pick_status":  pst,
        "is_live":      status in LIVE_STATUSES,
        "is_ft":        is_ft,
        "is_locked":    is_locked,
    }


@router.get("/my-picks")
def get_live_my_picks(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    conn    = get_connection()
    cur     = conn.cursor()

    cur.execute("""
        SELECT pick_id, pick_type, stake_units
        FROM user_followed_picks
        WHERE user_id = %s
    """, (user_id,))
    followed = cur.fetchall()

    result = []

    for row in followed:
        pick_id    = row["pick_id"]
        pick_type  = row["pick_type"]
        stake_u    = float(row["stake_units"])

        # ── VIP / FREE ──────────────────────────────────────────────────────
        if pick_type in ("vip", "free"):
            if pick_type == "vip":
                cur.execute("""
                    SELECT fixture_id, market, line, odd, result,
                           home_team_name AS home_team, away_team_name AS away_team,
                           home_team_id, away_team_id, match_date
                    FROM picks_vip WHERE id = %s
                """, (pick_id,))
            else:
                cur.execute("""
                    SELECT fixture_id, market, line, odd, result,
                           home_team, away_team, home_team_id, away_team_id, match_date
                    FROM picks_free WHERE id = %s
                """, (pick_id,))
            p = cur.fetchone()
            if not p or p["result"] is not None:
                continue

            odd = float(p["odd"] or 1)
            leg = _enrich_leg(
                p["fixture_id"], p["market"], p["line"],
                p["home_team"], p["away_team"],
                p["home_team_id"], p["away_team_id"],
                odd,
            )
            # Auto-save quando jogo encerrou
            if leg["is_ft"]:
                auto_res = _calc_result(
                    p["market"], p["line"],
                    leg["current_val"], leg["home_goals"], leg["away_goals"]
                )
                if auto_res:
                    _save_single_result(pick_id, pick_type, auto_res, odd, conn)
                    continue  # pick resolvido, sai da lista ao vivo

            result.append({
                "pick_id":     pick_id,
                "pick_type":   pick_type,
                "match_date":  str(p["match_date"]),
                "odd":         odd,
                "stake_units": stake_u,
                "is_live":     leg["is_live"],
                **{k: leg[k] for k in (
                    "fixture_id", "home_team", "away_team",
                    "home_team_id", "away_team_id",
                    "market", "line", "status", "elapsed",
                    "home_goals", "away_goals",
                    "stat_label", "current_val", "line_val",
                    "pick_status", "is_locked",
                )},
            })

        # ── MÚLTIPLA ────────────────────────────────────────────────────────
        elif pick_type == "multipla":
            cur.execute("""
                SELECT id, games, total_odd, result, match_date
                FROM picks_multiplas WHERE id = %s
            """, (pick_id,))
            p = cur.fetchone()
            if not p or p["result"] is not None:
                continue

            legs_raw = p["games"]
            if isinstance(legs_raw, str):
                try:
                    legs_raw = json.loads(legs_raw)
                except Exception:
                    legs_raw = []

            legs_out = []
            for leg_data in (legs_raw if isinstance(legs_raw, list) else []):
                fid = leg_data.get("fixture_id")
                if not fid:
                    continue
                home = leg_data.get("home") or leg_data.get("home_team") or ""
                away = leg_data.get("away") or leg_data.get("away_team") or ""
                h_id = leg_data.get("home_team_id")
                a_id = leg_data.get("away_team_id")
                if not home or not away:
                    cur.execute(
                        "SELECT home_team, away_team, home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
                        (fid,),
                    )
                    fx = cur.fetchone()
                    if fx:
                        home = home or fx["home_team"] or ""
                        away = away or fx["away_team"] or ""
                        h_id = h_id or fx["home_team_id"]
                        a_id = a_id or fx["away_team_id"]
                legs_out.append(_enrich_leg(
                    fid,
                    leg_data.get("market", ""),
                    leg_data.get("line", ""),
                    home,
                    away,
                    h_id,
                    a_id,
                    float(leg_data.get("odd", 1)),
                ))

            if legs_out:
                total_odd = float(p["total_odd"] or 1)
                # Auto-save quando todas as pernas encerraram
                if all(l["is_ft"] for l in legs_out):
                    leg_results = [
                        _calc_result(l["market"], l["line"], l["current_val"],
                                     l["home_goals"], l["away_goals"])
                        for l in legs_out
                    ]
                    _save_multipla_result(pick_id, leg_results, total_odd, conn)
                    continue

                result.append({
                    "pick_id":     pick_id,
                    "pick_type":   "multipla",
                    "match_date":  str(p["match_date"]),
                    "odd":         total_odd,
                    "stake_units": stake_u,
                    "is_live":     any(l["is_live"] for l in legs_out),
                    "legs":        legs_out,
                })

        # ── ALAVANCAGEM ─────────────────────────────────────────────────────
        elif pick_type == "alavancagem":
            cur.execute("""
                SELECT id, fixture_id_1, fixture_id_2,
                       market_1, line_1, odd_1, home_team_1, away_team_1,
                       market_2, line_2, odd_2, home_team_2, away_team_2,
                       odd_combined, result, match_date
                FROM picks_alavancagem WHERE id = %s
            """, (pick_id,))
            p = cur.fetchone()
            if not p or p["result"] is not None:
                continue

            legs_out = []
            for i in (1, 2):
                fid = p.get(f"fixture_id_{i}")
                if not fid:
                    continue
                # look up team_ids via fixtures table
                cur.execute(
                    "SELECT home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
                    (fid,),
                )
                fx = cur.fetchone()
                legs_out.append(_enrich_leg(
                    fid,
                    p.get(f"market_{i}", ""),
                    p.get(f"line_{i}", ""),
                    p.get(f"home_team_{i}", ""),
                    p.get(f"away_team_{i}", ""),
                    fx["home_team_id"] if fx else None,
                    fx["away_team_id"] if fx else None,
                    float(p.get(f"odd_{i}") or 1),
                ))

            if legs_out:
                odd_combined = float(p["odd_combined"] or 1)
                if all(l["is_ft"] for l in legs_out):
                    leg_results = [
                        _calc_result(l["market"], l["line"], l["current_val"],
                                     l["home_goals"], l["away_goals"])
                        for l in legs_out
                    ]
                    _save_alavancagem_result(pick_id, leg_results, odd_combined, conn)
                    continue

                result.append({
                    "pick_id":     pick_id,
                    "pick_type":   "alavancagem",
                    "match_date":  str(p["match_date"]),
                    "odd":         odd_combined,
                    "stake_units": stake_u,
                    "is_live":     any(l["is_live"] for l in legs_out),
                    "legs":        legs_out,
                })

    cur.close()
    conn.close()

    # Live picks first, then by date
    result.sort(key=lambda x: (0 if x.get("is_live") else 1, x.get("match_date", "")))
    return result
