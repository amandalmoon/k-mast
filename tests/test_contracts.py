import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from kmast.brokers.interfaces import MockBroker
from kmast.core.clock import ReplayClock
from kmast.core.config import BrokerConfig, RuntimeConfig, load_config
from kmast.core.contracts import (
    CapitalBudget,
    CashResidual,
    Forecast,
    PerformanceBridge,
    PortfolioDecision,
    PortfolioTarget,
    ReturnUnits,
    RiskDecision,
    RiskLimitSnapshot,
    SleeveBudget,
    SnapshotStore,
    StrategyTarget,
    TargetSnapshot,
    validate_optimizer_inputs,
)
from kmast.core.events import PointInTime, PublicEvent
from kmast.core.study import StudyContract
from kmast.data.normalization import normalize
from kmast.data.replay import ReplayPolicy, replay

from .conftest import NOW

ROOT = Path(__file__).resolve().parents[1]


def change(model, **updates):
    return type(model).model_validate(model.model_dump() | updates)


def snapshot(intent, **updates):
    return TargetSnapshot.model_validate(
        dict(
            strategy_id="A",
            snapshot_id="s1",
            revision=1,
            expected_symbols=("SYNTHETIC",),
            intents=(intent,),
        )
        | updates
    )


def units(**updates):
    return ReturnUnits.model_validate(
        dict(
            horizon=timedelta(days=1),
            capital_basis="REFERENCE_NAV",
            capital_policy_id="fixed",
            valuation_calendar="KRX_CLOSE",
            cost_model_version="synthetic-v1",
            risk_basis="REFERENCE_NAV",
            ledger_type="REFERENCE",
        )
        | updates
    )


def bridge(**updates):
    return PerformanceBridge.model_validate(
        dict(
            account_snapshot_id="synthetic",
            interval_start=NOW,
            interval_end=NOW + timedelta(days=1),
            starting_capital_krw=1000,
            ending_nav_krw=1100,
            gross_market_pnl=100,
        )
        | updates
    )


def decision(**updates):
    return PortfolioDecision.model_validate(
        dict(
            decision_id="p",
            as_of=NOW,
            policy_id="PBASE_FIXED",
            target_version="v1",
            expected_gross_increment_krw=10,
            incremental_execution_cost_krw=6,
            uncertainty_buffer_krw=5,
            cost_model_id="synthetic",
            risk_snapshot_id="r",
            benchmark_id="hold",
            risk_check="PASS",
            action="HOLD_TARGET",
            reason="TEST",
        )
        | updates
    )


def test_SEM_01_negative_weight(intent):
    with pytest.raises(ValidationError):
        change(intent, target_weight="-0.1")


def test_SEM_02_sum_over_one(intent):
    other = change(intent, intent_id="j", symbol="OTHER", target_weight="0.6")
    with pytest.raises(ValidationError):
        snapshot(intent, expected_symbols=("SYNTHETIC", "OTHER"), intents=(intent, other))


def test_SEM_03_snapshot_revision_atomicity(intent):
    store = SnapshotStore()
    original = snapshot(intent)
    store.replace(original, NOW)
    store.replace(original, NOW)
    for updates in ({"revision": 2}, {"snapshot_id": "s2"}, {"expected_symbols": ("MISSING",)}):
        with pytest.raises(ValidationError):
            snapshot(intent, **updates)
    conflicting = snapshot(change(intent, target_weight=0))
    with pytest.raises(ValueError):
        store.replace(conflicting, NOW)
    assert store.current("A") == original
    new = snapshot(
        change(intent, target_snapshot_id="s2", revision=2, target_weight=0),
        snapshot_id="s2",
        revision=2,
    )
    store.replace(new, NOW)
    assert store.current("A") == new
    with pytest.raises(ValueError):
        store.replace(original, NOW)


