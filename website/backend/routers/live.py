import os
import json
import time
import logging
import requests
from fastapi import APIRouter, Depends
from database import get_connection
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

API_BASE      = "https://v3.football.api-sports.io"
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"}
FT_STATUSES   = {"FT", "AET", "PEN"}

# TTL adaptativo: jogos ao vivo → curto; não iniciados → médio; encerrados → longo
_TTL_LIVE = 10   # segundos — atualiza depressa durante o jogo
_TTL_NS   = 60   # segundos — jogo ainda não começou
_TTL_FT   = 300  # segundos — encerrado, dados não mudam

_fix_cache:   dict[int, tuple[float, dict]] = {}
_stats_cache: dict[int, tuple[float, list]] = {}


def _cache_ttl(status: str) -> int:
    if status in LIVE_STATUSES:
        return _TTL_LIVE
    if status in FT_STATUSES:
        return _TTL_FT
    return _TTL_NS


def _headers():
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _fetch_fixture(fid: int) -> dict:
    now = time.time()
    if fid in _fix_cache:
        ts, cached = _fix_cache[fid]
        status = cached.get("fixture", {}).get("status", {}).get("short", "NS")
        if now - ts < _cache_ttl(status):
            return cached
    try:
        r = requests.get(f"{API_BASE}/fixtures", headers=_headers(),
                         params={"id": fid, "timezone": "America/Sao_Paulo"}, timeout=10)
        items = r.json().get("response", [])
        data  = items[0] if items else {}
    except Exception as e:
        logger.error("[LIVE] fixture %s: %s", fid, e)
        data = _fix_cache.get(fid, (0, {}))[1]  # mantém cache antigo em caso de erro
    _fix_cache[fid] = (now, data)
    return data


def _fetch_stats(fid: int, status: str) -> list:
    now = time.time()
    if fid in _stats_cache:
        ts, cached = _stats_cache[fid]
        if now - ts < _cache_ttl(status):
            return cached
    try:
        r = requests.get(f"{API_BASE}/fixtures/statistics", headers=_headers(),
                         params={"fixture": fid}, timeout=10)
        data = r.json().get("response", [])
    except Exception as e:
        logger.error("[LIVE STATS] fixture %s: %s", fid, e)
        data = _stats_cache.get(fid, (0, []))[1]  # mantém cache antigo em caso de erro
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
    """Resultado definitivo de um pick com jogo encerrado.

    Suporta handicap asiático quarter-ball (.25 / .75):
      Over X.25: GREEN se cur>X, HALF-LOSS se cur==X, RED se cur<X
      Over X.75: GREEN se cur>X+1, HALF-WIN se cur==X+1, RED se cur<=X
      Under X.25: GREEN se cur<X, HALF-WIN se cur==X, RED se cur>X
      Under X.75: GREEN se cur<=X, HALF-LOSS se cur==X+1, RED se cur>X+1
    Linhas inteiras (.0): PUSH quando cur==line.
    Linhas em .5: nunca PUSH (stats são inteiros).
    """
    if cur_val is None:
        return None
    direction, line_val = _extract_line(line)

    if direction in ("over", "under") and line_val is not None:
        frac = round(line_val % 1, 2)  # 0.0 | 0.25 | 0.5 | 0.75
        v    = int(cur_val)             # stats são sempre inteiros

        if direction == "over":
            if frac == 0.25:
                # split: Over floor e Over floor+0.5
                # floor = int(line_val)  ex: 2.25 → 2
                f = int(line_val)
                if v > f:   return "GREEN"
                if v == f:  return "HALF-LOSS"
                return "RED"
            elif frac == 0.75:
                # split: Over floor+0.5 e Over ceil
                # ceil = int(line_val) + 1  ex: 2.75 → ceil = 3
                c = int(line_val) + 1
                if v > c:   return "GREEN"
                if v == c:  return "HALF-WIN"
                return "RED"
            else:
                # .0 ou .5
                if v > line_val:   return "GREEN"
                if v < line_val:   return "RED"
                return "PUSH"   # só possível em linhas .0

        else:  # under
            if frac == 0.25:
                f = int(line_val)
                if v < f:   return "GREEN"
                if v == f:  return "HALF-WIN"
                return "RED"
            elif frac == 0.75:
                c = int(line_val) + 1
                if v < c:   return "GREEN"
                if v == c:  return "HALF-LOSS"
                return "RED"
            else:
                if v < line_val:   return "GREEN"
                if v > line_val:   return "RED"
                return "PUSH"

    if direction == "result":
        pst = _result_pick_status(line, home_goals, away_goals)
        return "GREEN" if pst == "winning" else "RED"
    return None


