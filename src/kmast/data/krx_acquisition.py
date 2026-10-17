"""DF009 separately approved historical basics transport; disabled by default.

Reservations are consumed before I/O. Completed immutable journal events recover
an interrupted budget/cache commit. A single OS lock must surround an active run.
"""

import http.client
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from kmast.data.historical_security import day
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest

ENDPOINTS = {
    "KOSPI": "/svc/apis/sto/stk_isu_base_info",
    "KOSDAQ": "/svc/apis/sto/ksq_isu_base_info",
}


class KRXBasicsWire:
    def __init__(
        self,
        folder: Path,
        queries: tuple[dict[str, str], ...],
        scope_sha256: str,
        key: str = "",
        *,
        enabled: bool = False,
    ) -> None:
        targets = tuple(digest(canonical(q)) for q in queries)
        for q in queries:
            if set(q) != {"market", "basDd"} or q["market"] not in ENDPOINTS:
                raise ValueError("KRX_QUERY_OUTSIDE_SCOPE")
            day(q["basDd"])
        self.queries = dict(zip(targets, queries, strict=True))
        if len(set(targets)) != len(targets) or not 1 <= len(targets) <= 48:
            raise ValueError("INVALID_KRX_BASICS_ALLOWLIST")
        if any(not re.fullmatch(r"[a-f0-9]{64}", r) for r in targets):
            raise ValueError("INVALID_QUERY_ALLOWLIST")
        self.folder, self.targets, self.scope = folder, frozenset(targets), scope_sha256
        self.key, self.enabled = key, enabled
        self.run_id = uuid.uuid4().hex
        self.path = folder / "budget.json"
        folder.mkdir(parents=True, exist_ok=True)
        maximum = min(96, 2 * len(targets))
        self.state: dict[str, Any] = (
            json.loads(self.path.read_bytes())
            if self.path.exists()
            else dict(
                scope_sha256=scope_sha256,
                maximum=maximum,
                used=0,
                events=[],
                halted=None,
            )
        )
        if self.state["scope_sha256"] != scope_sha256 or self.state["maximum"] != maximum:
            raise ValueError("PERSISTENT_SCOPE_CONFLICT")
        if self.state["used"] != len(self.state["events"]) or self.state["used"] > maximum:
            raise ValueError("PERSISTENT_BUDGET_CONFLICT")
        for number, event in enumerate(self.state["events"], 1):
            if event["number"] != number or event["request_identity"] not in self.targets:
                raise ValueError("PERSISTENT_JOURNAL_CONFLICT")
            final = folder / "events" / f"{number:04}.json"
            if final.exists():
                recovered = json.loads(final.read_bytes())
                if (
                    recovered["number"] != number
                    or recovered["request_identity"] != event["request_identity"]
                ):
                    raise ValueError("JOURNAL_IDENTITY_CONFLICT")
                self.state["events"][number - 1] = recovered
                if recovered.get("fatal"):
                    self.state["halted"] = recovered["fatal"]
        if self.path.exists():
            atomic_json(self.path, self.state)
        # Never compare a previous process's performance-clock origin after reboot.
        self.last_perf = time.perf_counter() if self.state["used"] else None

    def halt(self, reason: str) -> None:
        self.state["halted"] = reason
        atomic_json(self.path, self.state)
        raise ValueError(reason)

    def wait(self) -> None:
        if self.last_perf is None:
            return
        deadline = self.last_perf + 3.10
        while True:
            now = time.perf_counter()
            if now < self.last_perf:
                self.halt("PERFORMANCE_CLOCK_REVERSED")
            if now >= deadline:
                return
            time.sleep(deadline - now)

    def cached(self, request_identity: str) -> dict[str, Any] | None:
        cache = self.folder / "cache" / (request_identity + ".json")
        if cache.exists():
            record: dict[str, Any] = json.loads(cache.read_bytes())
            if (
                record["request_identity"] != request_identity
                or record["scope_sha256"] != self.scope
            ):
                self.halt("CACHE_SCOPE_CONFLICT")
            event = next(
                (e for e in self.state["events"] if e["number"] == record["request_number"]), None
            )
            if (
                event is None
                or event["request_identity"] != request_identity
                or event.get("sha256") != record["sha256"]
            ):
                self.halt("CACHE_JOURNAL_CONFLICT")
            if record["wire_stored"]:
                raw = (self.folder / "wire" / (record["sha256"] + ".bin")).read_bytes()
                if digest(raw) != record["sha256"]:
                    self.halt("CACHE_RAW_HASH_CONFLICT")
            return record
        attempts = [e for e in self.state["events"] if e["request_identity"] == request_identity]
        completed = [e for e in attempts if "completed_at" in e]
        if completed and (
            completed[-1].get("success") or completed[-1].get("terminal") or len(attempts) >= 2
        ):
            return self.publish_cache(completed[-1])
        return None

    def publish_cache(self, event: dict[str, Any]) -> dict[str, Any]:
        record = {
            k: event.get(k)
            for k in (
                "request_identity",
                "sha256",
                "wire_stored",
                "success",
                "api_status",
                "http_status",
                "completed_at",
                "error_category",
            )
        } | dict(scope_sha256=self.scope, request_number=event["number"])
        immutable_write(
            self.folder / "cache" / (event["request_identity"] + ".json"), canonical(record)
        )
        return record

    def get(self, request_identity: str) -> dict[str, Any]:
        if request_identity not in self.targets:
            raise ValueError("KRX_BASICS_OUTSIDE_APPROVED_ALLOWLIST")
        saved = self.cached(request_identity)
        if saved is not None:
            return saved
        if not self.enabled:
            raise ValueError("NETWORK_DISABLED")
        if not re.fullmatch(r"[a-zA-Z0-9]{40}", self.key):
            raise ValueError("INVALID_KEY_FORMAT")
        if self.state["halted"]:
            raise ValueError("PERSISTENT_COLLECTION_HALT")
        prior = [e for e in self.state["events"] if e["request_identity"] == request_identity]
        if len(prior) >= 2:
            raise ValueError("QUERY_ATTEMPTS_EXHAUSTED")
        for attempt in range(len(prior), 2):
            if self.state["used"] >= self.state["maximum"]:
                self.halt("APPROVED_BUDGET_EXHAUSTED")
            self.wait()
            # Consume before side effect. A crash leaves an unknown consumed attempt.
            self.state["used"] += 1
            event: dict[str, Any] = dict(
                number=self.state["used"],
                request_identity=request_identity,
                attempt=attempt,
                run_id=self.run_id,
                reserved_at=datetime.now(UTC).isoformat(),
                outcome="RESERVED_UNKNOWN",
                success=False,
                wire_stored=False,
            )
            self.state["events"].append(event)
            atomic_json(self.path, self.state)
            connection = http.client.HTTPSConnection("data-dbg.krx.co.kr", timeout=45)
            retry = False
            fatal: str | None = None
            try:
                # Construct only in memory. No exception message/URL is ever logged.
                query = urlencode({"basDd": self.queries[request_identity]["basDd"]})
                start_perf, start_utc = time.perf_counter(), datetime.now(UTC)
                prev = self.state["events"][-2] if len(self.state["events"]) > 1 else None
                perf_gap = start_perf - self.last_perf if self.last_perf is not None else None
                utc_gap = (
                    (start_utc - datetime.fromisoformat(prev["completed_at"])).total_seconds()
                    if prev and "completed_at" in prev
                    else None
                )
                event.update(
                    started_at=start_utc.isoformat(),
                    start_perf=start_perf,
                    completion_gap_perf=perf_gap,
                    completion_gap_utc=utc_gap,
                )
                if (perf_gap is not None and perf_gap < 3.05) or (
                    utc_gap is not None and utc_gap < 3.05
                ):
                    fatal = "OBSERVED_SPACING_VIOLATION_TRANSMISSION_BLOCKED"
                    event["outcome"] = "BLOCKED_BEFORE_SEND"
                else:
                    event["transmitted"] = True
                    connection.request(
                        "GET",
                        ENDPOINTS[self.queries[request_identity]["market"]] + "?" + query,
                        headers={"User-Agent": "KMAST-DF009", "AUTH_KEY": self.key},
                    )
                    response = connection.getresponse()
                    raw = response.read(32 * 1024 * 1024 + 1)
                    # Clock observation precedes filesystem persistence, after full response read.
                    completed_perf, completed_utc = time.perf_counter(), datetime.now(UTC)
                    event.update(
                        response_completed_perf=completed_perf,
                        completed_at=completed_utc.isoformat(),
                        http_status=response.status,
                        sha256=digest(raw),
                        bytes=len(raw),
                        outcome="RECEIVED",
                    )
                    if self.key.encode() in raw:
                        fatal = "SENSITIVE_RESPONSE_HASH_ONLY"
                    elif len(raw) > 32 * 1024 * 1024:
                        fatal = "RESPONSE_SIZE_LIMIT_HASH_ONLY"
                    else:
                        immutable_write(self.folder / "wire" / (digest(raw) + ".bin"), raw)
                        event["wire_stored"] = True
                        body = None
                        try:
                            body = json.loads(raw)
                        except (ValueError, UnicodeDecodeError):
                            pass
                        event["success"] = (
                            response.status == 200
                            and isinstance(body, dict)
                            and isinstance(body.get("OutBlock_1"), list)
                        )
                        if not event["success"]:
                            if response.status in {401, 403, 429}:
                                fatal = "KRX_AUTH_PERMISSION_OR_QUOTA_FAILURE"
                            retry = response.status >= 500
                            event["error_category"] = (
                                "TRANSIENT_PROVIDER_FAILURE"
                                if retry
                                else "KRX_RESPONSE_SCHEMA_UNKNOWN"
                            )
                            if not retry and not fatal:
                                fatal = "KRX_RESPONSE_SCHEMA_UNKNOWN"
            except ValueError:
                fatal = "KRX_RESPONSE_INTEGRITY_FAILURE"
                retry = False
            except (OSError, http.client.HTTPException):
                retry = True
                event.update(outcome="TRANSPORT_FAILURE", error_category="TRANSPORT_FAILURE")
            finally:
                connection.close()
                if "completed_at" not in event:
                    event.update(
                        completed_at=datetime.now(UTC).isoformat(),
                        response_completed_perf=time.perf_counter(),
                    )
                self.last_perf = time.perf_counter()
                event["terminal"] = bool(fatal or event["success"] or not retry or attempt == 1)
                event["fatal"] = fatal
                if fatal:
                    event["error_category"] = fatal
                    self.state["halted"] = fatal
                immutable_write(
                    self.folder / "events" / f"{event['number']:04}.json", canonical(event)
                )
                atomic_json(self.path, self.state)
            if fatal:
                raise ValueError(fatal)
            if event["terminal"]:
                return self.publish_cache(event)
        raise ValueError("UNREACHABLE_KRX_BASICS_ATTEMPT")
