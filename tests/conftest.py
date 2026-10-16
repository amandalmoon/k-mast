import socket
from datetime import UTC, datetime, timedelta

import pytest

from kmast.core.contracts import SignalIntent
from kmast.core.events import MarketEvent

NOW = datetime(2026, 10, 16, tzinfo=UTC)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network prohibited in contract tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def intent():
    return SignalIntent(
        intent_id="i",
        revision=1,
        target_snapshot_id="s1",
        strategy_id="A",
        model_version="m1",
        config_hash="c1",
        data_version="d1",
        symbol="SYNTHETIC",
        venue="KRX",
        session="REGULAR",
        decision_at=NOW,
        available_at=NOW,
        target_weight="0.5",
        horizon=timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        reason_code="TEST",
    )


@pytest.fixture
def event():
    return MarketEvent(
        event_id="e1",
        symbol="SYNTHETIC",
        venue="KRX",
        session="REGULAR",
        event_time=NOW,
        received_at=NOW,
        available_at=NOW,
        source="fixture",
        availability_method="OBSERVED_LIVE",
    )
