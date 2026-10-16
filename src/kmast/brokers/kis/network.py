"""Bounded real I/O. Constructors and imports never authenticate or connect."""

import http.client
import json
import time
from collections.abc import Callable
from datetime import timedelta
from threading import Lock
from typing import Any
from urllib.parse import urlencode, urlsplit

from pydantic import Field, SecretStr

from kmast.brokers.interfaces import OrdersBlocked
from kmast.brokers.kis.adapter import AccountRateLimiter, RatePolicy, Token, TokenManager
from kmast.brokers.kis.requests import MarketRequest
from kmast.core.base import Contract
from kmast.core.clock import Clock
from kmast.core.config import BrokerConfig


class DataError(RuntimeError):
    """Contains a fixed category only, never remote text, URL, header or credentials."""


class NetworkPolicy(Contract):
    allow_network_readonly: bool = False
    symbols: tuple[str, ...] = ()
    max_requests: int = Field(default=10, ge=1, le=50)
    max_days: int = Field(default=7, ge=1, le=366)
    timeout_seconds: float = Field(default=10, gt=0, le=30, allow_inf_nan=False)
    max_attempts: int = Field(default=3, ge=1, le=3)
    backoff_seconds: float = Field(default=1, ge=0.1, le=10, allow_inf_nan=False)


class NetworkPermit:
    def __init__(self, policy: NetworkPolicy) -> None:
        self.policy = policy
        self.used = 0
        self._lock = Lock()

    def require_enabled(self) -> None:
        if not self.policy.allow_network_readonly or not 1 <= len(set(self.policy.symbols)) <= 2:
            raise PermissionError("explicit bounded read-only network opt-in required")

    def require_request(self, request: MarketRequest) -> None:
        self.require_enabled()
        if request.symbol not in self.policy.symbols:
            raise PermissionError("symbol outside network scope")
        if request.start and request.end:
            if (request.end - request.start).days + 1 > self.policy.max_days:
                raise PermissionError("date range outside network scope")

    def consume(self) -> None:
        with self._lock:
            self.require_enabled()
            if self.used >= self.policy.max_requests:
                raise PermissionError("network request budget exhausted")
            self.used += 1


class HttpReply(Contract):
    status: int
    body: dict[str, Any] = Field(repr=False)
    continuation: str = ""


