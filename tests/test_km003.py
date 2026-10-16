import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from kmast.alpha.fixtures import OPEN, intraday, trend
from kmast.alpha.models import AlphaConfig, PositionView
from kmast.alpha.readiness import DataEvidence, ResearchPlan, economic_status
from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick
from kmast.alpha.rules import decide
from kmast.brokers.interfaces import MockBroker
from kmast.core.contracts import CapitalBudget, SleeveBudget
from kmast.data.normalization import content_hash
from kmast.simulation.bridge import plan_mock

from .km002_helpers import make_engine, mark, policy, reconcile


def change(model, **updates):
    return type(model).model_validate(model.model_dump() | updates)


def weight(result):
    return result.snapshot.intents[0].target_weight


def costs(**updates):
    return SimCosts.model_validate(
        dict(
            version="SYNTHETIC_COSTS_V1",
            fee_bps=10,
            sell_tax_bps=20,
            slippage_bps=0,
            max_participation=1,
        )
        | updates
    )


def tick(at=None, **updates):
    at = at or OPEN + timedelta(seconds=1)
    return Tick.model_validate(
        dict(
            identity="tick",
            symbol="005930",
            at=at,
            available_at=at,
            bid=130,
            ask=130,
            available_quantity=1000,
            executable=True,
        )
        | updates
    )


def funded_reference():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    signal = decide(trend(), AlphaConfig(strategy="A"))
    ref.submit(signal, {"005930": Decimal(130)})
    ref.match(tick(), OPEN + timedelta(seconds=1))
    assert ref.quantity("005930") == 19
    return ref


def test_ALPHA_001_strategy_has_no_broker_network_or_oms_import():
    allowed = ("kmast.alpha", "kmast.core", "kmast.data.normalization", "kmast.data.models")
    forbidden = {"eval", "exec", "__import__", "compile"}
    for path in Path("src/kmast/alpha").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert all(not m.startswith("kmast.") or m.startswith(allowed) for m in modules)
            assert all(
                m.split(".")[0]
                not in {
                    "socket",
                    "http",
                    "urllib",
                    "requests",
                    "websockets",
                    "subprocess",
                    "os",
                    "importlib",
                }
                for m in modules
            )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden


@pytest.mark.parametrize("strategy", list("ABCD"))
def test_ALPHA_002_absolute_nonnegative_targets(strategy):
    result = decide(
        trend() if strategy == "A" else intraday(strategy), AlphaConfig(strategy=strategy)
    )
    assert 0 < weight(result) <= 1
    assert sum(i.target_weight for i in result.snapshot.intents) <= 1
    assert all(i.target_basis == "SLEEVE_NAV_WEIGHT" for i in result.snapshot.intents)
    assert not result.live_approved


def test_ALPHA_003_full_snapshot_includes_old_delisted_position():
    context = trend()
    position = PositionView(
        symbol="OLD", weight=".2", entry_price=10, exit_deadline=OPEN + timedelta(days=1)
    )
    result = decide(change(context, positions=(position,)), AlphaConfig(strategy="A"))
    assert set(result.snapshot.expected_symbols) == {"005930", "OLD"}
    assert next(i.target_weight for i in result.snapshot.intents if i.symbol == "OLD") == 0


def test_ALPHA_004_signal_expiry_and_exit_deadline_are_separate():
    result = decide(trend(), AlphaConfig(strategy="A"))
    assert result.earliest_execution_at == OPEN
    assert result.snapshot.intents[0].valid_until == OPEN + timedelta(minutes=1)
    assert result.exit_deadlines[0][1] > result.snapshot.intents[0].valid_until
    context = intraday("C")
    position = PositionView(
        symbol="005930",
        weight=".1",
        entry_price=100,
        exit_deadline=context.now - timedelta(seconds=1),
    )
    assert weight(decide(change(context, positions=(position,)), AlphaConfig(strategy="C"))) == 0


def test_PIT_001_future_price_never_enters_trend_features():
    context = trend()
    bar = change(
        context.bars[-1],
        identity="future",
        start=OPEN,
        end=OPEN + timedelta(hours=6),
        available_at=OPEN + timedelta(hours=6),
        open=1000,
        high=1001,
        low=999,
        close=1000,
    )
    original = decide(context, AlphaConfig(strategy="A"))
    future = decide(change(context, bars=(*context.bars, bar)), AlphaConfig(strategy="A"))
    assert weight(original) == weight(future)
    assert original.feature_evidence == future.feature_evidence


def test_PIT_002_unfinished_minute_never_triggers():
    context = intraday()
    before = change(context, now=OPEN + timedelta(minutes=5, seconds=30))
    assert weight(decide(before, AlphaConfig(strategy="B"))) == 0


def test_PIT_003_future_disclosure_never_triggers():
    context = intraday("D")
    future = change(context.events[0], available_at=context.now + timedelta(seconds=1))
    assert weight(decide(change(context, events=(future,)), AlphaConfig(strategy="D"))) == 0


