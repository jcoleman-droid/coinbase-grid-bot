from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimulatedOrder:
    id: str
    side: str
    price: float
    amount: float
    status: str = "open"
    filled_amount: float = 0.0
    fill_price: float = 0.0
    fee: float = 0.0


class BacktestSimulator:
    def __init__(self, fee_pct: float = 0.006, slippage_bps: float = 5.0):
        self._fee_pct = fee_pct
        self._slippage_bps = slippage_bps
        self._orders: dict[str, SimulatedOrder] = {}
        self._next_id = 0
        self._base_balance = 0.0
        self._quote_balance = 0.0

    def set_balances(self, base: float, quote: float) -> None:
        self._base_balance = base
        self._quote_balance = quote

    def place_order(self, side: str, price: float, amount: float) -> SimulatedOrder:
        self._next_id += 1
        oid = f"sim-{self._next_id}"
        order = SimulatedOrder(id=oid, side=side, price=price, amount=amount)
        self._orders[oid] = order
        return order

    def process_candle(self, high: float, low: float) -> list[SimulatedOrder]:
        filled = []
        for order in list(self._orders.values()):
            if order.status != "open":
                continue

            if order.side == "buy" and low <= order.price:
                slip = order.price * (self._slippage_bps / 10000)
                fill_price = order.price + slip
                fee = fill_price * order.amount * self._fee_pct
                cost = fill_price * order.amount + fee

                if self._quote_balance < cost:
                    continue

                order.fill_price = fill_price
                order.filled_amount = order.amount
                order.fee = fee
                order.status = "filled"
                self._base_balance += order.amount
                self._quote_balance -= cost
                filled.append(order)

            elif order.side == "sell" and high >= order.price:
                slip = order.price * (self._slippage_bps / 10000)
                fill_price = order.price - slip
                fee = fill_price * order.amount * self._fee_pct

                if self._base_balance < order.amount:
                    continue

                order.fill_price = fill_price
                order.filled_amount = order.amount
                order.fee = fee
                order.status = "filled"
                self._base_balance -= order.amount
                self._quote_balance += fill_price * order.amount - fee
                filled.append(order)

        return filled

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id].status = "cancelled"
            return True
        return False

    @property
    def base_balance(self) -> float:
        return self._base_balance

    @property
    def quote_balance(self) -> float:
        return self._quote_balance
