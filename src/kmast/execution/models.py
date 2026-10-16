from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from kmast.core.base import Contract, Identifier, Weight
from kmast.core.contracts import CapitalBudget, PortfolioDecision, PortfolioTarget
from kmast.data.normalization import content_hash

Money = Annotated[Decimal, Field(max_digits=24, decimal_places=2, allow_inf_nan=False)]
Cash = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=2, allow_inf_nan=False)]
Price = Annotated[Decimal, Field(gt=0, max_digits=24, decimal_places=2, allow_inf_nan=False)]
Qty = Annotated[int, Field(ge=0, strict=True)]
PositiveQty = Annotated[int, Field(gt=0, strict=True)]
Sleeve = Literal["A", "B", "C", "D", "EXTERNAL", "CENTRAL"]
Side = Literal["BUY", "SELL"]
Status = Literal[
    "INTENT",
    "TARGET",
    "RISK_APPROVED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "REJECTED",
    "CANCEL_PENDING",
    "CANCELLED",
    "UNKNOWN",
    "RECONCILING",
]
TERMINAL = {"FILLED", "CANCELLED", "REJECTED"}
TRANSITIONS: dict[str, frozenset[str]] = {
    "INTENT": frozenset({"TARGET", "REJECTED"}),
    "TARGET": frozenset({"RISK_APPROVED", "REJECTED"}),
    "RISK_APPROVED": frozenset({"SUBMITTING", "REJECTED"}),
    "SUBMITTING": frozenset({"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "UNKNOWN", "REJECTED"}),
    "ACKNOWLEDGED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "UNKNOWN"}),
    "PARTIALLY_FILLED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "UNKNOWN"}),
    "CANCEL_PENDING": frozenset({"CANCEL_PENDING", "FILLED", "CANCELLED", "UNKNOWN"}),
    "UNKNOWN": frozenset({"RECONCILING", "UNKNOWN", "FILLED"}),
    "RECONCILING": frozenset(
        {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}
    ),
    "FILLED": frozenset(),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
}


class SettlementCalendar(Contract):
    version: Identifier
    source_ref: Identifier
    eligible_dates: tuple[date, ...]
    overrides: tuple[tuple[date, date], ...] = ()
    scope: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"

    @model_validator(mode="after")
    def unique(self) -> Self:
        if tuple(sorted(set(self.eligible_dates))) != self.eligible_dates:
            raise ValueError("calendar must be ordered and unique")
        if len(dict(self.overrides)) != len(self.overrides):
            raise ValueError("duplicate settlement override")
        if any(end <= start or end not in self.eligible_dates for start, end in self.overrides):
            raise ValueError("invalid settlement override")
        return self

    def due(self, trade_date: date) -> date:
        if trade_date not in self.eligible_dates:
            raise ValueError("trade date not in verified calendar")
        if trade_date in dict(self.overrides):
            return dict(self.overrides)[trade_date]
        later = [day for day in self.eligible_dates if day > trade_date]
        if len(later) < 2:
            raise ValueError("settlement calendar coverage insufficient")
        return later[1]


class Quote(Contract):
    symbol: Identifier
    venue: Literal["KRX"] = "KRX"
    session: Literal["REGULAR", "AUCTION", "CLOSED", "UNKNOWN"]
    price: Price
    at: AwareDatetime
    available_at: AwareDatetime
    sector: Identifier
    halted: bool = False
    vi: bool = False
    liquidity_quantity: Qty
    lower_limit: Price
    upper_limit: Price
    tick_size: Price
    lot_size: PositiveQty = 1
    source_ref: Identifier
    session_ends_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower_limit > self.upper_limit or self.at > self.available_at:
            raise ValueError("invalid quote bounds or time")
        return self


class Lot(Contract):
    lot_id: Identifier
    fill_id: Identifier
    symbol: Identifier
    quantity: PositiveQty
    unit_cost: Price
    origin_unit_cost: Price
    acquired_at: AwareDatetime
    origin_sleeve: Sleeve
    lineage: tuple[Identifier, ...]
    settled: bool = False
    holding_deadline: AwareDatetime | None = None


class Book(Contract):
    settled_cash: Cash = Decimal(0)
    unsettled_receivables: Cash = Decimal(0)
    unsettled_payables: Cash = Decimal(0)
    reserved_buy_cash: Cash = Decimal(0)
    dividend_receivable: Cash = Decimal(0)
    fees_payable: Cash = Decimal(0)
    taxes_payable: Cash = Decimal(0)
    other_liabilities: Cash = Decimal(0)
    capital_flows: Money = Decimal(0)
    realized_pnl: Money = Decimal(0)
    fees_and_taxes: Cash = Decimal(0)
    interest: Money = Decimal(0)
    dividends: Money = Decimal(0)
    account_opex: Cash = Decimal(0)
    lots: tuple[Lot, ...] = ()
    tax_cost_basis: Literal["UNVERIFIED_NOT_TAX_LEDGER"] = "UNVERIFIED_NOT_TAX_LEDGER"

    def quantity(self, symbol: str) -> int:
        return sum(lot.quantity for lot in self.lots if lot.symbol == symbol)

    def sellable(self, symbol: str) -> int:
        return sum(lot.quantity for lot in self.lots if lot.symbol == symbol and lot.settled)

    def cost(self, symbol: str) -> Decimal:
        return sum(
            (lot.quantity * lot.unit_cost for lot in self.lots if lot.symbol == symbol), Decimal(0)
        )

    @property
    def conservative_cash(self) -> Decimal:
        return (
            self.settled_cash
            - self.unsettled_payables
            - self.reserved_buy_cash
            - self.fees_payable
            - self.taxes_payable
            - self.other_liabilities
        )

    def nav(self, quotes: tuple[Quote, ...]) -> Decimal:
        prices = {quote.symbol: quote.price for quote in quotes}
        if any(lot.symbol not in prices for lot in self.lots):
            raise ValueError("VALUATION_UNVERIFIED: missing mark")
        return (
            self.settled_cash
            + self.unsettled_receivables
            - self.unsettled_payables
            + sum((lot.quantity * prices[lot.symbol] for lot in self.lots), Decimal(0))
            + self.dividend_receivable
            - self.other_liabilities
            - self.fees_payable
            - self.taxes_payable
        )

    def gross_pnl(self, quotes: tuple[Quote, ...]) -> Decimal:
        prices = {quote.symbol: quote.price for quote in quotes}
        return self.realized_pnl + sum(
            (lot.quantity * (prices[lot.symbol] - lot.unit_cost) for lot in self.lots), Decimal(0)
        )


class Attribution(Contract):
    sleeve: Sleeve
    book: Book = Book()


class Order(Contract):
    client_order_id: Identifier
    broker_order_id: Identifier | None = None
    symbol: Identifier
    side: Side
    quantity: PositiveQty
    limit_price: Price
    fee_buffer: Cash
    filled: Qty = 0
    fees_incurred: Cash = Decimal(0)
    allocations: tuple[tuple[Sleeve, PositiveQty], ...]
    state: Status = "SUBMITTING"
    target_version: Identifier
    decision_id: Identifier
    history: tuple[str, ...] = ("INTENT", "TARGET", "RISK_APPROVED", "SUBMITTING")
    holding_deadlines: tuple[tuple[Sleeve, AwareDatetime], ...] = ()

    @model_validator(mode="after")
    def quantities(self) -> Self:
        if self.filled > self.quantity or sum(q for _, q in self.allocations) != self.quantity:
            raise ValueError("invalid order quantities")
        if len(dict(self.allocations)) != len(self.allocations):
            raise ValueError("duplicate order sleeve")
        if any(s in {"EXTERNAL", "CENTRAL"} for s, _ in self.allocations):
            raise ValueError("managed orders cannot consume external/central inventory")
        if self.fees_incurred > self.fee_buffer:
            raise ValueError("execution costs exceed reserved buffer")
        if self.state == "FILLED" and self.filled != self.quantity:
            raise ValueError("FILLED requires full quantity")
        return self

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled

    @property
    def reserve(self) -> Decimal:
        if self.state in TERMINAL or self.side == "SELL":
            return Decimal(0)
        return self.limit_price * self.remaining + self.fee_buffer - self.fees_incurred


class Settlement(Contract):
    exec_id: Identifier
    side: Side
    notional: Cash
    fee: Cash
    tax: Cash
    sleeve_amounts: tuple[tuple[Sleeve, Cash, Cash, Cash], ...]
    due: date
    settled: bool = False


class FillReceipt(Contract):
    exec_id: Identifier
    fingerprint: Identifier
    order_id: Identifier
    allocations: tuple[tuple[Sleeve, PositiveQty], ...]
    at: AwareDatetime


class MockRiskPolicy(Contract):
    version: Identifier
    scope: Literal["UNVERIFIED", "SYNTHETIC_ONLY"] = "UNVERIFIED"
    approved_by: Identifier | None = None
    max_symbol_weight: Weight | None = None
    max_sector_weight: Weight | None = None
    max_gross_weight: Weight | None = None
    max_sleeve_weight: Weight | None = None
    loss_limit_krw: Cash | None = None
    sleeve_loss_limit_krw: Cash | None = None
    stress_loss_limit_krw: Cash | None = None
    stress_shock: Weight | None = None
    max_participation: Weight | None = None
    max_overnight_weight: Weight | None = None
    quote_max_age: timedelta = Field(default=timedelta(seconds=30), gt=timedelta(0))
    decision_lifetime: timedelta = Field(default=timedelta(seconds=10), gt=timedelta(0))
    allow_overnight: bool = False
    averaging_down_allowed: Literal[False] = False

    def complete(self) -> bool:
        return (
            self.scope == "SYNTHETIC_ONLY"
            and bool(self.approved_by)
            and all(
                getattr(self, field) is not None
                for field in (
                    "max_symbol_weight",
                    "max_sector_weight",
                    "max_gross_weight",
                    "max_sleeve_weight",
                    "loss_limit_krw",
                    "sleeve_loss_limit_krw",
                    "stress_loss_limit_krw",
                    "stress_shock",
                    "max_participation",
                    "max_overnight_weight",
                )
            )
        )


class TargetBatch(Contract):
    version: Identifier
    account_version: Identifier
    as_of: AwareDatetime
    expires_at: AwareDatetime
    budget: CapitalBudget
    targets: tuple[PortfolioTarget, ...]
    snapshot_refs: tuple[tuple[Identifier, Identifier, int], ...]
    holding_deadlines: tuple[tuple[Sleeve, AwareDatetime], ...] = ()
    scope: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(dict(self.holding_deadlines)) != len(self.holding_deadlines):
            raise ValueError("duplicate sleeve holding deadline")
        refs = {s: (snapshot, revision) for s, snapshot, revision in self.snapshot_refs}
        if len(refs) != len(self.snapshot_refs) or set(refs) != {
            s.strategy_id for s in self.budget.sleeves
        }:
            raise ValueError("snapshot manifest does not cover the budget")
        if len({t.symbol for t in self.targets}) != len(self.targets):
            raise ValueError("duplicate aggregate symbol")
        if any(t.target_version != self.version for t in self.targets):
            raise ValueError("mixed target versions")
        if any(revision < 0 for _, _, revision in self.snapshot_refs):
            raise ValueError("negative snapshot revision")
        if any(
            s.strategy_id not in refs
            or s.revision != refs[s.strategy_id][1]
            or s.budget_id != self.budget.budget_id
            for t in self.targets
            for s in t.sleeve_targets
        ):
            raise ValueError("mixed revision or budget in target manifest")
        if self.expires_at <= self.as_of:
            raise ValueError("invalid target lifetime")
        return self


class MockRiskDecision(Contract):
    decision_id: Identifier
    at: AwareDatetime
    expires_at: AwareDatetime
    status: Literal["ALLOW", "REDUCE", "REJECT", "HOLD", "RISK_REDUCTION_REQUIRED"]
    reasons: tuple[Identifier, ...]
    account_version: Identifier
    target_version: Identifier
    target_hash: Identifier
    policy: MockRiskPolicy
    live_approved: Literal[False] = False


class MockOrderSnapshot(Contract):
    client_order_id: Identifier
    broker_order_id: Identifier
    quantity: PositiveQty
    filled: Qty
    state: Literal["ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"]

    @model_validator(mode="after")
    def cumulative_quantity(self) -> Self:
        if self.filled > self.quantity:
            raise ValueError("broker cumulative fill exceeds quantity")
        if self.state == "FILLED" and self.filled != self.quantity:
            raise ValueError("broker FILLED quantity mismatch")
        if self.state in {"ACKNOWLEDGED", "REJECTED"} and self.filled:
            raise ValueError("broker acknowledgement/rejection cannot contain fills")
        if self.state == "PARTIALLY_FILLED" and not 0 < self.filled < self.quantity:
            raise ValueError("broker partial fill quantity mismatch")
        return self


class MockAccountSnapshot(Contract):
    source: Literal["SYNTHETIC_MOCK"] = "SYNTHETIC_MOCK"
    observed_at: AwareDatetime
    quantities: tuple[tuple[Identifier, Qty], ...]
    settled_cash: Cash
    receivables: Cash
    payables: Cash
    fees_payable: Cash
    taxes_payable: Cash
    reserved_buy_cash: Cash
    reserved_sells: tuple[tuple[Identifier, Qty], ...]
    buying_power: Cash
    withdrawal_available: Cash
    orders: tuple[MockOrderSnapshot, ...]


class ExecutionState(Contract):
    account_ref: Annotated[str, Field(pattern=r"^MOCK_[A-Za-z0-9_-]+$")]
    calendar: SettlementCalendar
    sequence: int = 0
    last_event_at: AwareDatetime | None = None
    account: Book = Book()
    attribution: tuple[Attribution, ...] = tuple(
        Attribution(sleeve=s) for s in ("A", "B", "C", "D", "EXTERNAL", "CENTRAL")
    )
    quotes: tuple[Quote, ...] = ()
    orders: tuple[Order, ...] = ()
    fills: tuple[FillReceipt, ...] = ()
    settlements: tuple[Settlement, ...] = ()
    decisions: tuple[MockRiskDecision, ...] = ()
    portfolio_decisions: tuple[PortfolioDecision, ...] = ()
    batches: tuple[TargetBatch, ...] = ()
    external_opex: Cash = Decimal(0)
    dividends_known: tuple[tuple[Identifier, Cash, Sleeve], ...] = ()
    dividends_paid: tuple[Identifier, ...] = ()
    reconciled: bool = False
    broker_buying_power: Cash | None = None
    withdrawal_available: Cash | None = None
    broker_snapshot_at: AwareDatetime | None = None
    cash_policy: Literal["UNVERIFIED", "SYNTHETIC_NO_UNSETTLED_REUSE"] = "UNVERIFIED"
    warnings: tuple[str, ...] = ()

    def book(self, sleeve: str) -> Book:
        return next(a.book for a in self.attribution if a.sleeve == sleeve)

    def quote(self, symbol: str) -> Quote:
        return next(q for q in self.quotes if q.symbol == symbol)

    def reserved_sell(self, symbol: str, sleeve: str | None = None) -> int:
        result = 0
        for order in self.orders:
            if order.symbol != symbol or order.side != "SELL" or order.state in TERMINAL:
                continue
            done: dict[str, int] = {}
            for fill in self.fills:
                if fill.order_id == order.client_order_id:
                    for owner, qty in fill.allocations:
                        done[owner] = done.get(owner, 0) + qty
            result += sum(
                qty - done.get(owner, 0)
                for owner, qty in order.allocations
                if sleeve is None or sleeve == owner
            )
        return result

    @property
    def account_version(self) -> str:
        return content_hash(
            {
                "account": self.account.model_dump(mode="json"),
                "attribution": [a.model_dump(mode="json") for a in self.attribution],
                "orders": [o.model_dump(mode="json") for o in self.orders],
                "quotes": [q.model_dump(mode="json") for q in self.quotes],
                "reconciled": self.reconciled,
                "buying_power": str(self.broker_buying_power),
                "cash_policy": self.cash_policy,
            }
        )

    def valuation_status(self, now: datetime, max_age: timedelta) -> str:
        for lot in self.account.lots:
            try:
                quote = self.quote(lot.symbol)
            except StopIteration:
                return "VALUATION_UNVERIFIED"
            if quote.available_at > now or now - quote.at > max_age or quote.halted:
                return "VALUATION_UNVERIFIED"
        return "MARKED_NOT_LIQUIDATION_GUARANTEED"
