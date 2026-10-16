"""Six deterministic synthetic scenarios. No network, credentials or real brokerage writes."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from kmast.core.clock import ReplayClock
from kmast.core.contracts import CapitalBudget, PortfolioTarget, SleeveBudget, StrategyTarget
from kmast.data.normalization import content_hash
from kmast.data.store import canonical, immutable_write
from kmast.execution.engine import MockExecution, ReferenceSleeve
from kmast.execution.events import (
    EVENT_ADAPTER,
    Allocate,
    CashPolicy,
    Fill,
    Flow,
    Mark,
    OrderNotice,
    SeedPosition,
    Settle,
)
from kmast.execution.ledger import reduce_event
from kmast.execution.models import (
    ExecutionState,
    MockRiskPolicy,
    Quote,
    SettlementCalendar,
    TargetBatch,
)
from kmast.execution.readers import (
    FakeAccountSnapshotProvider,
    FakeFillNotificationProvider,
    expected_mock_snapshot,
)
from kmast.execution.store import Journal

NOW = datetime(2026, 10, 16, tzinfo=UTC)
SEED = 20261016  # Scenario identifier; there is no random-market or fitted model in these cases.


def policy(**updates: object) -> MockRiskPolicy:
    return MockRiskPolicy.model_validate(
        dict(
            version="MOCK_FIXED_V1",
            scope="SYNTHETIC_ONLY",
            approved_by="SYNTHETIC_FIXTURE_ONLY",
            max_symbol_weight=".8",
            max_sector_weight=".9",
            max_gross_weight=".95",
            max_sleeve_weight=".5",
            loss_limit_krw=5000,
            sleeve_loss_limit_krw=3000,
            stress_loss_limit_krw=3000,
            stress_shock=".2",
            max_participation=".1",
            max_overnight_weight=".95",
            allow_overnight=True,
        )
        | updates
    )


def event_id(engine: MockExecution, prefix: str) -> str:
    return prefix + str(engine.state.sequence + 1)


def mark(engine: MockExecution, price: int = 10, halted: bool = False) -> None:
    now = engine.clock.now()
    engine.apply(
        Mark(
            event_id=event_id(engine, "mark"),
            at=now,
            quote=Quote(
                symbol="005930",
                session="REGULAR",
                price=Decimal(price),
                at=now,
                available_at=now,
                sector="MOCK_SECTOR",
                liquidity_quantity=100000,
                lower_limit=Decimal(1),
                upper_limit=Decimal(1000),
                tick_size=Decimal(1),
                source_ref="SYNTHETIC_QUOTE",
                halted=halted,
            ),
        )
    )


def resync(engine: MockExecution) -> None:
    engine.reconcile(
        event_id(engine, "sync"),
        FakeAccountSnapshotProvider(expected_mock_snapshot(engine.state, at=engine.clock.now())),
    )


def target(engine: MockExecution, quantities: tuple[int, int, int, int]) -> TargetBatch:
    version = "mock-target-" + str(engine.state.sequence)
    revision = engine.state.sequence
    budget = CapitalBudget(
        budget_id="MOCK_BUDGET",
        approved_by="SYNTHETIC_FIXTURE_ONLY",
        sleeves=tuple(
            SleeveBudget(strategy_id=s, weight=Decimal(w))
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
        for s, q in zip(("A", "B", "C", "D"), quantities, strict=True)
    )
    return TargetBatch(
        version=version,
        account_version=engine.state.account_version,
        as_of=engine.clock.now(),
        expires_at=engine.clock.now() + timedelta(minutes=1),
        budget=budget,
        targets=(
            PortfolioTarget(
                symbol="005930",
                aggregate_target_qty=sum(quantities),
                sleeve_targets=sleeves,
                snapshot_id=version,
                target_version=version,
            ),
        ),
        snapshot_refs=tuple((s, version + s, revision) for s in ("A", "B", "C", "D")),
        holding_deadlines=tuple(
            (s, engine.clock.now() + timedelta(days=10)) for s in ("A", "B", "C", "D")
        ),
    )


def approve(
    engine: MockExecution, quantities: tuple[int, int, int, int], reduction: bool = False
) -> str:
    verdict = engine.decide(
        event_id(engine, "decision"),
        target(engine, quantities),
        policy(),
        fee_buffer=Decimal(5),
        expected_gross=Decimal(-100 if reduction else 20),
        execution_cost=Decimal(2),
        uncertainty=Decimal(1),
        reduction=reduction,
    )
    if verdict.status not in {"ALLOW", "REDUCE"}:
        raise AssertionError(verdict.reasons)
    engine.plan(event_id(engine, "plan"), verdict, Decimal(5))
    order = engine.state.orders[-1]
    engine.apply(
        OrderNotice(
            event_id=event_id(engine, "ack"),
            at=engine.clock.now(),
            order_id=order.client_order_id,
            action="ACK",
            broker_order_id="MOCK_" + order.client_order_id,
        )
    )
    return order.client_order_id


def execute_fill(
    engine: MockExecution, order_id: str, qty: int, fee: int = 1, tax: int = 0
) -> Fill:
    order = next(o for o in engine.state.orders if o.client_order_id == order_id)
    event = Fill(
        event_id=event_id(engine, "fill"),
        at=engine.clock.now(),
        exec_id=event_id(engine, "exec"),
        order_id=order_id,
        quantity=qty,
        price=order.limit_price,
        fee=Decimal(fee),
        tax=Decimal(tax),
        trade_date=engine.clock.now().date(),
    )
    engine.apply(event)
    return event


def settle_all(engine: MockExecution) -> None:
    outstanding = [s for s in engine.state.settlements if not s.settled]
    if outstanding:
        due = max(s.due for s in outstanding)
        assert isinstance(engine.clock, ReplayClock)
        engine.clock.advance(datetime.combine(due, datetime.min.time(), UTC))
        for item in outstanding:
            engine.apply(
                Settle(
                    event_id=event_id(engine, "settle"),
                    at=engine.clock.now(),
                    exec_id=item.exec_id,
                    settlement_date=item.due,
                )
            )
        mark(engine)
        resync(engine)


def run_scenario(root: Path, case: str) -> dict[str, object]:
    folder = root / case
    folder.mkdir(parents=True, exist_ok=True)
    calendar = SettlementCalendar(
        version="MOCK_CALENDAR",
        source_ref="EXPLICIT_SYNTHETIC_DATES",
        eligible_dates=tuple(
            datetime(2026, 10, day).date() for day in (16, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30)
        ),
    )
    initial = ExecutionState(account_ref="MOCK_SCENARIO_" + case, calendar=calendar)
    complete = folder / "manifest.json"
    if complete.exists():
        result: dict[str, object] = json.loads(complete.read_bytes())
        if not (folder / "journal.sqlite").exists():
            journal = Journal(folder / "journal.sqlite", initial)
            try:
                for event in json.loads((folder / "events.json").read_bytes()):
                    journal.commit(EVENT_ADAPTER.validate_python(event))
            finally:
                journal.close()
        with MockExecution(folder / "journal.sqlite", initial, ReplayClock(NOW)) as restored:
            if content_hash(restored.state.model_dump(mode="json")) != result["output_hash"]:
                raise ValueError("scenario replay differs from expected manifest")
            if restored.journal.head != result["journal_head"] or restored.ready:
                raise ValueError("journal chain or startup lock differs on replay")
        return result
    with MockExecution(folder / "journal.sqlite", initial, ReplayClock(NOW)) as engine:
        engine.apply(Flow(event_id="deposit", at=NOW, amount=Decimal(10000)))
        for owner, amount in (("A", 4000), ("B", 3000), ("C", 2000), ("D", 500)):
            engine.apply(
                Allocate(
                    event_id="allocate-" + owner,
                    at=NOW,
                    from_sleeve="CENTRAL",
                    to_sleeve=owner,
                    cash=Decimal(amount),
                )
            )
        engine.apply(
            CashPolicy(event_id="cash-policy", at=NOW, policy="SYNTHETIC_NO_UNSETTLED_REUSE")
        )
        mark(engine)
        resync(engine)
        opening = engine.state
        if case == "A":
            order = approve(engine, (10, 0, 0, 0))
            execute_fill(engine, order, 4)
            execute_fill(engine, order, 6)
            settle_all(engine)
            mark(engine, 12)
            resync(engine)
            order = approve(engine, (0, 0, 0, 0))
            execute_fill(engine, order, 10, tax=1)
            settle_all(engine)
            report = engine.performance(NOW, Decimal(10000), opening)
            assert engine.state.account.settled_cash == 10016 and report.net_operating_pnl_krw == 16
        elif case == "B":
            order = approve(engine, (100, 50, 50, 0))
            execute_fill(engine, order, 200, fee=3)
            settle_all(engine)
            order = approve(engine, (100, 50, 20, 0))
            assert engine.state.orders[-1].quantity == 30 and engine.state.orders[-1].side == "SELL"
            execute_fill(engine, order, 30)
            assert engine.state.account.quantity("005930") == 170
        elif case == "C":
            verdict = engine.decide(
                event_id(engine, "decision"),
                target(engine, (10, 0, 0, 0)),
                policy(),
                fee_buffer=Decimal(5),
                expected_gross=Decimal(20),
            )
            engine.plan(event_id(engine, "plan"), verdict, Decimal(5))
            order_record = engine.state.orders[-1]
            engine.apply(
                OrderNotice(
                    event_id="timeout",
                    at=NOW,
                    order_id=order_record.client_order_id,
                    action="TIMEOUT",
                )
            )
            discovered = Fill(
                event_id="discovered-fill",
                at=NOW,
                exec_id="discovered-exec",
                order_id=order_record.client_order_id,
                quantity=4,
                price=Decimal(10),
                fee=Decimal(1),
                tax=Decimal(0),
                trade_date=NOW.date(),
            )
            expected = reduce_event(engine.state, discovered)
            engine.reconcile(
                "recover",
                FakeAccountSnapshotProvider(expected_mock_snapshot(expected, at=NOW)),
                FakeFillNotificationProvider((discovered,)),
            )
            assert engine.ready and engine.state.account.quantity("005930") == 4
            engine.plan("repeat-target", verdict, Decimal(5))
            assert len(engine.state.orders) == 1 and engine.state.account.reserved_buy_cash == 64
        elif case == "D":
            approve(engine, (300, 200, 100, 0))
            verdict = engine.decide(
                event_id(engine, "reject-cash"),
                target(engine, (1000, 200, 100, 0)),
                policy(),
                fee_buffer=Decimal(5),
                expected_gross=Decimal(9999),
            )
            assert verdict.status == "REJECT" and "INSUFFICIENT_ACCOUNT_CASH" in verdict.reasons
            assert engine.state.account.reserved_buy_cash == 6005 and len(engine.state.orders) == 1
        elif case == "E":
            engine.apply(
                SeedPosition(
                    event_id="external", at=NOW, symbol="005930", quantity=50, cost=Decimal(10)
                )
            )
            resync(engine)
            verdict = engine.decide(
                event_id(engine, "hold-external"), target(engine, (0, 0, 0, 0)), policy()
            )
            assert verdict.status == "HOLD" and not engine.state.orders
            assert engine.state.book("EXTERNAL").quantity("005930") == 50
        elif case == "F":
            order = approve(engine, (100, 0, 0, 0))
            execute_fill(engine, order, 100)
            settle_all(engine)
            mark(engine, 5)
            resync(engine)
            verdict = engine.decide(
                event_id(engine, "loss-stop"),
                target(engine, (101, 0, 0, 0)),
                policy(loss_limit_krw=Decimal(100)),
                expected_gross=Decimal(9999),
            )
            assert verdict.status == "RISK_REDUCTION_REQUIRED"
            approve(engine, (0, 0, 0, 0), reduction=True)
            mark(engine, 5, halted=True)
            verdict = engine.decide(
                event_id(engine, "halt-lock"),
                target(engine, (0, 0, 0, 0)),
                policy(),
                reduction=True,
            )
            assert verdict.status == "HOLD" and engine.state.account.quantity("005930") == 100
            assert engine.state.reserved_sell("005930") == 100
        else:
            raise ValueError("unknown scenario")
        events = [
            json.loads(row[0])
            for row in engine.journal.db.execute("SELECT payload FROM events ORDER BY seq")
        ]
        immutable_write(folder / "events.json", canonical(events))
        immutable_write(
            folder / "final-state.json", canonical(engine.state.model_dump(mode="json"))
        )
        result = {
            "scenario": case,
            "seed": SEED,
            "scope": "SYNTHETIC_ONLY",
            "input_hash": content_hash(
                {"initial": initial.model_dump(mode="json"), "events": events, "seed": SEED}
            ),
            "output_hash": content_hash(engine.state.model_dump(mode="json")),
            "journal_head": engine.journal.head,
            "quantity": engine.state.account.quantity("005930"),
            "settled_cash": str(engine.state.account.settled_cash),
            "nav": str(engine.state.account.nav(engine.state.quotes)),
            "orders": len(engine.state.orders),
            "reserved_buy_cash": str(engine.state.account.reserved_buy_cash),
            "events": len(events),
            "status": "PASS",
            "live_approved": False,
            "reference": ReferenceSleeve(
                sleeve_id="MOCK_REFERENCE_CASH",
                fixed_capital_krw=Decimal(4000),
                reference_nav_krw=Decimal(4000),
            ).model_dump(mode="json"),
        }
        immutable_write(complete, canonical(result))
        return result


def run(root: Path) -> tuple[dict[str, object], ...]:
    return tuple(run_scenario(root, case) for case in "ABCDEF")


def main() -> None:
    parser = argparse.ArgumentParser(description="KM-002 synthetic ledger/OMS only")
    parser.add_argument("--output", type=Path, default=Path("data/km002"))
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "scenarios": run(args.output),
                "status": "KM002_LEDGER_OMS_MOCK_READY",
                "data_status": "KM001_REAL_DATA_HOLD",
                "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
                "live_status": "LIVE_NOT_APPROVED",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
