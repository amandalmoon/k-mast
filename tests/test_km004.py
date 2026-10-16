from datetime import timedelta
from decimal import Decimal as D

import pytest

from kmast.brokers.interfaces import MockBroker
from kmast.core.contracts import ReturnUnits
from kmast.data.store import scrub
from kmast.portfolio.allocation import (
    ReturnSeries,
    RiskSettings,
    freeze_mock_fixed,
    risk_candidate,
    variance_and_rc,
)
from kmast.portfolio.data_gate import (
    ResearchDataGate,
    economic_gate,
    policy_to_keep,
    require_research,
)
from kmast.portfolio.demo import NOW, run
from kmast.portfolio.rebalance import RebalanceInputs, assess


def gate(**updates):
    return ResearchDataGate.model_validate(
        dict(
            strategy="A",
            real_rows=60,
            synthetic_rows=0,
            symbols=("005930",),
            start="2026-07-20",
            end="2026-10-16",
            origin_verified=True,
            hashes_verified=True,
            source_verified=True,
        )
        | updates
    )


def panel():
    units = ReturnUnits(
        horizon=timedelta(days=1),
        capital_basis="REFERENCE_NAV",
        capital_policy_id="FIXED",
        valuation_calendar="SYNTHETIC",
        cost_model_version="V1",
        risk_basis="REFERENCE_NAV",
        ledger_type="REFERENCE",
    )
    times = tuple(NOW - timedelta(days=i) for i in (3, 2, 1))
    return tuple(
        ReturnSeries(
            strategy=s,
            units=units,
            at=times,
            known_at=times,
            returns=tuple(map(D, values)),
            origin="SYNTHETIC",
            evidence_ref="FIXTURE",
        )
        for s, values in (("A", (".01", "-.01", ".02")), ("B", (".02", "-.02", ".01")))
    )


def settings():
    return RiskSettings(
        version="FIXTURE",
        min_samples=3,
        caps=(("A", D(".4")), ("B", D(".4"))),
        risk_budgets=(("A", D(".5")), ("B", D(".5"))),
    )


def decision(**updates):
    return assess(
        RebalanceInputs.model_validate(
            dict(
                identity="FIXTURE",
                at=NOW,
                account_snapshot="SNAP",
                target_version="V1",
                policy="PBASE_FIXED",
                hold_expected_gross_krw=0,
                new_expected_gross_krw=3,
                delay_decay_fraction=0,
                incremental_execution_cost=2,
                uncertainty_buffer=1,
                cost_version="V1",
                hard_risk_passed=True,
                account_and_quotes_fresh=True,
                execution_feasible=True,
            )
            | updates
        )
    )


@pytest.fixture(scope="module")
def joint(tmp_path_factory):
    path = tmp_path_factory.mktemp("joint")
    first = run(path)
    assert run(path) == first
    return first


def test_REALDATA_001():
    assert economic_gate(gate(synthetic_rows=1), True, True).startswith("HOLD_SYNTHETIC")


def test_REALDATA_002():
    assert "HASH_OR_ORIGIN_UNVERIFIED" in gate(hashes_verified=False).blockers()


def test_REALDATA_003():
    s = panel()[0]
    late = s.model_copy(update={"known_at": (NOW + timedelta(days=1),) * 3})
    assert risk_candidate((late, panel()[1]), settings(), NOW).status == "HOLD"


def test_REALDATA_004():
    with pytest.raises(PermissionError):
        require_research(gate(), (), (), NOW)
    assert "PIT_UNIVERSE_EVIDENCE_MISSING" in gate().blockers()


def test_REALDATA_005():
    assert gate(real_rows=0).status == "DATA_BLOCKED"


def test_REALDATA_006():
    assert gate().status == "LICENSE_HOLD"
    assert gate(license_evidence="SCOPED").status == "DATA_PARTIAL"


def test_PORT_007():
    p = risk_candidate(panel(), settings(), NOW)
    assert sum(w for _, w in p.weights) + p.cash_weight == 1
    assert p.cash_weight >= settings().reserve_weight


def test_PORT_008(joint):
    assert joint["unknown_reserve_preserved"] == "164.96"


def test_PORT_009(joint):
    assert joint["account_nav"] == "10014.65"


def test_PORT_010(joint):
    assert joint["difference_due_to_integer_shared_account"] == "0.198"


def test_PORT_011():
    a, b = panel()
    b = b.model_copy(update={"units": b.units.model_copy(update={"horizon": timedelta(days=2)})})
    assert risk_candidate((a, b), settings(), NOW).status == "HOLD"


def test_PORT_012():
    for covariance in (((D(0), D(0)), (D(0), D(0))), ((D(1),),), ((D(1), D(2)), (D(2), D(1)))):
        assert risk_candidate(panel(), settings(), NOW, covariance).status == "HOLD"


def test_PORT_013():
    assert risk_candidate(panel(), settings(), NOW) == risk_candidate(panel(), settings(), NOW)
    var, vol, rc = variance_and_rc(
        (D(".4"), D(".3")), ((D(".01"), D(".005")), (D(".005"), D(".04")))
    )
    assert (var, vol, sum(rc)) == (D(".0064"), D(".08"), D(".08"))


def test_REBAL_001():
    assert decision().action == "HOLD_TARGET"
    assert decision(new_expected_gross_krw=10, delay_decay_fraction=".8").action == "HOLD_TARGET"


def test_REBAL_002(joint):
    assert D(joint["account_net_pnl"]) - D(joint["project_net_pnl"]) == 10


def test_REBAL_003():
    assert decision(forced_reduction=True).action == "RISK_REDUCTION"


def test_REBAL_004():
    for policy in ("PBASE_FIXED", "PBASE_RISK"):
        d = decision(policy=policy, new_expected_gross_krw=100, account_and_quotes_fresh=False)
        assert d.action == "HOLD_TARGET" and d.risk_check == "FAIL"
        assert (
            decision(policy=policy, forced_reduction=True, execution_feasible=False).risk_check
            == "FAIL"
        )


def test_ECON_006(joint):
    assert joint["daily_rows"] == 7 and joint["cash_baseline_net"] == "-15"


def test_ECON_007(joint):
    assert joint["project_net_pnl"] != joint["weighted_reference_net"]


def test_ECON_008():
    assert economic_gate(gate(), False, True) == "HOLD_DATA"


def test_ECON_009(joint):
    assert joint["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"


def test_ECON_010():
    assert policy_to_keep(False) == policy_to_keep(True) == "PBASE_FIXED"


def test_SAFE_004():
    for operation in (MockBroker().submit_order, MockBroker().cancel_order):
        with pytest.raises(PermissionError):
            operation()


def test_SAFE_005():
    assert "SYNTHETIC_SECRET" not in str(
        scrub({"appsecret": "SYNTHETIC_SECRET"}, ("SYNTHETIC_SECRET",))
    )


def test_SAFE_006():
    p = risk_candidate(panel(), settings(), NOW)
    with pytest.raises(PermissionError):
        freeze_mock_fixed(p, "UNAPPROVED")
    assert freeze_mock_fixed(p, "SYNTHETIC_DIAGNOSTIC").policy_id == "PBASE_FIXED"
