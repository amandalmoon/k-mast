"""Bounded domestic PAPER acquisition with byte-level private response lineage.

No constructor authenticates; a process lock must surround each active run.
This is separate from frozen historical research and the original network Wire.
"""

import http.client
import json
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import FunctionType
from typing import Any
from urllib.parse import urlencode

from kmast.brokers.kis.network import HttpReply, Wire
from kmast.brokers.kis.wire_contract import validate_read_payload
from kmast.core.config import BrokerConfig
from kmast.core.enums import Environment
from kmast.data.models import Observation, Provenance
from kmast.data.store import SENSITIVE, DataStore, canonical, digest, scrub


def immutable_write(path: Path, value: bytes) -> None:
    """Publish a complete fsynced file without replacing an immutable destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise ValueError("IMMUTABLE_CONTENT_CONFLICT")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".df005-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != value:
                raise ValueError("IMMUTABLE_CONTENT_CONFLICT") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


class AtomicPanelStore(DataStore):
    """Reuse frozen store validation/format with atomic publication in a private namespace."""

    def put_raw(
        self,
        identity: str,
        payload: dict[str, Any],
        metadata: Provenance,
        secrets: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        method = FunctionType(
            DataStore.put_raw.__code__,
            dict(DataStore.put_raw.__globals__) | {"immutable_write": immutable_write},
        )
        result: dict[str, Any] = method(self, identity, payload, metadata, secrets)
        return result

    def put_dataset(self, records: tuple[Observation, ...], raw_identity: str) -> str:
        method = FunctionType(
            DataStore.put_dataset.__code__,
            dict(DataStore.put_dataset.__globals__) | {"immutable_write": immutable_write},
        )
        result: str = method(self, records, raw_identity)
        return result


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as file:
        file.write(canonical(value))
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


@contextmanager
def process_lock(path: Path) -> Iterator[None]:
    """OS releases the byte lock on crash; the inode remains safe for resumption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise PermissionError("COLLECTION_ALREADY_LOCKED") from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise PermissionError("COLLECTION_ALREADY_LOCKED") from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def sensitive(value: Any) -> bool:
    if isinstance(value, dict):
        return any(SENSITIVE.search(str(k)) or sensitive(v) for k, v in value.items())
    if isinstance(value, list):
        return any(sensitive(v) for v in value)
    return False