@pytest.mark.parametrize("field", ["known_at", "listed_at", "delisted_at"])
def test_PIT_004_historical_universe_is_used(field):
    context = trend()
    value = (
        context.now - timedelta(seconds=1)
        if field == "delisted_at"
        else context.now + timedelta(seconds=1)
    )
    universe = change(context.universe[0], **{field: value})
    assert weight(decide(change(context, universe=(universe,)), AlphaConfig(strategy="A"))) == 0


def test_TREND_001_current_high_excluded_from_breakout_reference():
    context = trend()
    current = change(context.bars[-1], high=9999)
    result = decide(change(context, bars=(*context.bars[:-1], current)), AlphaConfig(strategy="A"))
    assert weight(result) > 0
    assert result.earliest_execution_at > context.now


def test_TREND_002_relative_strength_uses_aligned_known_index():
    context = trend()
    index = change(context.benchmark[-1], open=400, high=401, low=399, close=400)
    assert (
        weight(
            decide(
                change(context, benchmark=(*context.benchmark[:-1], index)),
                AlphaConfig(strategy="A"),
            )
        )
        == 0
    )
    unavailable = change(context.benchmark[-1], available_at=context.now + timedelta(seconds=1))
    assert (
        weight(
            decide(
                change(context, benchmark=(*context.benchmark[:-1], unavailable)),
                AlphaConfig(strategy="A"),
            )
        )
        == 0
    )


def test_ORB_001_range_must_be_complete_and_confirmed_by_later_bar():
    context = intraday()
    assert (
        weight(decide(change(context, now=OPEN + timedelta(minutes=5)), AlphaConfig(strategy="B")))
        == 0
    )
    assert weight(decide(context, AlphaConfig(strategy="B"))) > 0


def test_ORB_002_rvol_uses_prior_same_elapsed_time_and_vwap_actual_notional():
    context = intraday()
    baseline = context.volume_baselines[0]
    wrong_time = change(baseline, elapsed_minutes=390)
    assert (
        weight(decide(change(context, volume_baselines=(wrong_time,)), AlphaConfig(strategy="B")))
        == 0
    )
    future = change(baseline, known_at=context.now + timedelta(seconds=1))
    assert (
        weight(decide(change(context, volume_baselines=(future,)), AlphaConfig(strategy="B"))) == 0
    )
    heavy_volume = change(baseline, cumulative_volume=100000)
    assert (
        weight(decide(change(context, volume_baselines=(heavy_volume,)), AlphaConfig(strategy="B")))
        == 0
    )


def test_REV_001_midquote_not_last_trade_drives_deviation():
    context = intraday("C")
    assert weight(decide(context, AlphaConfig(strategy="C"))) > 0
    quote = change(context.quotes[0], bid="99.9", ask="100.1", last_trade=90)
    assert weight(decide(change(context, quotes=(quote,)), AlphaConfig(strategy="C"))) == 0


def test_REV_002_nonfill_and_adverse_selection_remain_in_records():
    context = intraday("C")
    ref = ReferencePortfolio("C", Decimal(10000), costs())
    result = decide(context, AlphaConfig(strategy="C"))
    ref.submit(result, {"005930": Decimal(95)})
    now = context.now + timedelta(seconds=1)
    ref.match(tick(now, bid=95, ask=96), now)
    assert not ref.state.executions and ref.reserve > 0
    ref.expire(context.now + timedelta(minutes=1))
    assert ref.state.orders[0].status == "EXPIRED" and ref.state.orders[0].filled == 0
    assert ref.reserve == 0 and len(ref.state.orders) == 1
    adverse = funded_reference()
    adverse.mark("005930", Decimal(90), OPEN + timedelta(hours=6))
    row = adverse.value(OPEN + timedelta(hours=6))
    assert row.nav < 10000 and adverse.quantity("005930") == 19


def test_EVENT_001_receipt_date_is_not_intraday_publication():
    context = intraday("D")
    event = context.events[0]
    assert event.published_at is None
    assert (
        weight(decide(change(context, now=OPEN - timedelta(seconds=1)), AlphaConfig(strategy="D")))
        == 0
    )
    assert weight(decide(context, AlphaConfig(strategy="D"))) > 0
    with pytest.raises(ValidationError):
        change(event, available_at=OPEN - timedelta(seconds=1))


def test_EVENT_002_corrections_replace_family_and_do_not_duplicate_entry():
    context = intraday("D")
    original = context.events[0]
    correction = change(
        original,
        event_id="corrected",
        revision=1,
        supersedes_id="original",
        observed=80,
        available_at=context.now,
    )
    result = decide(change(context, events=(original, correction)), AlphaConfig(strategy="D"))
    assert weight(result) == 0 and result.feature_evidence[0][1] == ("corrected",)
    duplicate = decide(change(context, events=(original, original)), AlphaConfig(strategy="D"))
    assert weight(duplicate) == 0
    consumed = decide(
        change(context, consumed_event_families=(original.family,)), AlphaConfig(strategy="D")
    )
    assert weight(consumed) == 0


