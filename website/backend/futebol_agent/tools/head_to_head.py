import asyncio
from futebol_agent.api_football import (
    get_head_to_head, search_team, get_team_fixtures,
    get_team_season_statistics, get_team_fixtures_by_league,
    get_fixture_statistics_half,
)
from futebol_agent.config import LEAGUES, season_for


async def _resolve_team_id(name: str) -> int | None:
    teams = await search_team(name)
    if not teams:
        return None
    return teams[0]["team"]["id"]


def _fmt_past_fixture(f: dict) -> dict:
    fixture = f["fixture"]
    teams   = f["teams"]
    goals   = f["goals"]
    league  = f["league"]
    return {
        "date":   fixture["date"][:10],
        "league": league["name"],
        "home":   teams["home"]["name"],
        "away":   teams["away"]["name"],
        "score":  f"{goals['home'] or 0} x {goals['away'] or 0}",
        "winner": (
            teams["home"]["name"] if teams["home"]["winner"]
            else teams["away"]["name"] if teams["away"]["winner"]
            else "Empate"
        ),
    }


async def get_h2h(team1_name: str, team2_name: str, last: int = 8) -> dict:
    t1_id = await _resolve_team_id(team1_name)
    t2_id = await _resolve_team_id(team2_name)

    if not t1_id:
        return {"error": f"Time '{team1_name}' não encontrado."}
    if not t2_id:
        return {"error": f"Time '{team2_name}' não encontrado."}

    fixtures = await get_head_to_head(t1_id, t2_id, last)
    if not fixtures:
        return {"error": "Sem histórico de confrontos diretos disponível."}

    past = [_fmt_past_fixture(f) for f in fixtures]

    t1_wins = sum(
        1 for f in fixtures
        if (f["teams"]["home"]["winner"] and f["teams"]["home"]["id"] == t1_id)
        or (f["teams"]["away"]["winner"] and f["teams"]["away"]["id"] == t1_id)
    )
    t2_wins = sum(
        1 for f in fixtures
        if (f["teams"]["home"]["winner"] and f["teams"]["home"]["id"] == t2_id)
        or (f["teams"]["away"]["winner"] and f["teams"]["away"]["id"] == t2_id)
    )
    draws_count = len(past) - t1_wins - t2_wins

    return {
        "summary": {
            team1_name:  t1_wins,
            team2_name:  t2_wins,
            "empates":   draws_count,
            "total":     len(past),
        },
        "matches": past,
    }


async def get_team_stats_season(team_name: str, league_name: str) -> dict:
    teams = await search_team(team_name)
    if not teams:
        return {"error": f"Time '{team_name}' não encontrado."}
    team_id        = teams[0]["team"]["id"]
    team_real_name = teams[0]["team"]["name"]

    league_key = league_name.lower().replace(" ", "_").replace("ã", "a")
    league_id = None
    for key, lid in LEAGUES.items():
        if league_key in key or key in league_key:
            league_id = lid
            break
    if not league_id:
        return {"error": f"Liga '{league_name}' não encontrada."}

    season = season_for(league_id)
    data   = await get_team_season_statistics(team_id, league_id, season)
    if not data:
        return {"error": f"Sem estatísticas de temporada para {team_real_name} em {league_name}."}

    fixtures         = data.get("fixtures", {})
    goals            = data.get("goals", {})
    avg_goals_for    = goals.get("for", {}).get("average", {})
    avg_goals_against = goals.get("against", {}).get("average", {})
    biggest          = data.get("biggest", {})
    clean_sheet      = data.get("clean_sheet", {})
    failed_to_score  = data.get("failed_to_score", {})

    return {
        "team":   team_real_name,
        "league": league_name,
        "season": season,
        "played": fixtures.get("played", {}).get("total", 0),
        "wins":   fixtures.get("wins", {}).get("total", 0),
        "draws":  fixtures.get("draws", {}).get("total", 0),
        "losses": fixtures.get("loses", {}).get("total", 0),
        "avg_goals_for": {
            "home":  avg_goals_for.get("home", "0"),
            "away":  avg_goals_for.get("away", "0"),
            "total": avg_goals_for.get("total", "0"),
        },
        "avg_goals_against": {
            "home":  avg_goals_against.get("home", "0"),
            "away":  avg_goals_against.get("away", "0"),
            "total": avg_goals_against.get("total", "0"),
        },
        "clean_sheets":    clean_sheet.get("total", 0),
        "failed_to_score": failed_to_score.get("total", 0),
        "biggest_win":     biggest.get("wins", {}).get("total", ""),
        "biggest_loss":    biggest.get("loses", {}).get("total", ""),
        "form":            data.get("form", ""),
    }


def _extract_stat(statistics: list[dict], name: str) -> float:
    for s in statistics:
        if s["type"] == name:
            val = s["value"]
            if val is None:
                return 0.0
            if isinstance(val, str):
                try:
                    return float(val.replace("%", ""))
                except ValueError:
                    return 0.0
            return float(val)
    return 0.0