def _locked_leg_result(leg: dict) -> str | None:
    """
    Retorna resultado definitivo de uma leg se já determinado, else None.
    FT  → resultado completo via _calc_result.
    Bloqueado antes do FT (over/under cujo valor já cruzou a linha) → RED ou GREEN antecipado.
    """
    if leg["is_ft"]:
        return _calc_result(
            leg["market"], leg["line"],
            leg["current_val"], leg["home_goals"], leg["away_goals"],
        )
    if leg.get("is_locked"):
        direction, line_val = _extract_line(leg["line"])
        cur = leg.get("current_val")
        if cur is not None and line_val is not None:
            if direction == "under" and cur >= line_val:
                return "RED"    # Under X com cur >= X: impossível de recuperar
            if direction == "over" and cur > line_val:
                return "GREEN"  # Over X com cur > X: nunca vai descer
    return None


def _profit_for_result(result: str, odd: float) -> float:
    """Lucro por unidade apostada para cada tipo de resultado."""
    o = float(odd)
    if result == "GREEN":      return round(o - 1, 4)
    if result == "HALF-WIN":   return round((o - 1) / 2, 4)
    if result == "PUSH":       return 0.0
    if result == "HALF-LOSS":  return -0.5
    return -1.0  # RED


def _save_single_result(pick_id: int, pick_type: str, result: str, odd: float, conn) -> None:
    profit = _profit_for_result(result, odd)
    tbl = "picks_vip" if pick_type == "vip" else "picks_free"
    c = conn.cursor()
    c.execute(f"UPDATE {tbl} SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] %s #%s → %s (%+.4fu)", pick_type, pick_id, result, profit)


def _multipla_combined_result(legs_results: list[str | None]) -> str | None:
    """Resultado combinado de uma múltipla: qualquer RED → RED, qualquer HALF → propaga."""
    if any(r is None for r in legs_results):
        return None  # nem todas as pernas encerradas
    if any(r == "RED" for r in legs_results):
        return "RED"
    if all(r == "GREEN" for r in legs_results):
        return "GREEN"
    # mix de GREEN, PUSH, HALF-WIN, HALF-LOSS → PUSH
    return "PUSH"


def _save_multipla_result(pick_id: int, legs_results: list[str | None],
                          total_odd: float, conn) -> None:
    result = _multipla_combined_result(legs_results)
    if result is None:
        return
    profit = _profit_for_result(result, total_odd)
    c = conn.cursor()
    c.execute("UPDATE picks_multiplas SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] multipla #%s → %s (%+.4fu)", pick_id, result, profit)


def _save_alavancagem_result(pick_id: int, legs_results: list[str | None],
                             odd_combined: float, conn) -> None:
    result = _multipla_combined_result(legs_results)
    if result is None:
        return
    profit = _profit_for_result(result, odd_combined)
    c = conn.cursor()
    c.execute("UPDATE picks_alavancagem SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] alavancagem #%s → %s (%+.2fu)", pick_id, result, profit)


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
        home_stats, away_stats = _parse_stats(_fetch_stats(fid, status))

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
                           home_team_id, away_team_id, match_date, league_id
                    FROM picks_vip WHERE id = %s
                """, (pick_id,))
            else:
                cur.execute("""
                    SELECT fixture_id, market, line, odd, result,
                           home_team, away_team, home_team_id, away_team_id, match_date, league_id
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
                "league_id":   p.get("league_id"),
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
                total_odd   = float(p["total_odd"] or 1)
                leg_results = [_locked_leg_result(l) for l in legs_out]
                if any(r == "RED" for r in leg_results):
                    # Early RED: uma perna já perdeu — não precisamos esperar as outras
                    _save_multipla_result(pick_id, ["RED"] * len(legs_out), total_odd, conn)
                    continue
                if all(r is not None for r in leg_results):
                    # Todas as pernas encerradas sem RED
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
                leg_results  = [_locked_leg_result(l) for l in legs_out]
                if any(r == "RED" for r in leg_results):
                    _save_alavancagem_result(pick_id, ["RED"] * len(legs_out), odd_combined, conn)
                    continue
                if all(r is not None for r in leg_results):
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


# ─── Job de background ───────────────────────────────────────────────────────

