from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kmast.alpha.fixtures import OPEN, trend
from kmast.alpha.models import AlphaConfig
from kmast.alpha.reference import ReferencePortfolio
from kmast.alpha.rules import decide
from kmast.brokers.interfaces import MockBroker
from kmast.brokers.kis.network import NetworkPermit, NetworkPolicy
from kmast.core.study import StudyContract
from kmast.data.models import SecurityStatus, universe_asof
from kmast.data.normalization import content_hash
from kmast.data.parsers import parse_rest
from kmast.data.pipeline import collect_rest
from kmast.data.store import DataStore
from kmast.portfolio.data_gate import EvaluationScope
from kmast.research.cli import run
from kmast.research.economics import (
    CostScenario,
    EconomicResult,
    cash_excess,
    economic_acceptance,
    execution_claim,
)
from kmast.research.publication import require_public_file
from kmast.research.qualification import (
    LicenseScope,
    corporate_action_basis,
    day_status,
    g1,
    quality_summary,
)
from kmast.research.validation import CandidateFreeze, MatureLabel, sample_gate

from .test_contracts import bridge
from .test_km001 import daily
from .test_km003 import change, costs, tick, weight
from .test_km004 import gate


def rows(fixture):
    request, body, source = daily(fixture)
    return parse_rest(body, request, source)


def license_scope(**updates):
    return LicenseScope.model_validate(
        dict(
            provider="SYNTHETIC",
            document_title="TEST",
            official_url="https://example.invalid",
            checked_at=OPEN,
        )
        | updates
    )


def freeze():
    return CandidateFreeze(
        config_hash=content_hash(AlphaConfig(strategy="A").model_dump(mode="json")),
        source_hash="FIXTURE_CODE",
        data_manifest_hash="FIXTURE_DATA",
        frozen_at=OPEN,
        study=StudyContract(),
        candidate_search_count=1,
        lineage=("ORIGINAL",),
    )


def result(**updates):
    return EconomicResult.model_validate(
        dict(
            calculation_mode="SYNTHETIC_FUNCTIONAL",
            provenance_refs=("FIXTURE",),
            account_bridge=bridge(),
            external_operating_cost=10,
        )
        | updates
    )


def scope(**updates):
    return EvaluationScope.model_validate(
        dict(
            capital_krw=1000,
            start=OPEN,
            end=OPEN + timedelta(days=1),
            calendar="FIXTURE",
            capital_policy="FIXTURE",
            cost_policy="FIXTURE",
            origin="SYNTHETIC",
            ledger="ACCOUNT",
        )
        | updates
    )


def master(state="LISTED"):
    return SecurityStatus(
        symbol="005930",
        name="SYNTHETIC",
        listing_market="KOSPI",
        valid_from=OPEN.date(),
        available_at=OPEN,
        state=state,
        managed=False,
        classification_version="FIXTURE",
        source_ref="SYNTHETIC",
    )


def test_DATAQUAL_001(fixture):
    q = quality_summary(rows(fixture))
    assert q.synthetic_rows == 2 and q.real_rows == 0


def test_DATAQUAL_002(fixture):
    raw = rows(fixture)
    adjusted = tuple(change(r, price_basis="ADJUSTED", adjustment_asof=OPEN) for r in raw)
    q = quality_summary(raw + adjusted)
    assert (q.total_rows, q.unique_stock_days, q.raw_stock_days, q.adjusted_stock_days) == (
        4,
        2,
        2,
        2,
    )


def test_DATAQUAL_003(fixture, tmp_path):
    request, body, source = daily(fixture)
    store = DataStore(tmp_path)
    identity, loaded = collect_rest(store, "fixture", request, lambda: (body, source))
    assert store.load_dataset(identity) == tuple(sorted(loaded, key=lambda r: r.record_id))
    path = tmp_path / "normalized" / identity / "observations.parquet"
    path.write_bytes(path.read_bytes() + b"CORRUPTION")
    with pytest.raises(ValueError):
        store.load_dataset(identity)


