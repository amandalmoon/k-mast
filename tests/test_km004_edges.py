from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kmast.brokers.kis.requests import MarketRequest
from kmast.core.enums import Environment
from kmast.execution.events import SplitAction
from kmast.portfolio.allocation import risk_candidate
from tests.km002_helpers import buy, make_engine
from tests.test_km004 import panel, settings


def action(engine, **updates):
    return SplitAction.model_validate(
        dict(
            event_id="SPLIT:ONE",
            action_id="ONE",
            symbol="005930",
            multiplier=2,
            at=engine.clock.now(),
            available_at=engine.clock.now(),
            effective_date=engine.clock.now().date(),
            source_ref="SYNTHETIC",
        )
        | updates
    )


def test_split_preserves_nav_idempotence_and_requires_fresh_reconciliation(tmp_path):
    engine = make_engine(tmp_path / "one.sqlite")
    buy(engine, settled=True)
    before = engine.state.account.nav(engine.state.quotes)
    event = action(engine)
    engine.apply(event)
    assert engine.state.account.quantity("005930") == 20
    assert engine.state.book("A").quantity("005930") == 20
    assert engine.state.account.nav(engine.state.quotes) == before
    assert not engine.state.reconciled and engine.state.quote("005930").halted
    state = engine.state
    engine.apply(event)
    assert engine.state == state


def test_split_unsettled_inventory_is_atomic_rejection(tmp_path):
    engine = make_engine(tmp_path / "one.sqlite")
    buy(engine)
    state = engine.state
    with pytest.raises(ValueError):
        engine.apply(action(engine))
    assert engine.state == state


@pytest.mark.parametrize("updates", [{"event_id": "ARBITRARY"}, {"price_basis": "ADJUSTED"}])
def test_split_invalid_identity_basis(updates, tmp_path):
    engine = make_engine(tmp_path / "one.sqlite")
    with pytest.raises(ValidationError):
        action(engine, **updates)


def test_split_future_effective_and_fractional_quantity_rejected(tmp_path):
    engine = make_engine(tmp_path / "one.sqlite")
    buy(engine, settled=True)
    for updates in (
        {"effective_date": engine.clock.now().date() + timedelta(days=1)},
        {"multiplier": Decimal(".03")},
    ):
        state = engine.state
        with pytest.raises(ValueError):
            engine.apply(action(engine, **updates))
        assert engine.state == state


def test_index_daily_paper_exact_closed_route():
    request = MarketRequest(
        operation="index_daily", symbol="0001", start="2026-07-20", end="2026-10-16"
    )
    request.require_environment(Environment.PAPER)
    assert request.tr_id == "FHKUP03500100"
    assert request.params()["FID_COND_MRKT_DIV_CODE"] == "U"
    with pytest.raises(ValueError):
        MarketRequest(operation="index", symbol="0001").require_environment(Environment.PAPER)
    for updates in (
        {"symbol": "005930"},
        {"continuation": "N"},
        {"price_basis": "ADJUSTED"},
        {"end": "2026-01-01"},
    ):
        with pytest.raises(ValueError):
            MarketRequest.model_validate(request.model_dump() | updates)


def test_risk_insufficient_samples_and_floor_cap():
    assert (
        risk_candidate(
            panel(), settings().model_copy(update={"min_samples": 30}), panel()[0].at[-1]
        ).status
        == "HOLD"
    )
    p = risk_candidate(
        panel(),
        settings(),
        panel()[0].at[-1],
        ((Decimal("1e-30"), Decimal(0)), (Decimal(0), Decimal(".04"))),
    )
    assert p.status == "PROPOSAL_ONLY"
    assert all(w <= Decimal(".4") for _, w in p.weights)
