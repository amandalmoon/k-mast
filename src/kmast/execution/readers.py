from typing import Protocol

from kmast.execution.events import Fill
from kmast.execution.models import ExecutionState, MockAccountSnapshot, MockOrderSnapshot


class BrokerAccountReader(Protocol):
    def snapshot(self) -> MockAccountSnapshot: ...


class BrokerOrderReader(Protocol):
    def orders(self) -> tuple[MockOrderSnapshot, ...]: ...


class BrokerFillReader(Protocol):
    def fills(self) -> tuple[Fill, ...]: ...


class FakeAccountSnapshotProvider:
    def __init__(self, snapshot: MockAccountSnapshot) -> None:
        self.value = snapshot

    def snapshot(self) -> MockAccountSnapshot:
        return self.value

    def orders(self) -> tuple[MockOrderSnapshot, ...]:
        return self.value.orders


class FakeFillNotificationProvider:
    def __init__(self, notifications: tuple[Fill, ...]) -> None:
        self.notifications = notifications

    def fills(self) -> tuple[Fill, ...]:
        return self.notifications


def expected_mock_snapshot(state: ExecutionState, *, at: object) -> MockAccountSnapshot:
    """Construct a declared mock expectation, never evidence of a real broker observation."""
    return MockAccountSnapshot.model_validate(
        dict(
            observed_at=at,
            quantities=tuple(
                sorted(
                    (s, state.account.quantity(s))
                    for s in {lot.symbol for lot in state.account.lots}
                )
            ),
            settled_cash=state.account.settled_cash,
            receivables=state.account.unsettled_receivables,
            payables=state.account.unsettled_payables,
            fees_payable=state.account.fees_payable,
            taxes_payable=state.account.taxes_payable,
            reserved_buy_cash=state.account.reserved_buy_cash,
            reserved_sells=tuple(
                sorted(
                    (s, state.reserved_sell(s))
                    for s in {o.symbol for o in state.orders}
                    if state.reserved_sell(s)
                )
            ),
            buying_power=max(state.account.conservative_cash, 0),
            withdrawal_available=max(state.account.conservative_cash, 0),
            orders=tuple(
                MockOrderSnapshot(
                    client_order_id=o.client_order_id,
                    broker_order_id=o.broker_order_id or "MOCK_" + o.client_order_id,
                    quantity=o.quantity,
                    filled=o.filled,
                    state=(
                        "FILLED"
                        if o.remaining == 0
                        else "PARTIALLY_FILLED"
                        if o.filled
                        else "ACKNOWLEDGED"
                    )
                    if o.state in {"UNKNOWN", "RECONCILING", "SUBMITTING"}
                    else o.state,
                )
                for o in state.orders
            ),
        )
    )
