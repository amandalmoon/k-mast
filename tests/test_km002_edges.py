import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kmast.core.clock import ReplayClock
from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.execution.demo import run
from kmast.execution.engine import MockExecution, ReferenceSleeve
from kmast.execution.events import Fill, Flow, OrderNotice
from kmast.execution.ledger import change
from kmast.execution.portfolio import aggregate
from kmast.execution.readers import FakeAccountSnapshotProvider, expected_mock_snapshot
from kmast.execution.risk import evaluate

from .km002_helpers import (
    NOW,
    ack,
    batch,
    buy,
    fill,
    initial,
    make_engine,
    mark,
    plan,
    policy,
    reconcile,
)


@pytest.fixture
def engine(tmp_path):
    with make_engine(tmp_path / "edge.sqlite") as value:
        yield value


def test_process_death_before_commit_rolls_back_and_releases_os_lease(tmp_path):
    path = tmp_path / "crash.sqlite"
    genesis = initial(path)
    with MockExecution(path, genesis, ReplayClock(NOW)) as writer:
        writer.apply(Flow(event_id="committed", at=NOW, amount=100))
        expected = writer.state
    config = tmp_path / "genesis.json"
    config.write_text(genesis.model_dump_json(), encoding="utf-8")
    program = """import os, sys
from pathlib import Path
from datetime import datetime, UTC
from kmast.execution.models import ExecutionState
from kmast.execution.events import Flow
from kmast.execution.store import Journal
j = Journal(Path(sys.argv[2]), ExecutionState.model_validate_json(Path(sys.argv[1]).read_bytes()))
j.fault_hook = lambda: os._exit(77)
j.commit(Flow(event_id='never-committed', at=datetime(2026,10,16,tzinfo=UTC), amount=999))
"""
    child = subprocess.run(
        [sys.executable, "-c", program, str(config), str(path)],
        capture_output=True,
        timeout=20,
    )
    assert child.returncode == 77, child.stderr
    with MockExecution(path, genesis, ReplayClock(NOW)) as recovered:
        assert recovered.state == expected and not recovered.ready
        assert recovered.journal.db.execute("SELECT count(*) FROM events").fetchone()[0] == 1


@pytest.mark.parametrize("damage", ["event", "checkpoint", "missing-checkpoint"])
def test_restart_detects_persisted_corruption(tmp_path, damage):
    path = tmp_path / "corrupt.sqlite"
    genesis = initial(path)
    with MockExecution(path, genesis, ReplayClock(NOW)) as writer:
        writer.apply(Flow(event_id="capital", at=NOW, amount=100))
    with sqlite3.connect(path) as db:
        if damage == "event":
            db.execute("UPDATE events SET hash='tampered'")
        elif damage == "checkpoint":
            db.execute("UPDATE checkpoint SET state='{}'")
        else:
            db.execute("DELETE FROM checkpoint")
    with pytest.raises(ValueError, match="corruption|missing"):
        MockExecution(path, genesis, ReplayClock(NOW))


@pytest.mark.parametrize("uncertain", ["UNKNOWN", "CANCEL_PENDING"])
def test_confirmed_terminal_snapshot_releases_reserve_only_after_full_match(engine, uncertain):
    order, _ = plan(engine)
    if uncertain == "CANCEL_PENDING":
        ack(engine, order)
    engine.apply(
        OrderNotice(
            event_id="uncertain",
            at=NOW,
            order_id=order.client_order_id,
            action="TIMEOUT" if uncertain == "UNKNOWN" else "CANCEL_REQUEST",
        )
    )
    # Independent synthetic observation of final cancellation, not local cancel intent.
    observed = expected_mock_snapshot(
        change(engine.state, orders=(change(engine.state.orders[0], state="CANCELLED"),)), at=NOW
    )
    observed = change(
        observed,
        reserved_buy_cash=Decimal(0),
        buying_power=Decimal(10000),
        withdrawal_available=Decimal(10000),
    )
    wrong = change(observed, settled_cash=Decimal(9999))
    engine.reconcile("mismatch", FakeAccountSnapshotProvider(wrong))
    assert not engine.ready and engine.state.account.reserved_buy_cash == 105
    engine.reconcile("confirmed", FakeAccountSnapshotProvider(observed))
    assert engine.ready and engine.state.account.reserved_buy_cash == 0
    assert engine.state.orders[0].state == "CANCELLED"