class PanelWire(Wire):
    """Exact DF005 approval: 50 frozen stocks +2 indices, 900 calls, auth<=2.

    Unlike the original Wire, non-200/error responses are preserved when safe.
    Authentication bodies are hash-only and tokens exist only in memory.
    """

    def __init__(self, folder: Path, symbols: tuple[str, ...], *, enabled: bool = False):
        if len(set(symbols)) != 50 or any(
            not s.isascii() or not s.isdigit() or len(s) != 6 for s in symbols
        ):
            raise ValueError("FROZEN50_REQUIRED")
        self.folder = folder.resolve()
        self.symbols, self.enabled = symbols, enabled
        self.folder.mkdir(parents=True, exist_ok=True)
        self.budget_path = self.folder / "budget.json"
        self.state: dict[str, Any] = (
            json.loads(self.budget_path.read_bytes())
            if self.budget_path.exists()
            else {
                "requests": 0,
                "authentication": 0,
                "response_completed_epoch": 0,
                "response_pending": False,
                "events": [],
            }
        )
        self.last_monotonic = time.monotonic()
        self.last_event: dict[str, Any] = {}
        self.session_requests = 0
        self.session_limit = 900
        if self.state["response_pending"]:
            # Consumed call remains consumed even if a process died before receipt.
            event_path = self.folder / "events" / f"{self.state['requests']:04}.json"
            event = (
                json.loads(event_path.read_bytes())
                if event_path.exists()
                else dict(
                    sequence=self.state["requests"], body_status="INTERRUPTED_RESPONSE_UNAVAILABLE"
                )
            )
            if event["sequence"] != self.state["requests"]:
                raise ValueError("INTERRUPTED_JOURNAL_SEQUENCE_CONFLICT")
            old = [e for e in self.state["events"] if e["sequence"] == event["sequence"]]
            if old:
                if old != [event]:
                    raise ValueError("INTERRUPTED_JOURNAL_CONTENT_CONFLICT")
            else:
                self.state["events"].append(event)
            if event.get("received_at"):
                self.state["response_completed_epoch"] = max(
                    self.state["response_completed_epoch"],
                    datetime.fromisoformat(event["received_at"]).timestamp(),
                )
            self.state["response_pending"] = False
            immutable_write(event_path, canonical(event))
            atomic_json(self.budget_path, self.state)

    def validate(
        self,
        config: BrokerConfig,
        method: str,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> None:
        if not self.enabled or config.environment != Environment.PAPER:
            raise PermissionError("EXPLICIT_PAPER_READONLY_REQUIRED")
        if method == "POST" and path == "/oauth2/tokenP":
            if (
                set(params) != {"grant_type", "appkey", "appsecret"}
                or params["grant_type"] != "client_credentials"
            ):
                raise PermissionError("AUTH_SCOPE_DENIED")
            return
        if method != "GET":
            raise PermissionError("CAPABILITY_DENIED")
        request = validate_read_payload(config, path, params)
        if request.operation not in {"daily", "index_daily"} or request.venue != "KRX":
            raise PermissionError("DAILY_ONLY")
        allowed = self.symbols if request.operation == "daily" else ("0001", "1001")
        if request.symbol not in allowed or headers.get("tr_id") != request.tr_id:
            raise PermissionError("SYMBOL_TR_SCOPE_DENIED")
        if (
            request.start is None
            or request.end is None
            or not date(2022, 9, 1) <= request.start <= request.end <= date(2025, 10, 16)
        ):
            raise PermissionError("DATE_SCOPE_DENIED")

    def send(
        self,
        config: BrokerConfig,
        method: str,
        path: str,
        headers: dict[str, str],
        payload: dict[str, str],
    ) -> HttpReply:
        self.validate(config, method, path, payload, headers)
        auth = method == "POST"
        if (
            self.state["requests"] >= 900
            or self.session_requests >= self.session_limit
            or (auth and self.state["authentication"] >= 2)
        ):
            raise PermissionError("APPROVED_BUDGET_EXHAUSTED")
        # Both wall-time (across process resume) and monotonic time (within run).
        wall_wait = 3.05 - (time.time() - self.state["response_completed_epoch"])
        mono_wait = 3.05 - (time.monotonic() - self.last_monotonic)
        time.sleep(max(0.0, wall_wait, mono_wait))
        self.state["requests"] += 1
        self.state["authentication"] += int(auth)
        self.state["response_pending"] = True
        self.session_requests += 1
        atomic_json(self.budget_path, self.state)
        number = self.state["requests"]
        before = datetime.now(UTC)
        event: dict[str, Any] = dict(
            sequence=number,
            kind="AUTH" if auth else "DAILY",
            request_time=before.isoformat(),
            request_fingerprint=digest(canonical([method, path, payload])) if not auth else None,
        )
        if not auth:
            event.update(
                symbol=payload["FID_INPUT_ISCD"],
                operation="daily" if "FID_ORG_ADJ_PRC" in payload else "index_daily",
                basis=payload.get("FID_ORG_ADJ_PRC"),
                start=payload["FID_INPUT_DATE_1"],
                end=payload["FID_INPUT_DATE_2"],
            )
        raw = b""
        connection = http.client.HTTPSConnection(
            "openapivts.koreainvestment.com", 29443, timeout=20
        )
        try:
            connection.request(
                method,
                path + ("?" + urlencode(payload) if not auth else ""),
                body=json.dumps(payload).encode() if auth else None,
                headers=headers,
            )
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            event.update(
                http_status=response.status,
                wire_sha256=digest(raw),
                wire_bytes=len(raw),
                received_at=datetime.now(UTC).isoformat(),
            )
            if len(raw) > 4 * 1024 * 1024:
                event["body_status"] = "OVERSIZE_PREFIX_HASH_ONLY"
                raise RuntimeError("RESPONSE_TOO_LARGE")
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                event["body_status"] = "UNPARSED_BYTES_HASH_ONLY"
                return HttpReply(status=response.status, body={})
            if not isinstance(body, dict):
                event["body_status"] = "INVALID_SHAPE_HASH_ONLY"
                return HttpReply(status=response.status, body={})
            secrets = tuple(
                s.get_secret_value()
                for s in (config.app_key, config.app_secret, config.account_ref)
                if s
            )
            bearer = headers.get("authorization", "").removeprefix("Bearer ")
            if bearer:
                secrets += (bearer,)
            # Auth tokens never retained; quotation bytes must pass the sensitive-data check.
            unsafe = auth or sensitive(body) or any(s.encode() in raw for s in secrets if s)
            event["body_status"] = "SENSITIVE_HASH_ONLY" if unsafe else "WIRE_BYTES_RETAINED"
            if not unsafe:
                raw_path = self.folder / "wire" / (digest(raw) + ".bin")
                immutable_write(raw_path, raw)
                event["wire_path"] = raw_path.relative_to(self.folder).as_posix()
            if not auth:
                clean = scrub(body, secrets)
                clean_bytes = canonical(clean)
                clean_hash = digest(clean_bytes)
                immutable_write(self.folder / "canonical" / (clean_hash + ".json"), clean_bytes)
                event["canonical_sha256"] = clean_hash
                body = clean
            return HttpReply(status=response.status, body=body)
        except Exception:
            event.setdefault("body_status", "IO_FAILED_NO_BODY")
            raise RuntimeError("PANEL_RESPONSE_FAILED_INPUTS_SUPPRESSED") from None
        finally:
            connection.close()
            self.state["response_completed_epoch"] = time.time()
            self.last_monotonic = time.monotonic()
            self.state["response_pending"] = False
            self.state["events"].append(event)
            self.last_event = event
            immutable_write(self.folder / "events" / f"{number:04}.json", canonical(event))
            atomic_json(self.budget_path, self.state)
