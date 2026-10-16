from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from kmast.core.base import Contract, Identifier, Positive
from kmast.core.contracts import PortfolioDecision
from kmast.execution.models import (
    Cash,
    MockAccountSnapshot,
    MockRiskDecision,
    Money,
    PositiveQty,
    Price,
    Quote,
    Sleeve,
    TargetBatch,
)


class EventBase(Contract):
    event_id: Identifier
    at: AwareDatetime


class Flow(EventBase):
    kind: Literal["FLOW"] = "FLOW"
    amount: Money
    sleeve: Literal["CENTRAL", "EXTERNAL"] = "CENTRAL"


class Allocate(EventBase):
    kind: Literal["ALLOCATE"] = "ALLOCATE"
    from_sleeve: Sleeve
    to_sleeve: Sleeve
    cash: Cash


class SeedPosition(EventBase):
    kind: Literal["SEED_POSITION"] = "SEED_POSITION"
    symbol: Identifier
    quantity: PositiveQty
    cost: Price
    sleeve: Literal["EXTERNAL"] = "EXTERNAL"


class Mark(EventBase):
    kind: Literal["MARK"] = "MARK"
    quote: Quote


class CashPolicy(EventBase):
    kind: Literal["CASH_POLICY"] = "CASH_POLICY"
    policy: Literal["UNVERIFIED", "SYNTHETIC_NO_UNSETTLED_REUSE"]


class DecisionRecorded(EventBase):
    kind: Literal["DECISION"] = "DECISION"
    batch: TargetBatch
    decision: MockRiskDecision
    portfolio: PortfolioDecision


class Plan(EventBase):
    kind: Literal["PLAN"] = "PLAN"
    decision_id: Identifier
    fee_buffer_per_order: Cash


class OrderNotice(EventBase):
    kind: Literal["ORDER_NOTICE"] = "ORDER_NOTICE"
    order_id: Identifier
    action: Literal["ACK", "TIMEOUT", "CANCEL_REQUEST", "CANCEL_CONFIRMED", "REJECT"]
    broker_order_id: Identifier | None = None
    confirmed_filled: int | None = Field(default=None, ge=0, strict=True)


class Fill(EventBase):
    kind: Literal["FILL"] = "FILL"
    exec_id: Identifier
    order_id: Identifier
    quantity: PositiveQty
    price: Price
    fee: Cash
    tax: Cash
    trade_date: date
    source: Literal["SYNTHETIC_MOCK"] = "SYNTHETIC_MOCK"


class Settle(EventBase):
    kind: Literal["SETTLE"] = "SETTLE"
    exec_id: Identifier
    settlement_date: date


class Transfer(EventBase):
    kind: Literal["TRANSFER"] = "TRANSFER"
    from_sleeve: Literal["A", "B", "C", "D"]
    to_sleeve: Literal["A", "B", "C", "D"]
    symbol: Identifier
    quantity: PositiveQty
    reference_price: Price
    reference_at: AwareDatetime
    policy_ref: Identifier


class Income(EventBase):
    kind: Literal["INCOME"] = "INCOME"
    category: Literal[
        "INTEREST", "DIVIDEND_ACCRUAL", "DIVIDEND_PAYMENT", "ACCOUNT_OPEX", "EXTERNAL_OPEX"
    ]
    amount: Cash
    entitlement_id: Identifier | None = None
    sleeve: Sleeve = "CENTRAL"


class Reconcile(EventBase):
    kind: Literal["RECONCILE"] = "RECONCILE"
    snapshot: MockAccountSnapshot
    discovered_fills: tuple[Fill, ...] = ()


class SplitAction(EventBase):
    kind: Literal["SPLIT_ACTION"] = "SPLIT_ACTION"
    action_id: Identifier
    symbol: Identifier
    multiplier: Positive
    available_at: AwareDatetime
    effective_date: date
    source_ref: Identifier
    price_basis: Literal["RAW"] = "RAW"

    @model_validator(mode="after")
    def economic_identity(self) -> "SplitAction":
        if self.event_id != "SPLIT:" + self.action_id or self.available_at > self.at:
            raise ValueError("split requires canonical event identity and available source")
        return self


Event = Annotated[
    Flow
    | Allocate
    | SeedPosition
    | Mark
    | CashPolicy
    | DecisionRecorded
    | Plan
    | OrderNotice
    | Fill
    | Settle
    | Transfer
    | Income
    | Reconcile
    | SplitAction,
    # split is an additive event; existing event/state serialization is unchanged.
    Field(discriminator="kind"),
]
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