def test_plan_rechecks_quote_age_during_approval_lifetime(engine):
    engine.clock.advance(NOW + timedelta(seconds=29))
    reconcile(engine)
    verdict = engine.decide("approval", batch(engine), policy(), expected_gross=Decimal(10))
    assert verdict.status == "ALLOW"
    engine.clock.advance(NOW + timedelta(seconds=31))
    assert verdict.expires_at > engine.clock.now()
    with pytest.raises(PermissionError, match="risk conditions changed"):
        engine.plan("stale-plan", verdict)
    assert not engine.state.orders


def test_approval_expiry_and_fee_buffer_binding(engine):
    verdict = engine.decide(
        "approval", batch(engine), policy(), fee_buffer=Decimal(5), expected_gross=Decimal(10)
    )
    with pytest.raises(ValueError, match="fee buffer"):
        engine.plan("different-cost", verdict, Decimal(1))
    engine.clock.advance(verdict.expires_at)
    with pytest.raises(PermissionError, match="expired"):
        engine.plan("expired", verdict, Decimal(5))
    assert not engine.state.orders


def test_stale_strategy_revision_cannot_be_relabelled(engine):
    first = batch(engine)
    engine.decide("first", first, policy())
    # Same numeric revision under a new snapshot identity is not a fresh signal.
    stale = batch(engine, version="relabelled")
    stale = change(
        stale,
        snapshot_refs=tuple((s, "relabelled-" + s, rev) for s, _, rev in first.snapshot_refs),
        targets=tuple(
            change(
                t,
                sleeve_targets=tuple(
                    change(s, revision=first.snapshot_refs[0][2]) for s in t.sleeve_targets
                ),
            )
            for t in stale.targets
        ),
    )
    with pytest.raises(ValueError, match="snapshot revision"):
        engine.decide("stale", stale, policy())


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"max_sector_weight": Decimal(".001")}, "SECTOR_CONCENTRATION"),
        ({"max_gross_weight": Decimal(".001")}, "GROSS_EXPOSURE"),
        ({"stress_loss_limit_krw": Decimal(1)}, "COMMON_STRESS_LIMIT"),
        ({"max_overnight_weight": Decimal(".001")}, "OVERNIGHT_EXPOSURE"),
        ({"allow_overnight": False}, "OVERNIGHT_NOT_APPROVED"),
    ],
)
def test_joint_risk_limits_are_individually_binding(engine, overrides, reason):
    verdict = evaluate(engine.state, batch(engine), policy(**overrides), NOW)
    assert verdict.status == "REJECT" and reason in verdict.reasons


def test_unknown_holding_deadline_blocks_new_position(engine):
    verdict = evaluate(engine.state, change(batch(engine), holding_deadlines=()), policy(), NOW)
    assert verdict.status == "REJECT" and "HOLDING_DEADLINE_UNVERIFIED" in verdict.reasons


def test_overdue_original_holding_deadline_requires_reduction(engine):
    buy(engine, settled=True)
    engine.clock.advance(NOW + timedelta(days=11))
    mark(engine)
    reconcile(engine)
    verdict = evaluate(
        engine.state, batch(engine, {"A": 11, "B": 0, "C": 0, "D": 0}), policy(), engine.clock.now()
    )
    assert verdict.status == "RISK_REDUCTION_REQUIRED"
    assert "HOLDING_DEADLINE_BREACH" in verdict.reasons


def test_tiny_cost_split_conserves_cents_across_sleeves(engine):
    order, _ = plan(engine, {"A": 1, "B": 1, "C": 1, "D": 1})
    fill(engine, order, fee=Decimal(".01"))
    assert engine.state.account.fees_and_taxes == Decimal(".01")
    assert sum(a.book.fees_and_taxes for a in engine.state.attribution) == Decimal(".01")
    assert all(a.book.fees_and_taxes >= 0 for a in engine.state.attribution)


def test_overfill_is_atomic_and_execution_identity_is_content_bound(engine):
    order, _ = plan(engine)
    before = engine.state
    with pytest.raises(ValueError, match="exceeds outstanding"):
        fill(engine, order, qty=11)
    assert engine.state == before
    event = fill(engine, order, qty=4)
    before = engine.state
    engine.apply(change(event, event_id="repeated-envelope"))
    assert engine.state.account == before.account
    with pytest.raises(ValueError, match="conflicting execution"):
        engine.apply(change(event, event_id="conflict", fee=Decimal(2)))
    assert engine.state.account == before.account