def test_SEM_04_absolute_quantity_and_zero(intent):
    targets = tuple(
        StrategyTarget(strategy_id=s, symbol="X", target_qty=q, budget_id="b", revision=1)
        for s, q in (("A", 100), ("B", 50), ("C", 20))
    )
    target = PortfolioTarget(
        symbol="X",
        aggregate_target_qty=170,
        sleeve_targets=targets,
        snapshot_id="s",
        target_version="v",
    )
    assert target.explanatory_delta(200) == -30
    assert change(intent, target_weight=0).target_weight == 0
    with pytest.raises(ValidationError):
        change(intent, target_exposure=-30)


def test_DATA_01_naive_datetime(event):
    for field in (
        "event_time",
        "received_at",
        "available_at",
        "acquired_at",
        "training_cutoff",
        "label_known_at",
    ):
        with pytest.raises(ValidationError):
            change(event, **{field: NOW.replace(tzinfo=None)})


def test_DATA_02_future_information(event, intent):
    future = change(event, available_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError):
        future.require_available(NOW)
    with pytest.raises(ValidationError):
        change(intent, available_at=NOW + timedelta(seconds=1))


def test_DATA_03_duplicates(event):
    result = replay(
        (event, event), ReplayPolicy(config_version="c", code_version="v"), ReplayClock(NOW)
    )
    assert result.events == (event,)
    assert len(result.duplicate_ids) == 1
    with pytest.raises(ValueError):
        replay((event, change(event, price=1)), result.policy, ReplayClock(NOW))


def test_COST_01_unknown_cost_rejected():
    unknown = units(cost_basis="UNKNOWN")
    with pytest.raises(ValueError):
        validate_optimizer_inputs(
            (Forecast(units=unknown, expected_return=1, uncertainty=0),), unknown
        )


def test_COST_02_embedded_execution_not_subtracted():
    pnl = bridge(actual_exec_effect_diagnostic=-20, unfilled_opportunity_cost_diagnostic=30)
    assert pnl.net_operating_pnl_krw == 100
    with pytest.raises(ValidationError):
        bridge(estimated_slippage=20)
    with pytest.raises(ValidationError):
        bridge(ending_nav_krw=1080, actual_exec_effect_diagnostic=-20)


def test_PORT_01_capital_and_cash(intent):
    budget = CapitalBudget(budget_id="b", sleeves=(SleeveBudget(strategy_id="A", weight="0.6"),))
    cash = CashResidual.from_targets(budget, (snapshot(intent),))
    assert cash.central_reserve == Decimal("0.4")
    assert cash.sleeve_uninvested == (("A", Decimal("0.30")),)
    assert cash.central_reserve + cash.sleeve_uninvested[0][1] + Decimal("0.3") == 1
    with pytest.raises(ValidationError):
        CapitalBudget(
            budget_id="b",
            sleeves=(
                SleeveBudget(strategy_id="A", weight="0.6"),
                SleeveBudget(strategy_id="B", weight="0.6"),
            ),
        )


def test_PORT_03_hold_and_risk_reduction():
    assert decision().action == "HOLD_TARGET"
    with pytest.raises(ValidationError):
        decision(action="CHANGE_TARGET")
    assert (
        decision(
            action="RISK_REDUCTION", expected_gross_increment_krw=-100, risk_check="FAIL"
        ).action
        == "RISK_REDUCTION"
    )
    assert (
        decision(action="CHANGE_TARGET", expected_gross_increment_krw=12).action == "CHANGE_TARGET"
    )
    with pytest.raises(ValidationError):
        decision(action="CHANGE_TARGET", expected_gross_increment_krw=999, risk_check="FAIL")


@pytest.mark.parametrize(
    "updates",
    [
        {"horizon": timedelta(minutes=10)},
        {"capital_basis": "SLEEVE_NAV"},
        {"cost_basis": "NET_REALIZED_AFTER_EXECUTION_COST"},
        {"capital_policy_id": "other"},
        {"risk_basis": "ACCOUNT_NAV"},
        {"cost_model_version": "other"},
        {"valuation_calendar": "OTHER"},
        {"ledger_type": "ATTRIBUTION"},
    ],
)
def test_PORT_04_common_units(updates):
    with pytest.raises(ValueError):
        validate_optimizer_inputs(
            (Forecast(units=units(**updates), expected_return=1, uncertainty=0),), units()
        )


