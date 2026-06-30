from routers.live import _profit_for_result


def test_green_pays_odd_minus_one():
    assert _profit_for_result("GREEN", 2.0) == 1.0
    assert _profit_for_result("GREEN", 1.5) == 0.5


def test_red_loses_full_unit():
    assert _profit_for_result("RED", 2.0) == -1.0


def test_push_breaks_even():
    assert _profit_for_result("PUSH", 1.8) == 0.0


def test_half_win_pays_half_the_odd_gain():
    assert _profit_for_result("HALF-WIN", 2.0) == 0.5


def test_half_loss_loses_half_unit():
    assert _profit_for_result("HALF-LOSS", 2.0) == -0.5