def test_economic_no_trade_does_not_create_orders(engine):
    verdict = engine.decide(
        "no-edge",
        batch(engine),
        policy(),
        expected_gross=Decimal(2),
        execution_cost=Decimal(1),
        uncertainty=Decimal(1),
    )
    assert verdict.status == "ALLOW"
    assert engine.state.portfolio_decisions[-1].action == "HOLD_TARGET"
    with pytest.raises(PermissionError, match="not approved"):
        engine.plan("no-edge-plan", verdict)
    assert not engine.state.orders


def test_original_signal_snapshot_reaches_mock_order_through_aggregator(engine):
    manifest = batch(engine)
    snapshots = []
    for owner in ("A", "B", "C", "D"):
        intent = SignalIntent(
            intent_id="intent-" + owner,
            revision=1,
            target_snapshot_id="snapshot-" + owner,
            strategy_id=owner,
            model_version="MOCK",
            config_hash="MOCK",
            data_version="MOCK",
            symbol="005930",
            venue="KRX",
            session="REGULAR",
            decision_at=NOW,
            available_at=NOW,
            target_weight=Decimal(".025") if owner == "A" else Decimal(0),
            horizon=timedelta(days=1),
            valid_until=NOW + timedelta(minutes=1),
            reason_code="MOCK",
        )
        snapshots.append(
            TargetSnapshot(
                strategy_id=owner,
                snapshot_id="snapshot-" + owner,
                revision=1,
                expected_symbols=("005930",),
                intents=(intent,),
            )
        )
    target = aggregate(
        engine.state,
        manifest.budget,
        tuple(snapshots),
        NOW,
        "aggregated",
        holding_deadlines=manifest.holding_deadlines,
    )
    verdict = engine.decide("aggregate-decision", target, policy(), expected_gross=Decimal(10))
    engine.plan("aggregate-plan", verdict)
    assert engine.state.orders[-1].quantity == 10
    assert engine.state.orders[-1].allocations == (("A", 10),)


def test_opposing_pending_orders_never_net_away_uncertainty(engine):
    buy(engine, settled=True)
    pending, _ = plan(engine, {"A": 20, "B": 0, "C": 0, "D": 0})
    ack(engine, pending)
    verdict = evaluate(
        engine.state, batch(engine, {"A": 0, "B": 0, "C": 0, "D": 0}), policy(), engine.clock.now()
    )
    assert verdict.status == "HOLD" and "PENDING_OR_ATTRIBUTION_CONFLICT" in verdict.reasons
    opposite = change(engine.state.orders[-1], client_order_id="MOCK_OPPOSITE", side="SELL")
    conflict = change(engine.state, orders=(*engine.state.orders, opposite))
    target = change(batch(engine), account_version=conflict.account_version)
    verdict = evaluate(conflict, target, policy(), engine.clock.now())
    assert verdict.status == "HOLD" and "PENDING_OR_ATTRIBUTION_CONFLICT" in verdict.reasons


def test_partial_risk_reduction_allowed_while_remaining_sleeve_above_limit(engine):
    buy(engine, settled=True)
    verdict = evaluate(
        engine.state,
        batch(engine, {"A": 9, "B": 0, "C": 0, "D": 0}),
        policy(max_sleeve_weight=Decimal(".001")),
        engine.clock.now(),
        reduction=True,
    )
    assert verdict.status == "REDUCE"


def test_economic_fill_cannot_predate_order_approval(engine):
    engine.clock.advance(NOW + timedelta(seconds=1))
    order, _ = plan(engine)
    before = engine.state
    event = Fill(
        event_id="pre-order",
        at=NOW,
        exec_id="pre-order-exec",
        order_id=order.client_order_id,
        quantity=10,
        price=10,
        fee=1,
        tax=0,
        trade_date=NOW.date(),
    )
    with pytest.raises(ValueError, match="predates order approval"):
        engine.apply(event)
    assert engine.state == before


def test_reference_is_not_an_account_or_execution_ledger():
    with pytest.raises(ValidationError):
        ReferenceSleeve(
            sleeve_id="A", fixed_capital_krw=100, reference_nav_krw=100, ledger_type="ACTUAL"
        )


def test_six_scenarios_and_portable_event_replay_have_identical_hashes(tmp_path):
    source = tmp_path / "original"
    first = run(source)
    assert len(first) == 6 and all(item["status"] == "PASS" for item in first)
    assert run(source) == first
    destination = tmp_path / "portable"
    for case in "ABCDEF":
        (destination / case).mkdir(parents=True)
        for name in ("manifest.json", "events.json", "final-state.json"):
            shutil.copyfile(source / case / name, destination / case / name)
        assert (
            json.loads((destination / case / "manifest.json").read_bytes())["scope"]
            == "SYNTHETIC_ONLY"
        )
    assert run(destination) == first
