import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.execution.engine import MockExecution, ReferenceSleeve
from kmast.execution.events import Fill, Flow, Income, OrderNotice, Settle, Transfer
from kmast.execution.ledger import assert_integrity, change, reduce_event, transition
from kmast.execution.models import MockRiskPolicy
from kmast.execution.portfolio import aggregate
from kmast.execution.readers import (
    FakeAccountSnapshotProvider,
    FakeFillNotificationProvider,
    expected_mock_snapshot,
)
from kmast.execution.risk import evaluate

from .km002_helpers import (
    NOW,
    ack,
    batch,
    buy,
    fill,
    make_engine,
    mark,
    plan,
    policy,
    reconcile,
    settle,
)


@pytest.fixture
def engine(tmp_path):
    instance = make_engine(tmp_path / "mock.sqlite")
    yield instance
    instance.close()


def test_LED_001_buy_quantity_payable_nav(engine):
    order, event = buy(engine)
    assert engine.state.account.quantity("005930") == 10
    assert engine.state.account.unsettled_payables == 100
    assert engine.state.account.settled_cash == 10000
    assert engine.state.account.fees_payable == 1
    assert engine.state.account.nav(engine.state.quotes) == 9999
    assert_integrity(engine.state)


def test_LED_002_sell_receivable_nav(engine):
    buy(engine, settled=True)
    mark(engine, 12)
    reconcile(engine)
    order, _ = plan(engine, {"A": 0, "B": 0, "C": 0, "D": 0})
    ack(engine, order)
    fill(engine, order, tax=Decimal(1))
    assert engine.state.account.quantity("005930") == 0
    assert engine.state.account.unsettled_receivables == 120
    assert engine.state.account.settled_cash == 9899
    assert engine.state.account.nav(engine.state.quotes) == 10017


def test_LED_003_trading_day_settlement(engine):
    _, event = buy(engine)
    entry = engine.state.settlements[0]
    assert entry.due.isoformat() == "2026-10-20"  # Explicit fixture skips weekend.
    with pytest.raises(ValueError):
        engine.apply(
            Settle(event_id="early", at=NOW, exec_id=event.exec_id, settlement_date=entry.due)
        )
    settle(engine, event)
    assert engine.state.account.settled_cash == 9899
    assert engine.state.account.unsettled_payables == 0 and engine.state.account.fees_payable == 0
    assert engine.state.account.sellable("005930") == 10


def test_LED_004_fees_taxes_once(engine):
    _, event = buy(engine)
    nav = engine.state.account.nav(engine.state.quotes)
    settle(engine, event)
    assert engine.state.account.nav(engine.state.quotes) == nav
    assert engine.state.account.fees_and_taxes == 1
    with pytest.raises(ValueError):
        engine.apply(change(event, event_id="duplicate-conflict", fee=2))


def test_LED_005_duplicate_execution(engine):
    _, event = buy(engine)
    before = engine.state
    engine.apply(event)
    assert engine.state == before
    engine.apply(change(event, event_id="redelivery-new-envelope"))
    assert engine.state.account == before.account and len(engine.state.fills) == 1


def test_LED_006_fill_before_ack(engine):
    order, _ = plan(engine)
    fill(engine, order)
    ack(engine, order)
    assert engine.state.orders[-1].state == "FILLED"
    assert engine.state.account.quantity("005930") == 10


def test_LED_007_external_flows_not_profit(engine):
    before = engine.state.account.nav(engine.state.quotes)
    engine.apply(Flow(event_id="deposit", at=NOW, amount=100))
    engine.apply(Flow(event_id="withdraw", at=NOW, amount=-50))
    assert engine.state.account.nav(engine.state.quotes) == before + 50
    assert engine.state.account.nav(engine.state.quotes) - engine.state.account.capital_flows == 0
    with pytest.raises(ValueError):
        engine.apply(Flow(event_id="overdraw", at=NOW, amount=-100000))


