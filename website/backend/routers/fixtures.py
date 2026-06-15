import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from database import get_connection
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])

API_URL   = "https://v3.football.api-sports.io/fixtures"
TZ_BRAZIL = "America/Sao_Paulo"
BRT       = timezone(timedelta(hours=-3))

# ── Cache em memória ──────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 600  # 10 minutos


def _api_headers():
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _brazil_today() -> str:
    """Data de hoje no fuso de Brasília (UTC-3)."""
    return datetime.now(BRT).strftime("%Y-%m-%d")


def _fetch_by_utc_date(league_id: int, season: int, utc_date: str) -> list:
    """
    Busca fixtures para um dia UTC específico.
    Pede ao endpoint com timezone=BRT para já receber os horários convertidos.
    """
    cache_key = f"{league_id}:{utc_date}:{TZ_BRAZIL}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data

    try:
        resp = requests.get(API_URL, headers=_api_headers(), params={
            "league":   league_id,
            "season":   season,
            "date":     utc_date,
            "timezone": TZ_BRAZIL,
        }, timeout=10)
        resp.raise_for_status()
        result = resp.json().get("response", [])
        _cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logger.error("[FIXTURES API] Erro liga %s / %s: %s", league_id, utc_date, e)
        return []


def _parse_fixture(item: dict, league_name: str) -> dict:
    fix         = item["fixture"]
    teams       = item["teams"]
    goals       = item.get("goals", {})
    league_info = item.get("league", {})

    # A API retorna o horário no timezone solicitado (BRT) com offset -03:00.
    # Só formatamos sem o sufixo para o frontend exibir como horário local.
    dt_raw = fix.get("date", "")
    try:
        dt_brt = datetime.fromisoformat(dt_raw)
        dt_iso = dt_brt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        dt_iso = dt_raw

    return {
        "fixture_id":     fix["id"],
        "match_datetime": dt_iso,
        "league_id":      league_info.get("id"),
        "season":         league_info.get("season"),
        "league_name":    league_name,
        "league_logo":    league_info.get("logo"),
        "league_flag":    league_info.get("flag"),
        "league_country": league_info.get("country"),
        "status":         fix["status"]["short"],
        "elapsed":        fix.get("status", {}).get("elapsed"),
        "home_team_id":   teams["home"]["id"],
        "away_team_id":   teams["away"]["id"],
        "home_team":      teams["home"]["name"],
        "away_team":      teams["away"]["name"],
        "home_goals":     goals.get("home"),
        "away_goals":     goals.get("away"),
    }


def _brt_date_of(item: dict) -> str:
    """Retorna a data BRT (YYYY-MM-DD) de um fixture da API."""
    dt_raw = item.get("fixture", {}).get("date", "")
    try:
        dt = datetime.fromisoformat(dt_raw)
        # Se veio com offset, converte para BRT; senão assume BRT
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)
        return dt.astimezone(BRT).strftime("%Y-%m-%d")
    except Exception:
        return ""


