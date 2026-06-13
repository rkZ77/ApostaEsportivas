from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
import psycopg2.extras
from database import get_connection
from auth_utils import get_current_user, require_vip

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


def _safe_query(cur, sql, params=()):
    """Executa query e retorna resultados, ou [] se tabela não existir."""
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception:
        cur.connection.rollback()
        return []


def _safe_query_one(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except Exception:
        cur.connection.rollback()
        return None


def _enrich_multipla_legs(cur, rows: list) -> list:
    """Enriquece o JSONB de legs das múltiplas com home/away team IDs e nomes via fixtures."""
    import json as _json
    result = []
    for row in rows:
        m = dict(row)
        legs = m.get("legs") or []
        if isinstance(legs, str):
            try:
                legs = _json.loads(legs)
            except Exception:
                legs = []
        enriched = []
        for leg in (legs if isinstance(legs, list) else []):
            fid = leg.get("fixture_id") if isinstance(leg, dict) else None
            if fid:
                fx = _safe_query_one(cur, """
                    SELECT home_team, away_team, home_team_id, away_team_id, league_id
                    FROM fixtures WHERE fixture_id = %s
                """, (fid,))
                if fx:
                    leg = dict(leg)
                    leg.update({
                        "home": fx["home_team"],
                        "away": fx["away_team"],
                        "home_team_id": fx["home_team_id"],
                        "away_team_id": fx["away_team_id"],
                        "league_id":    fx["league_id"],
                    })
            enriched.append(leg)
        m["legs"] = enriched
        result.append(m)
    return result


@router.get("/today")
def get_today_suggestions(current_user: dict = Depends(get_current_user)):
    plan = current_user.get("plan", "free")
    is_vip = plan in ("vip", "admin")
    conn = get_connection()
    cur = conn.cursor()
    try:
        result = {}

        # Data de hoje no fuso de Brasília (UTC-3)
        TODAY_BR = "(NOW() AT TIME ZONE 'America/Sao_Paulo')::date"

        # Query reutilizável para picks_free — usa colunas diretas + fallback via JOIN
        _picks_free_sql = f"""
            SELECT pf.id, pf.fixture_id, pf.match_date, pf.home_team, pf.away_team,
                   pf.league_id, pf.league_name, pf.market, pf.line, pf.odd, pf.bet_house,
                   pf.confidence, pf.reasoning, pf.result, pf.profit,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            WHERE pf.match_date = {TODAY_BR}
               OR (pf.result IS NULL AND pf.match_date >= {TODAY_BR} - INTERVAL '3 days')
            ORDER BY pf.match_date DESC, pf.created_at DESC
            LIMIT 1
        """

        if is_vip:
            row = _safe_query_one(cur, _picks_free_sql)
            result["dica_do_dia"] = dict(row) if row else None

            # VIP picks completos com league_id e league_name
            rows = _safe_query(cur, f"""
                SELECT s.id, s.fixture_id, s.match_date,
                       s.home_team_name, s.away_team_name,
                       s.home_team_id, s.away_team_id,
                       s.market, s.line, s.odd, s.bet_house,
                       s.market_type, s.confidence, s.stake, s.ev,
                       s.reasoning, s.result, s.profit,
                       f.league_id,
                       l.name AS league_name
                FROM picks_vip s
                LEFT JOIN fixtures f ON f.fixture_id = s.fixture_id
                LEFT JOIN leagues l ON l.league_id = f.league_id
                WHERE s.match_date = {TODAY_BR}
                   OR (s.result IS NULL AND s.match_date >= {TODAY_BR} - INTERVAL '3 days')
                ORDER BY s.match_date DESC, s.confidence DESC
            """)
            result["vip"] = [dict(r) for r in rows]

            rows_m = _safe_query(cur, f"""
                SELECT id, match_date,
                       games AS legs,
                       total_odd, score_combo AS confidence,
                       reasoning, result, profit, created_at
                FROM picks_multiplas
                WHERE match_date = {TODAY_BR}
                   OR (result IS NULL AND match_date >= {TODAY_BR} - INTERVAL '3 days')
                ORDER BY match_date DESC, created_at DESC
                LIMIT 3
            """)
            result["multiplas"] = _enrich_multipla_legs(cur, rows_m)

            # Alavancagem — Copa do Mundo com team IDs
            alav = _safe_query_one(cur, f"""
                SELECT pa.id, pa.match_date, pa.tipo,
                       pa.home_team_1, pa.away_team_1, pa.market_1, pa.line_1, pa.odd_1, pa.bet_house_1,
                       pa.confidence_1, pa.reasoning_1,
                       pa.home_team_2, pa.away_team_2, pa.market_2, pa.line_2, pa.odd_2, pa.bet_house_2,
                       pa.confidence_2, pa.reasoning_2,
                       pa.odd_combined, pa.confidence_media,
                       pa.stake, pa.potential_return, pa.bankroll_before,
                       pa.result, pa.profit, pa.bankroll_after, pa.created_at,
                       f1.home_team_id AS home_team_id_1, f1.away_team_id AS away_team_id_1,
                       f2.home_team_id AS home_team_id_2, f2.away_team_id AS away_team_id_2
                FROM picks_alavancagem pa
                LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
                LEFT JOIN fixtures f2 ON f2.fixture_id = pa.fixture_id_2
                WHERE pa.match_date = {TODAY_BR}
                   OR (pa.result IS NULL AND pa.match_date >= {TODAY_BR} - INTERVAL '3 days')
                ORDER BY pa.match_date DESC
                LIMIT 1
            """)
            result["alavancagem"] = dict(alav) if alav else None
        else:
            row = _safe_query_one(cur, _picks_free_sql)
            result["dica_do_dia"] = dict(row) if row else None

        # Adiciona is_followed para VIP picks e dica_do_dia
        user_id = current_user.get("id")
        if user_id and result.get("vip"):
            vip_ids = [p["id"] for p in result["vip"] if p.get("id")]
            if vip_ids:
                frows = _safe_query(cur, """
                    SELECT pick_id FROM user_followed_picks
                    WHERE user_id = %s AND pick_type = 'vip' AND pick_id = ANY(%s)
                """, (user_id, vip_ids))
                followed_set = {r["pick_id"] for r in frows}
                for p in result["vip"]:
                    p["is_followed"] = p.get("id") in followed_set
                    p["pick_type"] = "vip"

        if user_id and result.get("dica_do_dia"):
            dica = result["dica_do_dia"]
            dica_id = dica.get("id")
            if dica_id:
                frow = _safe_query_one(cur, """
                    SELECT id FROM user_followed_picks
                    WHERE user_id = %s AND pick_type = 'free' AND pick_id = %s
                """, (user_id, dica_id))
                dica["is_followed"] = frow is not None
                dica["pick_type"] = "free"

        if user_id and result.get("multiplas"):
            m_ids = [m["id"] for m in result["multiplas"] if m.get("id")]
            if m_ids:
                frows = _safe_query(cur, """
                    SELECT pick_id FROM user_followed_picks
                    WHERE user_id = %s AND pick_type = 'multipla' AND pick_id = ANY(%s)
                """, (user_id, m_ids))
                followed_set = {r["pick_id"] for r in frows}
                for m in result["multiplas"]:
                    m["is_followed"] = m.get("id") in followed_set
                    m["pick_type"] = "multipla"

        if user_id and result.get("alavancagem"):
            alav = result["alavancagem"]
            alav_id = alav.get("id")
            if alav_id:
                frow = _safe_query_one(cur, """
                    SELECT id FROM user_followed_picks
                    WHERE user_id = %s AND pick_type = 'alavancagem' AND pick_id = %s
                """, (user_id, alav_id))
                alav["is_followed"] = frow is not None
                alav["pick_type"] = "alavancagem"

        return result
    finally:
        cur.close()
        conn.close()


@router.get("/vip")
def get_vip_suggestions(
    current_user: dict = Depends(require_vip),
    date_from:    Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:      Optional[str] = Query(None, description="YYYY-MM-DD"),
    market_type:  Optional[str] = Query(None, description="goals|corners|cards|result|btts"),
    resultado:    Optional[str] = Query(None, description="pending|GREEN|RED|PUSH|HALF-WIN|HALF-LOSS"),
    min_conf:     Optional[float] = Query(None, ge=0, le=1, description="0.0–1.0"),
    bet_house:    Optional[str] = Query(None),
    order_by:     str = Query("confidence", description="confidence|odd|match_date"),
    limit:        int = Query(50, ge=1, le=200),
):
    """Sugestões VIP com filtros dinâmicos."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions = []
        params = []

        # Data
        if date_from:
            conditions.append("s.match_date >= %s")
            params.append(date_from)
        else:
            conditions.append("s.match_date = CURRENT_DATE")

        if date_to:
            conditions.append("s.match_date <= %s")
            params.append(date_to)

        # Tipo de mercado
        if market_type and market_type != "all":
            conditions.append("s.market_type = %s")
            params.append(market_type)

        # Resultado
        if resultado == "pending":
            conditions.append("s.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("s.result = %s")
            params.append(resultado)

        # Confiança mínima
        if min_conf is not None:
            conditions.append("s.confidence >= %s")
            params.append(min_conf)

        # Casa de aposta
        if bet_house and bet_house != "all":
            conditions.append("s.bet_house ILIKE %s")
            params.append(f"%{bet_house}%")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        safe_order = {
            "confidence": "s.confidence DESC",
            "odd":        "s.odd DESC",
            "match_date": "s.match_date DESC, s.id DESC",
        }.get(order_by, "s.confidence DESC")

        params.append(limit)

        rows = _safe_query(cur, f"""
            SELECT
                s.id, s.fixture_id, s.match_date,
                s.home_team_name, s.away_team_name,
                s.home_team_id, s.away_team_id,
                s.market, s.line, s.odd, s.bet_house,
                s.market_type, s.confidence, s.stake, s.ev,
                s.reasoning, s.result, s.profit,
                s.created_at
            FROM picks_vip s
            {where}
            ORDER BY {safe_order}
            LIMIT %s
        """, params)

        picks = [dict(r) for r in rows]

        # Adiciona is_followed
        user_id = current_user.get("id")
        if user_id and picks:
            pick_ids = [p["id"] for p in picks if p.get("id")]
            if pick_ids:
                frows = _safe_query(cur, """
                    SELECT pick_id FROM user_followed_picks
                    WHERE user_id = %s AND pick_type = 'vip' AND pick_id = ANY(%s)
                """, (user_id, pick_ids))
                followed_set = {r["pick_id"] for r in frows}
                for p in picks:
                    p["is_followed"] = p.get("id") in followed_set
                    p["pick_type"] = "vip"

        return picks
    finally:
        cur.close()
        conn.close()


@router.get("/vip/meta")
def get_vip_meta(current_user: dict = Depends(require_vip)):
    """Retorna valores únicos para popular os selects de filtro."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        houses = _safe_query(cur, "SELECT DISTINCT bet_house FROM picks_vip WHERE bet_house IS NOT NULL ORDER BY bet_house")
        types  = _safe_query(cur, "SELECT DISTINCT market_type FROM picks_vip WHERE market_type IS NOT NULL ORDER BY market_type")
        return {
            "bet_houses":   [r["bet_house"] for r in houses],
            "market_types": [r["market_type"] for r in types],
        }
    finally:
        cur.close()
        conn.close()


@router.get("/{suggestion_id}/detail")
def get_suggestion_detail(
    suggestion_id: int,
    pick_type: str = Query("vip"),
    current_user: dict = Depends(get_current_user),
):
    """Detalhe completo: stats dos times, últimas 5 partidas, reasoning e odds."""
    import json as _json
    conn = get_connection()
    cur = conn.cursor()
    try:
        from fastapi import HTTPException

        is_vip = current_user.get("plan") in ("vip", "admin")

        # ── MÚLTIPLA ────────────────────────────────────────────────────────
        if pick_type == "multipla":
            cur.execute("""
                SELECT id, match_date, games AS legs,
                       total_odd, score_combo AS confidence,
                       reasoning, result, profit, created_at
                FROM picks_multiplas WHERE id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Múltipla não encontrada")
            d = dict(row)
            if not is_vip and not d.get("result"):
                raise HTTPException(403, "Acesso VIP necessário para picks pendentes")
            try:
                legs = _json.loads(d["legs"]) if isinstance(d["legs"], str) else (d["legs"] or [])
            except Exception:
                legs = []

            # Enriquece cada leg com nomes e IDs dos times via fixtures
            fixture_ids = [leg["fixture_id"] for leg in legs if leg.get("fixture_id")]
            fixture_map: dict = {}
            if fixture_ids:
                frows = _safe_query(cur, """
                    SELECT f.fixture_id,
                           f.home_team_id, f.away_team_id,
                           f.match_datetime,
                           ht.name AS home_team, at.name AS away_team
                    FROM fixtures f
                    LEFT JOIN teams ht ON ht.team_id = f.home_team_id
                    LEFT JOIN teams at ON at.team_id = f.away_team_id
                    WHERE f.fixture_id = ANY(%s)
                """, (fixture_ids,))
                for fr in frows:
                    fixture_map[fr["fixture_id"]] = fr

            enriched_legs = []
            for leg in legs:
                fid = leg.get("fixture_id")
                fi  = fixture_map.get(fid, {}) if fid else {}
                enriched_legs.append({
                    **leg,
                    "home_team":    fi.get("home_team") or leg.get("home_team") or leg.get("home"),
                    "away_team":    fi.get("away_team") or leg.get("away_team") or leg.get("away"),
                    "home_team_id": fi.get("home_team_id") or leg.get("home_team_id"),
                    "away_team_id": fi.get("away_team_id") or leg.get("away_team_id"),
                    "match_datetime": str(fi["match_datetime"]) if fi.get("match_datetime") else None,
                })

            n = len(enriched_legs)
            suggestion = {
                "id": d["id"],
                "match_date": d["match_date"],
                "home_team_name": f"Múltipla — {n} seleções",
                "away_team_name": "",
                "market": f"{n} seleções",
                "line": None,
                "odd": d["total_odd"],
                "confidence": d["confidence"],
                "reasoning": d["reasoning"],
                "result": d["result"],
                "profit": d["profit"],
                "legs": enriched_legs,
                "pick_type": "multipla",
            }
            ufp_m = _safe_query_one(cur, """
                SELECT stake_units FROM user_followed_picks
                WHERE user_id = %s AND pick_id = %s AND pick_type = 'multipla'
            """, (current_user["id"], suggestion_id))
            suggestion["user_stake_units"] = float(ufp_m["stake_units"]) if ufp_m else None
            return {"suggestion": suggestion, "home_stats": {}, "away_stats": {},
                    "home_recent": [], "away_recent": [], "odds": []}

        # ── ALAVANCAGEM ──────────────────────────────────────────────────────
        if pick_type == "alavancagem":
            cur.execute("""
                SELECT pa.*,
                       f1.match_datetime AS match_datetime,
                       f1.home_team_id   AS home_team_id,
                       f1.away_team_id   AS away_team_id,
                       f1.league_id      AS fix_league_id,
                       f1.season         AS fix_season
                FROM picks_alavancagem pa
                LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
                WHERE pa.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Alavancagem não encontrada")
            d = dict(row)
            if not is_vip and not d.get("result"):
                raise HTTPException(403, "Acesso VIP necessário para picks pendentes")
            legs = []
            if d.get("home_team_1"):
                legs.append({
                    "home": d["home_team_1"], "away": d["away_team_1"],
                    "market": d.get("market_1"), "line": d.get("line_1"),
                    "odd": d.get("odd_1"), "house": d.get("bet_house_1"),
                    "reasoning": d.get("reasoning_1"),
                })
            if d.get("home_team_2"):
                legs.append({
                    "home": d["home_team_2"], "away": d["away_team_2"],
                    "market": d.get("market_2"), "line": d.get("line_2"),
                    "odd": d.get("odd_2"), "house": d.get("bet_house_2"),
                    "reasoning": d.get("reasoning_2"),
                })
            alav_suggestion = {
                "id": d["id"],
                "fixture_id": d.get("fixture_id_1"),
                "match_date": d["match_date"],
                "match_datetime": d.get("match_datetime"),
                "home_team_name": d.get("home_team_1", "Alavancagem"),
                "away_team_name": d.get("away_team_1", ""),
                "home_team_id": d.get("home_team_id"),
                "away_team_id": d.get("away_team_id"),
                "fix_league_id": d.get("fix_league_id"),
                "fix_season": d.get("fix_season"),
                "market": d.get("market_1", "Alavancagem"),
                "line": d.get("line_1"),
                "odd": d.get("odd_combined"),
                "bet_house": d.get("bet_house_1"),
                "confidence": d.get("confidence_media"),
                "stake": d.get("stake"),
                "potential_return": d.get("potential_return"),
                "bankroll_before": d.get("bankroll_before"),
                "bankroll_after": d.get("bankroll_after"),
                "reasoning": d.get("reasoning_1") or "",
                "result": d["result"],
                "profit": d["profit"],
                "legs": legs,
                "pick_type": "alavancagem",
                "tipo": d.get("tipo"),
            }
            # Busca stats e forma do jogo principal (game 1)
            alav_home_id   = alav_suggestion.get("home_team_id")
            alav_away_id   = alav_suggestion.get("away_team_id")
            alav_league_id = alav_suggestion.get("fix_league_id")
            alav_season    = alav_suggestion.get("fix_season") or 2026

            STATS_COLS_ALV = """
                context_type,
                avg_goals_for, avg_goals_against, avg_total_goals,
                avg_corners_for, avg_corners_against, avg_total_corners,
                avg_yellow_for, avg_yellow_against, avg_total_yellow,
                avg_shots_on_for, avg_shots_on_against,
                avg_possession_for, avg_passes_accuracy_for,
                games_count
            """

            def get_alav_stats(team_id):
                res = {}
                if team_id and alav_league_id:
                    for r in _safe_query(cur, f"SELECT {STATS_COLS_ALV} FROM team_statistics WHERE team_id=%s AND league_id=%s AND season=%s ORDER BY context_type", (team_id, alav_league_id, alav_season)):
                        res[r["context_type"]] = dict(r)
                if not res and team_id:
                    for r in _safe_query(cur, f"SELECT {STATS_COLS_ALV} FROM team_statistics WHERE team_id=%s ORDER BY season DESC, context_type LIMIT 4", (team_id,)):
                        k = r["context_type"]
                        if k not in res:
                            res[k] = dict(r)
                return res

            def get_alav_recent(team_id, limit=5):
                if not team_id:
                    return []
                rows = _safe_query(cur, """
                    SELECT match_date, home_team_id, away_team_id,
                           home_goals, away_goals, total_goals,
                           home_corners, away_corners, total_corners
                    FROM match_statistics
                    WHERE (home_team_id = %s OR away_team_id = %s)
                      AND status IN ('FT', 'AET', 'PEN')
                    ORDER BY match_date DESC LIMIT %s
                """, (team_id, team_id, limit))
                result = []
                for r in rows:
                    rd = dict(r)
                    is_home = rd["home_team_id"] == team_id
                    rd["is_home"]   = is_home
                    rd["gf"]        = rd["home_goals"]   if is_home else rd["away_goals"]
                    rd["ga"]        = rd["away_goals"]   if is_home else rd["home_goals"]
                    rd["corners_f"] = rd["home_corners"] if is_home else rd["away_corners"]
                    rd["corners_a"] = rd["away_corners"] if is_home else rd["home_corners"]
                    rd["resultado"] = "W" if rd["gf"] > rd["ga"] else ("D" if rd["gf"] == rd["ga"] else "L")
                    result.append(rd)
                return result

            ufp_a = _safe_query_one(cur, """
                SELECT stake_units FROM user_followed_picks
                WHERE user_id = %s AND pick_id = %s AND pick_type = 'alavancagem'
            """, (current_user["id"], suggestion_id))
            alav_suggestion["user_stake_units"] = float(ufp_a["stake_units"]) if ufp_a else None
            return {
                "suggestion":  alav_suggestion,
                "home_stats":  get_alav_stats(alav_home_id),
                "away_stats":  get_alav_stats(alav_away_id),
                "home_recent": get_alav_recent(alav_home_id),
                "away_recent": get_alav_recent(alav_away_id),
                "odds":        [],
            }

        # ── FREE (picks_free) ────────────────────────────────────────────────
        if pick_type == "free":
            cur.execute("""
                SELECT pf.id, pf.fixture_id, pf.match_date,
                       pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                       pf.league_id, pf.league_name, pf.market, pf.line,
                       pf.odd, pf.bet_house, pf.confidence, pf.reasoning,
                       pf.result, pf.profit,
                       COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                       COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                       f.match_datetime,
                       f.league_id AS fix_league_id, f.season AS fix_season
                FROM picks_free pf
                LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
                WHERE pf.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pick não encontrado")
            suggestion = dict(row)
        else:
            # ── VIP (default) ────────────────────────────────────────────────
            cur.execute("""
                SELECT s.*, f.match_datetime, f.league_id AS fix_league_id, f.season AS fix_season
                FROM picks_vip s
                LEFT JOIN fixtures f ON f.fixture_id = s.fixture_id
                WHERE s.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Sugestão não encontrada")
            suggestion = dict(row)
            if not is_vip and not suggestion.get("result"):
                raise HTTPException(403, "Acesso VIP necessário para picks pendentes")

        home_id = suggestion.get("home_team_id")
        away_id = suggestion.get("away_team_id")

        # Liga/season: vem do fixture se disponível, senão busca no match_statistics
        league_id = suggestion.get("fix_league_id")
        season    = suggestion.get("fix_season") or 2026

        if not league_id:
            ms_row = _safe_query_one(cur, """
                SELECT league_id, season FROM match_statistics
                WHERE fixture_id = %s LIMIT 1
            """, (suggestion["fixture_id"],))
            if ms_row:
                league_id = ms_row["league_id"]
                season    = ms_row["season"]

        # ── Médias dos times (busca no league certo, fallback em qualquer) ──
        STATS_COLS = """
            context_type,
            avg_goals_for, avg_goals_against, avg_total_goals,
            avg_corners_for, avg_corners_against, avg_total_corners,
            avg_yellow_for, avg_yellow_against, avg_total_yellow,
            avg_shots_on_for, avg_shots_on_against,
            avg_possession_for, avg_passes_accuracy_for,
            games_count
        """

        def get_team_stats(team_id):
            result = {}
            # 1. Liga exata + season
            if league_id:
                for r in _safe_query(cur, f"SELECT {STATS_COLS} FROM team_statistics WHERE team_id=%s AND league_id=%s AND season=%s ORDER BY context_type", (team_id, league_id, season)):
                    result[r["context_type"]] = dict(r)
            # 2. Qualquer liga, season mais recente
            if not result:
                for r in _safe_query(cur, f"SELECT {STATS_COLS} FROM team_statistics WHERE team_id=%s ORDER BY season DESC, context_type LIMIT 4", (team_id,)):
                    k = r["context_type"]
                    if k not in result:
                        result[k] = dict(r)
            return result

        home_stats = get_team_stats(home_id)
        away_stats = get_team_stats(away_id)

        # ── Últimas 5 partidas de cada time ─────────────────────────────────
        def get_recent(team_id, limit=5):
            rows = _safe_query(cur, """
                SELECT match_date, league_id, home_team_id, away_team_id,
                       home_goals, away_goals, total_goals,
                       home_corners, away_corners, total_corners,
                       home_yellow_cards, away_yellow_cards,
                       home_possession, away_possession, status
                FROM match_statistics
                WHERE (home_team_id = %s OR away_team_id = %s)
                  AND status IN ('FT', 'AET', 'PEN')
                ORDER BY match_date DESC
                LIMIT %s
            """, (team_id, team_id, limit))
            result = []
            for r in rows:
                d = dict(r)
                is_home = d["home_team_id"] == team_id
                d["is_home"]   = is_home
                d["gf"]        = d["home_goals"]   if is_home else d["away_goals"]
                d["ga"]        = d["away_goals"]   if is_home else d["home_goals"]
                d["corners_f"] = d["home_corners"] if is_home else d["away_corners"]
                d["corners_a"] = d["away_corners"] if is_home else d["home_corners"]
                d["resultado"] = "W" if d["gf"] > d["ga"] else ("D" if d["gf"] == d["ga"] else "L")
                result.append(d)
            return result

        home_recent = get_recent(home_id)
        away_recent = get_recent(away_id)

        # ── Odds do fixture ──────────────────────────────────────────────────
        odds_rows = _safe_query(cur, """
            SELECT DISTINCT ov.market_name, ov.value_name, ov.odd_value,
                            ov.bookmaker_name, ov.market_type, ov.side_team
            FROM odds_values ov
            WHERE ov.fixture_id = %s
            ORDER BY ov.market_type, ov.odd_value
            LIMIT 80
        """, (suggestion["fixture_id"],))

        ufp_v = _safe_query_one(cur, """
            SELECT stake_units FROM user_followed_picks
            WHERE user_id = %s AND pick_id = %s AND pick_type = %s
        """, (current_user["id"], suggestion_id, pick_type))
        suggestion["user_stake_units"] = float(ufp_v["stake_units"]) if ufp_v else None

        return {
            "suggestion":  suggestion,
            "home_stats":  home_stats,
            "away_stats":  away_stats,
            "home_recent": home_recent,
            "away_recent": away_recent,
            "odds":        [dict(r) for r in odds_rows],
        }
    finally:
        cur.close()
        conn.close()


@router.get("/{fixture_id}/standings")
async def get_standings_for_fixture(
    fixture_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Classificação da liga do jogo — direto da API-Football (sem cache)."""
    from futebol_agent.api_football import get_standings

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            "SELECT league_id, home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
            (fixture_id,),
        )
        fx = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not fx:
        return {"groups": [], "home_team_id": None, "away_team_id": None}

    league_id = fx["league_id"]
    home_id   = fx["home_team_id"]
    away_id   = fx["away_team_id"]

    try:
        raw_groups = await get_standings(league_id)
    except Exception:
        return {"groups": [], "home_team_id": home_id, "away_team_id": away_id}

    def _fmt(entry: dict) -> dict:
        team  = entry.get("team", {})
        stats = entry.get("all", {})
        goals = stats.get("goals", {})
        return {
            "pos":     entry.get("rank"),
            "team_id": team.get("id"),
            "team":    team.get("name"),
            "pts":     entry.get("points"),
            "played":  stats.get("played"),
            "won":     stats.get("win"),
            "draw":    stats.get("draw"),
            "lost":    stats.get("lose"),
            "gf":      goals.get("for"),
            "ga":      goals.get("against"),
            "gd":      entry.get("goalsDiff"),
            "form":    entry.get("form", ""),
        }

    groups = []
    for group in raw_groups:
        name = group[0].get("group", "") if group else ""
        groups.append({"group": name, "teams": [_fmt(e) for e in group]})

    return {"groups": groups, "home_team_id": home_id, "away_team_id": away_id}


@router.get("/history")
def get_history(days: int = 30, current_user: dict = Depends(require_vip)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        rows = _safe_query(cur, """
            SELECT s.id, s.fixture_id, s.match_date,
                   s.home_team_name, s.away_team_name,
                   s.home_team_id, s.away_team_id,
                   s.market, s.line, s.odd, s.bet_house,
                   s.confidence, s.stake, s.ev,
                   s.result, s.profit
            FROM picks_vip s
            WHERE s.match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
              AND s.result IS NOT NULL
            ORDER BY s.match_date DESC, s.id DESC
        """, (days,))
        return [dict(r) for r in rows]
    finally:
        cur.close()
        conn.close()


@router.get("/recent-results")
def get_recent_results(
    limit: int = Query(15, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Resultados recentes de todas as fontes: VIP, Free, Múltiplas, Alavancagem."""
    is_vip = current_user.get("plan") in ("vip", "admin")
    conn = get_connection()
    cur = conn.cursor()
    try:
        results = []

        # ── VIP (resultados visíveis para todos) ────────────────────────────
        rows = _safe_query(cur, """
            SELECT pv.id, pv.match_date,
                   pv.home_team_name, pv.away_team_name,
                   pv.home_team_id, pv.away_team_id,
                   pv.market, pv.line, pv.odd, pv.bet_house,
                   pv.confidence, pv.result, pv.profit,
                   COALESCE(ufp.stake_units, 1) AS stake
            FROM picks_vip pv
            LEFT JOIN user_followed_picks ufp
                ON ufp.pick_id = pv.id AND ufp.pick_type = 'vip' AND ufp.user_id = %s
            WHERE pv.result IS NOT NULL
            ORDER BY pv.match_date DESC, pv.id DESC
            LIMIT %s
        """, (current_user["id"], limit))
        for r in rows:
            d = dict(r)
            d["pick_type"] = "vip"
            results.append(d)

        # ── FREE ─────────────────────────────────────────────────────────────
        rows = _safe_query(cur, """
            SELECT pf.id, pf.match_date,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, f.home_team_id,
                       (SELECT fx.home_team_id FROM fixtures fx
                        WHERE fx.home_team = pf.home_team AND fx.home_team_id IS NOT NULL LIMIT 1)
                   ) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id,
                       (SELECT fx.away_team_id FROM fixtures fx
                        WHERE fx.away_team = pf.away_team AND fx.away_team_id IS NOT NULL LIMIT 1)
                   ) AS away_team_id,
                   pf.market, pf.line, pf.odd, pf.bet_house,
                   pf.confidence, pf.result, pf.profit,
                   COALESCE(ufp.stake_units, 1) AS stake
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            LEFT JOIN user_followed_picks ufp
                ON ufp.pick_id = pf.id AND ufp.pick_type = 'free' AND ufp.user_id = %s
            WHERE pf.result IS NOT NULL
            ORDER BY pf.match_date DESC, pf.id DESC
            LIMIT %s
        """, (current_user["id"], limit,))
        for r in rows:
            d = dict(r)
            d["pick_type"] = "free"
            results.append(d)

        # ── MÚLTIPLAS (resultados visíveis para todos) ───────────────────────
        rows = _safe_query(cur, """
            SELECT pm.id, pm.match_date,
                   pm.total_odd AS odd,
                   pm.score_combo AS confidence,
                   pm.result, pm.profit,
                   pm.games AS legs,
                   COALESCE(ufp.stake_units, 1) AS stake
            FROM picks_multiplas pm
            LEFT JOIN user_followed_picks ufp
                ON ufp.pick_id = pm.id AND ufp.pick_type = 'multipla' AND ufp.user_id = %s
            WHERE pm.result IS NOT NULL
            ORDER BY pm.match_date DESC, pm.id DESC
            LIMIT %s
        """, (current_user["id"], limit,))
        import json as _json
        for r in rows:
            d = dict(r)
            try:
                legs = _json.loads(d["legs"]) if isinstance(d["legs"], str) else (d["legs"] or [])
            except Exception:
                legs = []
            n = len(legs)
            first = legs[0] if legs else {}
            d["home_team_name"] = first.get("home") or first.get("home_team") or f"Múltipla · {n} seleções"
            d["away_team_name"] = first.get("away") or first.get("away_team") or ""
            d["home_team_id"]   = first.get("home_team_id")
            d["away_team_id"]   = first.get("away_team_id")
            d["market"]         = f"Múltipla · {n} seleções"
            d["line"]           = None
            d["bet_house"]      = None
            d["legs_count"]     = n
            # recalcula profit por unidade igual banca.py (ignora valor armazenado)
            result_val = d.get("result")
            odd_val = float(d.get("odd") or 1)
            if result_val == "GREEN":
                d["profit"] = round(odd_val - 1, 4)
            elif result_val == "RED":
                d["profit"] = -1.0
            elif result_val == "PUSH":
                d["profit"] = 0.0
            del d["legs"]
            d["pick_type"] = "multipla"
            results.append(d)

        # ── ALAVANCAGEM (resultados visíveis para todos) ─────────────────────
        rows = _safe_query(cur, """
            SELECT pa.id, pa.match_date,
                   pa.home_team_1 AS home_team_name,
                   pa.away_team_1 AS away_team_name,
                   COALESCE(f1.home_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.home_team_1 LIMIT 1)
                   ) AS home_team_id,
                   COALESCE(f1.away_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.away_team_1 LIMIT 1)
                   ) AS away_team_id,
                   pa.market_1 AS market, pa.line_1 AS line,
                   pa.odd_combined AS odd, pa.bet_house_1 AS bet_house,
                   pa.confidence AS confidence,
                   pa.result, pa.profit,
                   pa.bankroll_before
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            WHERE pa.result IS NOT NULL
            ORDER BY pa.match_date DESC, pa.id DESC
            LIMIT %s
        """, (limit,))
        for r in rows:
            d = dict(r)
            d["pick_type"] = "alavancagem"
            results.append(d)

        # Ordena tudo por data desc, pega limit
        results.sort(key=lambda x: str(x.get("match_date") or ""), reverse=True)
        return results[:limit]
    finally:
        cur.close()
        conn.close()


@router.get("/picks-free")
def get_picks_free_history(
    current_user: dict = Depends(get_current_user),
    date_from:  Optional[str] = Query(None),
    date_to:    Optional[str] = Query(None),
    resultado:  Optional[str] = Query(None),
    limit:      int = Query(100, ge=1, le=500),
):
    """Histórico de picks gratuitos (Pick do Dia) com filtros."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions: list = []
        params: list = []
        if date_from:
            conditions.append("pf.match_date >= %s"); params.append(date_from)
        else:
            conditions.append("pf.match_date >= CURRENT_DATE - INTERVAL '30 days'")
        if date_to:
            conditions.append("pf.match_date <= %s"); params.append(date_to)
        if resultado == "pending":
            conditions.append("pf.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("pf.result = %s"); params.append(resultado)
        where = "WHERE " + " AND ".join(conditions)
        params.append(limit)
        rows = _safe_query(cur, f"""
            SELECT pf.id, pf.fixture_id, pf.match_date,
                   pf.home_team, pf.away_team,
                   pf.league_id, pf.league_name,
                   pf.market, pf.line, pf.odd, pf.bet_house,
                   pf.confidence, pf.reasoning, pf.result, pf.profit,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            {where}
            ORDER BY pf.match_date DESC
            LIMIT %s
        """, params)
        return [dict(r) for r in rows]
    finally:
        cur.close()
        conn.close()


@router.get("/multiplas")
def get_multiplas(
    current_user: dict = Depends(require_vip),
    date_from:  Optional[str] = Query(None),
    date_to:    Optional[str] = Query(None),
    resultado:  Optional[str] = Query(None),
    order_by:   str = Query("match_date"),
    limit:      int = Query(100, ge=1, le=500),
):
    """Lista de múltiplas com filtros."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions: list = []
        params: list = []
        if date_from:
            conditions.append("match_date >= %s"); params.append(date_from)
        else:
            conditions.append("match_date >= CURRENT_DATE - INTERVAL '30 days'")
        if date_to:
            conditions.append("match_date <= %s"); params.append(date_to)
        if resultado == "pending":
            conditions.append("result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("result = %s"); params.append(resultado)
        where = "WHERE " + " AND ".join(conditions)
        order_col = "total_odd" if order_by == "odd" else "score_combo" if order_by == "confidence" else "match_date"
        params.append(limit)
        rows = _safe_query(cur, f"""
            SELECT id, match_date,
                   games AS legs,
                   total_odd, score_combo AS confidence,
                   reasoning, result, profit, created_at
            FROM picks_multiplas
            {where}
            ORDER BY {order_col} DESC, created_at DESC
            LIMIT %s
        """, params)
        return _enrich_multipla_legs(cur, rows)
    finally:
        cur.close()
        conn.close()


@router.get("/stats/quick")
def get_quick_stats(current_user: dict = Depends(get_current_user)):
    """Win rate do mês, lucro mensal, sequência atual."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Stats do mês corrente
        month_row = _safe_query_one(cur, """
            SELECT
                COUNT(*) FILTER (WHERE result IS NOT NULL)     AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')       AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')         AS reds,
                COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
            FROM picks_vip
            WHERE DATE_TRUNC('month', match_date) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        stats = dict(month_row) if month_row else {"total": 0, "greens": 0, "reds": 0, "profit": 0}
        total  = stats["total"] or 0
        greens = stats["greens"] or 0
        stats["win_rate"] = round(greens / total * 100, 1) if total > 0 else 0.0

        # Sequência atual (últimos resultados ordenados)
        recent = _safe_query(cur, """
            SELECT result FROM picks_vip
            WHERE result IS NOT NULL
            ORDER BY match_date DESC, id DESC
            LIMIT 20
        """)
        streak = 0
        streak_type = None
        for r in recent:
            res = r["result"]
            if res in ("GREEN", "HALF-WIN"):
                outcome = "green"
            elif res in ("RED", "HALF-LOSS"):
                outcome = "red"
            else:
                continue
            if streak_type is None:
                streak_type = outcome
            if outcome == streak_type:
                streak += 1
            else:
                break

        stats["streak"]      = streak
        stats["streak_type"] = streak_type  # "green" | "red" | None
        return stats
    finally:
        cur.close()
        conn.close()


@router.get("/latest-pick")
def get_latest_pick(current_user: dict = Depends(get_current_user)):
    """Retorna o pick mais recente — frontend usa para detectar novos picks."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        row = _safe_query_one(cur, """
            SELECT id, match_date, created_at
            FROM picks_vip
            ORDER BY id DESC
            LIMIT 1
        """)
        if not row:
            return {"id": 0, "created_at": None, "match_date": None}
        return dict(row)
    finally:
        cur.close()
        conn.close()


def _source_games_sql(source: str, date_cond: str) -> str:
    """Retorna subquery normalizada para cada fonte de picks."""
    if source == "free":
        return f"""
            SELECT pf.id, 'free' AS pick_type, pf.match_date,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                   pf.market, pf.line, pf.odd, pf.bet_house,
                   pf.result, pf.profit, 1::numeric AS stake
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            WHERE pf.result IS NOT NULL {date_cond}
        """
    if source == "multipla":
        return f"""
            SELECT id, 'multipla' AS pick_type, match_date,
                   CONCAT('Múltipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' sel.') AS home_team_name,
                   NULL AS away_team_name, NULL AS home_team_id, NULL AS away_team_id,
                   CONCAT('Múltipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' sel.') AS market,
                   NULL AS line, total_odd AS odd, NULL AS bet_house,
                   result,
                   CASE result
                       WHEN 'GREEN' THEN ROUND((total_odd - 1)::numeric, 4)
                       WHEN 'RED'   THEN -1.0
                       WHEN 'PUSH'  THEN 0.0
                       ELSE NULL
                   END AS profit,
                   1::numeric AS stake
            FROM picks_multiplas
            WHERE result IS NOT NULL {date_cond}
        """
    if source == "alavancagem":
        return f"""
            SELECT pa.id, 'alavancagem' AS pick_type, pa.match_date,
                   pa.home_team_1 AS home_team_name, pa.away_team_1 AS away_team_name,
                   COALESCE(f1.home_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.home_team_1 LIMIT 1)
                   ) AS home_team_id,
                   COALESCE(f1.away_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.away_team_1 LIMIT 1)
                   ) AS away_team_id,
                   pa.market_1 AS market, pa.line_1 AS line,
                   pa.odd_combined AS odd, pa.bet_house_1 AS bet_house,
                   pa.result, pa.profit, COALESCE(pa.stake, 1) AS stake
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            WHERE pa.result IS NOT NULL {date_cond}
        """
    # vip (default)
    return f"""
        SELECT id, 'vip' AS pick_type, match_date,
               home_team_name, away_team_name, home_team_id, away_team_id,
               market, line, odd, bet_house,
               result, profit, COALESCE(stake, 1) AS stake
        FROM picks_vip
        WHERE result IS NOT NULL {date_cond}
    """


def _build_combined_sql(source: str, date_cond: str) -> str:
    if source in ("vip", "free", "multipla", "alavancagem"):
        return _source_games_sql(source, date_cond)
    # all
    return " UNION ALL ".join(
        _source_games_sql(s, date_cond) for s in ("vip", "free", "multipla", "alavancagem")
    )


@router.get("/results/games")
def get_results_games(
    current_user: dict = Depends(get_current_user),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    days:      int = Query(30, ge=1, le=3650),
    resultado: Optional[str] = Query(None),
    source:    str = Query("all"),
    offset:    int = Query(0, ge=0),
    limit:     int = Query(50, ge=1, le=200),
):
    """Picks individuais com resultado, paginados. source: all|vip|free|multipla|alavancagem"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        date_cond = ""
        params: list = []
        if date_from:
            date_cond += " AND match_date >= %s"; params.append(date_from)
        else:
            date_cond += " AND match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')"; params.append(days)
        if date_to:
            date_cond += " AND match_date <= %s"; params.append(date_to)

        result_cond = ""
        if resultado and resultado != "all":
            result_cond = " AND result = %s"; params.append(resultado)

        inner_sql = _build_combined_sql(source, date_cond)
        combined_params = params * (1 if source != "all" else 4)

        count_sql = f"SELECT COUNT(*) AS n FROM ({inner_sql}) AS c WHERE TRUE {result_cond}"
        count_row = _safe_query_one(cur, count_sql, combined_params + (params if result_cond else []))
        total = count_row["n"] if count_row else 0

        page_params = combined_params + (params if result_cond else []) + [limit, offset]
        rows = _safe_query(cur, f"""
            SELECT * FROM ({inner_sql}) AS c
            WHERE TRUE {result_cond}
            ORDER BY match_date DESC, id DESC
            LIMIT %s OFFSET %s
        """, page_params)

        items = [dict(r) for r in rows]

        # Substitui stake de VIP/Free/Múltipla pelo stake pessoal do usuário
        personal_types = ("vip", "free", "multipla")
        ids_by_type: dict[str, list] = {t: [] for t in personal_types}
        for x in items:
            pt = x.get("pick_type")
            if pt in ids_by_type:
                ids_by_type[pt].append(x["id"])

        stake_map: dict[tuple, float] = {}
        for pt, ids in ids_by_type.items():
            if ids:
                rows_s = _safe_query(cur, """
                    SELECT pick_id, stake_units
                    FROM user_followed_picks
                    WHERE pick_type = %s AND user_id = %s AND pick_id = ANY(%s)
                """, (pt, current_user["id"], ids))
                for r in rows_s:
                    stake_map[(pt, r["pick_id"])] = float(r["stake_units"])

        for item in items:
            key = (item.get("pick_type"), item["id"])
            if key in stake_map:
                item["stake"] = stake_map[key]

        return {"total": total, "items": items}
    finally:
        cur.close(); conn.close()


@router.get("/results/monthly")
def get_results_monthly(
    current_user: dict = Depends(get_current_user),
    source: str = Query("all"),
):
    """Resumo mensal."""
    inner_sql = _build_combined_sql(source, "")
    n_legs = 1 if source != "all" else 4

    conn = get_connection()
    cur = conn.cursor()
    try:
        rows = _safe_query(cur, f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', match_date), 'YYYY-MM') AS month,
                COUNT(*)                                              AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')             AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')               AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')              AS push,
                COALESCE(SUM(profit), 0)                             AS profit,
                COALESCE(SUM(stake),  0)                             AS stake
            FROM ({inner_sql}) AS c
            GROUP BY DATE_TRUNC('month', match_date)
            ORDER BY DATE_TRUNC('month', match_date) DESC
        """, [] * n_legs)
        result = []
        for r in rows:
            d = dict(r)
            t = d["total"] or 0
            g = d["greens"] or 0
            s = float(d["stake"] or 0)
            p = float(d["profit"] or 0)
            d["win_rate"] = round(g / t * 100, 1) if t > 0 else 0.0
            d["roi"]      = round(p / s * 100, 1) if s > 0 else 0.0
            result.append(d)
        return result
    finally:
        cur.close(); conn.close()


@router.get("/alavancagem")
def get_alavancagem(
    current_user: dict = Depends(require_vip),
    date_from:    Optional[str] = Query(None),
    date_to:      Optional[str] = Query(None),
    resultado:    Optional[str] = Query(None),
    limit:        int = Query(200, ge=1, le=500),
):
    """Histórico de picks de alavancagem (Copa do Mundo). VIP only."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions: list = []
        params: list = []
        if date_from:
            conditions.append("pa.match_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("pa.match_date <= %s")
            params.append(date_to)
        if resultado == "pending":
            conditions.append("pa.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("pa.result = %s"); params.append(resultado)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = _safe_query(cur, f"""
            SELECT pa.id, pa.match_date, pa.tipo,
                   pa.home_team_1, pa.away_team_1, pa.market_1, pa.line_1, pa.odd_1, pa.bet_house_1,
                   pa.confidence_1, pa.reasoning_1,
                   pa.home_team_2, pa.away_team_2, pa.market_2, pa.line_2, pa.odd_2, pa.bet_house_2,
                   pa.confidence_2, pa.reasoning_2,
                   pa.odd_combined, pa.confidence_media,
                   pa.stake, pa.potential_return, pa.bankroll_before,
                   pa.result, pa.profit, pa.bankroll_after, pa.created_at,
                   f1.home_team_id AS home_team_id_1, f1.away_team_id AS away_team_id_1,
                   f2.home_team_id AS home_team_id_2, f2.away_team_id AS away_team_id_2
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            LEFT JOIN fixtures f2 ON f2.fixture_id = pa.fixture_id_2
            {where}
            ORDER BY pa.match_date DESC
            LIMIT %s
        """, params)
        return [dict(r) for r in rows]
    finally:
        cur.close()
        conn.close()


@router.get("/alavancagem/today")
def get_alavancagem_today(current_user: dict = Depends(require_vip)):
    """Pick de alavancagem de hoje. VIP only."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        row = _safe_query_one(cur, """
            SELECT pa.id, pa.match_date, pa.tipo,
                   pa.home_team_1, pa.away_team_1, pa.market_1, pa.line_1, pa.odd_1, pa.bet_house_1,
                   pa.confidence_1, pa.reasoning_1,
                   pa.home_team_2, pa.away_team_2, pa.market_2, pa.line_2, pa.odd_2, pa.bet_house_2,
                   pa.confidence_2, pa.reasoning_2,
                   pa.odd_combined, pa.confidence_media,
                   pa.stake, pa.potential_return, pa.bankroll_before,
                   pa.result, pa.profit, pa.bankroll_after, pa.created_at,
                   f1.home_team_id AS home_team_id_1, f1.away_team_id AS away_team_id_1,
                   f2.home_team_id AS home_team_id_2, f2.away_team_id AS away_team_id_2
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            LEFT JOIN fixtures f2 ON f2.fixture_id = pa.fixture_id_2
            WHERE pa.match_date = CURRENT_DATE
            LIMIT 1
        """)
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


@router.get("/results")
def get_results(
    current_user: dict = Depends(get_current_user),
    days:      int = Query(30, ge=1, le=3650),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    source:    str = Query("all"),
):
    conn = get_connection()
    cur = conn.cursor()
    try:
        date_cond = ""
        params_q: list = []
        if date_from:
            date_cond += " AND match_date >= %s"; params_q.append(date_from)
        if date_to:
            date_cond += " AND match_date <= %s"; params_q.append(date_to)
        if not date_from:
            date_cond += " AND match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')"; params_q.append(days)

        inner_sql = _build_combined_sql(source, date_cond)
        n_legs = 1 if source != "all" else 4
        combined_params = params_q * n_legs

        row = _safe_query_one(cur, f"""
            SELECT
                COUNT(*)                                            AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')           AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')             AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')            AS push,
                COUNT(*) FILTER (WHERE result = 'HALF-WIN')        AS half_wins,
                COUNT(*) FILTER (WHERE result = 'HALF-LOSS')       AS half_losses,
                COALESCE(SUM(profit), 0)                           AS profit_total,
                COALESCE(SUM(stake),  0)                           AS stake_total,
                MIN(match_date)                                     AS desde
            FROM ({inner_sql}) AS c
        """, combined_params)
        stats = dict(row) if row else {}

        rows = _safe_query(cur, f"""
            SELECT match_date,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE result = 'GREEN') AS greens,
                   COALESCE(SUM(profit), 0)                 AS profit
            FROM ({inner_sql}) AS c
            GROUP BY match_date
            ORDER BY match_date DESC
        """, combined_params)
        stats["by_day"] = [dict(r) for r in rows]
        return stats
    finally:
        cur.close()
        conn.close()
