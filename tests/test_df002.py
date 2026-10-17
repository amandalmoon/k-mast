"""DF-002 causal/accounting controls. Fixtures are self-authored, not market evidence."""

from decimal import Decimal as D

import pytest

from kmast.alpha.fixtures import trend
from kmast.alpha.models import AlphaConfig, PositionView
from kmast.alpha.rules import decide
from kmast.research.attribution import attribute, exposure_diagnostic
from kmast.research.exploratory import candidate_a, replay
from scripts.collect_data_first import Budget, MarketOnlyWire

from .test_data_first import panel, policy
from .test_km003 import change


def run(rows=None, index=None, **updates):
    r, i = panel()
    return replay(rows or r, index or i, policy(**updates), "ALPHA_A")


def test_causal_001_future_append_preserves_full_intent_identity():
    rows, index = panel()
    small = run(rows[:27], index[:27])
    full = run(rows, index)
    assert small["signal_log"] == full["signal_log"][: len(small["signal_log"])]


def test_causal_002_future_correction_preserves_evidence_and_reason():
    rows, index = panel()
    future = change(
        rows[-1], record_id="CORRECTED_FUTURE", high=rows[-1].high + 10, close=rows[-1].close + 10
    )
    before, after = run(), run(rows[:-1] + (future,), index)
    assert before["signal_log"] == after["signal_log"]


def test_causal_003_final_volume_is_not_opening_fill_eligibility():
    rows, index = panel()
    changed = rows[:22] + (change(rows[22], volume=0, turnover=0),) + rows[23:]
    a, b = run(), run(changed, index)
    assert a["signal_log"][:2] == b["signal_log"][:2]
    assert a["signal_log"][1]["executions"]
    assert b["signal_log"][0]["opening_confidence"] == "UNVERIFIED"


def test_causal_004_current_open_and_close_do_not_enter_decision():
    rows, index = panel()
    changed = rows[:22] + (change(rows[22], open=300, close=301, high=302, low=299),) + rows[23:]
    a, b = run(), run(changed, index)
    assert a["signal_log"][1]["executions"]
    assert a["signal_log"][1]["intent"] == b["signal_log"][1]["intent"]
    assert a["signal_log"][1]["lineage"] == b["signal_log"][1]["lineage"]
    assert not b["signal_log"][1]["executions"]  # modeled gap misses prior-close limit


def test_causal_005_adjusted_execution_and_duplicate_actions_not_injected():
    rows, index = panel()
    with pytest.raises(ValueError):
        run(
            (change(rows[0], price_basis="ADJUSTED", adjustment_asof=rows[0].available_at),)
            + rows[1:],
            index,
        )
    assert run()["corporate_action_total_return_pnl"] is None
    assert run()["reference_state"]["dividends"] == "0"


def test_exec_audit_001_exact_same_input_replay():
    assert run() == run()


def test_position_state_is_part_of_signal_identity():
    from datetime import timedelta

    context = trend()
    config = AlphaConfig(strategy="A")
    old = PositionView(
        symbol="005930", weight=".1", entry_price=100, exit_deadline=context.now + timedelta(days=1)
    )
    flat = candidate_a(context, "005930", config, None, 1)
    held = candidate_a(context, "005930", config, old, 1)
    assert flat.snapshot.snapshot_id != held.snapshot.snapshot_id


def test_exec_audit_002_fraction_floor_expiry_and_zero_capacity():
    rows, index = panel()
    result = replay(rows, index, policy(capital=1000, fill_fraction=".5"), "HOLD_25")
    orders = result["reference_state"]["orders"]
    assert orders and all(
        o["quantity"] == 1 and o["filled"] == 0 and o["status"] == "EXPIRED" for o in orders
    )
    assert result["executions"] == 0
    assert all(s["prior_volume_capacity"] == 0 for s in result["signal_log"])


def test_exec_audit_003_availability_submission_execution_clocks():
    result = run()
    for s in result["signal_log"]:
        assert s["lineage"]["last_available_at"] <= s["decision_at"]
        for order in s["orders"]:
            assert (
                s["decision_at"]
                == order["submitted_at"]
                < order["executable_after"]
                < order["expires_at"]
            )
        for e in s["executions"]:
            assert s["decision_at"] < e[1]