@router.get("/leagues")
def get_leagues(current_user: dict = Depends(get_current_user)):
    """Retorna as ligas monitoradas com logo e bandeira da API Football."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT league_id, name, season FROM leagues ORDER BY name")
    db_leagues = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for row in db_leagues:
        lid    = row["league_id"]
        season = row["season"]
        # Logo da liga é determinístico — sem chamada API extra
        logo = f"https://media.api-sports.io/football/leagues/{lid}.png"
        flag = None
        country = None

        # Busca flag e country via API (usa cache do dia se já tiver fixture)
        try:
            resp = requests.get(
                "https://v3.football.api-sports.io/leagues",
                headers=_api_headers(),
                params={"id": lid, "season": season},
                timeout=8,
            )
            data = resp.json().get("response", [])
            if data:
                entry   = data[0]
                logo    = entry["league"].get("logo", logo)
                flag    = entry["country"].get("flag")
                country = entry["country"].get("name")
        except Exception:
            pass

        result.append({
            "league_id": lid,
            "name":      row["name"],
            "season":    season,
            "logo":      logo,
            "flag":      flag,
            "country":   country,
        })

    return result


@router.get("/today")
def get_today_fixtures(
    current_user: dict = Depends(get_current_user),
    date: Optional[str] = Query(None, description="YYYY-MM-DD no fuso de Brasília"),
):
    """
    Jogos do dia das ligas monitoradas — horários em BRT, cache 10 min.

    Busca o dia solicitado E o dia UTC seguinte, pois jogos após 21h BRT
    caem no próximo dia UTC (BRT = UTC-3, então 21h BRT = 00h UTC+1).
    Filtra pelo horário BRT para mostrar apenas os jogos do dia correto.
    """
    target_brt = date or _brazil_today()

    # Valida formato antes de usar
    try:
        local_dt = datetime.strptime(target_brt, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Formato de data inválido. Use YYYY-MM-DD.")
    next_utc_date = (local_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    utc_dates_to_query = [target_brt, next_utc_date]

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT league_id, name, season FROM leagues ORDER BY league_id")
    leagues = cur.fetchall()

    if not leagues:
        cur.close(); conn.close()
        return []

    seen_ids: set[int] = set()
    all_fixtures: list[dict] = []

    for row in leagues:
        for utc_date in utc_dates_to_query:
            items = _fetch_by_utc_date(row["league_id"], row["season"], utc_date)
            for item in items:
                fid = item["fixture"]["id"]
                if fid in seen_ids:
                    continue
                if _brt_date_of(item) != target_brt:
                    continue
                seen_ids.add(fid)
                all_fixtures.append(_parse_fixture(item, row["name"]))

    # Marca quais fixtures têm pick cadastrado para o dia
    if all_fixtures:
        fixture_ids = [f["fixture_id"] for f in all_fixtures]
        placeholders = ",".join(["%s"] * len(fixture_ids))
        cur.execute(f"""
            SELECT fixture_id, market, 'free' AS pick_type FROM picks_free
            WHERE fixture_id IN ({placeholders}) AND match_date = %s
            UNION ALL
            SELECT fixture_id, market, 'vip' AS pick_type FROM picks_vip
            WHERE fixture_id IN ({placeholders}) AND match_date = %s
        """, fixture_ids + [target_brt] + fixture_ids + [target_brt])
        picks_map: dict[int, dict] = {}
        for r in cur.fetchall():
            fid = r["fixture_id"]
            # prefere vip se houver os dois
            if fid not in picks_map or picks_map[fid]["pick_type"] == "free":
                picks_map[fid] = {"market": r["market"], "pick_type": r["pick_type"]}

        for f in all_fixtures:
            pick = picks_map.get(f["fixture_id"])
            f["has_pick"]    = pick is not None
            f["pick_market"] = pick["market"] if pick else None
            f["pick_type_flag"] = pick["pick_type"] if pick else None
    else:
        for f in all_fixtures:
            f["has_pick"] = False
            f["pick_market"] = None
            f["pick_type_flag"] = None

    cur.close()
    conn.close()

    all_fixtures.sort(key=lambda x: x["match_datetime"] or "")
    return all_fixtures


@router.get("/{fixture_id}/stats")
def get_fixture_stats(fixture_id: int, current_user: dict = Depends(get_current_user)):
    """Estatísticas do fixture: médias por time + últimas 5 partidas de cada time."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM fixtures WHERE fixture_id = %s", (fixture_id,))
    fix = cur.fetchone()
    if not fix:
        cur.close(); conn.close()
        raise HTTPException(404, "Fixture não encontrado")

    home_id  = fix["home_team_id"]
    away_id  = fix["away_team_id"]
    league   = fix["league_id"]

    def get_team_stats(team_id, context):
        cur.execute("""
            SELECT games_count,
                   avg_goals_for, avg_goals_against, avg_total_goals,
                   avg_corners_for, avg_corners_against,
                   avg_shots_on_for, avg_shots_on_against,
                   avg_possession_for,
                   avg_yellow_for, avg_red_for
            FROM team_statistics
            WHERE team_id = %s AND league_id = %s AND context_type = %s
            ORDER BY season DESC LIMIT 1
        """, (team_id, league, context))
        row = cur.fetchone()
        return dict(row) if row else {}

    def get_recent(team_id):
        cur.execute("""
            SELECT ms.fixture_id, ms.match_date, ms.league_id,
                   ms.home_team_id, ms.away_team_id,
                   ms.home_goals, ms.away_goals, ms.status
            FROM match_statistics ms
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.status IN ('FT','AET','PEN')
              AND ms.fixture_id != %s
            ORDER BY ms.match_date DESC
            LIMIT 5
        """, (team_id, team_id, fixture_id))
        rows = [dict(r) for r in cur.fetchall()]

        # Enrich with team names
        all_ids = set()
        for r in rows:
            all_ids.add(r["home_team_id"])
            all_ids.add(r["away_team_id"])
        if all_ids:
            cur.execute("""
                SELECT DISTINCT ON (team_id) team_id, name
                FROM teams WHERE team_id = ANY(%s)
                ORDER BY team_id, season DESC
            """, (list(all_ids),))
            names = {r["team_id"]: r["name"] for r in cur.fetchall()}
            for r in rows:
                r["home_team_name"] = names.get(r["home_team_id"], "")
                r["away_team_name"] = names.get(r["away_team_id"], "")
        return rows

    home_stats   = get_team_stats(home_id, "HOME")
    away_stats   = get_team_stats(away_id, "AWAY")
    home_recent  = get_recent(home_id)
    away_recent  = get_recent(away_id)

    cur.close(); conn.close()
    return {
        "fixture": dict(fix),
        "home_stats":  home_stats,
        "away_stats":  away_stats,
        "home_recent": home_recent,
        "away_recent": away_recent,
    }
