from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kmast.alpha.fixtures import OPEN, intraday, trend
from kmast.alpha.models import AlphaConfig, PositionView
from kmast.alpha.readiness import DataEvidence, economic_status, observation_bar
from kmast.alpha.reference import ReferencePortfolio, RefState
from kmast.alpha.rules import decide
from kmast.simulation.cli import run

from .test_km003 import change, costs, funded_reference, tick, weight


def test_partial_fills_keep_reservation_and_execution_identity():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.submit(decide(trend(), AlphaConfig(strategy="A")), {"005930": Decimal(130)})
    one = tick(available_quantity=4)
    ref.match(one, one.at)
    assert ref.quantity("005930") == 4 and ref.state.orders[0].status == "PARTIAL"
    assert ref.reserve == Decimal("1951.95")
    before = ref.state
    ref.match(one, one.at)
    assert ref.state == before
    with pytest.raises(ValueError, match="conflicting execution"):
        ref.match(change(one, available_quantity=5), one.at)
    second = tick(OPEN + timedelta(seconds=2), identity="next", available_quantity=100)
    ref.match(second, second.at)
    assert ref.quantity("005930") == 19 and ref.reserve == 0
    assert ref.state.peak_reserved_cash == Decimal("2472.47")


def test_trade_after_decision_and_at_or_after_earliest_session_only():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    result = decide(trend(), AlphaConfig(strategy="A"))
    ref.submit(result, {"005930": Decimal(130)})
    for index, at in enumerate((trend().now, OPEN - timedelta(seconds=1))):
        event = tick(at, identity="not-yet" + str(index))
        ref.match(event, at)
        assert not ref.state.executions
    event = tick(OPEN)
    ref.match(event, OPEN)
    assert ref.quantity("005930") == 19


def test_no_market_close_fill_even_when_tick_is_incorrectly_marked_executable():
    context = intraday("B")
    ref = ReferencePortfolio("B", Decimal(10000), costs())
    result = decide(context, AlphaConfig(strategy="B", order_lifetime=timedelta(days=1)))
    ref.submit(result, {"005930": Decimal(130)})
    event = tick(context.session_close)
    ref.match(event, event.at)
    assert not ref.state.executions


def test_minimum_lot_applies_to_partial_matching():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.submit(decide(trend(), AlphaConfig(strategy="A")), {"005930": Decimal(130)}, lot_size=2)
    event = tick(available_quantity=3)
    ref.match(event, event.at)
    assert ref.quantity("005930") == 2


def test_fifo_sell_realization_costs_and_holding_time():
    ref = funded_reference()
    context = trend()
    signal = decide(context, AlphaConfig(strategy="A"), revision=2)
    intent = change(
        signal.snapshot.intents[0],
        target_weight=Decimal(0),
        decision_at=OPEN,
        available_at=OPEN,
        valid_until=OPEN + timedelta(minutes=1),
    )
    snapshot = change(signal.snapshot, intents=(intent,))
    exit_signal = change(signal, snapshot=snapshot)
    ref.submit(exit_signal, {"005930": Decimal(140)})
    event = tick(OPEN + timedelta(seconds=2), identity="sell", bid=140, ask=140)
    ref.match(event, event.at)
    assert ref.quantity("005930") == 0
    assert ref.state.realized == 190
    assert ref.state.costs == Decimal("10.45")
    assert ref.state.holding_seconds == 19 and ref.state.closed_quantity == 19
    row = ref.value(OPEN + timedelta(hours=6))
    assert row.nav == Decimal("10179.55")


