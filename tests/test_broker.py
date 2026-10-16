from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError

from kmast.brokers.kis.adapter import (
    AccountRateLimiter,
    KISReadAdapter,
    RatePolicy,
    ReadRoute,
    StreamState,
    Token,
    TokenManager,
)
from kmast.core.clock import ReplayClock
from kmast.core.config import BrokerConfig

from .conftest import NOW


def config(environment="PAPER", account="SYNTHETIC_ACCOUNT"):
    return BrokerConfig(
        environment=environment,
        credential_environment=environment,
        account_environment=environment,
        account_ref=account,
        endpoint=(
            "https://openapivts.koreainvestment.com:29443"
            if environment == "PAPER"
            else "https://openapi.koreainvestment.com:9443"
        ),
    )


class Provider:
    def __init__(self, clock):
        self.clock = clock
        self.calls = 0

    def issue(self, cfg):
        self.calls += 1
        return Token(
            value="SYNTHETIC_TOKEN",
            account_ref=cfg.account_ref,
            environment=cfg.environment,
            issued_at=self.clock.now(),
            expires_at=self.clock.now() + timedelta(minutes=1),
        )


def test_token_single_refresh_expiry_and_redaction():
    clock = ReplayClock(NOW)
    provider = Provider(clock)
    manager = TokenManager(config(), provider, clock)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tokens = list(pool.map(lambda _: manager.get(), range(12)))
    assert provider.calls == 1 and all(t == tokens[0] for t in tokens)
    assert "SYNTHETIC_TOKEN" not in repr(tokens[0]) + tokens[0].model_dump_json()
    clock.advance(NOW + timedelta(seconds=31))
    manager.get()
    assert provider.calls == 2
    manager.invalidate()
    manager.get()
    assert provider.calls == 3


def test_auth_errors_and_mismatched_scopes_fail_closed():
    class BadProvider:
        def issue(self, cfg):
            raise RuntimeError("SECRET_MUST_NOT_PROPAGATE")

    with pytest.raises(RuntimeError, match="^authentication unavailable$"):
        TokenManager(config(), BadProvider(), ReplayClock(NOW)).get()

    class WrongScope:
        def issue(self, cfg):
            return Token(
                value="SYNTHETIC",
                account_ref="OTHER",
                environment="LIVE",
                issued_at=NOW,
                expires_at=NOW + timedelta(days=1),
            )

    with pytest.raises(RuntimeError, match="authentication unavailable"):
        TokenManager(config(), WrongScope(), ReplayClock(NOW)).get()


def test_rate_limiter_account_environment_and_tr():
    time = [0.0]
    limiter = AccountRateLimiter(lambda: time[0])
    policy = RatePolicy(interval_seconds=1, evidence_ref="SYNTHETIC_TEST_NOT_BROKER_LIMIT")
    limiter.acquire(config(), "READ1", policy)
    with pytest.raises(RuntimeError):
        limiter.acquire(config(), "READ2", policy)
    limiter.acquire(config(account="OTHER"), "READ1", policy)
    limiter.acquire(config(environment="LIVE"), "READ1", policy)
    time[0] = 1.0
    limiter.acquire(config(), "READ2", policy)


def test_stream_reconnection_requires_new_sync():
    state = StreamState().reconnect()
    ready = state.mark_ready(state.generation)
    assert ready.state == "READY"
    reconnect = ready.reconnect()
    with pytest.raises(ValueError):
        reconnect.mark_ready(ready.generation)
    assert reconnect.mark_ready(reconnect.generation).state == "READY"
    with pytest.raises(ValidationError):
        StreamState(state="READY", generation=2, synchronized_generation=1)


def test_read_transport_injection_and_order_block():
    class Transport:
        def get(self, cfg, route, token):
            return {"status": "SYNTHETIC_OK"}

    cfg = config()
    clock = ReplayClock(NOW)
    provider = Provider(clock)
    manager = TokenManager(cfg, provider, clock)
    limiter = AccountRateLimiter(lambda: 0)
    policy = RatePolicy(interval_seconds=1, evidence_ref="SYNTHETIC")
    adapter = KISReadAdapter(cfg, manager, Transport(), limiter, policy)
    with pytest.raises(PermissionError):
        adapter.read("quote")
    assert provider.calls == 0
    for operation in (adapter.submit_order, adapter.cancel_order):
        with pytest.raises(PermissionError):
            operation()
    route = ReadRoute(
        operation="test",
        path="/uapi/SYNTHETIC/read",
        tr_id="TEST_NOT_REAL_TR",
        official_evidence="SYNTHETIC_TEST_ONLY",
    )
    adapter = KISReadAdapter(cfg, manager, Transport(), limiter, policy, (route,))
    assert adapter.read("test") == {"status": "SYNTHETIC_OK"}


@pytest.mark.parametrize("path", ["/uapi/order", "/uapi/cancel", "https://evil", "/uapi/../order"])
def test_write_routes_rejected(path):
    with pytest.raises(ValidationError):
        ReadRoute(operation="x", path=path, tr_id="SYNTHETIC", official_evidence="test")


def test_replay_clock_is_monotonic():
    clock = ReplayClock(NOW)
    with pytest.raises(ValueError):
        clock.advance(NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        ReplayClock(NOW.replace(tzinfo=None))
