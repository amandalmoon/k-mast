"""DF003 controls use authored fixtures, never actual market-performance evidence."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from kmast.alpha.fixtures import trend
from kmast.alpha.models import AlphaConfig, PositionView
from kmast.alpha.rules import features
from kmast.research.exploratory import candidate_a, replay
from kmast.research.holding_analysis import analyze_holding, beta, exposure_pair
from kmast.research.hypotheses import HoldingController, hypothesis_replay, reduction_status
from scripts.collect_data_first import Budget, MarketOnlyWire

from .test_data_first import panel, policy
from .test_km003 import change


def shifted(ctx, days):
    delta = timedelta(days=days)

    def bars(rows):
        return tuple(
            change(b, start=b.start + delta, end=b.end + delta, available_at=b.available_at + delta)
            for b in rows
        )

    return change(
        ctx,
        now=ctx.now + delta,
        session_open=ctx.session_open + delta,
        session_close=ctx.session_close + delta,
        next_session_open=ctx.next_session_open + delta,
        bars=bars(ctx.bars),
        benchmark=bars(ctx.benchmark),
        expected_daily_ends=tuple(d + delta for d in ctx.expected_daily_ends),
    )


def test_protocol_sealed_trial_budget_and_no_grid():
    root = Path(__file__).resolve().parents[1]
    raw = (root / "artifacts/df003/DF003_PROTOCOL.json").read_bytes()
    seal = json.loads((root / "artifacts/df003/protocol-seal.json").read_bytes())
    protocol = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == seal["protocol_sha256"]
    assert protocol["trials"]["total_references"] == 216
    assert protocol["trials"]["parameter_grid_combinations_per_candidate"] == 1
    assert protocol["data_status"] == "PREVIOUSLY_CONSUMED_EXPLORATORY_SURVIVOR_SAMPLE"


@pytest.mark.parametrize("fraction", ["1", ".5"])
def test_a0_is_exact_frozen_v3_including_partial(fraction):
    rows, index = panel()
    p = policy(fill_fraction=fraction)
    assert hypothesis_replay(rows, index, p, "A0") == replay(rows, index, p, "ALPHA_A")


def test_calendar_vs_observed_sessions_across_weekend():
    rows, index = panel()
    a0 = hypothesis_replay(rows, index, policy(), "A0")
    a1 = hypothesis_replay(rows, index, policy(), "A1")

    def first(r):
        return next(e[1][:10] for e in r["reference_state"]["executions"] if e[3] < 0)

    assert first(a0) == "2026-10-06" and first(a1) == "2026-10-08"
    assert any(
        s.get("holding_rule_trace", {}).get("reason") == "OBSERVED_SESSION_5_EXIT"
        for s in a1["signal_log"]
    )


def test_special_excluded_observation_does_not_increment_session_count():
    ctx = trend()
    delta = (__import__("datetime").date(2026, 1, 2) - ctx.bars[-1].end.date()).days
    special = shifted(ctx, delta)
    position = PositionView(
        symbol="005930",
        weight=".1",
        entry_price=100,
        exit_deadline=special.now + timedelta(days=99),
    )
    controller = HoldingController("A1")
    controller(special, "005930", AlphaConfig(strategy="A"), position, 1)
    assert controller.completed == 0


def test_ma_candidate_rejects_unavailable_future_bar():
    ctx = trend()
    last = change(ctx.bars[-1], available_at=ctx.now + timedelta(seconds=1))
    with pytest.raises(ValueError, match="future"):
        HoldingController("A2")(
            change(ctx, bars=ctx.bars[:-1] + (last,)), "005930", AlphaConfig(strategy="A"), None, 1
        )


def test_atr_uses_completed_history_and_preserves_basic_stop():
    ctx = trend()
    cfg = AlphaConfig(strategy="A")
    position = PositionView(
        symbol="005930", weight=".1", entry_price=100, exit_deadline=ctx.now + timedelta(days=99)
    )
    a3 = HoldingController("A3")
    a3(ctx, "005930", cfg, position, 1)
    later = shifted(ctx, 1)
    last = change(later.bars[-1], open=121, close=121, high=122, low=120)
    later = change(later, bars=later.bars[:-1] + (last,))
    trailing = a3(later, "005930", cfg, position, 2)
    ma = HoldingController("A2")(later, "005930", cfg, position, 2)
    assert trailing.reasons[0][1] == "ATR20_X3_EXIT"
    assert trailing.snapshot.intents[0].target_weight == 0 < ma.snapshot.intents[0].target_weight
    assert a3.trace[-1]["input_last_date"] < later.next_session_open.date().isoformat()
    stopped = change(position, entry_price=200)
    assert (
        HoldingController("A3")(ctx, "005930", cfg, stopped, 1).reasons[0][1] == "BASIC_STOP_EXIT"
    )


def test_maximum_observed_sessions_prevents_unbounded_holding():
    ctx = trend()
    controller = HoldingController("A2")
    cfg = AlphaConfig(strategy="A")
    position = PositionView(
        symbol="005930", weight=".1", entry_price=100, exit_deadline=ctx.now + timedelta(days=99)
    )
    offsets = [i for i in range(32) if (ctx.bars[-1].end + timedelta(days=i)).weekday() < 5]
    for n, offset in enumerate(offsets[:20], 1):
        result = controller(shifted(ctx, offset), "005930", cfg, position, n)
    assert controller.completed == 20
    assert result.reasons[0][1] == "OBSERVED_SESSION_20_EXIT"


def test_entry_control_changes_only_flat_entry_predicate():
    ctx = trend()
    last = change(ctx.bars[-1], open="119.5", close="119.5", high="120.5", low="118.5")
    ctx = change(ctx, bars=ctx.bars[:-1] + (last,))
    cfg = AlphaConfig(strategy="A")
    baseline = HoldingController("A1")(ctx, "005930", cfg, None, 1)
    control = HoldingController("T1")(ctx, "005930", cfg, None, 1)
    assert baseline.snapshot.intents[0].target_weight == 0
    assert control.snapshot.intents[0].target_weight == features(ctx, cfg, "005930")[1] > 0
    assert baseline.snapshot.intents[0].evidence_refs == control.snapshot.intents[0].evidence_refs
    assert baseline.earliest_execution_at == control.earliest_execution_at


def test_exit_rule_does_not_change_entry_size_or_frozen_candidate():
    ctx = trend()
    cfg = AlphaConfig(strategy="A")
    targets = [
        HoldingController(c)(ctx, "005930", cfg, None, 1).snapshot.intents[0].target_weight
        for c in ("A0", "A1", "A2", "A3")
    ]
    assert len(set(targets)) == 1
    assert (
        candidate_a(ctx, "005930", cfg, None, 1).snapshot.intents[0].model_version == "candidate-v1"
    )


def test_no_original_callback_global_mutation():
    original = replay.__globals__["candidate_a"]
    rows, index = panel()
    hypothesis_replay(rows, index, policy(), "A3")
    assert replay.__globals__["candidate_a"] is original


def test_future_append_preserves_hypothesis_decisions():
    rows, index = panel()
    small = hypothesis_replay(rows[:28], index[:28], policy(), "A3")
    full = hypothesis_replay(rows, index, policy(), "A3")
    assert small["signal_log"] == full["signal_log"][: len(small["signal_log"])]


def test_same_capital_cost_window_but_actual_exposure_not_target():
    rows, index = panel()
    values = [hypothesis_replay(rows, index, policy(), c) for c in ("A0", "A1", "A2", "A3")]
    assert (
        len(
            {
                (v["capital"], v["evaluation_start"], v["days"], v["recurring_operating_cost"])
                for v in values
            }
        )
        == 1
    )
    assert all(v["policy"] == values[0]["policy"] for v in values)
    a = analyze_holding(values[0], "A0")
    assert any(D(day["actual_close_weight"]) != D(day["target_weight"]) for day in a["daily"])


def test_partial_one_share_and_pending_order_are_different():
    rows, index = panel()
    p = policy(capital=1000, fill_fraction=".5")
    r = replay(rows, index, p, "HOLD_25")
    assert r["executions"] == 0 and all(
        o["status"] == "EXPIRED" for o in r["reference_state"]["orders"]
    )
    status = reduction_status(True, 1, 0, "UNKNOWN", forced=True)
    assert status["status"] == "RISK_REDUCTION_HOLD" and status["remaining_quantity"] == 1
    assert status["pending_quantity"] == 0 and status["automatic_residual_fill"] is False


def test_partial_sell_resubmission_and_expiry_leave_one_real_share():
    from kmast.alpha.reference import ReferencePortfolio, RefLot, SimCosts, Tick, update

    ctx = trend()
    book = ReferencePortfolio(
        "A",
        D(10000),
        SimCosts(
            version="AUTHORED_PARTIAL",
            fee_bps=0,
            sell_tax_bps=0,
            slippage_bps=0,
            max_participation=1,
        ),
    )
    book.state = update(
        book.state,
        cash=D(9700),
        lots=(RefLot(symbol="005930", quantity=3, unit_cost=100, at=ctx.now - timedelta(days=1)),),
    )
    book.mark("005930", D(100), ctx.now)
    for i in range(4):
        now = shifted(ctx, i)
        pos = PositionView(
            symbol="005930",
            weight=".03",
            entry_price=100,
            exit_deadline=ctx.now - timedelta(days=1),
        )
        signal = candidate_a(now, "005930", AlphaConfig(strategy="A"), pos, i + 1)
        book.submit(signal, {"005930": D(100)})
        at = now.next_session_open + timedelta(seconds=1)
        capacity = int(book.quantity("005930") * D(".5"))
        book.match(
            Tick(
                identity=f"AUTHORED-{i}",
                symbol="005930",
                at=at,
                available_at=at,
                bid=100,
                ask=100,
                available_quantity=capacity,
                executable=True,
            ),
            at,
        )
        book.expire(now.next_session_open + timedelta(minutes=1))
    assert book.quantity("005930") == 1 and len(book.state.executions) == 2
    assert all(o.status == "EXPIRED" for o in book.state.orders)
    assert not any(o.status in {"OPEN", "PARTIAL"} for o in book.state.orders)
    assert (
        reduction_status(True, 1, 0, "MODEL_ONLY", forced=True)["status"] == "RISK_REDUCTION_HOLD"
    )


def test_halted_tick_does_not_fill_even_with_positive_capacity():
    from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick

    ctx = trend()
    signal = candidate_a(ctx, "005930", AlphaConfig(strategy="A"), None, 1)
    book = ReferencePortfolio(
        "A",
        D(10000),
        SimCosts(
            version="AUTHORED_HALT", fee_bps=0, sell_tax_bps=0, slippage_bps=0, max_participation=1
        ),
    )
    book.submit(signal, {"005930": D(130)})
    at = ctx.next_session_open + timedelta(seconds=1)
    book.match(
        Tick(
            identity="AUTHORED_HALT",
            symbol="005930",
            at=at,
            available_at=at,
            bid=130,
            ask=130,
            available_quantity=1000,
            executable=False,
        ),
        at,
    )
    assert not book.state.executions and book.quantity("005930") == 0


@pytest.mark.parametrize(
    "state,executable", [("HALTED", False), ("UNKNOWN", None), ("MODEL_ONLY", None)]
)
def test_halt_unknown_and_force_reduction_never_guarantee_fill(state, executable):
    s = reduction_status(True, 1, 1, state, forced=True)
    assert s["actual_executable"] is executable and s["status"] == "RISK_REDUCTION_HOLD"
    assert s["actual_order_calls"] == 0


def test_costs_single_count_and_no_oos_promotion():
    rows, index = panel()
    r = hypothesis_replay(rows, index, policy(), "A2")
    s = analyze_holding(r, "A2")["summary"]
    assert D(s["gross_before_modeled_slippage"]) - D(s["embedded_slippage"]) - D(
        s["explicit_cost"]
    ) - D(s["operating_cost"]) == D(s["project_net"])
    assert (
        s["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and s["confirmatory_status"] == "NOT_EXECUTED"
    )
    assert r["live_status"] == "LIVE_NOT_APPROVED"


def test_posthoc_exposure_control_never_allocates_and_zero_is_unknown():
    a = dict(average_close_exposure=".1", cash_excess="100")
    b = dict(average_close_exposure=".2", cash_excess="100")
    p = exposure_pair(a, b)
    assert p["a_cash_excess_scaled"] == "100" and p["b_cash_excess_scaled"] == "50"
    assert p["label"] == "POSTHOC_DIAGNOSTIC" and not p["allocation_feedback"]
    assert (
        exposure_pair(dict(average_close_exposure="0", cash_excess="0"), b)["a_cash_excess_scaled"]
        is None
    )
    assert beta([D(1), D(2)], [D(0), D(0)]) is None


def test_preservation_manifest_covers_v2_v3_and_frozen_sources():
    root = Path(__file__).resolve().parents[1]
    proof = json.loads((root / "artifacts/df003/preflight.json").read_bytes())
    assert proof["v2"] == 72 and proof["v3"] == 90
    for name in (
        "src/kmast/alpha/rules.py",
        "src/kmast/research/exploratory.py",
        "src/kmast/research/attribution.py",
    ):
        assert (
            hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            == proof["frozen_text_hashes"][name]
        )
    assert sum("/df002-v3-reviewed/" in p for p in proof["protected_hashes"]) == 90


def test_broker_order_cancel_and_unregistered_rules_blocked(tmp_path):
    wire = MarketOnlyWire(None, Budget(tmp_path / "budget.json"))
    for route in ("order-cash", "order-rvsecncl"):
        with pytest.raises(PermissionError):
            wire.send(None, "POST", "/uapi/domestic-stock/v1/trading/" + route, {}, {})
    with pytest.raises(ValueError):
        HoldingController("A99")