def test_corporate_split_and_dividend_are_idempotent_and_preserve_economics():
    ref = funded_reference()
    before = ref.nav
    at = OPEN + timedelta(hours=1)
    ref.corporate_action("split", "005930", at, available_at=at, now=at, split=Decimal(2))
    assert ref.quantity("005930") == 38 and ref.nav == before
    ref.corporate_action("split", "005930", at, available_at=at, now=at, split=Decimal(2))
    assert ref.quantity("005930") == 38
    ref.corporate_action(
        "dividend", "005930", at, available_at=at, now=at, cash_per_share=Decimal(1)
    )
    assert ref.nav == before + 38 and ref.state.dividends == 38
    ref.value(OPEN + timedelta(hours=6))
    assert RefState.model_validate_json(ref.state.model_dump_json()) == ref.state
    with pytest.raises(ValueError, match="conflicting corporate"):
        ref.corporate_action(
            "dividend", "005930", at, available_at=at, now=at, cash_per_share=Decimal(2)
        )


def test_future_and_fractional_corporate_action_require_evidence():
    ref = funded_reference()
    at = OPEN + timedelta(hours=1)
    with pytest.raises(ValueError, match="not available"):
        ref.corporate_action("future", "005930", at, available_at=at, now=OPEN)
    before = ref.state
    with pytest.raises(ValueError, match="fractional"):
        ref.corporate_action(
            "fractional", "005930", at, available_at=at, now=at, split=Decimal(".5")
        )
    assert ref.state == before


def test_corporate_price_discontinuity_cannot_create_fake_breakout():
    context = change(trend(), corporate_action_discontinuities=("005930",))
    result = decide(context, AlphaConfig(strategy="A"))
    assert weight(result) == 0 and "CORPORATE_ACTION" in result.reasons[0][1]


@pytest.mark.parametrize("strategy", ["A", "B", "C"])
def test_missing_bar_grid_blocks_instead_of_compressing_time(strategy):
    context = trend() if strategy == "A" else intraday(strategy)
    context = change(context, bars=context.bars[1:])
    assert weight(decide(context, AlphaConfig(strategy=strategy))) == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"information_shock": True},
        {"recovering_liquidity": False},
        {"bid": 90, "ask": 100},
        {"available_at": OPEN + timedelta(hours=1)},
    ],
)
def test_reversion_filters_preserve_risk_rejections(updates):
    context = intraday("C")
    quote = change(context.quotes[0], **updates)
    assert weight(decide(change(context, quotes=(quote,)), AlphaConfig(strategy="C"))) == 0


def test_losing_position_never_increases_and_original_deadline_not_renewed():
    context = intraday("C")
    deadline = context.now + timedelta(minutes=1)
    old = PositionView(symbol="005930", weight=".1", entry_price=130, exit_deadline=deadline)
    result = decide(change(context, positions=(old,)), AlphaConfig(strategy="C"))
    assert weight(result) == 0
    assert result.exit_deadlines[0][1] == deadline


def test_ambiguous_benchmark_and_duplicate_universe_rejected():
    context = trend()
    with pytest.raises(ValidationError):
        change(context, universe=context.universe * 2)
    with pytest.raises(ValidationError):
        change(
            context,
            benchmark=(*context.benchmark, change(context.benchmark[0], identity="duplicate-end")),
        )


def test_real_rows_alone_never_imply_ready():
    evidence = DataEvidence(
        strategy="A", source="USER_FILE", origin="REAL", rows=100000, resolution="DAILY"
    )
    assert evidence.status == "DATA_BLOCKED"
    assert economic_status(evidence) == "HOLD_DATA"


def test_unverified_km001_observations_cannot_enter_strategy(fixture):
    # The KM-001 fixture advertises its actual limitations; never remove flags for convenience.
    from kmast.data.parsers import parse_rest

    from .test_km001 import daily

    request, body, meta = daily(fixture)
    row = parse_rest(body, request, meta)[0]
    with pytest.raises(ValueError):
        observation_bar(row, "unverified")


def test_authored_cli_replay_retains_all_four_reference_hashes_and_mock_ledger(tmp_path):
    first = run(tmp_path)
    assert first["real_market_rows"] == 0
    assert run(tmp_path) == first
    assert first["status"] == "KM003_STRATEGY_CODE_READY_DATA_HOLD"
