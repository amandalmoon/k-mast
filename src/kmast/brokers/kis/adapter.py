from collections.abc import Callable
from datetime import timedelta
from threading import Lock
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, SecretStr, model_validator

from kmast.brokers.interfaces import OrdersBlocked
from kmast.core.base import Contract, Identifier, Positive
from kmast.core.clock import Clock
from kmast.core.config import BrokerConfig
from kmast.core.enums import Environment


class Token(Contract):
    value: SecretStr = Field(repr=False, exclude=True)
    account_ref: SecretStr = Field(repr=False, exclude=True)
    environment: Environment
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def lifetime(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("invalid token lifetime")
        return self


class AuthProvider(Protocol):
    def issue(self, config: BrokerConfig) -> Token: ...


class TokenManager:
    """Memory only, renewal serialized; provider is injected and no real provider is bundled."""

    def __init__(
        self,
        config: BrokerConfig,
        provider: AuthProvider,
        clock: Clock,
        refresh_margin: timedelta = timedelta(seconds=30),
    ) -> None:
        if refresh_margin < timedelta(0):
            raise ValueError("negative refresh margin")
        self.config, self.provider, self.clock = config, provider, clock
        self.margin = refresh_margin
        self._token: Token | None = None
        self._lock = Lock()

    def get(self) -> Token:
        with self._lock:
            now = self.clock.now()
            if self._token is None or now + self.margin >= self._token.expires_at:
                try:
                    token = self.provider.issue(self.config)
                    now = self.clock.now()
                    if (
                        token.environment != self.config.environment
                        or token.account_ref != self.config.account_ref
                        or token.issued_at > now
                        or token.expires_at <= now + self.margin
                    ):
                        raise ValueError("invalid token scope or expiry")
                except Exception:
                    self._token = None
                    raise RuntimeError("authentication unavailable") from None
                self._token = token
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None


class ReadRoute(Contract):
    operation: Identifier
    path: Identifier
    tr_id: Identifier
    official_evidence: Identifier
    method: Literal["GET"] = "GET"

    @model_validator(mode="after")
    def read_only(self) -> Self:
        if not self.path.startswith("/uapi/") or any(
            marker in self.path.lower() for marker in ("order", "cancel", "rvse", "..", ":", "?")
        ):
            raise ValueError("not a read-only route")
        return self


class RestTransport(Protocol):
    def get(self, config: BrokerConfig, route: ReadRoute, token: Token) -> dict[str, str]: ...


class RatePolicy(Contract):
    interval_seconds: Positive
    evidence_ref: Identifier


class AccountRateLimiter:
    """Nonblocking conservative pacing, share one instance per process/account gateway."""

    def __init__(self, monotonic: Callable[[], float]) -> None:
        self.monotonic = monotonic
        self._last: dict[tuple[Environment, SecretStr, str], float] = {}
        self._lock = Lock()

    def acquire(self, config: BrokerConfig, tr_id: str, policy: RatePolicy) -> None:
        with self._lock:
            now = self.monotonic()
            # Both account-wide and TR-specific budgets must be available.
            keys = [
                (config.environment, config.account_ref, "*"),
                (config.environment, config.account_ref, tr_id),
            ]
            if any(
                now < self._last.get(key, float("-inf")) + float(policy.interval_seconds)
                for key in keys
            ):
                raise RuntimeError("rate limited; retry read later")
            for key in keys:
                self._last[key] = now


class StreamState(Contract):
    state: Literal["DISCONNECTED", "CONNECTING", "SYNCING", "READY", "GAP"] = "DISCONNECTED"
    generation: int = Field(default=0, ge=0)
    synchronized_generation: int | None = None
    last_event_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def synchronized(self) -> Self:
        if self.state == "READY" and self.synchronized_generation != self.generation:
            raise ValueError("stream requires fresh synchronization")
        return self

    def reconnect(self) -> "StreamState":
        return StreamState(state="SYNCING", generation=self.generation + 1)

    def mark_ready(self, generation: int) -> "StreamState":
        if self.state != "SYNCING" or generation != self.generation:
            raise ValueError("stale synchronization")
        return StreamState(
            state="READY", generation=self.generation, synchronized_generation=generation
        )


class KISReadAdapter(OrdersBlocked):
    """No network implementation, routes or production auth supplied in KM-000."""

    def __init__(
        self,
        config: BrokerConfig,
        auth: TokenManager,
        transport: RestTransport,
        limiter: AccountRateLimiter,
        rate_policy: RatePolicy,
        routes: tuple[ReadRoute, ...] = (),
    ) -> None:
        if config != auth.config:
            raise ValueError("auth/config mismatch")
        self.config, self.auth, self.transport = config, auth, transport
        self.limiter, self.rate_policy = limiter, rate_policy
        self.routes = {r.operation: r for r in routes}
        if len(self.routes) != len(routes):
            raise ValueError("duplicate read route")

    def read(self, operation: str) -> dict[str, str]:
        route = self.routes.get(operation)
        if route is None:
            raise PermissionError("read route not verified")
        self.limiter.acquire(self.config, route.tr_id, self.rate_policy)
        token = self.auth.get()
        try:
            return self.transport.get(self.config, route, token)
        except Exception:
            raise RuntimeError("broker read unavailable") from None