def test_DATAQUAL_004():
    assert universe_asof((master("DELISTED"),), OPEN.date(), OPEN) == ()
    assert (
        universe_asof((change(master(), available_at=OPEN + timedelta(days=1)),), OPEN.date(), OPEN)
        == ()
    )


def test_DATAQUAL_005():
    args = ("005930", OPEN.date(), OPEN)
    assert day_status(*args, None, (), False) == "UNKNOWN_CALENDAR"
    assert day_status(*args, (), (), False) == "CLOSED"
    assert day_status(*args, (OPEN.date(),), (master("SUSPENDED"),), False) == "SUSPENDED"
    assert day_status(*args, (OPEN.date(),), (master(),), False) == "MISSING_EXPECTED"


def test_DATAQUAL_006():
    with pytest.raises(ValueError):
        corporate_action_basis("ADJUSTED", True)
    corporate_action_basis("RAW", True)


def test_DATAQUAL_007(fixture):
    assert g1(gate(), license_scope(), quality_summary(rows(fixture))) == "HOLD_LICENSE_UNVERIFIED"


def test_DATAQUAL_008(fixture):
    with pytest.raises(ValueError):
        rows(fixture)[0].require_strategy_input(OPEN - timedelta(days=10))


def test_DATAQUAL_009(tmp_path):
    report = run(tmp_path)
    assert report["data_access"] == "DATA_NOT_ACCESSIBLE" and report["status"] == "KM005_DATA_HOLD"
    assert all(value is None for value in report["metrics"].values())


def test_STRAT_001():
    with pytest.raises(ValidationError):
        AlphaConfig(strategy="A", max_weight=-1)
    assert freeze().config_hash == content_hash(AlphaConfig(strategy="A").model_dump(mode="json"))


def test_STRAT_002():
    context = trend()
    last = context.bars[-1]
    # Current bar's high is not the previous-window breakout threshold.
    raised_high = change(last, high=last.high * 100)
    assert (
        weight(
            decide(
                change(context, bars=context.bars[:-1] + (raised_high,)), AlphaConfig(strategy="A")
            )
        )
        > 0
    )
    future = tuple(
        change(b, available_at=context.now + timedelta(days=1)) for b in context.benchmark
    )
    assert weight(decide(change(context, benchmark=future), AlphaConfig(strategy="A"))) == 0


def test_STRAT_003():
    context = trend()
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.submit(decide(context, AlphaConfig(strategy="A")), {"005930": Decimal(130)})
    event = tick(context.now)
    ref.match(event, event.at)
    assert not ref.state.executions


def test_STRAT_004():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.submit(decide(trend(), AlphaConfig(strategy="A")), {"005930": Decimal(130)})
    ref.match(tick(executable=False), OPEN + timedelta(seconds=1))
    assert not ref.state.executions


def test_STRAT_005():
    context = trend()
    halted = change(context.universe[0], halted=True)
    assert weight(decide(change(context, universe=(halted,)), AlphaConfig(strategy="A"))) == 0
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.submit(decide(context, AlphaConfig(strategy="A")), {"005930": Decimal(120)})
    ref.match(tick(), OPEN + timedelta(seconds=1))
    assert not ref.state.executions  # Ask 130 exceeds executable limit 120.


def test_EXEC_001():
    ref = ReferencePortfolio("A", Decimal(10000), costs())
    ref.submit(decide(trend(), AlphaConfig(strategy="A")), {"005930": Decimal(130)})
    event = tick(available_quantity=4)
    ref.match(event, event.at)
    assert ref.state.orders[0].status == "PARTIAL" and ref.reserve > 0
    assert ref.quantity("005930") == 4


def test_EXEC_002():
    states = []
    for _ in range(2):
        ref = ReferencePortfolio("A", Decimal(10000), costs())
        ref.submit(decide(trend(), AlphaConfig(strategy="A")), {"005930": Decimal(130)})
        ref.match(tick(), OPEN + timedelta(seconds=1))
        states.append(ref.state)
    assert states[0] == states[1]


