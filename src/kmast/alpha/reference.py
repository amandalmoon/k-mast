"""Independent reference accounts. Matching requires a later, explicit executable tick."""

from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from pydantic import AwareDatetime, Field

from kmast.alpha.models import AlphaResult
from kmast.core.base import Contract, Identifier, Nonnegative, Positive, Weight
from kmast.data.normalization import content_hash


class SimCosts(Contract):
    version: Identifier
    fee_bps: Nonnegative
    sell_tax_bps: Nonnegative
    slippage_bps: Nonnegative
    max_participation: Weight
    cost_scope: Literal["SYNTHETIC_ASSUMPTION", "REAL_UNVERIFIED"] = "SYNTHETIC_ASSUMPTION"


class Tick(Contract):
    identity: Identifier
    symbol: Identifier
    at: AwareDatetime
    available_at: AwareDatetime
    bid: Positive
    ask: Positive
    available_quantity: int = Field(ge=0, strict=True)
    executable: bool
    origin: Literal["SYNTHETIC", "REAL_UNVERIFIED"] = "SYNTHETIC"


class RefLot(Contract):
    symbol: Identifier
    quantity: int = Field(gt=0, strict=True)
    unit_cost: Positive
    at: AwareDatetime


class RefOrder(Contract):
    identity: Identifier
    symbol: Identifier
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, strict=True)
    lot_size: int = Field(default=1, gt=0, strict=True)
    filled: int = Field(default=0, ge=0, strict=True)
    limit: Positive
    submitted_at: AwareDatetime
    executable_after: AwareDatetime
    market_close: AwareDatetime | None = None
    expires_at: AwareDatetime
    status: Literal["OPEN", "PARTIAL", "FILLED", "EXPIRED", "REJECTED"] = "OPEN"


class Valuation(Contract):
    at: AwareDatetime
    nav: Nonnegative
    cash: Nonnegative
    occupied_capital: Nonnegative
    reserved_cash: Nonnegative
    mark_status: Literal["FRESH", "UNVERIFIED"]


class RefState(Contract):
    strategy: Literal["A", "B", "C", "D"]
    ledger_type: Literal["REFERENCE"] = "REFERENCE"
    capital: Positive
    cash: Nonnegative
    lots: tuple[RefLot, ...] = ()
    orders: tuple[RefOrder, ...] = ()
    marks: tuple[tuple[Identifier, Positive, AwareDatetime], ...] = ()
    realized: Decimal = Field(default=Decimal(0), allow_inf_nan=False)
    costs: Nonnegative = Decimal(0)
    dividends: Nonnegative = Decimal(0)
    operating_costs: Nonnegative = Decimal(0)
    turnover: Nonnegative = Decimal(0)
    executions: tuple[
        tuple[Identifier, AwareDatetime, Identifier, int, Positive, Nonnegative], ...
    ] = ()
    holding_seconds: Nonnegative = Decimal(0)
    closed_quantity: int = Field(default=0, ge=0)
    panel: tuple[Valuation, ...] = ()
    facts: tuple[tuple[Identifier, Identifier], ...] = ()
    warnings: tuple[Identifier, ...] = ()
    unexecutable_symbols: tuple[Identifier, ...] = ()
    peak_reserved_cash: Nonnegative = Decimal(0)
    peak_occupied_capital: Nonnegative = Decimal(0)


def update(state: RefState, **changes: object) -> RefState:
    return RefState.model_validate(state.model_dump() | changes)