def test_REF_001_independent_reference_books():
    first = funded_reference()
    second = ReferencePortfolio("B", Decimal(10000), costs())
    assert first.quantity("005930") == 19 and second.quantity("005930") == 0
    assert first.nav == Decimal("9997.53") and second.nav == 10000


def test_REF_002_daily_panel_keeps_cash_days_and_unrealized_positions():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.value(OPEN - timedelta(days=1))
    ref.submit(decide(trend(), AlphaConfig(strategy="A")), {"005930": Decimal(130)})
    ref.match(tick(), OPEN + timedelta(seconds=1))
    ref.mark("005930", Decimal(140), OPEN + timedelta(hours=6))
    ref.value(OPEN + timedelta(hours=6))
    ref.value(OPEN + timedelta(days=3, hours=6))
    dates = tuple(row.at.date() for row in ref.state.panel)
    metrics = ref.metrics(dates)
    assert metrics["daily_observations"] == 3
    assert metrics["NET_OPERATING_PNL_KRW"] == "187.53"
    assert ref.state.panel[-1].mark_status == "UNVERIFIED"
    with pytest.raises(ValueError, match="complete common"):
        ref.metrics(dates[:-1])


def test_REF_003_reference_never_posts_to_mock_account(tmp_path):
    with make_engine(tmp_path / "actual.sqlite") as engine:
        before = engine.state
        funded_reference()
        assert engine.state == before


def test_COST_004_single_cost_and_external_opex():
    ref = funded_reference()
    row = ref.value(OPEN + timedelta(hours=6), Decimal(5))
    assert ref.state.costs == Decimal("2.47")
    assert row.nav == Decimal("9992.53")
    metrics = ref.metrics((row.at.date(),))
    assert Decimal(metrics["gross_pnl"]) == 0
    assert Decimal(metrics["after_trading_cost_pnl"]) == Decimal("-2.47")
    assert Decimal(metrics["NET_OPERATING_PNL_KRW"]) == Decimal("-7.47")


def test_ECON_004_synthetic_rows_cannot_approve_economics():
    evidence = DataEvidence(
        strategy="A", source="AUTHORED", origin="SYNTHETIC", rows=100000, resolution="DAILY"
    )
    assert evidence.status == "DATA_BLOCKED" and economic_status(evidence) == "HOLD_DATA"


def test_ECON_005_costs_and_cash_comparison():
    ref = funded_reference()
    ref.mark("005930", Decimal("130.1"), OPEN + timedelta(hours=6))
    row = ref.value(OPEN + timedelta(hours=6), Decimal(20))
    metrics = ref.metrics((row.at.date(),))
    assert Decimal(metrics["gross_pnl"]) == Decimal("1.90")
    assert Decimal(metrics["NET_OPERATING_PNL_KRW"]) == Decimal("-20.57")
    assert Decimal(metrics["cash_excess_krw"]) < 0 and metrics["economic_status"] == "HOLD"


def test_VAL_011_changed_candidate_cannot_inherit_oos():
    config = AlphaConfig(strategy="A")
    plan = ResearchPlan(
        trial_id="candidate",
        config_hash=content_hash(config.model_dump(mode="json")),
        data_hash="SYNTHETIC_HASH",
        research_start=OPEN - timedelta(days=90),
        research_end=OPEN - timedelta(days=60),
        validation_start=OPEN - timedelta(days=59),
        validation_end=OPEN - timedelta(days=30),
        locked_oos_start=OPEN - timedelta(days=29),
        locked_oos_end=OPEN,
        registered_at=OPEN,
        exposures=("AUTHORED_FIXTURE_ALREADY_SEEN",),
    )
    plan.require_version(config, "SYNTHETIC_HASH")
    with pytest.raises(PermissionError):
        plan.require_version(change(config, lookback=21), "SYNTHETIC_HASH")
    with pytest.raises(ValidationError):
        change(plan, oos_authorized=True)


def test_SAFE_003_real_order_and_cancel_remain_disabled():
    for action in (MockBroker().submit_order, MockBroker().cancel_order):
        with pytest.raises(PermissionError):
            action()


def test_real_alpha_snapshot_reaches_existing_mock_risk_oms(tmp_path):
    result = decide(trend(), AlphaConfig(strategy="A"))
    with make_engine(tmp_path / "integration.sqlite") as engine:
        mark(engine, Decimal(130))
        reconcile(engine)
        budget = CapitalBudget(
            budget_id="MOCK_A",
            approved_by="SYNTHETIC_ONLY",
            sleeves=(SleeveBudget(strategy_id="A", weight=".4"),),
        )
        verdict = plan_mock(
            engine,
            (result,),
            budget,
            policy(),
            "alpha-bridge",
            synthetic_expected_gross=Decimal(20),
            execution_cost=Decimal(2),
            uncertainty=Decimal(1),
            fee_buffer=Decimal(5),
        )
        assert verdict.status == "ALLOW" and engine.state.orders[-1].quantity == 7
        assert engine.state.orders[-1].allocations == (("A", 7),)