class Wire:
    """No redirects/proxies; only closed KIS quotation paths or two auth POSTs."""

    def __init__(self, permit: NetworkPermit) -> None:
        self.permit = permit

    def send(
        self,
        config: BrokerConfig,
        method: str,
        path: str,
        headers: dict[str, str],
        payload: dict[str, str],
    ) -> HttpReply:
        from kmast.brokers.kis.requests import ROUTES

        allowed = {"/uapi/domestic-stock/v1/quotations/" + value[0] for value in ROUTES.values()}
        if not (
            (method == "GET" and path in allowed)
            or (method == "POST" and path in {"/oauth2/tokenP", "/oauth2/Approval"})
        ):
            raise PermissionError("capability denied")
        if method == "GET":
            from kmast.brokers.kis.wire_contract import validate_read_payload

            request = validate_read_payload(config, path, payload)
            self.permit.require_request(request)
        self.permit.consume()
        url = urlsplit(config.endpoint)
        assert url.hostname is not None
        connection = http.client.HTTPSConnection(
            url.hostname, url.port, timeout=self.permit.policy.timeout_seconds
        )
        try:
            query = path + ("?" + urlencode(payload) if method == "GET" else "")
            body = json.dumps(payload).encode() if method == "POST" else None
            connection.request(method, query, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise DataError("RESPONSE_TOO_LARGE")
            # HTTP status classification precedes JSON parsing (HTML 5xx is common).
            if response.status != 200:
                return HttpReply(status=response.status, body={})
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise DataError("MALFORMED_RESPONSE")
            return HttpReply(
                status=response.status, body=decoded, continuation=response.getheader("tr_cont", "")
            )
        except (TimeoutError, OSError):
            raise DataError("NETWORK_TIMEOUT_OR_IO") from None
        except (ValueError, http.client.HTTPException):
            raise DataError("MALFORMED_RESPONSE") from None
        finally:
            connection.close()


class KISAuth:
    def __init__(self, wire: Wire, clock: Clock) -> None:
        self.wire, self.clock = wire, clock

    def _issue(self, config: BrokerConfig, websocket: bool) -> dict[str, Any]:
        if config.app_key is None or config.app_secret is None:
            raise DataError("CREDENTIALS_UNAVAILABLE")
        reply = self.wire.send(
            config,
            "POST",
            "/oauth2/Approval" if websocket else "/oauth2/tokenP",
            {"content-type": "application/json; charset=utf-8"},
            {
                "grant_type": "client_credentials",
                "appkey": config.app_key.get_secret_value(),
                "secretkey" if websocket else "appsecret": config.app_secret.get_secret_value(),
            },
        )
        if reply.status != 200:
            raise DataError("AUTH_FAILED")
        return reply.body

    def issue(self, config: BrokerConfig) -> Token:
        body = self._issue(config, False)
        try:
            lifetime = int(body["expires_in"])
            if (
                lifetime <= 30
                or not isinstance(body["access_token"], str)
                or not body["access_token"]
            ):
                raise ValueError
            now = self.clock.now()
            return Token(
                value=body["access_token"],
                account_ref=config.account_ref,
                environment=config.environment,
                issued_at=now,
                expires_at=now + timedelta(seconds=lifetime),
            )
        except (KeyError, ValueError, TypeError):
            raise DataError("AUTH_RESPONSE_INVALID") from None

    def approval(self, config: BrokerConfig) -> SecretStr:
        body = self._issue(config, True)
        key = body.get("approval_key")
        if not isinstance(key, str) or not key:
            raise DataError("APPROVAL_RESPONSE_INVALID")
        return SecretStr(key)


class MarketClient(OrdersBlocked):
    def __init__(
        self,
        config: BrokerConfig,
        wire: Wire,
        tokens: TokenManager,
        limiter: AccountRateLimiter,
        rate: RatePolicy,
        clock: Clock,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if config != tokens.config:
            raise ValueError("auth environment mismatch")
        self.config, self.wire, self.tokens = config, wire, tokens
        self.limiter, self.rate, self.clock, self.sleep = limiter, rate, clock, sleep
        self.audit: list[dict[str, str | int]] = []

    def read(self, request: MarketRequest) -> HttpReply:
        from kmast.data.models import KST

        self.wire.permit.require_request(request)
        request.require_environment(self.config.environment)
        request.require_nonfuture(self.clock.now().astimezone(KST))
        policy = self.wire.permit.policy
        for attempt in range(policy.max_attempts):
            try:
                self.limiter.acquire(self.config, request.tr_id, self.rate)
            except RuntimeError:
                self.sleep(float(self.rate.interval_seconds))
                self.limiter.acquire(self.config, request.tr_id, self.rate)
            try:
                token = self.tokens.get()
                assert self.config.app_key is not None and self.config.app_secret is not None
                reply = self.wire.send(
                    self.config,
                    "GET",
                    request.path,
                    {
                        "authorization": "Bearer " + token.value.get_secret_value(),
                        "appkey": self.config.app_key.get_secret_value(),
                        "appsecret": self.config.app_secret.get_secret_value(),
                        "tr_id": request.tr_id,
                        "custtype": "P",
                        "tr_cont": request.continuation,
                    },
                    request.params(),
                )
                self.audit.append(
                    {
                        "operation": request.operation,
                        "tr_id": request.tr_id,
                        "attempt": attempt + 1,
                        "status": reply.status,
                    }
                )
                if reply.status in {401, 403}:
                    self.tokens.invalidate()
                    raise DataError("AUTH_REJECTED")
                if reply.status == 429 or reply.status >= 500:
                    raise DataError("TRANSIENT_HTTP")
                if reply.status != 200:
                    raise DataError("PERMANENT_HTTP")
                if reply.body.get("rt_cd") != "0":
                    if reply.body.get("msg_cd") in {
                        "EGW00103",
                        "EGW00105",
                        "EGW00121",
                        "EGW00122",
                        "EGW00123",
                    }:
                        self.tokens.invalidate()
                        raise DataError("AUTH_REJECTED")
                    if reply.body.get("msg_cd") == "EGW00201":
                        raise DataError("TRANSIENT_RATE_LIMIT")
                    raise DataError("BROKER_ERROR_UNCLASSIFIED")
                return reply
            except DataError as error:
                if str(error) not in {
                    "NETWORK_TIMEOUT_OR_IO",
                    "TRANSIENT_HTTP",
                    "TRANSIENT_RATE_LIMIT",
                }:
                    raise
                if attempt + 1 == policy.max_attempts:
                    raise DataError("READ_RETRY_EXHAUSTED") from None
                self.sleep(policy.backoff_seconds * 2**attempt)
        raise DataError("READ_UNAVAILABLE")
