"""One deterministic conservation trace, not a profitability experiment."""

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from kmast.alpha.models import AlphaResult
from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick
from kmast.core.clock import ReplayClock
from kmast.core.contracts import CapitalBudget, SignalIntent, SleeveBudget, TargetSnapshot
from kmast.data.normalization import content_hash
from kmast.data.store import canonical, immutable_write
from kmast.execution.demo import mark, policy, resync
from kmast.execution.engine import MockExecution
from kmast.execution.events import (
    Allocate,
    CashPolicy,
    Fill,
    Flow,
    Income,
    OrderNotice,
    Settle,
    SplitAction,
    Transfer,
)
from kmast.execution.models import ExecutionState, MockRiskDecision, SettlementCalendar
from kmast.simulation.bridge import plan_mock

NOW = datetime(2026, 10, 16, tzinfo=UTC)
OWNERS: tuple[Literal["A", "B", "C", "D"], ...] = ("A", "B", "C", "D")
BUDGETS = (Decimal(".4"), Decimal(".3"), Decimal(".2"), Decimal(".05"))


def snapshot(
    owner: str, weight: Decimal, now: datetime, revision: int, identity: str
) -> TargetSnapshot:
    return TargetSnapshot(
        strategy_id=owner,
        snapshot_id=identity,
        revision=revision,
        expected_symbols=("005930",),
        intents=(
            SignalIntent(
                intent_id=identity + "-intent",
                revision=revision,
                target_snapshot_id=identity,
                strategy_id=owner,
                model_version="KM004_SYNTHETIC_CONSERVATION",
                config_hash="FIXED",
                data_version="AUTHORED_NOT_MARKET",
                symbol="005930",
                venue="KRX",
                session="REGULAR",
                decision_at=now,
                available_at=now,
                target_weight=weight,
                horizon=timedelta(days=10),
                valid_until=now + timedelta(minutes=1),
                reason_code="SYNTHETIC_ONLY",
            ),
        ),
    )


def result(snap: TargetSnapshot, now: datetime) -> AlphaResult:
    return AlphaResult(
        snapshot=snap,
        exit_deadlines=(("005930", NOW + timedelta(days=10)),),
        earliest_execution_at=now,
        feature_evidence=(),
        reasons=(),
    )


def rebalance(
    engine: MockExecution,
    quantities: tuple[int, int, int, int],
    budget: CapitalBudget,
    identity: str,
    reduction: bool = False,
) -> MockRiskDecision:
    nav = engine.state.account.nav(engine.state.quotes)
    price = engine.state.quote("005930").price
    results = tuple(
        result(
            snapshot(
                owner,
                (Decimal(qty) + Decimal(".000001")) * price / (nav * cap) if qty else Decimal(0),
                engine.clock.now(),
                engine.state.sequence,
                identity + owner,
            ),
            engine.clock.now(),
        )
        for owner, cap, qty in zip(OWNERS, BUDGETS, quantities, strict=True)
    )
    if reduction:
        from kmast.execution.portfolio import aggregate

        batch = aggregate(
            engine.state, budget, tuple(r.snapshot for r in results), engine.clock.now(), identity
        )
        verdict = engine.decide(
            identity + "-risk", batch, policy(), reduction=True, fee_buffer=Decimal(5)
        )
        if verdict.status == "REDUCE":
            engine.plan(identity + "-plan", verdict, Decimal(5))
    else:
        verdict = plan_mock(
            engine,
            results,
            budget,
            policy(),
            identity,
            synthetic_expected_gross=Decimal(20),
            execution_cost=Decimal(2),
            uncertainty=Decimal(1),
            fee_buffer=Decimal(5),
        )
    return verdict