def test_PORT_05_unapproved_and_breached_risk():
    limits = RiskLimitSnapshot(
        snapshot_id="r", account_version="a", expires_at=NOW + timedelta(days=1)
    )
    risk = RiskDecision(
        decision_id="d",
        target_version="v",
        max_qty=1,
        expires_at=limits.expires_at,
        reasons=("TEST",),
        account_version="a",
        risk_snapshot=limits,
        hard_limits_passed=True,
    )
    with pytest.raises(PermissionError):
        risk.require_contract_approval(NOW, "a", "v")
    approved = change(
        limits, approved_by="synthetic-test", stress_loss_limit=1, expected_shortfall_limit=1
    )
    valid = change(risk, risk_snapshot=approved)
    valid.require_contract_approval(NOW, "a", "v")
    for when, account, version in (
        (NOW, "old", "v"),
        (NOW, "a", "old"),
        (limits.expires_at, "a", "v"),
    ):
        with pytest.raises(PermissionError):
            valid.require_contract_approval(when, account, version)
    with pytest.raises(PermissionError):
        change(valid, hard_limits_passed=False).require_contract_approval(NOW, "a", "v")


def test_PNL_01_flows_are_not_profit():
    assert bridge(ending_nav_krw=1600, external_net_flow=500).net_operating_pnl_krw == 100
    assert (
        bridge(gross_market_pnl=0, ending_nav_krw=1500, external_net_flow=500).net_operating_pnl_krw
        == 0
    )
    with pytest.raises(ValidationError):
        bridge(internal_net_transfer=100)


def test_PNL_02_single_recognition():
    pnl = bridge(
        cash_interest=10,
        dividend_income=20,
        explicit_fees_and_taxes=5,
        recurring_operating_costs=15,
        ending_nav_krw=1110,
    )
    assert pnl.net_operating_pnl_krw == 110
    with pytest.raises(ValidationError):
        change(pnl, ledger_type="REFERENCE")
    with pytest.raises(ValidationError):
        change(pnl, ending_nav_krw=1095)


def test_CFG_01_fail_closed_defaults():
    assert not RuntimeConfig().order_enabled and not RuntimeConfig().live_enabled
    for mode in ("RESEARCH", "SHADOW", "PAPER"):
        cfg = load_config(ROOT / "configs" / f"{mode.lower()}.yaml")
        assert not cfg.order_enabled and not cfg.live_enabled
        for flag in ("order_enabled", "live_enabled"):
            with pytest.raises(ValidationError):
                change(cfg, **{flag: True})
    with pytest.raises(ValueError):
        load_config(ROOT / "configs/live.yaml")
    with pytest.raises(ValidationError):
        RuntimeConfig(mode="LIVE")
    for operation in (MockBroker().submit_order, MockBroker().cancel_order):
        with pytest.raises(PermissionError):
            operation()


def test_CFG_02_environment_isolation():
    raw = dict(
        environment="PAPER",
        credential_environment="PAPER",
        account_environment="PAPER",
        account_ref="synthetic",
        endpoint="https://openapivts.koreainvestment.com:29443",
    )
    BrokerConfig.model_validate(raw)
    for updates in (
        {"credential_environment": "LIVE"},
        {"account_environment": "LIVE"},
        {"endpoint": "https://openapi.koreainvestment.com:9443"},
    ):
        with pytest.raises(ValidationError):
            BrokerConfig.model_validate(raw | updates)


def test_SEC_01_secret_outputs(tmp_path, caplog):
    secret = "SYNTHETIC_SECRET_DO_NOT_LOG"
    config = BrokerConfig(
        environment="PAPER",
        credential_environment="PAPER",
        account_environment="PAPER",
        account_ref=secret,
        app_key=secret,
        app_secret=secret,
        endpoint="https://openapivts.koreainvestment.com:29443",
    )
    assert secret not in repr(config) + config.model_dump_json()
    path = tmp_path / "invalid.yaml"
    path.write_text(f"unknown: {secret}\n", encoding="utf-8")
    with pytest.raises(ValueError) as err:
        load_config(path)
    assert secret not in str(err.value) + caplog.text


