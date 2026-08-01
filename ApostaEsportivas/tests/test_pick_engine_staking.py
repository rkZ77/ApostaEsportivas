from services.pick_engine.staking import calculate_stake


def test_non_positive_ev_uses_minimum_stake_for_single_picks():
    assert calculate_stake(0.80, 2.0, ev=0.0, pick_type="vip") == (0.01, 1)


def test_vip_stake_is_capped_and_converted_to_units():
    stake_pct, units = calculate_stake(0.90, 2.0, ev=0.20, pick_type="vip")

    assert stake_pct == 0.05
    assert units == 5


def test_multipla_accepts_its_score_without_ev():
    stake_pct, units = calculate_stake(0.75, 3.0, pick_type="multipla")

    assert stake_pct == 0.025
    assert units == 2
