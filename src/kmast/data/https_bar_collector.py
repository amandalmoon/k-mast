"""Default-off exact-scope PAPER HTTPS read-only collector; no WS/account/order routes."""

import http.client
import json
import os
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

from kmast.core.config import BrokerConfig
from kmast.data.https_bar_gate import (
    END,
    HOST,
    PROPOSAL_HASH,
    ROOT_URL,
    STORE,
    authorize,
    checked_call,
    earliest,
    window,
)
from kmast.data.https_bar_store import BODY_CAP, Journal
from kmast.data.panel_acquisition import process_lock
from kmast.data.store import canonical, digest


class Clock(Protocol):
    def now(self) -> datetime: ...
    def mono(self) -> int: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def mono(self) -> int:
        return time.perf_counter_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class Reply:
    status: int | None
    raw: bytes
    request_at: datetime
    request_mono: int
    response_at: datetime
    response_mono: int
    error: str | None = None
    retry_after: int = 0
    tls_verified: bool = False
    request_started: bool = True


class Transport(Protocol):
    origin: str

    def exchange(
        self,
        ordinal: int,
        call: dict[str, Any] | None,
        config: BrokerConfig,
        token: str | None,
        clock: Clock,
    ) -> Reply: ...


class PaperHTTPS:
    origin = "OBSERVED"

    def __init__(
        self,
        raw_plan: bytes,
        approval: dict[str, Any],
        preflight: dict[str, Any],
        *,
        enabled: bool = False,
    ):
        self.raw_plan, self.approval, self.preflight, self.enabled = (
            raw_plan,
            approval,
            preflight,
            enabled,
        )

    def exchange(
        self,
        ordinal: int,
        call: dict[str, Any] | None,
        config: BrokerConfig,
        token: str | None,
        clock: Clock,
    ) -> Reply:
        plan = authorize(
            self.raw_plan, self.approval, self.preflight, clock.now(), enabled=self.enabled
        )
        if ordinal == 0:
            if call is not None:
                raise PermissionError("EXACT_TOKEN_ROUTE_REQUIRED")
        elif call is None:
            raise PermissionError("EXACT_FROZEN_MARKET_ROUTE_REQUIRED")
        else:
            checked_call(plan, ordinal, call)
        # No arbitrary URL or environment proxy. HTTPSConnection never follows redirects.
        if config.environment.value != "PAPER" or config.endpoint != ROOT_URL:
            raise PermissionError("EXACT_PAPER_TLS_HOST_REQUIRED")
        if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
            raise PermissionError("UNREVIEWED_TLS_TRUST_OVERRIDE_DENIED")
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        if not ctx.check_hostname or ctx.verify_mode != ssl.CERT_REQUIRED:
            raise PermissionError("TRUSTED_CA_HOSTNAME_VERIFICATION_REQUIRED")
        window(clock.now())
        connection = http.client.HTTPSConnection(HOST, 29443, timeout=10, context=ctx)
        start, mono = clock.now(), clock.mono()
        raw, status, retry, secure = b"", None, 0, False
        error, started = None, False
        try:
            connection.connect()  # Cert chain and hostname checked before exposing secrets.
            sock = connection.sock
            if (
                sock is None
                or not sock.getpeercert()
                or sock.version() not in {"TLSv1.2", "TLSv1.3"}
            ):
                raise PermissionError("TLS_PEER_VERIFICATION_REQUIRED")
            secure = True
            window(clock.now())  # TLS handshake may have crossed the hard cutoff.
            headers = {"content-type": "application/json; charset=utf-8"}
            if ordinal == 0:
                if config.app_key is None or config.app_secret is None:
                    raise PermissionError("PAPER_CREDENTIALS_REQUIRED")
                path, method = "/oauth2/tokenP", "POST"
                payload = json.dumps(
                    dict(
                        grant_type="client_credentials",
                        appkey=config.app_key.get_secret_value(),
                        appsecret=config.app_secret.get_secret_value(),
                    )
                ).encode()
            else:
                if call is None or call["url"].split("/uapi/")[0] != ROOT_URL or token is None:
                    raise PermissionError("EXACT_FROZEN_MARKET_ROUTE_REQUIRED")
                if config.app_key is None or config.app_secret is None:
                    raise PermissionError("PAPER_CREDENTIALS_REQUIRED")
                path = call["url"].removeprefix(ROOT_URL) + "?" + urlencode(call["parameters"])
                method, payload = "GET", None
                headers.update(
                    authorization="Bearer " + token,
                    appkey=config.app_key.get_secret_value(),
                    appsecret=config.app_secret.get_secret_value(),
                    tr_id=call["tr_id"],
                    custtype="P",
                )
            start, mono = clock.now(), clock.mono()
            window(start)
            started = True
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            status = response.status
            value = response.getheader("Retry-After", "")
            if value:
                try:
                    retry = (
                        int(value)
                        if value.isascii() and value.isdigit()
                        else max(
                            0, ceil((parsedate_to_datetime(value) - clock.now()).total_seconds())
                        )
                    )
                except (TypeError, ValueError, OverflowError):
                    retry = 3600
            raw = response.read(BODY_CAP + 1)
            if len(raw) > BODY_CAP:
                error = "OVERSIZED_OR_PARTIAL_BODY"
        except PermissionError:
            error = "TLS_OR_WINDOW_DENIED"
        except http.client.IncompleteRead as exc:
            raw = exc.partial[: BODY_CAP + 1]
            error = "PARTIAL_BODY_CAPTURED"
        except (OSError, http.client.HTTPException):
            error = "HTTP_IO_INTERRUPTED"
        finally:
            completed, completed_mono = clock.now(), clock.mono()
            connection.close()
            if error is not None:
                # Partial/error bodies have no complete-response timestamp. Anchor
                # retries after transport teardown, never before it finishes.
                completed, completed_mono = clock.now(), clock.mono()
        return Reply(
            status, raw, start, mono, completed, completed_mono, error, retry, secure, started
        )