def resolve_all_pending() -> dict:
    """
    Tenta resolver todos os picks pendentes usando dados ao vivo da API.
    Chamado pelo APScheduler a cada 5 min. Retorna contagem de resolvidos por tipo.
    """
    conn = get_connection()
    cur  = conn.cursor()
    resolved: dict = {"vip": 0, "free": 0, "multipla": 0, "alavancagem": 0}

    try:
        # ── VIP ──────────────────────────────────────────────────────────────
        cur.execute("""
            SELECT id, fixture_id, market, line, odd,
                   home_team_name AS home_team, away_team_name AS away_team,
                   home_team_id, away_team_id
            FROM picks_vip WHERE result IS NULL AND fixture_id IS NOT NULL
        """)
        for p in cur.fetchall():
            odd = float(p["odd"] or 1)
            leg = _enrich_leg(p["fixture_id"], p["market"], p["line"],
                              p["home_team"], p["away_team"],
                              p["home_team_id"], p["away_team_id"], odd)
            if leg["is_ft"]:
                res = _calc_result(p["market"], p["line"],
                                   leg["current_val"], leg["home_goals"], leg["away_goals"])
                if res:
                    _save_single_result(p["id"], "vip", res, odd, conn)
                    resolved["vip"] += 1

        # ── FREE ─────────────────────────────────────────────────────────────
        cur.execute("""
            SELECT id, fixture_id, market, line, odd,
                   home_team, away_team, home_team_id, away_team_id
            FROM picks_free WHERE result IS NULL AND fixture_id IS NOT NULL
        """)
        for p in cur.fetchall():
            odd = float(p["odd"] or 1)
            leg = _enrich_leg(p["fixture_id"], p["market"], p["line"],
                              p["home_team"], p["away_team"],
                              p["home_team_id"], p["away_team_id"], odd)
            if leg["is_ft"]:
                res = _calc_result(p["market"], p["line"],
                                   leg["current_val"], leg["home_goals"], leg["away_goals"])
                if res:
                    _save_single_result(p["id"], "free", res, odd, conn)
                    resolved["free"] += 1

        # ── MÚLTIPLA ─────────────────────────────────────────────────────────
        cur.execute("SELECT id, games, total_odd FROM picks_multiplas WHERE result IS NULL")
        for p in cur.fetchall():
            games = p["games"]
            if isinstance(games, str):
                try:    games = json.loads(games)
                except: continue
            if not isinstance(games, list) or not games:
                continue

            legs_out = []
            for leg_data in games:
                fid = leg_data.get("fixture_id")
                if not fid:
                    continue
                home = leg_data.get("home") or leg_data.get("home_team") or ""
                away = leg_data.get("away") or leg_data.get("away_team") or ""
                legs_out.append(_enrich_leg(
                    fid,
                    leg_data.get("market", ""),
                    leg_data.get("line", ""),
                    home, away,
                    leg_data.get("home_team_id"),
                    leg_data.get("away_team_id"),
                    float(leg_data.get("odd", 1)),
                ))

            if not legs_out:
                continue

            total_odd   = float(p["total_odd"] or 1)
            leg_results = [_locked_leg_result(l) for l in legs_out]
            if any(r == "RED" for r in leg_results):
                _save_multipla_result(p["id"], ["RED"] * len(legs_out), total_odd, conn)
                resolved["multipla"] += 1
            elif all(r is not None for r in leg_results):
                _save_multipla_result(p["id"], leg_results, total_odd, conn)
                resolved["multipla"] += 1

        # ── ALAVANCAGEM ──────────────────────────────────────────────────────
        cur.execute("""
            SELECT id, fixture_id_1, fixture_id_2,
                   market_1, line_1, odd_1, home_team_1, away_team_1,
                   market_2, line_2, odd_2, home_team_2, away_team_2,
                   odd_combined
            FROM picks_alavancagem WHERE result IS NULL
        """)
        for p in cur.fetchall():
            legs_out = []
            for i in (1, 2):
                fid = p.get(f"fixture_id_{i}")
                if not fid:
                    continue
                c2 = conn.cursor()
                try:
                    c2.execute(
                        "SELECT home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
                        (fid,),
                    )
                    fx = c2.fetchone()
                finally:
                    c2.close()
                legs_out.append(_enrich_leg(
                    fid,
                    p.get(f"market_{i}", ""),
                    p.get(f"line_{i}", ""),
                    p.get(f"home_team_{i}", "") or "",
                    p.get(f"away_team_{i}", "") or "",
                    fx["home_team_id"] if fx else None,
                    fx["away_team_id"] if fx else None,
                    float(p.get(f"odd_{i}") or 1),
                ))

            if not legs_out:
                continue

            odd_combined = float(p["odd_combined"] or 1)
            leg_results  = [_locked_leg_result(l) for l in legs_out]
            if any(r == "RED" for r in leg_results):
                _save_alavancagem_result(p["id"], ["RED"] * len(legs_out), odd_combined, conn)
                resolved["alavancagem"] += 1
            elif all(r is not None for r in leg_results):
                _save_alavancagem_result(p["id"], leg_results, odd_combined, conn)
                resolved["alavancagem"] += 1

    finally:
        cur.close()
        conn.close()

    logger.info("[AUTO-RESULT] resolvidos: %s", resolved)
    return resolved
