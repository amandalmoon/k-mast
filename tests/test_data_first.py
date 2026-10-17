"""Self-authored KIS-shaped wire fixtures. These are never market performance evidence."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from kmast.alpha.fixtures import trend
from kmast.alpha.models import AlphaConfig, PositionView
from kmast.alpha.rules import decide
from kmast.data.models import Observation
from kmast.research.exploratory import ExplorationPolicy, candidate_a, daily_bar, replay
from scripts.collect_data_first import Budget, MarketOnlyWire

from .test_km003 import change


def policy(**updates):
    return ExplorationPolicy.model_validate(
        dict(
            version="SELF_AUTHORED_TEST_ONLY",
            capital=100000,
            daily_operating_cost=1,
            scope_acceptance="SAMPLED_SURVIVOR_PRICE_ONLY_NOT_PIT",
        )
        | updates
    )


def panel():
    days = []
    day = date(2026, 9, 1)
    while len(days) < 32:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    at = datetime(2026, 10, 17, tzinfo=UTC)
    stock, index = [], []
    for i, day in enumerate(days):
        for symbol, target in (("005930", stock), ("0001", index)):
            close = (
                D(100 + i if i < 21 else 150 + (i - 21) * 2) if symbol == "005930" else D(200 + i)
            )
            target.append(
                Observation(
                    record_id="SELF_AUTHORED_" + symbol + str(i),
                    kind="DAILY" if symbol == "005930" else "INDEX",
                    symbol=symbol,
                    venue="KRX",
                    session="UNKNOWN",
                    exchange_date=day,
                    received_at=at,
                    acquired_at=at,
                    available_at=at,
                    availability_method="OBSERVED_LIVE",
                    availability_evidence="SELF_AUTHORED_WIRE_NOT_REAL",
                    open=close - 1,
                    high=close + 1,
                    low=close - 2,
                    close=close,
                    price=close,
                    volume=1000000,
                    turnover=close * 1000000,
                    complete=True,
                    quality_flags=("SESSION_UNVERIFIED",),
                    timestamp_precision="DATE_ONLY",
                    source_hash="f" * 64,
                    parser_version="SELF_AUTHORED",
                    data_origin="KIS_READONLY",
                )
            )
    return tuple(stock), tuple(index)


def test_aggregate_request_budget_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.collect_data_first.time.sleep", lambda _: None)
    path = tmp_path / "budget.json"
    first = Budget(path)
    for _ in range(47):
        first.consume("market")
    resumed = Budget(path)
    resumed.consume("auth")
    with pytest.raises(PermissionError):
        resumed.consume("market")
    assert resumed.state["used"] == 48


def test_collector_denies_order_before_io(tmp_path):
    wire = MarketOnlyWire(None, Budget(tmp_path / "budget.json"))
    with pytest.raises(PermissionError):
        wire.send(None, "POST", "/uapi/domestic-stock/v1/trading/order-cash", {}, {})


def test_source_flags_and_real_timestamps_are_not_overwritten():
    rows, _ = panel()
    original = rows[0].model_dump_json()
    bar = daily_bar(rows[0], rows[1].available_at)
    assert bar.origin == "REAL" and rows[0].model_dump_json() == original
    assert rows[0].event_time is None and rows[0].quality_flags == ("SESSION_UNVERIFIED",)
    with pytest.raises(ValueError):
        rows[0].require_strategy_input(rows[0].available_at)


def test_adjusted_execution_inputs_rejected():
    rows, _ = panel()
    with pytest.raises(ValueError):
        daily_bar(
            change(rows[0], price_basis="ADJUSTED", adjustment_asof=rows[0].available_at),
            rows[1].available_at,
        )


def test_frozen_a_rules_match_existing_candidate_without_pit_fabrication():
    context = trend()
    config = AlphaConfig(strategy="A")
    exploratory = candidate_a(change(context, universe=()), "005930", config, None, 1)
    original = decide(context, config)
    assert (
        exploratory.snapshot.intents[0].target_weight == original.snapshot.intents[0].target_weight
    )
    assert exploratory.reasons == original.reasons


def test_existing_stop_deadline_no_averaging_rules_match():
    context = trend()
    old = PositionView(
        symbol="005930", weight=".1", entry_price=200, exit_deadline=context.now + timedelta(days=1)
    )
    original = decide(change(context, positions=(old,)), AlphaConfig(strategy="A"))
    exploratory = candidate_a(
        change(context, universe=()), "005930", AlphaConfig(strategy="A"), old, 1
    )
    assert (
        exploratory.snapshot.intents[0].target_weight
        == original.snapshot.intents[0].target_weight
        == 0
    )


def test_prices_used_for_features_precede_execution_day():
    rows, index = panel()
    result = replay(rows, index, policy(), "ALPHA_A")
    assert all(r["input_last_date"] < r["day"] for r in result["signal_log"])
    assert result["executions"] > 0


def test_future_close_does_not_change_prior_targets():
    rows, index = panel()
    original = replay(rows, index, policy(), "ALPHA_A")
    changed = rows[:-1] + (change(rows[-1], close=rows[-1].close + 1, high=rows[-1].high + 1),)
    result = replay(changed, index, policy(), "ALPHA_A")
    assert result["signal_log"] == original["signal_log"]


def test_scenario_replay_is_deterministic():
    rows, index = panel()
    assert replay(rows, index, policy(), "ALPHA_A") == replay(rows, index, policy(), "ALPHA_A")


def test_costs_opex_and_nav_reconcile_once():
    rows, index = panel()
    r = replay(rows, index, policy(), "ALPHA_A")
    assert D(r["ending_nav"]) - D(r["capital"]) == D(r["scenario_project_net_pnl"])
    assert D(r["trading_net_pnl"]) - D(r["recurring_operating_cost"]) == D(
        r["scenario_project_net_pnl"]
    )
    assert D(r["price_pnl_including_embedded_slippage"]) - D(r["explicit_fees_taxes"]) == D(
        r["trading_net_pnl"]
    )


def test_zero_fill_scenario_keeps_cash_and_no_fake_trades():
    rows, index = panel()
    r = replay(rows, index, policy(fill_fraction=0), "ALPHA_A")
    assert r["executions"] == 0 and r["final_quantity"] == 0
    assert D(r["scenario_project_net_pnl"]) == -D(r["recurring_operating_cost"])


def test_duplicate_dates_and_missing_index_are_rejected():
    rows, index = panel()
    for stock, bench in ((rows + (rows[-1],), index), (rows, index[:-1])):
        with pytest.raises(ValueError):
            replay(stock, bench, policy(), "ALPHA_A")


def test_scope_acceptance_and_live_approval_cannot_be_implicit():
    with pytest.raises(ValidationError):
        ExplorationPolicy(version="MISSING_SCOPE")
    with pytest.raises(ValidationError):
        policy(live_approved=True)


def test_sale_proceeds_not_reused_next_observed_session():
    rows, index = panel()
    r = replay(rows, index, policy(), "ALPHA_A")
    days = sorted(row.exchange_date for row in rows)
    last_sale = -100
    for execution in r["reference_state"]["executions"]:
        at = datetime.fromisoformat(execution[1]).date()
        offset = days.index(at)
        if execution[3] < 0:
            last_sale = offset
        else:
            assert offset - last_sale >= 2


def test_cash_baseline_same_window_and_opex():
    rows, index = panel()
    cash = replay(rows, index, policy(), "CASH")
    alpha = replay(rows, index, policy(), "ALPHA_A")
    assert cash["days"] == alpha["days"] and cash["evaluation_start"] == alpha["evaluation_start"]
    assert cash["executions"] == 0 and cash["mdd"] == str(D(cash["days"]) / D(cash["capital"]))


def test_synthetic_origin_is_not_admitted_as_real_evidence():
    rows, index = panel()
    with pytest.raises(ValueError):
        replay(
            tuple(change(r, data_origin="SYNTHETIC_FIXTURE") for r in rows),
            index,
            policy(),
            "ALPHA_A",
        )
