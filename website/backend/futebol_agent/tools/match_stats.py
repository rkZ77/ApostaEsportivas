from futebol_agent.api_football import (
    get_fixture_statistics, get_fixture_events, get_fixture_by_id,
    get_fixture_lineups, get_fixture_players, get_injuries,
    get_predictions, search_fixture,
)


async def get_match_full_stats(fixture_id: int) -> dict:
    stats_raw    = await get_fixture_statistics(fixture_id)
    events_raw   = await get_fixture_events(fixture_id)
    fixture_data = await get_fixture_by_id(fixture_id)

    stats: dict = {}
    for team_data in stats_raw:
        team_name = team_data["team"]["name"]
        stats[team_name] = {}
        for stat in team_data["statistics"]:
            stats[team_name][stat["type"]] = stat["value"]

    events = []
    for e in events_raw:
        events.append({
            "minute": e["time"]["elapsed"],
            "team":   e["team"]["name"],
            "player": e["player"]["name"],
            "type":   e["type"],
            "detail": e["detail"],
        })

    result: dict = {"statistics": stats, "events": events}

    if fixture_data:
        fixture = fixture_data["fixture"]
        teams   = fixture_data["teams"]
        goals   = fixture_data["goals"]
        status  = fixture["status"]
        result["match_info"] = {
            "home":   teams["home"]["name"],
            "away":   teams["away"]["name"],
            "score":  f"{goals['home'] or 0} x {goals['away'] or 0}",
            "minute": status.get("elapsed") or 0,
            "status": status["long"],
        }

    return result


async def find_and_get_stats(team1: str, team2: str) -> dict:
    fixtures = await search_fixture(team1, team2)
    if not fixtures:
        return {"error": f"Partida entre '{team1}' e '{team2}' não encontrada ao vivo ou hoje."}
    f = fixtures[0]
    fixture_id = f["fixture"]["id"]
    data = await get_match_full_stats(fixture_id)
    data["fixture_id"] = fixture_id
    return data


async def get_match_injuries(fixture_id: int) -> list[dict]:
    raw = await get_injuries(fixture_id)
    return [{
        "team":   p["team"]["name"],
        "player": p["player"]["name"],
        "reason": p["player"]["reason"],
        "type":   p["player"]["type"],
    } for p in raw]


async def get_match_lineups(fixture_id: int) -> list[dict]:
    raw = await get_fixture_lineups(fixture_id)
    result = []
    for team_data in raw:
        pos_map = {"G": [], "D": [], "M": [], "F": []}
        for entry in team_data.get("startXI", []):
            p = entry["player"]
            pos_map.get(p["pos"], pos_map["M"]).append(p["name"])
        result.append({
            "team":        team_data["team"]["name"],
            "formation":   team_data.get("formation", "?"),
            "coach":       team_data.get("coach", {}).get("name", "?"),
            "gk":          pos_map["G"],
            "defenders":   pos_map["D"],
            "midfielders": pos_map["M"],
            "forwards":    pos_map["F"],
            "substitutes": [e["player"]["name"] for e in team_data.get("substitutes", [])],
        })
    return result


async def get_match_player_stats(fixture_id: int) -> list[dict]:
    raw = await get_fixture_players(fixture_id)
    result = []
    for team_data in raw:
        team_name = team_data["team"]["name"]
        players = []
        for entry in team_data.get("players", []):
            p = entry["player"]
            s = entry["statistics"][0] if entry.get("statistics") else {}
            games    = s.get("games", {})
            minutes  = games.get("minutes") or 0
            if minutes == 0:
                continue
            shots    = s.get("shots", {})
            goals    = s.get("goals", {})
            passes   = s.get("passes", {})
            tackles  = s.get("tackles", {})
            duels    = s.get("duels", {})
            dribbles = s.get("dribbles", {})
            fouls    = s.get("fouls", {})
            cards    = s.get("cards", {})
            players.append({
                "name":              p["name"],
                "pos":               games.get("position", "?"),
                "minutes":           minutes,
                "rating":            games.get("rating"),
                "captain":           games.get("captain", False),
                "goals":             goals.get("total") or 0,
                "assists":           goals.get("assists") or 0,
                "shots":             shots.get("total") or 0,
                "shots_on":          shots.get("on") or 0,
                "key_passes":        passes.get("key") or 0,
                "pass_acc":          passes.get("accuracy"),
                "tackles":           tackles.get("total") or 0,
                "interceptions":     tackles.get("interceptions") or 0,
                "duels_won":         duels.get("won") or 0,
                "dribbles":          dribbles.get("success") or 0,
                "fouls_drawn":       fouls.get("drawn") or 0,
                "fouls_committed":   fouls.get("committed") or 0,
                "yellow":            cards.get("yellow") or 0,
                "red":               cards.get("red") or 0,
            })
        players.sort(key=lambda x: (float(x["rating"] or 0), x["minutes"]), reverse=True)
        result.append({"team": team_name, "players": players})
    return result


async def get_match_prediction(fixture_id: int) -> dict | None:
    raw = await get_predictions(fixture_id)
    if not raw:
        return None
    pred       = raw.get("predictions", {})
    teams      = raw.get("teams", {})
    comparison = raw.get("comparison", {})
    return {
        "winner":       pred.get("winner", {}).get("name"),
        "win_or_draw":  pred.get("win_or_draw"),
        "advice":       pred.get("advice"),
        "percent":      pred.get("percent", {}),
        "goals":        pred.get("goals", {}),
        "under_over":   pred.get("under_over"),
        "home_form":    teams.get("home", {}).get("league", {}).get("form", ""),
        "away_form":    teams.get("away", {}).get("league", {}).get("form", ""),
        "comparison":   {k: comparison.get(k, {}) for k in ["form", "att", "def", "poisson_distribution", "h2h"]},
    }