def run(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    if (root / "summary.json").exists():
        stored: dict[str, object] = json.loads((root / "summary.json").read_bytes())
        initial = ExecutionState.model_validate_json((root / "initial.json").read_bytes())
        from kmast.execution.events import EVENT_ADAPTER
        from kmast.execution.store import Journal

        journal = Journal(root / "journal.sqlite", initial)
        try:
            if journal.state.sequence == 0:
                for event in json.loads((root / "events.json").read_bytes()):
                    journal.commit(EVENT_ADAPTER.validate_python(event))
            if content_hash(journal.state.model_dump(mode="json")) != stored["account_state_hash"]:
                raise ValueError("joint account replay differs")
        finally:
            journal.close()
        return stored
    calendar = SettlementCalendar(
        version="SYNTHETIC_ONLY",
        source_ref="EXPLICIT_DATES",
        eligible_dates=tuple(date(2026, 10, d) for d in (16, 19, 20, 21, 22, 23, 26, 27)),
    )
    initial = ExecutionState(account_ref="MOCK_KM004_JOINT", calendar=calendar)
    immutable_write(root / "initial.json", canonical(initial.model_dump(mode="json")))
    clock = ReplayClock(NOW)
    budget = CapitalBudget(
        budget_id="SYNTHETIC_FIXED",
        approved_by="SYNTHETIC_TEST_ONLY",
        sleeves=tuple(
            SleeveBudget(strategy_id=s, weight=w) for s, w in zip(OWNERS, BUDGETS, strict=True)
        ),
    )
    refcost = SimCosts(
        version="SYNTHETIC_10_20_BPS",
        fee_bps=10,
        sell_tax_bps=20,
        slippage_bps=0,
        max_participation=1,
    )
    refs = {s: ReferencePortfolio(s, Decimal(10000), refcost) for s in OWNERS}
    cash = ReferencePortfolio("A", Decimal(10000), refcost)
    refweights = (Decimal(".025"), Decimal(".016667"), Decimal(".025"), Decimal(0))
    for owner, weight in zip(OWNERS, refweights, strict=True):
        refs[owner].submit(
            result(snapshot(owner, weight, NOW, 1, "ref" + owner), NOW), {"005930": Decimal(10)}
        )
    at = NOW + timedelta(seconds=1)
    for ref in refs.values():
        ref.match(
            Tick(
                identity="ref-entry",
                symbol="005930",
                at=at,
                available_at=at,
                bid=10,
                ask=10,
                available_quantity=10000,
                executable=True,
            ),
            at,
        )
    panel = []
    with MockExecution(root / "journal.sqlite", initial, clock) as engine:
        engine.apply(Flow(event_id="capital", at=NOW, amount=10000))
        for owner, cap in zip(OWNERS, BUDGETS, strict=True):
            engine.apply(
                Allocate(
                    event_id="allocate" + owner,
                    at=NOW,
                    from_sleeve="CENTRAL",
                    to_sleeve=owner,
                    cash=10000 * cap,
                )
            )
        engine.apply(
            CashPolicy(event_id="cash-policy", at=NOW, policy="SYNTHETIC_NO_UNSETTLED_REUSE")
        )
        mark(engine)
        resync(engine)
        opening = engine.state
        verdict = rebalance(engine, (10, 5, 5, 0), budget, "initial-target")
        assert verdict.status == "ALLOW" and engine.state.orders[-1].quantity == 20
        order = engine.state.orders[-1]
        clock.advance(at)
        engine.apply(
            Fill(
                event_id="partial",
                at=at,
                exec_id="partial-exec",
                order_id=order.client_order_id,
                quantity=4,
                price=10,
                fee=Decimal(".04"),
                tax=0,
                trade_date=at.date(),
            )
        )
        engine.apply(
            OrderNotice(event_id="timeout", at=at, order_id=order.client_order_id, action="TIMEOUT")
        )
        reserve = engine.state.account.reserved_buy_cash
        resync(engine)
        engine.apply(
            Fill(
                event_id="remaining",
                at=at,
                exec_id="remaining-exec",
                order_id=order.client_order_id,
                quantity=16,
                price=10,
                fee=Decimal(".16"),
                tax=0,
                trade_date=at.date(),
            )
        )
        for day in calendar.eligible_dates[:7]:
            event_at = datetime.combine(day, datetime.min.time(), UTC)
            if event_at > clock.now():
                clock.advance(event_at)
            if day.day == 20:
                for item in engine.state.settlements:
                    engine.apply(
                        Settle(
                            event_id="settle-" + item.exec_id,
                            at=clock.now(),
                            exec_id=item.exec_id,
                            settlement_date=item.due,
                        )
                    )
                mark(engine)
                engine.apply(
                    Transfer(
                        event_id="internal",
                        at=clock.now(),
                        from_sleeve="A",
                        to_sleeve="B",
                        symbol="005930",
                        quantity=2,
                        reference_price=10,
                        reference_at=clock.now(),
                        policy_ref="SYNTHETIC_TRANSFER",
                    )
                )
                for owner in OWNERS:
                    qty = engine.state.book(owner).quantity("005930")
                    if not qty:
                        continue
                    for category in ("DIVIDEND_ACCRUAL", "DIVIDEND_PAYMENT"):
                        engine.apply(
                            Income(
                                event_id=category + owner,
                                at=clock.now(),
                                category=category,
                                amount=qty,
                                entitlement_id="DIV-" + owner,
                                sleeve=owner,
                            )
                        )
                for ref in refs.values():
                    if ref.quantity("005930"):
                        ref.corporate_action(
                            "dividend",
                            "005930",
                            clock.now(),
                            available_at=clock.now(),
                            now=clock.now(),
                            cash_per_share=Decimal(1),
                        )
            if day.day == 21:
                engine.apply(
                    SplitAction(
                        event_id="SPLIT:split2",
                        action_id="split2",
                        at=clock.now(),
                        available_at=clock.now(),
                        effective_date=day,
                        symbol="005930",
                        multiplier=2,
                        source_ref="SYNTHETIC_SPLIT",
                    )
                )
                engine.apply(
                    Income(
                        event_id="account-opex", at=clock.now(), category="ACCOUNT_OPEX", amount=5
                    )
                )
                engine.apply(
                    Income(
                        event_id="external-opex",
                        at=clock.now(),
                        category="EXTERNAL_OPEX",
                        amount=10,
                    )
                )
                for ref in refs.values():
                    if ref.quantity("005930"):
                        ref.corporate_action(
                            "split",
                            "005930",
                            clock.now(),
                            available_at=clock.now(),
                            now=clock.now(),
                            split=Decimal(2),
                        )
            if day.day == 22:
                mark(engine, 5)
                resync(engine)
                assert (
                    rebalance(engine, (16, 14, 0, 0), budget, "reduce-C", reduction=True).status
                    == "REDUCE"
                )
                sell = engine.state.orders[-1]
                assert sell.quantity == 10 and sell.allocations == (("C", 10),)
                engine.apply(
                    Fill(
                        event_id="sell",
                        at=clock.now(),
                        exec_id="sell-exec",
                        order_id=sell.client_order_id,
                        quantity=10,
                        price=5,
                        fee=Decimal(".05"),
                        tax=Decimal(".10"),
                        trade_date=day,
                    )
                )
                ref = refs["C"]
                ref.submit(
                    result(snapshot("C", Decimal(0), clock.now(), 2, "refC-exit"), clock.now()),
                    {"005930": Decimal(5)},
                )
                refat = clock.now() + timedelta(seconds=1)
                ref.match(
                    Tick(
                        identity="ref-exit",
                        symbol="005930",
                        at=refat,
                        available_at=refat,
                        bid=5,
                        ask=5,
                        available_quantity=10000,
                        executable=True,
                    ),
                    refat,
                )
            if day.day == 26:
                for item in engine.state.settlements:
                    if not item.settled:
                        engine.apply(
                            Settle(
                                event_id="settle-" + item.exec_id,
                                at=clock.now(),
                                exec_id=item.exec_id,
                                settlement_date=item.due,
                            )
                        )
            close = event_at + timedelta(minutes=10)
            clock.advance(close)
            price = 5 if day.day >= 21 else 10
            mark(engine, price)
            for ref in refs.values():
                ref.mark("005930", Decimal(price), close)
                ref.value(close, Decimal(15) if day.day == 21 else Decimal(0))
            cash.value(close, Decimal(15) if day.day == 21 else Decimal(0))
            performance = engine.performance(NOW, Decimal(10000), opening)
            panel.append(
                {
                    "at": close.isoformat(),
                    "account_nav": str(performance.account_nav_krw),
                    "project_net_pnl": str(performance.net_operating_pnl_krw),
                    "reference_navs": {s: str(r.nav) for s, r in refs.items()},
                    "cash_nav": str(cash.nav),
                }
            )
        report = engine.performance(NOW, Decimal(10000), opening)
        weighted = sum(
            ((refs[s].nav - 10000) * w for s, w in zip(OWNERS, BUDGETS, strict=True)), Decimal(0)
        ) + (cash.nav - 10000) * Decimal(".05")
        assert report.net_operating_pnl_krw == Decimal("4.65") and weighted == Decimal("4.452")
        state = engine.state.model_dump(mode="json")
        immutable_write(root / "final-state.json", canonical(state))
        immutable_write(
            root / "events.json",
            canonical(
                [
                    json.loads(r[0])
                    for r in engine.journal.db.execute("SELECT payload FROM events ORDER BY seq")
                ]
            ),
        )
        for owner, ref in refs.items():
            immutable_write(
                root / ("reference-" + owner + ".json"),
                canonical(ref.state.model_dump(mode="json")),
            )
        immutable_write(root / "panel.json", canonical(panel))
        summary = {
            "scope": "SYNTHETIC_ONLY_CONSERVATION_NOT_ALPHA",
            "account_state_hash": content_hash(state),
            "account_nav": str(report.account_nav_krw),
            "project_net_pnl": str(report.net_operating_pnl_krw),
            "account_net_pnl": str(report.account_bridge.net_operating_pnl_krw),
            "weighted_reference_net": str(weighted),
            "difference_due_to_integer_shared_account": str(
                report.net_operating_pnl_krw - weighted
            ),
            "unknown_reserve_preserved": str(reserve),
            "daily_rows": len(panel),
            "cash_baseline_net": str(cash.nav - 10000),
            "actual_broker_orders": 0,
            "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
            "live_status": "LIVE_NOT_APPROVED",
        }
        immutable_write(root / "summary.json", canonical(summary))
        return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/km004-joint"))
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))


if __name__ == "__main__":
    main()