def safe_market_body(raw: bytes, secrets: tuple[bytes, ...]) -> bool:
    if any(s and s in raw for s in secrets) or re.search(
        rb'"(?:access_token|approval_key|appkey|appsecret|secretkey|cano|'
        rb'acnt[^" ]*|account[^" ]*)"\s*:',
        raw,
        re.IGNORECASE,
    ):
        return False
    try:
        pending = [json.loads(raw)]
        needles = [s.decode("utf-8") for s in secrets if s]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if any(
                    re.fullmatch(
                        r"access_token|approval_key|appkey|appsecret|secretkey|cano|acnt.*|account.*",
                        k,
                        re.IGNORECASE,
                    )
                    for k in value
                ):
                    return False
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str) and any(secret in value for secret in needles):
                return False
        return True
    except (ValueError, UnicodeError, RecursionError):
        # Undecodable/partial bodies may hide escaped credentials; retain hash only.
        return False


class Collector:
    def __init__(
        self,
        root: Path,
        raw_plan: bytes,
        approval: dict[str, Any],
        preflight: dict[str, Any],
        credentials: Callable[[], BrokerConfig],
        *,
        enabled: bool = False,
        clock: Clock | None = None,
        transport: Transport | None = None,
    ):
        self.root, self.raw_plan = root, raw_plan
        self.approval, self.preflight, self.credentials = approval, preflight, credentials
        self.enabled, self.clock = enabled, clock or SystemClock()
        self.transport = transport  # No HTTP object constructed, no secret loading here.
        self.token: str | None = None
        self.state = "NETWORK_DISABLED"
        self.last_response_mono: int | None = None
        self.last_response_at: datetime | None = None
        self.interval = 3.10

    def guard(self) -> dict[str, Any]:
        return authorize(
            self.raw_plan, self.approval, self.preflight, self.clock.now(), enabled=self.enabled
        )

    def wait(self, not_before: datetime | None = None) -> None:
        self.guard()
        while True:
            window(self.clock.now())
            now, mono = self.clock.now(), self.clock.mono()
            wall = (not_before - now).total_seconds() if not_before else 0
            cooldown = (
                self.interval - (mono - self.last_response_mono) / 1e9
                if self.last_response_mono is not None
                else 0
            )
            remaining = max(wall, cooldown)
            if remaining <= 0:
                self.guard()
                return
            if (END - now).total_seconds() <= remaining:
                raise PermissionError("DF017_MISSED_COLLECTION_WINDOW")
            self.clock.sleep(min(remaining, 0.25))

    def run(self) -> dict[str, Any]:
        try:
            return self._run()
        finally:
            self.token = None
            self.state = "STOPPED"

    def _run(self) -> dict[str, Any]:
        plan = self.guard()  # Before keys, lock/store creation or HTTP transport objects.
        self.interval = max(3.10, float(self.preflight["provider_interval_seconds"]))
        transport = self.transport or PaperHTTPS(
            self.raw_plan, self.approval, self.preflight, enabled=self.enabled
        )
        if transport.origin == "OBSERVED" and self.root.resolve() != STORE.absolute():
            raise PermissionError("EXACT_NEW_PRIVATE_PILOT_STORE_REQUIRED")
        binding = dict(
            proposal_sha256=PROPOSAL_HASH,
            approval_sha256=digest(canonical(self.approval)),
            preflight_sha256=digest(canonical(self.preflight)),
            origin=transport.origin,
            hash_retention_allowed=True,
        )
        with process_lock(self.root / "process.lock"):
            journal = Journal(self.root, binding)
            if journal.reservations:
                # Token was never persisted. Fail closed instead of reissuing or refunding.
                raise PermissionError("SPENT_AUTH_OR_INTERRUPTED_SESSION_NO_AUTOMATIC_REAUTH")
            config = self.credentials()
            if config.environment.value != "PAPER" or config.endpoint != ROOT_URL:
                raise PermissionError("EXACT_PAPER_CONFIG_REQUIRED")
            secrets = tuple(
                s.get_secret_value().encode() for s in (config.app_key, config.app_secret) if s
            )
            self.state = "AUTHORIZED_READONLY"
            for ordinal in range(23):
                call = None if ordinal == 0 else plan["calls"][ordinal - 1]
                if call is not None:
                    checked_call(plan, ordinal, call)
                for attempt in range(2 if ordinal else 1):
                    self.wait(earliest(call) if call is not None else None)
                    if call and "FID_INPUT_HOUR_1" in call["parameters"]:
                        hour = self.clock.now().astimezone(END.tzinfo).strftime("%H%M%S")
                        if call["parameters"]["FID_INPUT_HOUR_1"] > hour:
                            raise PermissionError("FUTURE_QUERY_DENIED_BEFORE_IO")
                    i = journal.reserve(ordinal, self.clock.now())
                    try:
                        reply = transport.exchange(ordinal, call, config, self.token, self.clock)
                    except Exception:
                        journal.finish(
                            i,
                            dict(
                                status=None,
                                error="TRANSPORT_FAILED_UNKNOWN_START",
                                terminal=True,
                                auth_ok=False,
                                successful_response=False,
                                request_at=None,
                                request_mono=None,
                                response_at=None,
                                attempt_ended_at=self.clock.now().isoformat(),
                                attempt_ended_mono=self.clock.mono(),
                            ),
                            None,
                            None,
                        )
                        raise RuntimeError("TRANSPORT_FAILED_INPUTS_SUPPRESSED") from None
                    self.last_response_at, self.last_response_mono = (
                        reply.response_at,
                        reply.response_mono,
                    )
                    wall_elapsed = (reply.response_at - reply.request_at).total_seconds()
                    mono_elapsed = (reply.response_mono - reply.request_mono) / 1e9
                    if wall_elapsed < 0 or mono_elapsed < 0 or abs(wall_elapsed - mono_elapsed) > 1:
                        reply = replace(reply, error="CLOCK_DISCONTINUITY_HOLD")
                    self.interval = max(self.interval, min(reply.retry_after, 3600))
                    normalized = None
                    data = None
                    try:
                        data = json.loads(reply.raw)
                        if not isinstance(data, dict):
                            raise ValueError
                    except (ValueError, UnicodeError):
                        data = None
                    valid = (
                        reply.status == 200
                        and reply.error is None
                        and reply.tls_verified
                        and data is not None
                    )
                    if ordinal == 0:
                        token = data.get("access_token") if data else None
                        valid = valid and isinstance(token, str) and 16 <= len(token) <= 8192
                        if valid:
                            self.token = token
                    else:
                        valid = valid and data is not None and data.get("rt_cd") == "0"
                        from kmast.data.https_bar_quality import diagnose

                        if reply.error is None and safe_market_body(
                            reply.raw, secrets + ((self.token or "").encode(),)
                        ):
                            if call is not None:
                                normalized = diagnose(reply, call, transport.origin, self.clock)
                    retry = (
                        ordinal > 0
                        and attempt == 0
                        and (
                            reply.status == 429
                            or (reply.status is not None and 500 <= reply.status <= 599)
                            or reply.error in {"HTTP_IO_INTERRUPTED", "PARTIAL_BODY_CAPTURED"}
                        )
                    )
                    raw_allowed = ordinal > 0 and safe_market_body(
                        reply.raw, secrets + ((self.token or "").encode(),)
                    )
                    metadata = dict(
                        status=reply.status,
                        error=reply.error,
                        terminal=not retry,
                        auth_ok=valid if ordinal == 0 else None,
                        successful_response=valid,
                        captured_sha256=digest(reply.raw),
                        captured_bytes=len(reply.raw),
                        request_at=reply.request_at.isoformat() if reply.request_started else None,
                        request_mono=reply.request_mono if reply.request_started else None,
                        request_started=reply.request_started,
                        response_at=reply.response_at.isoformat() if reply.error is None else None,
                        response_mono=reply.response_mono if reply.error is None else None,
                        attempt_ended_at=reply.response_at.isoformat(),
                        attempt_ended_mono=reply.response_mono,
                        validation_complete_at=(
                            normalized["validation_complete_at"]
                            if normalized
                            else self.clock.now().isoformat()
                        ),
                        tls_verified=reply.tls_verified,
                        sensitive_withheld=not raw_allowed,
                        retry_after_seconds=reply.retry_after,
                    )
                    journal.finish(i, metadata, reply.raw if raw_allowed else None, normalized)
                    if ordinal == 0 and not valid:
                        raise PermissionError("PAPER_AUTH_FAILED_NO_REISSUE")
                    if reply.status in {401, 403} or reply.error == "TLS_OR_WINDOW_DENIED":
                        raise PermissionError("PAPER_ACCESS_OR_TLS_BLOCKED")
                    if reply.error == "CLOCK_DISCONTINUITY_HOLD":
                        raise PermissionError("CLOCK_DISCONTINUITY_HOLD")
                    if self.clock.now() >= END:
                        raise PermissionError("DF017_MISSED_COLLECTION_WINDOW")
                    if not retry:
                        break
            journal.verify()
            return dict(
                status="COLLECTION_ENDED_REQUIRES_INDEPENDENT_QUALIFICATION",
                origin=transport.origin,
                attempted=len(journal.reservations),
                logical_queries=22,
                execution_verified=False,
                profit=None,
                rvol="RVOL_NOT_READY",
            )
