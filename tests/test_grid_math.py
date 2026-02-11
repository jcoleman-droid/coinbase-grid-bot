from src.strategy.grid_math import (
    calculate_order_amount,
    compute_grid_levels,
    determine_order_sides,
)


def test_arithmetic_grid_levels():
    levels = compute_grid_levels(100.0, 200.0, 6, "arithmetic")
    assert len(levels) == 6
    assert levels[0] == 100.0
    assert levels[-1] == 200.0
    # Even spacing
    step = levels[1] - levels[0]
    for i in range(1, len(levels)):
        assert abs((levels[i] - levels[i - 1]) - step) < 0.01


def test_geometric_grid_levels():
    levels = compute_grid_levels(100.0, 400.0, 3, "geometric")
    assert len(levels) == 3
    assert abs(levels[0] - 100.0) < 0.01
    assert abs(levels[1] - 200.0) < 0.01
    assert abs(levels[2] - 400.0) < 0.01


def test_determine_order_sides():
    levels = [100.0, 110.0, 120.0, 130.0, 140.0]
    sides = determine_order_sides(levels, 125.0)
    assert sides[0] == (100.0, "buy")
    assert sides[1] == (110.0, "buy")
    assert sides[2] == (120.0, "buy")
    assert sides[3] == (130.0, "sell")
    assert sides[4] == (140.0, "sell")


def test_calculate_order_amount_usd():
    amount = calculate_order_amount(100.0, None, 50000.0)
    assert abs(amount - 0.002) < 0.0001


def test_calculate_order_amount_base():
    amount = calculate_order_amount(None, 0.5, 50000.0)
    assert amount == 0.5