def test_LED_008_internal_transfer_conserves_loss_lineage(engine):
    buy(engine, settled=True)
    mark(engine, 8)
    before = engine.state
    quote = engine.state.quote("005930")
    engine.apply(
        Transfer(
            event_id="A-to-B",
            at=engine.clock.now(),
            from_sleeve="A",
            to_sleeve="B",
            symbol="005930",
            quantity=10,
            reference_price=8,
            reference_at=quote.at,
            policy_ref="SYNTHETIC_TRANSFER",
        )
    )
    assert engine.state.account == before.account
    assert engine.state.book("A").quantity("005930") == 0
    assert engine.state.book("B").quantity("005930") == 10
    lot = engine.state.book("B").lots[0]
    assert lot.origin_sleeve == "A" and lot.origin_unit_cost == 10 and lot.unit_cost == 8
    assert lot.acquired_at == before.book("A").lots[0].acquired_at
    assert engine.state.book("A").realized_pnl == -20
    assert_integrity(engine.state)


def test_LED_009_external_holdings_protected(engine):
    from kmast.execution.events import SeedPosition

    engine.apply(SeedPosition(event_id="external", at=NOW, symbol="005930", quantity=50, cost=10))
    reconcile(engine)
    verdict = evaluate(engine.state, batch(engine, {"A": 0, "B": 0, "C": 0, "D": 0}), policy(), NOW)
    assert verdict.status == "HOLD" and verdict.reasons == ("NO_DELTA",)
    assert (
        engine.state.account.quantity("005930")
        == engine.state.book("EXTERNAL").quantity("005930")
        == 50
    )


def test_LED_010_reference_is_independent(engine):
    before = engine.state
    reference = ReferenceSleeve(sleeve_id="A", fixed_capital_krw=100000, reference_nav_krw=110000)
    assert reference.ledger_type == "REFERENCE" and engine.state == before
    assert engine.state.account.nav(engine.state.quotes) == sum(
        a.book.nav(engine.state.quotes) for a in engine.state.attribution
    )


def test_CASH_001_reservation_not_expense(engine):
    order, _ = plan(engine)
    assert engine.state.account.reserved_buy_cash == 105
    assert engine.state.account.settled_cash == 10000
    assert engine.state.account.nav(engine.state.quotes) == 10000


def test_CASH_002_unknown_keeps_reservation(engine):
    order, _ = plan(engine)
    engine.apply(
        OrderNotice(event_id="timeout", at=NOW, order_id=order.client_order_id, action="TIMEOUT")
    )
    assert engine.state.account.reserved_buy_cash == 105
    assert not engine.ready


def test_CASH_003_unverified_reuse_blocks(engine):
    from kmast.execution.events import CashPolicy

    engine.apply(CashPolicy(event_id="unknown-cash", at=NOW, policy="UNVERIFIED"))
    verdict = evaluate(engine.state, batch(engine), policy(), NOW)
    assert verdict.status == "HOLD" and "CASH_POLICY_UNVERIFIED" in verdict.reasons


def test_CASH_004_sellable_limit(engine):
    buy(engine)  # Not settled, no reusable sellable inventory under conservative policy.
    target = batch(engine, {"A": 0, "B": 0, "C": 0, "D": 0})
    verdict = evaluate(engine.state, target, policy(), NOW)
    assert verdict.status == "REJECT" and "SELLABLE_QUANTITY_EXCEEDED" in verdict.reasons


def test_OMS_001_illegal_transition(engine):
    order, _ = plan(engine)
    with pytest.raises(ValueError):
        transition(order, "TARGET")
    with pytest.raises(ValueError):
        engine.apply(
            OrderNotice(
                event_id="cancel-too-soon",
                at=NOW,
                order_id=order.client_order_id,
                action="CANCEL_CONFIRMED",
                confirmed_filled=0,
            )
        )


def test_OMS_002_partial_fill_remaining(engine):
    order, _ = plan(engine)
    ack(engine, order)
    fill(engine, order, qty=4)
    current = engine.state.orders[-1]
    assert current.filled == 4 and current.remaining == 6 and current.state == "PARTIALLY_FILLED"
    assert engine.state.account.reserved_buy_cash == 64
    assert engine.state.account.unsettled_payables == 40