class ReferencePortfolio:
    def __init__(self, strategy: Literal["A", "B", "C", "D"], capital: Decimal, costs: SimCosts):
        self.state = RefState(strategy=strategy, capital=capital, cash=capital)
        self.costs = costs

    def quantity(self, symbol: str) -> int:
        return sum(lot.quantity for lot in self.state.lots if lot.symbol == symbol)

    @property
    def nav(self) -> Decimal:
        prices = {s: p for s, p, _ in self.state.marks}
        if any(lot.symbol not in prices for lot in self.state.lots):
            raise ValueError("missing reference valuation mark")
        return self.state.cash + sum(
            (lot.quantity * prices[lot.symbol] for lot in self.state.lots), Decimal(0)
        )

    def reserve_for(self, order: RefOrder) -> Decimal:
        if order.side != "BUY" or order.status not in {"OPEN", "PARTIAL"}:
            return Decimal(0)
        notional = (order.quantity - order.filled) * order.limit
        return notional + (notional * self.costs.fee_bps / 10000).quantize(
            Decimal(".01"),
            rounding=ROUND_CEILING,
        )

    @property
    def reserve(self) -> Decimal:
        return sum((self.reserve_for(o) for o in self.state.orders), Decimal(0))

    def submit(self, result: AlphaResult, limits: dict[str, Decimal], lot_size: int = 1) -> None:
        if result.snapshot.strategy_id != self.state.strategy or lot_size < 1:
            raise ValueError("reference identity or lot unit mismatch")
        nav = self.nav
        orders = list(self.state.orders)
        for signal in result.snapshot.intents:
            identity = content_hash([result.snapshot.snapshot_id, signal.symbol])
            if any(o.identity == identity for o in orders):
                continue
            price = limits[signal.symbol]
            if price <= 0:
                raise ValueError("invalid reference limit")
            desired = int(signal.target_weight * nav / price) // lot_size * lot_size
            active = [
                o for o in orders if o.symbol == signal.symbol and o.status in {"OPEN", "PARTIAL"}
            ]
            pending = sum((o.quantity - o.filled) * (1 if o.side == "BUY" else -1) for o in active)
            delta = desired - self.quantity(signal.symbol) - pending
            if not delta:
                continue
            side = "BUY" if delta > 0 else "SELL"
            conflict = any(o.side != side for o in active)
            cost = abs(delta) * price * (1 + self.costs.fee_bps / 10000)
            reserved = sum((self.reserve_for(o) for o in orders), Decimal(0))
            rejected = (
                conflict
                or (side == "BUY" and cost > self.state.cash - reserved)
                or (
                    result.execution_window_end is not None
                    and result.earliest_execution_at >= result.execution_window_end
                )
            )
            order = RefOrder(
                identity=identity,
                symbol=signal.symbol,
                side=side,
                quantity=abs(delta),
                lot_size=lot_size,
                limit=price,
                submitted_at=signal.decision_at,
                executable_after=result.earliest_execution_at,
                market_close=result.execution_window_end,
                expires_at=signal.valid_until,
                status="REJECTED" if rejected else "OPEN",
            )
            orders.append(order)
        self.state = update(self.state, orders=tuple(orders))
        self.state = update(
            self.state, peak_reserved_cash=max(self.state.peak_reserved_cash, self.reserve)
        )

    def expire(self, now: AwareDatetime) -> None:
        self.state = update(
            self.state,
            orders=tuple(
                RefOrder.model_validate(o.model_dump() | {"status": "EXPIRED"})
                if o.status in {"OPEN", "PARTIAL"} and o.expires_at <= now
                else o
                for o in self.state.orders
            ),
        )

    def match(self, tick: Tick, now: AwareDatetime) -> None:
        if tick.available_at > now or tick.at > tick.available_at or tick.bid > tick.ask:
            raise ValueError("noncausal or crossed execution tick")
        fingerprint = content_hash(tick.model_dump(mode="json"))
        old = dict(self.state.facts).get(tick.identity)
        if old:
            if old != fingerprint:
                raise ValueError("conflicting execution identity")
            return
        if self.state.executions and tick.at < self.state.executions[-1][1]:
            raise ValueError("out of order economic execution")
        self.expire(now)
        state = self.state
        capacity = int(tick.available_quantity * self.costs.max_participation)
        orders = list(state.orders)
        for index, order in enumerate(orders):
            if (
                order.symbol != tick.symbol
                or order.status not in {"OPEN", "PARTIAL"}
                or tick.at <= order.submitted_at
                or tick.at < order.executable_after
                or tick.at >= order.expires_at
                or (order.market_close is not None and tick.at >= order.market_close)
                or not tick.executable
                or capacity <= 0
            ):
                continue
            buying = order.side == "BUY"
            price = (
                (tick.ask if buying else tick.bid)
                * (1 + self.costs.slippage_bps / 10000 * (1 if buying else -1))
            ).quantize(Decimal(".01"), rounding=ROUND_CEILING if buying else ROUND_FLOOR)
            if (
                (buying and price > order.limit)
                or (not buying and price < order.limit)
                or price <= 0
            ):
                continue  # A touched passive limit is not queue/priority evidence.
            qty = min(order.quantity - order.filled, capacity)
            qty = qty // order.lot_size * order.lot_size
            if not qty:
                continue
            notional = qty * price
            fee = (
                notional * (self.costs.fee_bps + (0 if buying else self.costs.sell_tax_bps)) / 10000
            ).quantize(Decimal(".01"), rounding=ROUND_CEILING)
            lots = list(state.lots)
            realized = state.realized
            duration = state.holding_seconds
            closed = state.closed_quantity
            if buying:
                if notional + fee > state.cash:
                    continue
                lots.append(RefLot(symbol=tick.symbol, quantity=qty, unit_cost=price, at=tick.at))
            else:
                if qty > sum(lot.quantity for lot in lots if lot.symbol == tick.symbol):
                    raise ValueError("reference oversell")
                remaining = qty
                kept = []
                for lot in lots:
                    take = min(remaining, lot.quantity) if lot.symbol == tick.symbol else 0
                    remaining -= take
                    realized += take * (price - lot.unit_cost)
                    duration += take * Decimal(str((tick.at - lot.at).total_seconds()))
                    closed += take
                    if lot.quantity > take:
                        kept.append(
                            RefLot.model_validate(
                                lot.model_dump() | {"quantity": lot.quantity - take}
                            )
                        )
                lots = kept
            filled = order.filled + qty
            orders[index] = RefOrder.model_validate(
                order.model_dump()
                | {
                    "filled": filled,
                    "status": "FILLED" if filled == order.quantity else "PARTIAL",
                }
            )
            state = update(
                state,
                cash=state.cash + (-notional if buying else notional) - fee,
                lots=tuple(lots),
                costs=state.costs + fee,
                realized=realized,
                turnover=state.turnover + notional,
                holding_seconds=duration,
                closed_quantity=closed,
                executions=(
                    *state.executions,
                    (
                        tick.identity + order.identity,
                        tick.at,
                        tick.symbol,
                        qty if buying else -qty,
                        price,
                        fee,
                    ),
                ),
            )
            capacity -= qty
        self.state = update(
            state,
            orders=tuple(orders),
            facts=(*state.facts, (tick.identity, fingerprint)),
            unexecutable_symbols=tuple(
                sorted(
                    (set(state.unexecutable_symbols) - {tick.symbol})
                    if tick.executable
                    else (set(state.unexecutable_symbols) | {tick.symbol})
                )
            ),
        )
        self.mark(tick.symbol, (tick.bid + tick.ask) / 2, tick.at)

    def mark(self, symbol: str, price: Decimal, at: AwareDatetime) -> None:
        previous = next((t for s, _, t in self.state.marks if s == symbol), None)
        if price <= 0 or (previous is not None and at < previous):
            raise ValueError("invalid or backwards valuation mark")
        self.state = update(
            self.state,
            marks=tuple(
                sorted([m for m in self.state.marks if m[0] != symbol] + [(symbol, price, at)])
            ),
        )

        self.state = update(
            self.state,
            peak_occupied_capital=max(
                self.state.peak_occupied_capital,
                self.nav - self.state.cash,
            ),
        )

    def corporate_action(
        self,
        identity: str,
        symbol: str,
        at: AwareDatetime,
        *,
        available_at: AwareDatetime,
        now: AwareDatetime,
        split: Decimal = Decimal(1),
        cash_per_share: Decimal = Decimal(0),
    ) -> None:
        if not at <= available_at <= now:
            raise ValueError("corporate action not available at simulation clock")
        fingerprint = content_hash([symbol, at.isoformat(), str(split), str(cash_per_share)])
        old = dict(self.state.facts).get(identity)
        if old:
            if old != fingerprint:
                raise ValueError("conflicting corporate action")
            return
        if self.state.panel and at <= self.state.panel[-1].at:
            raise ValueError("late corporate action requires explicit replay")
        if (
            split <= 0
            or cash_per_share < 0
            or self.reserve
            or any(o.status in {"OPEN", "PARTIAL"} for o in self.state.orders)
        ):
            raise ValueError("invalid action or pending order adjustment required")
        dividend = self.quantity(symbol) * cash_per_share
        lots = []
        for lot in self.state.lots:
            if lot.symbol != symbol:
                lots.append(lot)
                continue
            if lot.quantity * split != int(lot.quantity * split):
                raise ValueError("fractional entitlement requires cash-in-lieu evidence")
            lots.append(
                RefLot.model_validate(
                    lot.model_dump()
                    | {
                        "quantity": int(lot.quantity * split),
                        "unit_cost": lot.unit_cost / split,
                    }
                )
            )
        marks = tuple((s, p / split if s == symbol else p, t) for s, p, t in self.state.marks)
        self.state = update(
            self.state,
            lots=tuple(lots),
            marks=marks,
            cash=self.state.cash + dividend,
            dividends=self.state.dividends + dividend,
            facts=(*self.state.facts, (identity, fingerprint)),
        )

    def value(self, at: AwareDatetime, daily_operating_cost: Decimal = Decimal(0)) -> Valuation:
        if self.state.panel and at <= self.state.panel[-1].at:
            raise ValueError("valuation clock must advance")
        if daily_operating_cost < 0 or daily_operating_cost > self.state.cash - self.reserve:
            raise ValueError("operating cost exceeds unreserved cash")
        if any(t > at for _, _, t in self.state.marks):
            raise ValueError("future valuation mark")
        self.state = update(
            self.state,
            cash=self.state.cash - daily_operating_cost,
            operating_costs=self.state.operating_costs + daily_operating_cost,
        )
        stale = any(t.date() < at.date() for s, _, t in self.state.marks if self.quantity(s))
        stale = stale or any(self.quantity(symbol) for symbol in self.state.unexecutable_symbols)
        row = Valuation(
            at=at,
            nav=self.nav,
            cash=self.state.cash,
            occupied_capital=self.nav - self.state.cash,
            reserved_cash=self.reserve,
            mark_status="UNVERIFIED" if stale else "FRESH",
        )
        unrealized = sum(
            (
                lot.quantity
                * (dict((s, p) for s, p, _ in self.state.marks)[lot.symbol] - lot.unit_cost)
                for lot in self.state.lots
            ),
            Decimal(0),
        )
        if row.nav - self.state.capital != (
            self.state.realized
            + unrealized
            + self.state.dividends
            - self.state.costs
            - self.state.operating_costs
        ):
            raise ValueError("reference conservation failure")
        self.state = update(self.state, panel=(*self.state.panel, row))
        return row

    def metrics(
        self, expected_dates: tuple[date, ...], cash_rate_daily: Decimal = Decimal(0)
    ) -> dict[str, object]:
        rows = self.state.panel
        if not rows or tuple(row.at.date() for row in rows) != expected_dates:
            raise ValueError("complete common daily panel required")
        last = self.state.capital
        peak = last
        twr = Decimal(1)
        drawdown = Decimal(0)
        for row in rows:
            if last <= 0:
                raise ValueError("undefined return after capital exhaustion")
            twr *= row.nav / last
            peak = max(peak, row.nav)
            drawdown = max(drawdown, 1 - row.nav / peak)
            last = row.nav
        net = rows[-1].nav - self.state.capital
        cash_nav = (
            self.state.capital * (1 + cash_rate_daily) ** len(rows) - self.state.operating_costs
        )
        return {
            "gross_pnl": str(net + self.state.costs + self.state.operating_costs),
            "after_trading_cost_pnl": str(net + self.state.operating_costs),
            "NET_OPERATING_PNL_KRW": str(net),
            "initial_capital": str(self.state.capital),
            "average_nav": str(sum((r.nav for r in rows), Decimal(0)) / len(rows)),
            "time_weighted_return": str(twr - 1),
            "cash_excess_krw": str(rows[-1].nav - cash_nav),
            "max_drawdown": str(drawdown),
            "turnover": str(self.state.turnover / self.state.capital),
            "average_closed_holding_seconds": str(
                self.state.holding_seconds / self.state.closed_quantity
            )
            if self.state.closed_quantity
            else None,
            "execution_count": len(self.state.executions),
            "independent_sample_count": None,
            "daily_observations": len(rows),
            "unfilled_quantity": sum(
                o.quantity - o.filled for o in self.state.orders if o.status != "REJECTED"
            ),
            "rejected_quantity": sum(
                o.quantity for o in self.state.orders if o.status == "REJECTED"
            ),
            "rejected_orders": sum(o.status == "REJECTED" for o in self.state.orders),
            "max_occupied_capital": str(self.state.peak_occupied_capital),
            "max_reserved_cash": str(self.state.peak_reserved_cash),
            "economic_status": "HOLD",
            "reason": "REAL_DATA_AND_COSTS_UNVERIFIED",
        }