def test_pnl_audit_001_cost_is_counted_once_with_slip_embedded():
    r = run()
    a = attribute(r)["summary"]
    assert D(a["explicit_cost"]) == D(a["commission"]) + D(a["tax"])
    assert D(a["gross_before_modeled_slippage"]) - D(a["embedded_slippage"]) - D(
        a["explicit_cost"]
    ) - D(a["operating_cost"]) == D(a["project_net"])


def test_pnl_audit_002_daily_nav_bridge_and_final_pnl():
    r = run()
    a = attribute(r)
    assert sum((D(d["nav_change"]) for d in a["daily"]), D(0)) == D(r["scenario_project_net_pnl"])
    assert abs(D(a["summary"]["time_weighted_return"]) - D(r["return_after_scenario_cost"])) < D(
        "1e-24"
    )


def test_pnl_audit_003_unrealized_and_opportunity_not_cash_profit():
    r = run(fill_fraction=".5")
    a = attribute(r)["summary"]
    assert abs(
        D(a["realized_net_allocated_cost"])
        + D(a["unrealized_net_entry_fee"])
        - D(a["operating_cost"])
        - D(a["project_net"])
    ) < D("1e-18")
    diagnostic = exposure_diagnostic(r)
    assert diagnostic["used_in_signal"] is False and diagnostic["cost_adjusted_pnl"] is None


def test_trade_excursions_exclude_close_after_opening_exit():
    result = run()
    analysis = attribute(result)
    assert analysis["fifo_trades"]
    for trade in analysis["fifo_trades"]:
        start, end = trade["entry_at"][:10], trade["exit_at"][:10]
        price = D(trade["entry_price"])
        observed = [
            D(row["close"]) / price - 1
            for row in result["observed_price_log"]
            if start <= row["day"] < end
        ]
        observed += [D(0), D(trade["exit_price"]) / price - 1]
        assert D(trade["close_mfe_proxy"]) == max(observed)
        assert D(trade["close_mae_proxy"]) == min(observed)
        assert trade["true_intraday_mfe"] is None and trade["true_intraday_mae"] is None


def test_bench_001_common_window_capital_cost_and_preregistered_trend():
    rows, index = panel()
    results = [
        replay(rows, index, policy(), m)
        for m in ("ALPHA_A", "CASH", "BUY_HOLD", "HOLD_25", "TREND_25")
    ]
    assert (
        len(
            {
                (
                    r["evaluation_start"],
                    r["evaluation_end"],
                    r["capital"],
                    r["days"],
                    r["recurring_operating_cost"],
                )
                for r in results
            }
        )
        == 1
    )
    assert all(r["policy"] == results[0]["policy"] for r in results)
    assert all(D(s["target_weight"]) in {D(0), D(".25")} for s in results[-1]["signal_log"])


def test_bench_002_posthoc_matching_is_not_confirmatory():
    diagnostic = exposure_diagnostic(run())
    assert "POSTHOC" in diagnostic["label"] and diagnostic["risk_equivalence"] == "NOT_PROVEN"
    assert attribute(run())["summary"]["confirmatory_status"] == "NOT_EXECUTED"


def test_safe_010_actual_orders_and_cancel_denied(tmp_path):
    wire = MarketOnlyWire(None, Budget(tmp_path / "budget.json"))
    for path in ("order-cash", "order-rvsecncl"):
        with pytest.raises(PermissionError):
            wire.send(None, "POST", "/uapi/domestic-stock/v1/trading/" + path, {}, {})
    assert not (tmp_path / "budget.json").exists()


@pytest.mark.parametrize("weight,entry,days", [(".1", 100, 1), (".25", 200, 1), (".2", 100, -1)])
def test_frozen_feature_and_position_decisions_equivalent(weight, entry, days):
    from datetime import timedelta

    context = trend()
    config = AlphaConfig(strategy="A")
    position = PositionView(
        symbol="005930",
        weight=weight,
        entry_price=entry,
        exit_deadline=context.now + timedelta(days=days),
    )
    expected = decide(change(context, positions=(position,)), config)
    actual = candidate_a(change(context, universe=()), "005930", config, position, 1)
    assert actual.snapshot.intents[0].target_weight == expected.snapshot.intents[0].target_weight
    assert actual.reasons == expected.reasons
    assert actual.feature_evidence == expected.feature_evidence