def test_OMS_003_cancel_pending_can_fill(engine):
    order, _ = plan(engine)
    ack(engine, order)
    engine.apply(
        OrderNotice(
            event_id="cancel-request",
            at=NOW,
            order_id=order.client_order_id,
            action="CANCEL_REQUEST",
        )
    )
    fill(engine, order, qty=4)
    assert engine.state.orders[-1].state == "CANCEL_PENDING"
    assert engine.state.account.reserved_buy_cash == 64
    with pytest.raises(ValueError):
        engine.apply(
            OrderNotice(
                event_id="bad-cancel-ack",
                at=NOW,
                order_id=order.client_order_id,
                action="CANCEL_CONFIRMED",
                confirmed_filled=0,
            )
        )
    engine.apply(
        OrderNotice(
            event_id="cancel-ack",
            at=NOW,
            order_id=order.client_order_id,
            action="CANCEL_CONFIRMED",
            confirmed_filled=4,
        )
    )
    assert (
        engine.state.account.reserved_buy_cash == 0 and engine.state.account.quantity("005930") == 4
    )


def test_OMS_004_unknown_no_resubmission(engine):
    order, decision = plan(engine)
    engine.apply(
        OrderNotice(event_id="unknown", at=NOW, order_id=order.client_order_id, action="TIMEOUT")
    )
    with pytest.raises(PermissionError):
        engine.plan("no-resubmit", decision, Decimal(5))
    assert len(engine.state.orders) == 1


def test_OMS_005_ack_lost_fill_discovered(engine):
    order, _ = plan(engine)
    engine.apply(
        OrderNotice(event_id="lost-ack", at=NOW, order_id=order.client_order_id, action="TIMEOUT")
    )
    event = Fill(
        event_id="discovered-fill",
        at=NOW,
        exec_id="discovered",
        order_id=order.client_order_id,
        quantity=10,
        price=10,
        fee=1,
        tax=0,
        trade_date=NOW.date(),
    )
    expected = reduce_event(engine.state, event)
    snapshot = expected_mock_snapshot(expected, at=NOW)
    engine.reconcile(
        "recover-fill",
        FakeAccountSnapshotProvider(snapshot),
        FakeFillNotificationProvider((event,)),
    )
    assert engine.ready and engine.state.orders[-1].state == "FILLED"
    assert engine.state.account.quantity("005930") == 10


def test_OMS_006_same_target_is_idempotent(engine):
    order, decision = plan(engine)
    engine.plan("same-target-again", decision, Decimal(5))
    assert len(engine.state.orders) == 1 and engine.state.account.reserved_buy_cash == 105


def test_OMS_007_restart_restores_orders(engine):
    order, _ = plan(engine)
    fill(engine, order, qty=4)
    before = engine.state
    path = engine.journal.path
    genesis = engine.journal.initial
    clock = engine.clock
    engine.close()
    with MockExecution(path, genesis, clock) as restored:
        assert restored.state == before and not restored.ready
        reconcile(restored)
        assert restored.ready and restored.state.account.reserved_buy_cash == 64


def test_OMS_008_snapshot_mismatch_locks(engine):
    snapshot = expected_mock_snapshot(engine.state, at=NOW)
    engine.reconcile("mismatch", FakeAccountSnapshotProvider(change(snapshot, settled_cash=9999)))
    assert not engine.ready and "BROKER_SNAPSHOT_MISMATCH" in engine.state.warnings
    with pytest.raises(PermissionError):
        engine.decide("blocked", batch(engine), policy())


def test_RISK_001_symbol_limit(engine):
    verdict = evaluate(
        engine.state,
        batch(engine, {"A": 100, "B": 0, "C": 0, "D": 0}),
        policy(max_symbol_weight="0.05"),
        NOW,
    )
    assert verdict.status == "REJECT" and "SYMBOL_CONCENTRATION" in verdict.reasons


