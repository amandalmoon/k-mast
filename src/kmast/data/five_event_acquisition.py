"""DF012 bounded wire derived from frozen DF005; originals remain unchanged."""

import http.client
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from kmast.brokers.kis.network import HttpReply, Wire
from kmast.brokers.kis.wire_contract import validate_read_payload
from kmast.core.config import BrokerConfig
from kmast.core.enums import Environment
from kmast.data.panel_acquisition import atomic_json, immutable_write, sensitive
from kmast.data.store import canonical, digest, scrub


class ExpansionWire(Wire):
    """DF012 opt-in: five frozen stock windows and one index gap, total 24 calls, auth<=2.

    Unlike the original Wire, non-200/error responses are preserved when safe.
    Authentication bodies are hash-only and tokens exist only in memory.
    """

    def __init__(self, folder: Path, symbols: tuple[str, ...], *, enabled: bool = False):
        if set(symbols) != {"012330", "014130", "352770", "352700", "041960"} or any(
            not s.isascii() or not s.isdigit() or len(s) != 6 for s in symbols
        ):
            raise ValueError("FROZEN5_REQUIRED")
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
        self.last_monotonic = time.perf_counter()
        self.last_event: dict[str, Any] = {}
        self.session_requests = 0
        self.session_limit = 24
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
        allowed = self.symbols if request.operation == "daily" else ("0001",)
        if request.symbol not in allowed or headers.get("tr_id") != request.tr_id:
            raise PermissionError("SYMBOL_TR_SCOPE_DENIED")
        windows = {
            "012330": (date(2022, 10, 9), date(2023, 1, 7)),
            "014130": (date(2022, 8, 27), date(2022, 11, 25)),
            "352770": (date(2023, 7, 1), date(2023, 9, 29)),
            "352700": (date(2024, 9, 6), date(2024, 12, 5)),
            "041960": (date(2024, 3, 30), date(2024, 6, 28)),
            "0001": (date(2022, 8, 27), date(2022, 8, 31)),
        }
        if (request.start, request.end) != windows.get(request.symbol):
            raise PermissionError("EXACT_PAGE_DATE_SCOPE_DENIED")
        if request.operation == "index_daily" and request.price_basis != "RAW":
            raise PermissionError("INDEX_RAW_ONLY")
        fingerprint = digest(canonical([method, path, params]))
        if self.state.get("query_attempts", {}).get(fingerprint, 0) >= 2:
            raise PermissionError("QUERY_RETRY_CEILING")

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
            self.state["requests"] >= 24
            or self.session_requests >= self.session_limit
            or (auth and self.state["authentication"] >= 2)
        ):
            raise PermissionError("APPROVED_BUDGET_EXHAUSTED")
        # Both wall-time (across process resume) and monotonic time (within run).
        wall_wait = 3.10 - (time.time() - self.state["response_completed_epoch"])
        mono_wait = 3.10 - (time.perf_counter() - self.last_monotonic)
        while max(wall_wait, mono_wait) > 0:
            time.sleep(max(wall_wait, mono_wait))
            wall_wait = 3.10 - (time.time() - self.state["response_completed_epoch"])
            mono_wait = 3.10 - (time.perf_counter() - self.last_monotonic)
        self.state["requests"] += 1
        self.state["authentication"] += int(auth)
        self.state["response_pending"] = True
        if not auth:
            fingerprint = digest(canonical([method, path, payload]))
            attempts = self.state.setdefault("query_attempts", {})
            attempts[fingerprint] = attempts.get(fingerprint, 0) + 1
        self.session_requests += 1
        atomic_json(self.budget_path, self.state)
        number = self.state["requests"]
        before = datetime.now(UTC)
        event: dict[str, Any] = dict(
            sequence=number,
            kind="AUTH" if auth else "DAILY",
            completion_gap_perf_seconds=time.perf_counter() - self.last_monotonic,
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
            self.last_monotonic = time.perf_counter()
            self.state["response_pending"] = False
            self.state["events"].append(event)
            self.last_event = event
            immutable_write(self.folder / "events" / f"{number:04}.json", canonical(event))
            atomic_json(self.budget_path, self.state)
