from futebol_agent.api_football import get_live_fixtures, get_fixtures_today
from futebol_agent.config import FEATURED_LEAGUE_IDS


def _fmt_fixture(f: dict) -> dict:
    fixture = f["fixture"]
    league  = f["league"]
    teams   = f["teams"]
    goals   = f["goals"]
    status  = fixture["status"]
    return {
        "fixture_id":   fixture["id"],
        "league":       f"{league['country']} - {league['name']}",
        "home":         teams["home"]["name"],
        "away":         teams["away"]["name"],
        "score":        f"{goals['home'] or 0} x {goals['away'] or 0}",
        "minute":       status.get("elapsed") or 0,
        "status":       status["long"],
        "status_short": status["short"],
    }


async def get_live_matches(only_featured: bool = True) -> list[dict]:
    league_ids = list(FEATURED_LEAGUE_IDS) if only_featured else None
    fixtures = await get_live_fixtures(league_ids)
    return [_fmt_fixture(f) for f in fixtures]


async def get_today_matches(league_id: int | None = None) -> list[dict]:
    fixtures = await get_fixtures_today(league_id)
    allowed = {league_id} if league_id else FEATURED_LEAGUE_IDS
    return [_fmt_fixture(f) for f in fixtures if f["league"]["id"] in allowed]
