"""Authored integration paths and analytical outputs; never a market backtest or approval."""

import argparse
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from kmast.alpha.fixtures import OPEN, intraday, trend
from kmast.alpha.models import AlphaConfig, Context, PositionView
from kmast.alpha.readiness import DataEvidence, ResearchPlan
from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick
from kmast.alpha.rules import decide
from kmast.core.clock import ReplayClock
from kmast.core.contracts import CapitalBudget, SleeveBudget
from kmast.data.normalization import content_hash
from kmast.data.store import canonical, immutable_write
from kmast.execution.demo import mark, policy, resync
from kmast.execution.engine import MockExecution
from kmast.execution.events import Allocate, CashPolicy, Fill, Flow
from kmast.execution.models import ExecutionState, SettlementCalendar
from kmast.simulation.bridge import plan_mock


def replace_context(context: Context, **updates: object) -> Context:
    return Context.model_validate(context.model_dump() | updates)


def reference_case(
    strategy: Literal["A", "B", "C", "D"], capital: Decimal
) -> tuple[ReferencePortfolio, Context]:
    context = trend() if strategy == "A" else intraday(strategy)
    config = AlphaConfig(strategy=strategy)
    cost = SimCosts(
        version="SYNTHETIC_ONLY_10_20_5_BPS",
        fee_bps=10,
        sell_tax_bps=20,
        slippage_bps=5,
        max_participation=Decimal(".1"),
    )
    book = ReferencePortfolio(strategy, capital, cost)
    first = OPEN - timedelta(days=1) + timedelta(hours=6, minutes=30)
    last = OPEN + timedelta(days=3, hours=6, minutes=30)
    close = OPEN + timedelta(hours=6, minutes=30)
    book.value(first, capital / 10000)
    result = decide(context, config)
    prices = {"A": 130, "B": 115, "C": 95, "D": 100}
    price = Decimal(prices[strategy])
    # C deliberately retains passive nonfills; other cases use capped aggressive orders.
    limit = price if strategy == "C" else price + 1
    book.submit(result, {"005930": limit})
    at = result.earliest_execution_at + timedelta(seconds=1)
    book.match(
        Tick(
            identity="entry-" + strategy,
            symbol="005930",
            at=at,
            available_at=at,
            bid=price,
            ask=price,
            available_quantity=1000,
            executable=True,
        ),
        at,
    )
    if strategy in {"B", "C"}:
        exit_at = close - timedelta(seconds=30)
        held = (
            ()
            if not book.quantity("005930")
            else (
                PositionView(
                    symbol="005930",
                    weight=Decimal(".25"),
                    entry_price=price,
                    exit_deadline=exit_at,
                ),
            )
        )
        exit_context = replace_context(context, now=exit_at, positions=held)
        exit_result = decide(exit_context, config, revision=2)
        book.submit(exit_result, {"005930": price - 1})
        book.match(
            Tick(
                identity="halted-exit-" + strategy,
                symbol="005930",
                at=exit_at + timedelta(seconds=1),
                available_at=exit_at + timedelta(seconds=1),
                bid=price - 5,
                ask=price - 5,
                available_quantity=0,
                executable=False,
            ),
            exit_at + timedelta(seconds=1),
        )
        book.expire(close + timedelta(seconds=31))
    else:
        book.expire(close)
    book.mark("005930", price - 5, close)
    book.value(close, capital / 10000)
    book.mark("005930", price - 10, last)
    book.value(last, capital / 10000)
    return book, context