def test_RISK_002_strategy_budget(engine):
    verdict = evaluate(
        engine.state, batch(engine, {"A": 500, "B": 0, "C": 0, "D": 0}), policy(), NOW
    )
    assert verdict.status == "REJECT" and "STRATEGY_BUDGET_EXCEEDED" in verdict.reasons


def test_RISK_003_account_cash(engine):
    state = change(engine.state, broker_buying_power=Decimal(50))
    verdict = evaluate(state, batch_from_state(engine, state), policy(), NOW, fee_buffer=Decimal(5))
    assert verdict.status == "REJECT" and "INSUFFICIENT_ACCOUNT_CASH" in verdict.reasons


def batch_from_state(engine, state):
    return change(batch(engine), account_version=state.account_version)


@pytest.mark.parametrize(
    "updates",
    [{"session": "CLOSED"}, {"halted": True}, {"vi": True}, {"at": NOW - timedelta(minutes=2)}],
)
def test_RISK_004_quote_session(engine, updates):
    if "at" in updates:
        engine.clock.advance(NOW + timedelta(minutes=2))
        reconcile(engine)
    else:
        mark(engine, **updates)
    verdict = evaluate(engine.state, batch(engine), policy(), engine.clock.now())
    assert verdict.status in {"REJECT", "HOLD"}


def test_RISK_005_loss_limit_stops_entry(engine):
    buy(engine, qty=100, settled=True)
    mark(engine, 5)
    reconcile(engine)
    target = batch(engine, {"A": 101, "B": 0, "C": 0, "D": 0})
    verdict = evaluate(engine.state, target, policy(loss_limit_krw=100), engine.clock.now())
    assert verdict.status == "RISK_REDUCTION_REQUIRED" and "LOSS_LIMIT_BREACH" in verdict.reasons


def test_RISK_006_reduction_bypasses_no_trade_only(engine):
    buy(engine, settled=True)
    order, verdict = plan(
        engine, {"A": 0, "B": 0, "C": 0, "D": 0}, reduction=True, expected_gross=Decimal(-100)
    )
    assert verdict.status == "REDUCE" and order.side == "SELL"
    assert engine.state.portfolio_decisions[-1].action == "RISK_REDUCTION"


def test_RISK_007_unverified_policy_never_live(engine):
    verdict = evaluate(engine.state, batch(engine), MockRiskPolicy(version="unknown"), NOW)
    assert verdict.status == "HOLD" and not verdict.live_approved
    with pytest.raises(ValidationError):
        change(verdict, live_approved=True)


def test_PORT_001_aggregate_absolute_targets(engine):
    budget = batch(engine).budget
    signals = []
    for owner, weight in (("A", ".25"), ("B", ".166667"), ("C", ".1"), ("D", "0")):
        intent = SignalIntent(
            intent_id=owner,
            revision=1,
            target_snapshot_id="s" + owner,
            strategy_id=owner,
            model_version="fixture",
            config_hash="fixture",
            data_version="fixture",
            symbol="005930",
            venue="KRX",
            session="REGULAR",
            decision_at=NOW,
            available_at=NOW,
            target_weight=weight,
            horizon=timedelta(days=1),
            valid_until=NOW + timedelta(minutes=1),
            reason_code="SYNTHETIC",
        )
        signals.append(
            TargetSnapshot(
                strategy_id=owner,
                snapshot_id="s" + owner,
                revision=1,
                expected_symbols=("005930",),
                intents=(intent,),
            )
        )
    target = aggregate(engine.state, budget, tuple(signals), NOW, "aggregate170")
    assert target.targets[0].aggregate_target_qty == 170
    assert target.targets[0].explanatory_delta(200) == -30


