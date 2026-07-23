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
    """Ligas ativas cadastradas no sistema · sem autenticação."""
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
    # league via match_statistics, nao fixtures -- fixtures e' so fila
    # operacional, o registro ja resolvido/graded quase sempre ja saiu de
    # la; match_statistics e' o registro permanente (sem FK, nunca deletado).
    return f"""
        SELECT pv.match_date,
               pv.home_team_name, pv.away_team_name,
               pv.home_team_id,   pv.away_team_id,
               pv.market, pv.line, pv.odd,
               pv.result, pv.profit,
               1::numeric AS stake,
               'vip' AS source,
               ms.league_id AS league_id,
               COALESCE(l.name, 'Liga ' || ms.league_id) AS league_name
        FROM picks_vip pv
        LEFT JOIN match_statistics ms ON ms.fixture_id = pv.fixture_id
        LEFT JOIN leagues l ON l.league_id = ms.league_id
        WHERE pv.result IS NOT NULL {date_cond}
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
               'free' AS source,
               COALESCE(pf.league_id, ms.league_id) AS league_id,
               COALESCE(pf.league_name, l.name, 'Liga ' || COALESCE(pf.league_id, ms.league_id)) AS league_name
        FROM picks_free pf
        LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
        LEFT JOIN match_statistics ms ON ms.fixture_id = pf.fixture_id
        LEFT JOIN leagues l ON l.league_id = COALESCE(pf.league_id, ms.league_id)
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
               'multiplas' AS source,
               NULL::INTEGER AS league_id,
               'Múltiplas' AS league_name
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
               'alavancagem' AS source,
               NULL::INTEGER AS league_id,
               'Alavancagem' AS league_name
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


def _collect_results(cur, date_cond: str, date_params: tuple, source: Optional[str],
                     limit: int = 30, offset: int = 0) -> list:
    """Corre cada sub-query separada, assim uma falha não apaga as outras.
    Paginação: cada sub-query busca até offset+limit linhas (pior caso, se a
    janela [offset, offset+limit) inteira vier de uma unica fonte) -- depois
    do merge+sort global, so' entao aplica o slice [offset:offset+limit]."""
    builders = [_SUB_BUILDERS[source]] if (source and source in _SUB_BUILDERS) else list(_SUB_BUILDERS.values())
    fetch_n = offset + limit
    rows: list = []
    for fn in builders:
        sub = fn(date_cond)
        batch = _q(cur, f"SELECT * FROM ({sub}) t ORDER BY match_date DESC, result LIMIT %s", date_params + (fetch_n,))
        rows.extend(batch)
    rows.sort(key=lambda r: (str(r["match_date"]), str(r.get("result",""))), reverse=True)
    return rows[offset:offset + limit]


def _count_recent(cur, date_cond: str, date_params: tuple, source: Optional[str]) -> int:
    """Total de linhas pra paginação de 'recent' -- mesma defesa por sub-query
    de _collect_results (uma fonte com erro conta 0 em vez de derrubar o total)."""
    builders = [_SUB_BUILDERS[source]] if (source and source in _SUB_BUILDERS) else list(_SUB_BUILDERS.values())
    total = 0
    for fn in builders:
        sub = fn(date_cond)
        row = _q1(cur, f"SELECT COUNT(*) AS c FROM ({sub}) t", date_params)
        total += row["c"] if row else 0
    return total


