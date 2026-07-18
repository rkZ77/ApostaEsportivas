import time
import httpx
from typing import Any
from datetime import date
from futebol_agent.config import API_FOOTBALL_BASE, API_FOOTBALL_HEADERS, API_TIMEZONE, season_for

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


_TZ_ENDPOINTS = {"fixtures", "fixtures/headtohead"}

# Cache em memoria por (endpoint, params) -- achado real de consumo de cota:
# o agente de chat tinha ZERO cache nas 16 ferramentas que chamam a API ao
# vivo (fixtures, standings, h2h, stats, predictions, odds, etc), cada
# mensagem do chat podia disparar varias chamadas repetidas sem necessidade
# (ex: perguntar sobre o mesmo time duas vezes gastava cota duas vezes).
# TTL curto (10s) so pra dado genuinamente ao vivo (jogos em andamento/odds
# ao vivo), TTL longo (5 min) pro resto -- standings/stats/h2h/predictions
# nao mudam segundo a segundo.
_cache: dict[tuple, tuple[float, dict]] = {}
_LIVE_TTL = 10
_DEFAULT_TTL = 300


def _is_live_call(endpoint: str, params: dict) -> bool:
    return endpoint == "odds/live" or params.get("live") == "all"


async def _get(endpoint: str, params: dict) -> dict[str, Any]:
    if endpoint in _TZ_ENDPOINTS:
        params.setdefault("timezone", API_TIMEZONE)

    cache_key = (endpoint, tuple(sorted(params.items())))
    ttl = _LIVE_TTL if _is_live_call(endpoint, params) else _DEFAULT_TTL
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < ttl:
        return cached[1]

    url = f"{API_FOOTBALL_BASE}/{endpoint}"
    resp = await get_client().get(url, headers=API_FOOTBALL_HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    _cache[cache_key] = (time.time(), data)
    return data


async def get_live_fixtures(league_ids: list[int] | None = None) -> list[dict]:
    data = await _get("fixtures", {"live": "all"})
    fixtures = data.get("response", [])
    if league_ids:
        fixtures = [f for f in fixtures if f["league"]["id"] in league_ids]
    return fixtures


async def get_fixture_by_id(fixture_id: int) -> dict | None:
    data = await _get("fixtures", {"id": fixture_id})
    resp = data.get("response", [])
    return resp[0] if resp else None


def _name_matches(query: str, full_name: str) -> bool:
    q = query.lower().strip()
    n = full_name.lower()
    return q in n or any(q in word for word in n.split())


async def search_fixture(team1: str, team2: str) -> list[dict]:
    data = await _get("fixtures", {"live": "all"})
    results = [
        f for f in data.get("response", [])
        if (_name_matches(team1, f["teams"]["home"]["name"]) or _name_matches(team1, f["teams"]["away"]["name"]))
        and (_name_matches(team2, f["teams"]["home"]["name"]) or _name_matches(team2, f["teams"]["away"]["name"]))
    ]
    if results:
        return results
    today_data = await _get("fixtures", {"date": date.today().isoformat()})
    return [
        f for f in today_data.get("response", [])
        if (_name_matches(team1, f["teams"]["home"]["name"]) or _name_matches(team1, f["teams"]["away"]["name"]))
        and (_name_matches(team2, f["teams"]["home"]["name"]) or _name_matches(team2, f["teams"]["away"]["name"]))
    ]


async def get_fixture_statistics(fixture_id: int) -> list[dict]:
    data = await _get("fixtures/statistics", {"fixture": fixture_id})
    return data.get("response", [])


async def get_fixture_statistics_half(fixture_id: int) -> list[dict]:
    data = await _get("fixtures/statistics", {"fixture": fixture_id, "half": "true"})
    return data.get("response", [])


async def get_fixture_events(fixture_id: int) -> list[dict]:
    data = await _get("fixtures/events", {"fixture": fixture_id})
    return data.get("response", [])


async def get_fixtures_today(league_id: int | None = None) -> list[dict]:
    params: dict = {"date": date.today().isoformat()}
    if league_id:
        params["league"] = league_id
        params["season"] = season_for(league_id)
    data = await _get("fixtures", params)
    return data.get("response", [])


async def get_standings(league_id: int) -> list[dict]:
    season = season_for(league_id)
    data = await _get("standings", {"league": league_id, "season": season})
    resp = data.get("response", [])
    if not resp:
        return []
    return resp[0]["league"]["standings"]


async def get_head_to_head(team1_id: int, team2_id: int, last: int = 10) -> list[dict]:
    data = await _get("fixtures/headtohead", {"h2h": f"{team1_id}-{team2_id}", "last": last})
    return data.get("response", [])


async def get_team_fixtures(team_id: int, last: int = 5) -> list[dict]:
    data = await _get("fixtures", {"team": team_id, "last": last})
    return data.get("response", [])


async def get_team_fixtures_by_league(team_id: int, league_id: int, season: int, last: int = 10) -> list[dict]:
    data = await _get("fixtures", {"team": team_id, "league": league_id, "season": season, "last": last})
    return data.get("response", [])


async def search_team(name: str) -> list[dict]:
    data = await _get("teams", {"search": name})
    return data.get("response", [])


async def get_fixture_lineups(fixture_id: int) -> list[dict]:
    data = await _get("fixtures/lineups", {"fixture": fixture_id})
    return data.get("response", [])


async def get_fixture_players(fixture_id: int) -> list[dict]:
    data = await _get("fixtures/players", {"fixture": fixture_id})
    return data.get("response", [])


async def get_team_season_statistics(team_id: int, league_id: int, season: int) -> dict | None:
    data = await _get("teams/statistics", {"team": team_id, "league": league_id, "season": season})
    resp = data.get("response")
    return resp if resp else None


async def get_fixture_odds(fixture_id: int) -> list[dict]:
    data = await _get("odds", {"fixture": fixture_id})
    return data.get("response", [])


async def get_live_odds(fixture_id: int) -> dict:
    data = await _get("odds/live", {"fixture": fixture_id})
    entries = data.get("response", [])
    if not entries:
        return {"status": "sem_cobertura", "odds": []}
    entry = entries[0]
    status = entry.get("status", {})
    odds = entry.get("odds", [])
    if status.get("stopped"):
        return {"status": "intervalo", "odds": odds}
    if status.get("blocked"):
        return {"status": "suspenso", "odds": odds}
    if status.get("finished"):
        return {"status": "finished", "odds": odds}
    if not odds:
        return {"status": "sem_mercados", "odds": []}
    return {"status": "ok", "odds": odds}


async def get_injuries(fixture_id: int) -> list[dict]:
    data = await _get("injuries", {"fixture": fixture_id})
    return data.get("response", [])


async def get_predictions(fixture_id: int) -> dict | None:
    data = await _get("predictions", {"fixture": fixture_id})
    resp = data.get("response", [])
    return resp[0] if resp else None