def _new_totals() -> dict:
    return {
        "corners": 0.0, "shots": 0.0, "shots_on": 0.0, "shots_off": 0.0,
        "shots_blocked": 0.0, "shots_inside": 0.0, "shots_outside": 0.0,
        "possession": 0.0, "yellow_cards": 0.0, "red_cards": 0.0,
        "fouls": 0.0, "offsides": 0.0, "saves": 0.0,
        "passes": 0.0, "passes_pct": 0.0, "xg": 0.0,
    }

_STAT_KEYS = [
    ("corners",       "Corner Kicks"),
    ("shots",         "Total Shots"),
    ("shots_on",      "Shots on Goal"),
    ("shots_off",     "Shots off Goal"),
    ("shots_blocked", "Blocked Shots"),
    ("shots_inside",  "Shots insidebox"),
    ("shots_outside", "Shots outsidebox"),
    ("possession",    "Ball Possession"),
    ("yellow_cards",  "Yellow Cards"),
    ("red_cards",     "Red Cards"),
    ("fouls",         "Fouls"),
    ("offsides",      "Offsides"),
    ("saves",         "Goalkeeper Saves"),
    ("passes",        "Total passes"),
    ("passes_pct",    "Passes %"),
    ("xg",            "expected_goals"),
]


async def get_team_historical_stats(team_name: str, league_name: str, last: int = 8, venue: str = "all") -> dict:
    teams = await search_team(team_name)
    if not teams:
        return {"error": f"Time '{team_name}' não encontrado."}
    team_id        = teams[0]["team"]["id"]
    team_real_name = teams[0]["team"]["name"]

    league_key = league_name.lower().replace(" ", "_").replace("ã", "a")
    league_id = None
    for key, lid in LEAGUES.items():
        if league_key in key or key in league_key:
            league_id = lid
            break
    if not league_id:
        return {"error": f"Liga '{league_name}' não encontrada."}

    season   = season_for(league_id)
    fixtures = await get_team_fixtures_by_league(team_id, league_id, season, last=last * 2)
    finished = [f for f in fixtures if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")]

    if venue == "home":
        finished = [f for f in finished if f["teams"]["home"]["id"] == team_id]
    elif venue == "away":
        finished = [f for f in finished if f["teams"]["away"]["id"] == team_id]

    if not finished:
        return {"error": f"Sem jogos finalizados para {team_real_name} em {league_name} ({venue})."}

    finished = finished[-last:]
    all_stats = await asyncio.gather(
        *[get_fixture_statistics_half(f["fixture"]["id"]) for f in finished],
        return_exceptions=True,
    )

    totals = _new_totals(); totals_1h = _new_totals(); totals_2h = _new_totals()
    goals_scored = 0.0; goals_conceded = 0.0; count = 0

    for f, stats in zip(finished, all_stats):
        if isinstance(stats, Exception) or not stats or len(stats) < 2:
            continue
        team_entry = next((s for s in stats if s["team"]["id"] == team_id), None)
        if not team_entry:
            continue
        ts    = team_entry.get("statistics", [])
        ts_1h = team_entry.get("statistics_1h", [])
        ts_2h = team_entry.get("statistics_2h", [])
        for key, src in _STAT_KEYS:
            totals[key]    += _extract_stat(ts, src)
            totals_1h[key] += _extract_stat(ts_1h, src)
            totals_2h[key] += _extract_stat(ts_2h, src)
        is_home = f["teams"]["home"]["id"] == team_id
        g = f["goals"]
        if is_home:
            goals_scored   += g["home"] or 0; goals_conceded += g["away"] or 0
        else:
            goals_scored   += g["away"] or 0; goals_conceded += g["home"] or 0
        count += 1

    if count == 0:
        return {"error": f"Sem dados de estatísticas disponíveis para {team_real_name} em {league_name}."}

    def avg(v: float) -> str: return f"{v / count:.1f}"
    def avg_half(d: dict) -> dict: return {k: avg(v) for k, v in d.items()}

    return {
        "team": team_real_name, "league": league_name, "season": season,
        "games_analyzed": count, "venue": venue,
        "avg_goals_scored": avg(goals_scored), "avg_goals_conceded": avg(goals_conceded),
        "total": avg_half(totals), "first_half": avg_half(totals_1h), "second_half": avg_half(totals_2h),
    }


async def get_team_historical_stats_any(team_name: str, last: int = 8, venue: str = "all") -> dict:
    teams = await search_team(team_name)
    if not teams:
        return {"error": f"Time '{team_name}' não encontrado."}
    team_id        = teams[0]["team"]["id"]
    team_real_name = teams[0]["team"]["name"]

    fixtures = await get_team_fixtures(team_id, last=last * 2)
    finished = [f for f in fixtures if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")]

    if venue == "home":
        finished = [f for f in finished if f["teams"]["home"]["id"] == team_id]
    elif venue == "away":
        finished = [f for f in finished if f["teams"]["away"]["id"] == team_id]

    if not finished:
        return {"error": f"Sem jogos finalizados para {team_real_name} ({venue})."}

    finished  = finished[-last:]
    all_stats = await asyncio.gather(
        *[get_fixture_statistics_half(f["fixture"]["id"]) for f in finished],
        return_exceptions=True,
    )

    totals = _new_totals(); totals_1h = _new_totals(); totals_2h = _new_totals()
    goals_scored = 0.0; goals_conceded = 0.0; count = 0

    for f, stats in zip(finished, all_stats):
        if isinstance(stats, Exception) or not stats or len(stats) < 2:
            continue
        team_entry = next((s for s in stats if s["team"]["id"] == team_id), None)
        if not team_entry:
            continue
        ts    = team_entry.get("statistics", [])
        ts_1h = team_entry.get("statistics_1h", [])
        ts_2h = team_entry.get("statistics_2h", [])
        for key, src in _STAT_KEYS:
            totals[key]    += _extract_stat(ts, src)
            totals_1h[key] += _extract_stat(ts_1h, src)
            totals_2h[key] += _extract_stat(ts_2h, src)
        is_home = f["teams"]["home"]["id"] == team_id
        g = f["goals"]
        if is_home:
            goals_scored   += g["home"] or 0; goals_conceded += g["away"] or 0
        else:
            goals_scored   += g["away"] or 0; goals_conceded += g["home"] or 0
        count += 1

    if count == 0:
        return {"error": f"Sem dados de estatísticas disponíveis para {team_real_name}."}

    def avg(v: float) -> str: return f"{v / count:.1f}"
    def avg_half(d: dict) -> dict: return {k: avg(v) for k, v in d.items()}

    return {
        "team": team_real_name, "league": "qualquer competição",
        "leagues_seen": list({f["league"]["name"] for f in finished}),
        "season": "recente", "games_analyzed": count, "venue": venue,
        "avg_goals_scored": avg(goals_scored), "avg_goals_conceded": avg(goals_conceded),
        "total": avg_half(totals), "first_half": avg_half(totals_1h), "second_half": avg_half(totals_2h),
    }


def _ht_result(f: dict, team_id: int) -> str | None:
    ht = f.get("score", {}).get("halftime", {})
    h, a = ht.get("home"), ht.get("away")
    if h is None or a is None:
        return None
    is_home = f["teams"]["home"]["id"] == team_id
    team_goals, opp_goals = (h, a) if is_home else (a, h)
    if team_goals > opp_goals:
        return "V"
    if team_goals < opp_goals:
        return "D"
    return "E"


async def get_team_halftime_record(team_name: str, league_name: str | None = None, last: int = 10) -> dict:
    teams = await search_team(team_name)
    if not teams:
        return {"error": f"Time '{team_name}' não encontrado."}
    team_id        = teams[0]["team"]["id"]
    team_real_name = teams[0]["team"]["name"]

    if league_name:
        league_key = league_name.lower().replace(" ", "_").replace("ã", "a")
        league_id = None
        for key, lid in LEAGUES.items():
            if league_key in key or key in league_key:
                league_id = lid
                break
        if not league_id:
            return {"error": f"Liga '{league_name}' não encontrada."}
        fixtures = await get_team_fixtures_by_league(team_id, league_id, season_for(league_id), last=last)
    else:
        fixtures = await get_team_fixtures(team_id, last=last)

    finished = [f for f in fixtures if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")]
    if not finished:
        return {"error": f"Sem jogos finalizados para {team_real_name}."}

    wins = draws = losses = 0
    rows = []
    for f in finished:
        res = _ht_result(f, team_id)
        if res is None:
            continue
        if res == "V":
            wins += 1
        elif res == "D":
            losses += 1
        else:
            draws += 1
        is_home = f["teams"]["home"]["id"] == team_id
        opp = f["teams"]["away"]["name"] if is_home else f["teams"]["home"]["name"]
        ht  = f["score"]["halftime"]
        rows.append({
            "date":     f["fixture"]["date"][:10],
            "opponent": opp,
            "ht_score": f"{ht['home']}x{ht['away']}",
            "result":   res,
        })

    total = wins + draws + losses
    if total == 0:
        return {"error": f"Sem dados de placar do intervalo para {team_real_name}."}

    return {
        "team": team_real_name, "games_analyzed": total,
        "ht_wins": wins, "ht_draws": draws, "ht_losses": losses,
        "matches": rows,
    }


async def get_team_recent_form(team_name: str, last: int = 5) -> dict:
    teams = await search_team(team_name)
    if not teams:
        return {"error": f"Time '{team_name}' não encontrado."}
    team_id  = teams[0]["team"]["id"]
    fixtures = await get_team_fixtures(team_id, last)
    if not fixtures:
        return {"error": "Sem jogos recentes disponíveis."}

    matches = []
    for f in fixtures:
        fmt = _fmt_past_fixture(f)
        team_is_home = f["teams"]["home"]["id"] == team_id
        result = (
            "V" if (team_is_home and f["teams"]["home"]["winner"]) or (not team_is_home and f["teams"]["away"]["winner"])
            else "D" if (team_is_home and f["teams"]["away"]["winner"]) or (not team_is_home and f["teams"]["home"]["winner"])
            else "E"
        )
        fmt["result_for_team"] = result
        matches.append(fmt)

    return {
        "team":         teams[0]["team"]["name"],
        "form":         "".join(m["result_for_team"] for m in matches),
        "last_matches": matches,
    }