def test_EXEC_003():
    with pytest.raises(PermissionError):
        execution_claim("DAILY", "EXACT_FILL")
    execution_claim("DAILY", "ASSUMED_SCENARIO")


def test_ECON_011():
    b = bridge(
        gross_market_pnl=100,
        explicit_fees_and_taxes=5,
        ending_nav_krw=1095,
        actual_exec_effect_diagnostic=7,
    )
    assert result(account_bridge=b).net_operating_pnl_krw == 85  # Embedded 7 not deducted twice.


def test_ECON_012():
    r = result()
    assert r.account_bridge.ending_nav_krw == 1100 and r.net_operating_pnl_krw == 90


def test_ECON_013():
    cash = result(account_bridge=bridge(ending_nav_krw=1000, gross_market_pnl=0))
    assert cash_excess(result(), cash, scope(), scope()) == 100


def test_ECON_014():
    with pytest.raises(ValueError):
        cash_excess(result(), result(), scope(), scope(capital_krw=2000))


def test_ECON_015():
    assert (
        result(calculation_mode="SIMULATED_REAL_MARKET_DATA").calculation_mode
        != "ACTUAL_BROKER_REALIZED"
    )
    with pytest.raises(ValidationError):
        result(calculation_mode="ACTUAL_BROKER_REALIZED")


def test_ECON_016():
    basic = result(account_bridge=bridge(explicit_fees_and_taxes=5, ending_nav_krw=1095))
    worse = result(account_bridge=bridge(explicit_fees_and_taxes=15, ending_nav_krw=1085))
    assert worse.net_operating_pnl_krw == basic.net_operating_pnl_krw - 10


def test_ECON_017():
    scenario = CostScenario(
        identity="UNKNOWN",
        effective_from=OPEN.date(),
        effective_to=OPEN.date(),
        provenance="UNVERIFIED",
    )
    assert not scenario.verified_for(OPEN.date(), OPEN.date())
    assert economic_acceptance(True, False, True, True)["G2"] == "HOLD_COSTS"


def test_ECON_018():
    assert economic_acceptance(True, True, True, False)["G3"] == "HOLD_MULTISTRATEGY_PANEL"


def test_VAL_012():
    f = freeze()
    with pytest.raises(PermissionError):
        f.require_oos(f.identity, OPEN + timedelta(days=1), True)


def test_VAL_013():
    with pytest.raises(ValidationError):
        MatureLabel(
            feature_at=OPEN,
            label_known_at=OPEN + timedelta(days=5),
            training_cutoff=OPEN + timedelta(days=1),
        )


def test_VAL_014():
    f = freeze()
    revised = change(
        f, config_hash="REVISED", candidate_search_count=2, lineage=f.lineage + (f.identity,)
    )
    assert revised.identity != f.identity
    with pytest.raises(PermissionError):
        revised.require_oos(f.identity, OPEN + timedelta(days=1), True)


def test_VAL_015():
    assert sample_gate(60, 100) == sample_gate(60, None) == "HOLD_INSUFFICIENT_EVIDENCE"


def test_VAL_016():
    first = freeze()
    second = change(first, candidate_search_count=2, lineage=(first.identity, "SECOND_TRIAL"))
    assert second.candidate_search_count == 2 and first.identity in second.lineage


def test_SAFE_007():
    for action in (MockBroker().submit_order, MockBroker().cancel_order):
        with pytest.raises(PermissionError):
            action()


def test_SAFE_008():
    for path in (".env", "data/km005-private/raw.json", "data/km004-private/file.parquet"):
        with pytest.raises(PermissionError):
            require_public_file(path)
    with pytest.raises(PermissionError):
        require_public_file("artifacts/raw.json", {"data_origin": "KIS_READONLY", "close": 123})
    require_public_file("artifacts/metadata.json", {"source_hash": "ONLY_A_HASH"})


def test_SAFE_009():
    permit = NetworkPermit(NetworkPolicy())
    with pytest.raises(PermissionError):
        permit.consume()
    assert permit.used == 0
