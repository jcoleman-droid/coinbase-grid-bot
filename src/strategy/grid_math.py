from __future__ import annotations

import numpy as np


def compute_grid_levels(
    lower: float, upper: float, num_levels: int, spacing: str = "arithmetic"
) -> list[float]:
    if spacing == "arithmetic":
        return [float(x) for x in np.linspace(lower, upper, num_levels)]
    elif spacing == "geometric":
        return [float(x) for x in np.geomspace(lower, upper, num_levels)]
    raise ValueError(f"Unknown spacing: {spacing}")


def determine_order_sides(
    levels: list[float], current_price: float
) -> list[tuple[float, str]]:
    result = []
    for price in levels:
        side = "buy" if price < current_price else "sell"
        result.append((price, side))
    return result


def calculate_order_amount(
    order_size_usd: float | None,
    order_size_base: float | None,
    price: float,
) -> float:
    if order_size_base is not None:
        return order_size_base
    if order_size_usd is not None:
        return order_size_usd / price
    raise ValueError("Either order_size_usd or order_size_base must be set")
