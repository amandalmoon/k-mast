import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from kmast.core.clock import ReplayClock
from kmast.core.contracts import CapitalBudget, PortfolioTarget, SleeveBudget, StrategyTarget
from kmast.execution.engine import MockExecution
from kmast.execution.events import Allocate, CashPolicy, Fill, Flow, Mark, OrderNotice, Settle
from kmast.execution.models import (
    ExecutionState,
    MockRiskPolicy,
    Quote,
    SettlementCalendar,
    TargetBatch,
)
from kmast.execution.readers import FakeAccountSnapshotProvider, expected_mock_snapshot

NOW = datetime(2026, 10, 16, tzinfo=UTC)


def initial(path):
    return ExecutionState(
        account_ref="MOCK_" + hashlib.sha256(str(path).encode()).hexdigest()[:16],
        calendar=SettlementCalendar(
            version="FIXTURE_CALENDAR",
            source_ref="SYNTHETIC_EXPLICIT_TRADING_DATES",
            eligible_dates=tuple(
                date(2026, 10, day) for day in (16, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30)
            ),
        ),
    )


def eid(engine, prefix):
    return prefix + str(engine.state.sequence + 1)


def mark(engine, price=Decimal(10), symbol="005930", **updates):
    quote = Quote.model_validate(
        dict(
            symbol=symbol,
            session="REGULAR",
            price=price,
            at=engine.clock.now(),
            available_at=engine.clock.now(),
            sector="SYNTHETIC_SECTOR",
            liquidity_quantity=100000,
            lower_limit=1,
            upper_limit=1000,
            tick_size=1,
            source_ref="SYNTHETIC_NOT_REAL_MARKET",
        )
        | updates
    )
    engine.apply(Mark(event_id=eid(engine, "mark"), at=engine.clock.now(), quote=quote))
    return quote


def reconcile(engine):
    snap = expected_mock_snapshot(engine.state, at=engine.clock.now())
    engine.reconcile(eid(engine, "reconcile"), FakeAccountSnapshotProvider(snap))
    return snap


def make_engine(path, funded=True):
    engine = MockExecution(path, initial(path), ReplayClock(NOW))
    if funded:
        engine.apply(Flow(event_id="capital", at=NOW, amount=10000))
        for owner, cash in (("A", 4000), ("B", 3000), ("C", 2000), ("D", 500)):
            engine.apply(
                Allocate(
                    event_id="allocate-" + owner,
                    at=NOW,
                    from_sleeve="CENTRAL",
                    to_sleeve=owner,
                    cash=cash,
                )
            )
        engine.apply(
            CashPolicy(event_id="cash-policy", at=NOW, policy="SYNTHETIC_NO_UNSETTLED_REUSE")
        )
        mark(engine)
    reconcile(engine)
    return engine


def policy(**updates):
    return MockRiskPolicy.model_validate(
        dict(
            version="SYNTHETIC_POLICY_V1",
            scope="SYNTHETIC_ONLY",
            approved_by="FIXTURE_ONLY_NOT_LIVE_APPROVAL",
            max_symbol_weight="0.8",
            max_sector_weight="0.9",
            max_gross_weight="0.95",
            max_sleeve_weight="0.5",
            loss_limit_krw=5000,
            sleeve_loss_limit_krw=3000,
            stress_loss_limit_krw=3000,
            stress_shock="0.2",
            max_participation="0.1",
            max_overnight_weight="0.95",
            allow_overnight=True,
        )
        | updates
    )


def batch(engine, quantities=None, version=None, **updates):
    if quantities is None:
        quantities = {"A": 10, "B": 0, "C": 0, "D": 0}
    version = version or "target-" + str(engine.state.sequence)
    revision = engine.state.sequence
    budget = CapitalBudget(
        budget_id="fixture-budget",
        approved_by="FIXTURE_ONLY",
        sleeves=tuple(
            SleeveBudget(strategy_id=s, weight=w)
            for s, w in (("A", ".4"), ("B", ".3"), ("C", ".2"), ("D", ".05"))
        ),
    )
    sleeves = tuple(
        StrategyTarget(
            strategy_id=s,
            symbol="005930",
            target_qty=q,
            budget_id=budget.budget_id,
            revision=revision,
        )
        for s, q in quantities.items()
    )
    return TargetBatch.model_validate(
        dict(
            version=version,
            account_version=engine.state.account_version,
            as_of=engine.clock.now(),
            expires_at=engine.clock.now() + timedelta(minutes=1),
            budget=budget,
            targets=(
                PortfolioTarget(
                    symbol="005930",
                    aggregate_target_qty=sum(quantities.values()),
                    sleeve_targets=sleeves,
                    snapshot_id=version,
                    target_version=version,
                ),
            ),
            snapshot_refs=tuple(
                (s.strategy_id, version + s.strategy_id, revision) for s in budget.sleeves
            ),
            holding_deadlines=tuple(
                (s.strategy_id, engine.clock.now() + timedelta(days=10)) for s in budget.sleeves
            ),
        )
        | updates
    )


def plan(
    engine, quantities=None, *, reduction=False, fee_buffer=Decimal(5), expected_gross=Decimal(10)
):
    target = batch(engine, quantities)
    verdict = engine.decide(
        eid(engine, "decision"),
        target,
        policy(),
        fee_buffer=fee_buffer,
        expected_gross=expected_gross,
        execution_cost=Decimal(2),
        uncertainty=Decimal(1),
        reduction=reduction,
    )
    assert verdict.status in {"ALLOW", "REDUCE"}, verdict.reasons
    engine.plan(eid(engine, "plan"), verdict, fee_buffer)
    return engine.state.orders[-1], verdict


def ack(engine, order):
    engine.apply(
        OrderNotice(
            event_id=eid(engine, "ack"),
            at=engine.clock.now(),
            order_id=order.client_order_id,
            action="ACK",
            broker_order_id="MOCK_" + order.client_order_id,
        )
    )


def fill(engine, order, qty=None, fee=Decimal(1), tax=Decimal(0), exec_id=None):
    event = Fill(
        event_id=eid(engine, "fill"),
        at=engine.clock.now(),
        exec_id=exec_id or eid(engine, "exec"),
        order_id=order.client_order_id,
        quantity=qty or order.remaining,
        price=order.limit_price,
        fee=fee,
        tax=tax,
        trade_date=engine.clock.now().date(),
    )
    engine.apply(event)
    return event


def settle(engine, event):
    due = next(s.due for s in engine.state.settlements if s.exec_id == event.exec_id)
    engine.clock.advance(datetime.combine(due, datetime.min.time(), UTC))
    engine.apply(
        Settle(
            event_id=eid(engine, "settle"),
            at=engine.clock.now(),
            exec_id=event.exec_id,
            settlement_date=due,
        )
    )
    for quote in engine.state.quotes:
        mark(engine, quote.price, quote.symbol)
    reconcile(engine)


def buy(engine, qty=10, settled=False, owner="A"):
    quantities = {s: engine.state.book(s).quantity("005930") for s in ("A", "B", "C", "D")}
    quantities[owner] += qty
    order, _ = plan(engine, quantities)
    ack(engine, order)
    event = fill(engine, order)
    if settled:
        settle(engine, event)
    return order, event