def mock_integration(output: Path) -> dict[str, object]:
    calendar = SettlementCalendar(
        version="MOCK_ONLY",
        source_ref="AUTHORED",
        eligible_dates=tuple((OPEN + timedelta(days=n)).date() for n in (0, 3, 4, 5, 6)),
    )
    initial = ExecutionState(account_ref="MOCK_KM003_FIXED_BUDGET", calendar=calendar)
    now = OPEN + timedelta(minutes=6)
    clock = ReplayClock(now)
    with MockExecution(output / "journal.sqlite", initial, clock) as engine:
        if engine.state.sequence:
            state, _ = engine.journal.replay()
            return {
                "status": "PASS_REPLAY",
                "state_hash": content_hash(state.model_dump(mode="json")),
            }
        engine.apply(Flow(event_id="deposit", at=now, amount=10000))
        allocations = (("A", 4000), ("B", 3000), ("C", 2000), ("D", 500))
        for owner, cash in allocations:
            engine.apply(
                Allocate(
                    event_id="allocate-" + owner,
                    at=now,
                    from_sleeve="CENTRAL",
                    to_sleeve=owner,
                    cash=cash,
                )
            )
        engine.apply(
            CashPolicy(event_id="cash-policy", at=now, policy="SYNTHETIC_NO_UNSETTLED_REUSE")
        )
        mark(engine, 130)
        resync(engine)
        contexts = {
            "A": replace_context(
                trend(),
                now=now,
                session_open=OPEN,
                session_close=OPEN + timedelta(hours=6, minutes=30),
                next_session_open=OPEN + timedelta(days=3),
            ),
            **{s: intraday(s) for s in ("B", "C", "D")},
        }
        configs = tuple(AlphaConfig(strategy=s) for s in ("A", "B", "C", "D"))
        results = tuple(decide(contexts[c.strategy], c) for c in configs)
        budget = CapitalBudget(
            budget_id="MOCK_FIXED",
            approved_by="SYNTHETIC_ONLY",
            sleeves=tuple(
                SleeveBudget(strategy_id=s, weight=Decimal(cash) / 10000) for s, cash in allocations
            ),
        )
        verdict = plan_mock(
            engine,
            results,
            budget,
            policy(),
            "fixed-alpha",
            synthetic_expected_gross=Decimal(20),
            execution_cost=Decimal(2),
            uncertainty=Decimal(1),
            fee_buffer=Decimal(5),
        )
        if verdict.status != "ALLOW" or not engine.state.orders:
            raise ValueError("synthetic strategy/risk/OMS integration failed")
        order = engine.state.orders[-1]
        fill_at = now + timedelta(seconds=1)
        clock.advance(fill_at)
        engine.apply(
            Fill(
                event_id="fill",
                at=fill_at,
                exec_id="MOCK_ALPHA_FILL",
                order_id=order.client_order_id,
                quantity=order.quantity,
                price=130,
                fee=1,
                tax=0,
                trade_date=now.date(),
            )
        )
        immutable_write(output / "mock-state.json", canonical(engine.state.model_dump(mode="json")))
        immutable_write(
            output / "mock-events.json",
            canonical(
                [
                    json.loads(row[0])
                    for row in engine.journal.db.execute("SELECT payload FROM events ORDER BY seq")
                ]
            ),
        )
        return {
            "status": "PASS",
            "state_hash": content_hash(engine.state.model_dump(mode="json")),
            "quantity": engine.state.account.quantity("005930"),
            "risk": verdict.status,
            "policy": "PBASE_FIXED",
            "live_approved": False,
        }