def test_ARCH_01_strategy_dependency_boundary():
    allowed = {"typing", "kmast.core.contracts", "kmast.core.events"}
    files = list((ROOT / "src/kmast/strategies").glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec", "open", "compile"}
    assert MockBroker().read("quote")["source"] == "SYNTHETIC_MOCK"


def test_REPLAY_01_deterministic(event):
    policy = ReplayPolicy(config_version="c", code_version="v")
    a = replay((event, event), policy, ReplayClock(NOW))
    b = replay((normalize(event.model_dump()), event), policy, ReplayClock(NOW))
    assert a == b
    assert (
        replay((event, event), change(policy, config_version="c2"), ReplayClock(NOW)).result_hash
        != a.result_hash
    )


def test_VAL_08_no_implicit_economic_approval():
    study = StudyContract()
    assert study.g3_status() == "HOLD" and study.missing_economic_fields()
    for key in ("optimizer_approved", "live_approved"):
        with pytest.raises(ValidationError):
            change(study, **{key: True})


def test_publication_bounds_no_invented_timestamp():
    raw = dict(
        event_id="p",
        event_type="DISCLOSURE",
        first_seen_at=NOW,
        usable_at=NOW,
        revision_id="r",
        availability_method="OBSERVED_LIVE",
    )
    with pytest.raises(ValidationError):
        PublicEvent.model_validate(raw)
    event = PublicEvent.model_validate(
        raw | {"published_lower": NOW - timedelta(days=1), "published_upper": NOW}
    )
    assert event.published_at is None
    event.require_available(NOW)
    with pytest.raises(ValueError):
        event.require_available(NOW - timedelta(seconds=1))


def test_historical_acquisition_and_label_maturity(event):
    historical = change(
        event,
        received_at=NOW + timedelta(days=100),
        acquired_at=NOW + timedelta(days=100),
        availability_method="DOCUMENTED_RELEASE_PLUS_DELAY",
        availability_evidence="synthetic-release",
    )
    historical.require_available(NOW)
    assert historical.acquired_at > historical.available_at
    lineage = PointInTime(
        availability_method="OBSERVED_LIVE",
        training_cutoff=NOW,
        label_known_at=NOW + timedelta(days=1),
        fold_id="f",
    )
    with pytest.raises(ValueError):
        lineage.require_mature_label()
    change(lineage, label_known_at=NOW).require_mature_label()


def test_corrections_do_not_rewrite_past(event):
    later = NOW + timedelta(seconds=1)
    correction = change(
        event,
        event_id="e2",
        revision=1,
        supersedes_id="e1",
        received_at=later,
        available_at=later,
        price=2,
    )
    policy = ReplayPolicy(config_version="c", code_version="v")
    with pytest.raises(ValueError):
        replay((correction, event), policy, ReplayClock(NOW))
    result = replay((correction, event), policy, ReplayClock(later))
    assert result.events == (event, correction)
    with pytest.raises(ValueError):
        replay((correction,), policy, ReplayClock(later))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1.01"])
def test_nonfinite_or_excess_weight(intent, value):
    with pytest.raises(ValidationError):
        change(intent, target_weight=value)


def test_risk_budget_baseline_schema():
    with pytest.raises(ValidationError):
        CapitalBudget(
            budget_id="b",
            policy_id="PBASE_RISK",
            sleeves=(SleeveBudget(strategy_id="A", weight="0.2"),),
        )
    budget = CapitalBudget(
        budget_id="b",
        policy_id="PBASE_RISK",
        sleeves=(
            SleeveBudget(strategy_id="A", weight="0.2", risk_budget="0.5", capital_cap="0.4"),
        ),
    )
    assert budget.cash_residual == Decimal("0.8")