@router.get("/results")
def public_results(
    month:  Optional[str] = Query(None, description="YYYY-MM · filtra por mês"),
    source: Optional[str] = Query(None, description="all | vip | free | multiplas | alavancagem"),
    recent_limit:  int = Query(10, ge=1, le=50, description="Itens por página em 'recent'"),
    recent_offset: int = Query(0, ge=0, description="Offset de paginação em 'recent'"),
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

        # ── Por liga. So' ligas de verdade (league_id IS NOT NULL) -- Múltipla/
        # Alavancagem nao tem league_id real (pernas podem ser de ligas
        # diferentes) e NAO sao ligas, entao ficam de fora desta lista (pedido
        # explicito do usuario: "na liga nao aparece multiplas alavancagem,
        # aparece so ligas mesmo" -- esses tipos continuam cobertos pelo filtro
        # "Fonte" e por `counts` abaixo, so nao entram na quebra POR LIGA).
        # Agrupa por league_id (nao league_name -- o nome denormalizado em
        # picks_free pode estar desatualizado em relacao a leagues.name atual,
        # ex: "Copa do Mundo" vs "Copa do Mundo FIFA" pro mesmo league_id, o
        # que duplicaria a liga em duas linhas).
        by_league_raw = _q(cur, f"""
            SELECT
                league_id,
                COUNT(*)                                  AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')  AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')    AS reds,
                COALESCE(SUM(profit), 0)                  AS profit,
                COALESCE(SUM(stake), 0)                   AS stake_total
            FROM ({union_sql}) AS t
            WHERE league_id IS NOT NULL
            GROUP BY league_id
            ORDER BY total DESC
        """, p)
        _league_names = {r["league_id"]: r["name"] for r in _q(cur, "SELECT league_id, name FROM leagues")}
        by_league = []
        for r in by_league_raw:
            d = dict(r)
            d["league_name"] = _league_names.get(d["league_id"], f"Liga {d['league_id']}")
            by_league.append(d)

        # ── Recentes (por sub-query para não quebrar tudo se uma coluna faltar) ──
        single_source = source if source in _SUB_BUILDERS else None
        recent_total = _count_recent(cur, date_cond, date_params, single_source)
        recent = _collect_results(cur, date_cond, date_params, single_source,
                                   limit=recent_limit, offset=recent_offset)

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
            "by_league": [dict(r) for r in by_league],
            "recent":  [dict(r) for r in recent],
            "recent_total": recent_total,
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


@router.get("/today-summary")
def public_today_summary():
    """Contagem de picks publicados hoje (qualquer status, inclusive ainda
    sem resultado -- jogo pode estar rolando) -- sem isso a home so mostrava
    estatisticas agregadas historicas, sem nenhum sinal de atividade do dia
    atual (achado real: usuario relatou 'nao aparece nada do dia' na home)."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        row = _q1(cur, """
            SELECT
                COUNT(*) FILTER (WHERE t.source = 'vip')         AS vip,
                COUNT(*) FILTER (WHERE t.source = 'free')        AS free,
                COUNT(*) FILTER (WHERE t.source = 'multiplas')   AS multiplas,
                COUNT(*) FILTER (WHERE t.source = 'alavancagem') AS alavancagem,
                COUNT(*)                                         AS total
            FROM (
                SELECT 'vip'         AS source FROM picks_vip         WHERE match_date = CURRENT_DATE
                UNION ALL
                SELECT 'free'        AS source FROM picks_free        WHERE match_date = CURRENT_DATE
                UNION ALL
                SELECT 'multiplas'   AS source FROM picks_multiplas   WHERE match_date = CURRENT_DATE
                UNION ALL
                SELECT 'alavancagem' AS source FROM picks_alavancagem WHERE match_date = CURRENT_DATE
            ) t
        """)
        return dict(row) if row else {"vip": 0, "free": 0, "multiplas": 0, "alavancagem": 0, "total": 0}
    finally:
        cur.close()
        conn.close()


@router.get("/fixtures-today")
def public_fixtures_today(days_ahead: int = Query(0, ge=0, le=7)):
    """Jogos de hoje (ou dias_a_frente adiante) das ligas cobertas, sem
    autenticacao -- so calendario (times, liga, horario), sem odds/picks.
    Usado pro card de compartilhamento 'jogos de hoje/amanha'."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT f.fixture_id, f.home_team, f.away_team,
                   f.home_team_id, f.away_team_id,
                   f.league_id, COALESCE(l.name, 'Liga ' || f.league_id) AS league_name,
                   f.match_datetime
            FROM fixtures f
            LEFT JOIN leagues l ON l.league_id = f.league_id
            WHERE f.match_datetime::date = CURRENT_DATE + (%s * INTERVAL '1 day')
              AND f.status = 'NS'
            ORDER BY f.match_datetime
            LIMIT 8
        """, (days_ahead,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("match_datetime") and hasattr(d["match_datetime"], "isoformat"):
                d["match_datetime"] = d["match_datetime"].isoformat()
            result.append(d)
        return result
    finally:
        cur.close()
        conn.close()


@router.get("/free-pick-today")
def public_free_pick_today():
    """Teaser da Dica do Dia (free) de hoje, sem autenticacao -- usado pra
    dar um gostinho do produto pra quem ainda nao tem conta. Nao expoe
    mercado/linha/reasoning, so o suficiente pra linkar pra /p/free/{id}."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT pf.id, pf.match_date,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, fx.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, fx.away_team_id) AS away_team_id,
                   pf.odd, pf.result
            FROM picks_free pf
            LEFT JOIN fixtures fx ON fx.fixture_id = pf.fixture_id
            WHERE pf.match_date = CURRENT_DATE
            ORDER BY pf.created_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("match_date") and hasattr(d["match_date"], "isoformat"):
            d["match_date"] = d["match_date"].isoformat()
        return d
    finally:
        cur.close()
        conn.close()


@router.get("/leaderboard")
def public_leaderboard():
    """Top 5 usuarios por yield ROI · anonimizados para landing page (min 5 picks resolvidos)."""
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