def test_PORT_002_revision_and_snapshot_binding(engine):
    target = batch(engine)
    with pytest.raises(ValidationError):
        change(
            target, snapshot_refs=tuple((s, snap, rev + 1) for s, snap, rev in target.snapshot_refs)
        )
    engine.apply(Flow(event_id="new-account", at=NOW, amount=10))
    verdict = evaluate(engine.state, target, policy(), NOW)
    assert verdict.status == "HOLD" and "STALE_ACCOUNT_OR_TARGET" in verdict.reasons


def test_PORT_003_budget_and_cash(engine):
    budget = batch(engine).budget
    assert budget.cash_residual == Decimal(".05")
    assert engine.state.book("CENTRAL").settled_cash == 500
    assert (
        sum(a.book.settled_cash for a in engine.state.attribution)
        == engine.state.account.settled_cash
    )


def test_PNL_001_realized_unrealized(engine):
    opening = engine.state
    buy(engine, settled=True)
    mark(engine, 12)
    result = engine.performance(NOW, Decimal(10000), opening)
    assert result.account_bridge.gross_market_pnl == 20
    assert result.net_operating_pnl_krw == 19
    assert engine.state.account.realized_pnl == 0


def test_PNL_002_external_operating_cost_not_broker_withdrawal(engine):
    opening = engine.state
    engine.apply(Income(event_id="server-invoice", at=NOW, category="EXTERNAL_OPEX", amount=20))
    engine.clock.advance(NOW + timedelta(seconds=1))
    result = engine.performance(NOW, Decimal(10000), opening)
    assert result.account_nav_krw == 10000 and result.account_bridge.net_operating_pnl_krw == 0
    assert result.net_operating_pnl_krw == -20


def test_PNL_003_cost_once_and_dividend_receivable(engine):
    engine.apply(
        Income(
            event_id="entitlement",
            at=NOW,
            category="DIVIDEND_ACCRUAL",
            amount=10,
            entitlement_id="d1",
        )
    )
    nav = engine.state.account.nav(engine.state.quotes)
    engine.apply(
        Income(
            event_id="dividend-payment",
            at=NOW,
            category="DIVIDEND_PAYMENT",
            amount=10,
            entitlement_id="d1",
        )
    )
    assert (
        engine.state.account.nav(engine.state.quotes) == nav
        and engine.state.account.dividends == 10
    )
    with pytest.raises(ValueError):
        engine.apply(
            Income(
                event_id="double-payment",
                at=NOW,
                category="DIVIDEND_PAYMENT",
                amount=10,
                entitlement_id="d1",
            )
        )


def test_OPS_001_transaction_rollback_replay(engine):
    before = engine.state

    def crash():
        raise RuntimeError("SYNTHETIC_CRASH_BEFORE_COMMIT")

    engine.journal.fault_hook = crash
    with pytest.raises(RuntimeError):
        engine.apply(Flow(event_id="crash", at=NOW, amount=10))
    engine.journal.fault_hook = None
    assert engine.state == before
    assert engine.journal.replay()[0] == before


def test_OPS_002_single_writer_across_processes(engine, tmp_path):
    genesis = engine.journal.initial
    with pytest.raises(RuntimeError, match="already has a writer"):
        MockExecution(tmp_path / "other.sqlite", genesis, engine.clock)
    config_path = tmp_path / "genesis.json"
    config_path.write_text(genesis.model_dump_json(), encoding="utf-8")
    code = """from pathlib import Path
from kmast.execution.models import ExecutionState
from kmast.execution.store import Journal
import sys
s = ExecutionState.model_validate_json(Path(sys.argv[1]).read_bytes())
try:
    Journal(Path(sys.argv[2]), s)
except RuntimeError:
    sys.exit(0)
sys.exit(9)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(config_path), str(tmp_path / "child.sqlite")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_SAFE_002_no_live_broker_capability(engine):
    import ast
    from pathlib import Path

    from kmast.brokers.interfaces import MockBroker

    for method in (MockBroker().submit_order, MockBroker().cancel_order):
        with pytest.raises(PermissionError):
            method()
    for path in Path("src/kmast/execution").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("kmast.brokers", "http", "requests", "websockets", "socket")
                )
