"""DF008 separately approved document-only transport; disabled by default.

Reservations are consumed before I/O. Completed immutable journal events recover
an interrupted budget/cache commit. A single OS lock must surround an active run.
"""

import http.client
import io
import json
import re
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest


class DocumentWire:
    def __init__(
        self,
        folder: Path,
        targets: tuple[str, ...],
        scope_sha256: str,
        key: str = "",
        *,
        enabled: bool = False,
    ) -> None:
        if len(set(targets)) != len(targets) or not 1 <= len(targets) <= 100:
            raise ValueError("INVALID_DOCUMENT_ALLOWLIST")
        if any(not re.fullmatch(r"[0-9]{14}", r) for r in targets):
            raise ValueError("INVALID_RECEIPT_ALLOWLIST")
        self.folder, self.targets, self.scope = folder, frozenset(targets), scope_sha256
        self.key, self.enabled = key, enabled
        self.run_id = uuid.uuid4().hex
        self.path = folder / "budget.json"
        folder.mkdir(parents=True, exist_ok=True)
        maximum = min(200, 2 * len(targets))
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
            if event["number"] != number or event["receipt"] not in self.targets:
                raise ValueError("PERSISTENT_JOURNAL_CONFLICT")
            final = folder / "events" / f"{number:04}.json"
            if final.exists():
                recovered = json.loads(final.read_bytes())
                if recovered["number"] != number or recovered["receipt"] != event["receipt"]:
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

    def cached(self, receipt: str) -> dict[str, Any] | None:
        cache = self.folder / "cache" / (receipt + ".json")
        if cache.exists():
            record: dict[str, Any] = json.loads(cache.read_bytes())
            if record["receipt"] != receipt or record["scope_sha256"] != self.scope:
                self.halt("CACHE_SCOPE_CONFLICT")
            event = next(
                (e for e in self.state["events"] if e["number"] == record["request_number"]), None
            )
            if (
                event is None
                or event["receipt"] != receipt
                or event.get("sha256") != record["sha256"]
            ):
                self.halt("CACHE_JOURNAL_CONFLICT")
            if record["wire_stored"]:
                raw = (self.folder / "wire" / (record["sha256"] + ".bin")).read_bytes()
                if digest(raw) != record["sha256"]:
                    self.halt("CACHE_RAW_HASH_CONFLICT")
            return record
        attempts = [e for e in self.state["events"] if e["receipt"] == receipt]
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
                "receipt",
                "sha256",
                "wire_stored",
                "success",
                "api_status",
                "http_status",
                "completed_at",
                "error_category",
            )
        } | dict(scope_sha256=self.scope, request_number=event["number"])
        immutable_write(self.folder / "cache" / (event["receipt"] + ".json"), canonical(record))
        return record

    def get(self, receipt: str) -> dict[str, Any]:
        if receipt not in self.targets:
            raise ValueError("DOCUMENT_OUTSIDE_APPROVED_ALLOWLIST")
        saved = self.cached(receipt)
        if saved is not None:
            return saved
        if not self.enabled:
            raise ValueError("NETWORK_DISABLED")
        if not re.fullmatch(r"[a-zA-Z0-9]{40}", self.key):
            raise ValueError("INVALID_KEY_FORMAT")
        if self.state["halted"]:
            raise ValueError("PERSISTENT_COLLECTION_HALT")
        prior = [e for e in self.state["events"] if e["receipt"] == receipt]
        if len(prior) >= 2:
            raise ValueError("RECEIPT_ATTEMPTS_EXHAUSTED")
        for attempt in range(len(prior), 2):
            if self.state["used"] >= self.state["maximum"]:
                self.halt("APPROVED_BUDGET_EXHAUSTED")
            self.wait()
            # Consume before side effect. A crash leaves an unknown consumed attempt.
            self.state["used"] += 1
            event: dict[str, Any] = dict(
                number=self.state["used"],
                receipt=receipt,
                attempt=attempt,
                run_id=self.run_id,
                reserved_at=datetime.now(UTC).isoformat(),
                outcome="RESERVED_UNKNOWN",
                success=False,
                wire_stored=False,
            )
            self.state["events"].append(event)
            atomic_json(self.path, self.state)
            connection = http.client.HTTPSConnection("opendart.fss.or.kr", timeout=45)
            retry = False
            fatal: str | None = None
            try:
                # Construct only in memory. No exception message/URL is ever logged.
                query = urlencode({"rcept_no": receipt, "crtfc_key": self.key})
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
                        "GET", "/api/document.xml?" + query, headers={"User-Agent": "KMAST-DF008"}
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
                        event["success"] = response.status == 200 and zipfile.is_zipfile(
                            io.BytesIO(raw)
                        )
                        if not event["success"]:
                            status: str | None = None
                            try:
                                status = ET.fromstring(raw).findtext("status")
                            except ET.ParseError:
                                pass
                            event["api_status"] = (
                                status if status and re.fullmatch(r"[0-9]{3}", status) else None
                            )
                            if status in {"010", "011", "012", "020", "021", "100", "101", "901"}:
                                fatal = "DART_AUTH_QUOTA_OR_SCOPE_FAILURE"
                            retry = response.status >= 500 or status in {"800", "900"}
                            event["error_category"] = (
                                "PROVIDER_DOCUMENT_UNAVAILABLE"
                                if not retry
                                else "TRANSIENT_PROVIDER_FAILURE"
                            )
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
        raise ValueError("UNREACHABLE_DOCUMENT_ATTEMPT")
