from futebol_agent.tools.head_to_head import _ht_result

TEAM_ID = 1


def _fixture(home_id, away_id, ht_home, ht_away):
    return {
        "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
        "score": {"halftime": {"home": ht_home, "away": ht_away}},
    }


def test_team_winning_at_halftime_as_home():
    f = _fixture(TEAM_ID, 2, 1, 0)
    assert _ht_result(f, TEAM_ID) == "V"


def test_team_losing_at_halftime_as_away():
    f = _fixture(2, TEAM_ID, 1, 0)
    assert _ht_result(f, TEAM_ID) == "D"


def test_draw_at_halftime():
    f = _fixture(TEAM_ID, 2, 1, 1)
    assert _ht_result(f, TEAM_ID) == "E"


def test_missing_halftime_score_returns_none():
    f = _fixture(TEAM_ID, 2, None, None)
    assert _ht_result(f, TEAM_ID) is None