def run(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {}
    for strategy in ("A", "B", "C", "D"):
        book, context = reference_case(strategy, Decimal(10000))
        config = AlphaConfig(strategy=strategy)
        state = book.state.model_dump(mode="json")
        immutable_write(
            output / strategy / "context.json", canonical(context.model_dump(mode="json"))
        )
        immutable_write(
            output / strategy / "config.json", canonical(config.model_dump(mode="json"))
        )
        immutable_write(output / strategy / "reference.json", canonical(state))
        result = decide(context, config)
        immutable_write(
            output / strategy / "signal.json", canonical(result.model_dump(mode="json"))
        )
        data_hash = content_hash(context.model_dump(mode="json"))
        plan = ResearchPlan(
            trial_id="AUTHORED_FUNCTIONAL_" + strategy,
            config_hash=content_hash(config.model_dump(mode="json")),
            data_hash=data_hash,
            research_start=OPEN - timedelta(days=360),
            research_end=OPEN - timedelta(days=180),
            validation_start=OPEN - timedelta(days=179),
            validation_end=OPEN - timedelta(days=90),
            locked_oos_start=OPEN - timedelta(days=89),
            locked_oos_end=OPEN - timedelta(days=1),
            registered_at=OPEN,
            exposures=("AUTHORED_FIXTURE_ALREADY_SEEN_NO_CONFIRMATORY_OOS",),
        )
        immutable_write(output / strategy / "trial.json", canonical(plan.model_dump(mode="json")))
        evidence = DataEvidence(
            strategy=strategy,
            source="AUTHORED_FIXTURE_NOT_MARKET_DATA",
            origin="SYNTHETIC",
            rows=len(context.bars),
            resolution="DAILY" if strategy == "A" else "MINUTE",
        )
        metrics = book.metrics(tuple(row.at.date() for row in book.state.panel))
        metrics.update(
            {
                "input_hash": data_hash,
                "output_hash": content_hash(state),
                "data_status": evidence.status,
                "blockers": list(evidence.blockers()),
                "origin": "SYNTHETIC_FUNCTIONAL_TRACE",
            }
        )
        immutable_write(output / strategy / "metrics.json", canonical(metrics))
        results[strategy] = metrics
    integration = mock_integration(output)
    # Replay checks existing artifacts and journal without replacing first-run evidence.
    if integration["status"] == "PASS_REPLAY":
        stored: dict[str, object] = json.loads((output / "summary.json").read_bytes())
        prior_integration = stored["mock_integration"]
        if (
            not isinstance(prior_integration, dict)
            or prior_integration["state_hash"] != integration["state_hash"]
        ):
            raise ValueError("mock integration replay hash differs")
        return stored
    fixed_nav = Decimal("499.85")  # Central 500 cash, three 0.05 operating-cost allocations.
    fixed_pnl = Decimal("-.15")
    fixed_costs = Decimal(0)
    allocations: tuple[tuple[Literal["A", "B", "C", "D"], int], ...] = (
        ("A", 4000),
        ("B", 3000),
        ("C", 2000),
        ("D", 500),
    )
    for strategy, capital in allocations:
        fixed_book, _ = reference_case(strategy, Decimal(capital))
        immutable_write(
            output / "fixed-budget" / (strategy + ".json"),
            canonical(fixed_book.state.model_dump(mode="json")),
        )
        fixed_nav += fixed_book.nav
        fixed_pnl += fixed_book.nav - capital
        fixed_costs += fixed_book.state.costs
    hold_book, _ = reference_case("A", Decimal(10000))
    immutable_write(output / "simple-hold.json", canonical(hold_book.state.model_dump(mode="json")))
    baseline = {
        "cash": {
            "initial_capital": "10000",
            "closing_nav": "9997",
            "operating_costs": "3",
            "cash_rate_daily": "0",
            "scope": "SYNTHETIC_SAME_CAPITAL_COST_SCHEDULE",
        },
        "simple_hold": {
            "initial_capital": "10000",
            "target_weight": ".25",
            "closing_nav": str(hold_book.nav),
            "scope": "ONE_ENTRY_25_PERCENT_HOLD",
            "note": "Same entry as A on this trace; no difference attributable to alpha",
        },
        "fixed_budget_reference": {
            "initial_capital": "10000",
            "closing_nav": str(fixed_nav),
            "NET_OPERATING_PNL_KRW": str(fixed_pnl),
            "trading_costs": str(fixed_costs),
            "operating_costs": "3",
            "policy": "PBASE_FIXED",
            "scope": "REFERENCE_ONLY_NOT_ACCOUNT_LEDGER",
        },
        "fixed_budget_account": integration,
        "market_benchmark_performance": None,
        "reason": "NO_REAL_BENCHMARK_OR_RISK_MATCHED_MARKET_SAMPLE",
    }
    summary = {
        "status": "KM003_STRATEGY_CODE_READY_DATA_HOLD",
        "economics": "ECONOMIC_EDGE_UNVERIFIED",
        "live": "LIVE_NOT_APPROVED",
        "real_market_rows": 0,
        "strategies": results,
        "baselines": baseline,
        "mock_integration": integration,
        "interpretation": "Functional traces only; market profitability remains unverified",
    }
    immutable_write(output / "summary.json", canonical(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline KM-003 functional strategy paths")
    parser.add_argument("--output", type=Path, default=Path("data/km003"))
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))


if __name__ == "__main__":
    main()
