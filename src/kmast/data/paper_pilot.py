"""DF014 exact-scope PAPER gates, crash-safe reservations and bounded FrameArchive."""

import json
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from kmast.data.models import KST
from kmast.data.orb_observation import COLUMNS, Context, FrameArchive, Receipt
from kmast.data.panel_acquisition import immutable_write
from kmast.data.store import canonical, digest

TARGETS = {"073240": "KOSPI", "462860": "KOSDAQ"}
CHANNELS = {"H0STCNT0", "H0STASP0"}
ENDPOINT = "ws://ops.koreainvestment.com:31000"
AUTH_URL = "https://openapivts.koreainvestment.com:29443/oauth2/Approval"
CAPS = {"AUTH": 1, "CONNECT": 2, "SUB": 8, "UNSUB": 4, "CONTROL": 2400}
CONTROL_RESERVE = 8 * 1024 * 1024


def window(now: datetime) -> None:
    if now.tzinfo is None:
        raise PermissionError("AWARE_PILOT_CLOCK_REQUIRED")
    local = now.astimezone(KST)
    if local.strftime("%Y-%m-%d") != "2026-10-19":
        raise PermissionError("EXACT_PILOT_DAY_REQUIRED_NO_RESCHEDULE")
    if not "08:50:00" <= local.strftime("%H:%M:%S") < "09:25:00":
        raise PermissionError("OUTSIDE_FROZEN_OBSERVATION_WINDOW")


def evidence(record: dict[str, Any], name: str) -> bool:
    entry = record.get(name)
    if not isinstance(entry, dict) or entry.get("verified") is not True:
        return False
    path, expected = entry.get("path"), entry.get("sha256")
    return bool(
        isinstance(path, str)
        and isinstance(expected, str)
        and Path(path).is_file()
        and digest(Path(path).read_bytes()) == expected
    )


def authorize(
    approval: dict[str, Any],
    preflight: dict[str, Any],
    protocol_hash: str,
    now: datetime,
    *,
    enabled: bool,
    environment: str,
) -> None:
    if not __debug__:
        raise PermissionError("OPTIMIZED_INTERPRETER_CANNOT_RUN_FROZEN_ARCHIVE_AUDIT")
    if not enabled or environment != "PAPER":
        raise PermissionError("EXPLICIT_PAPER_OPT_IN_REQUIRED")
    expected = dict(
        symbols=sorted(TARGETS),
        channels=sorted(CHANNELS),
        day="2026-10-19",
        start="08:50:00",
        end="09:25:00",
        timezone="Asia/Seoul",
        environment="PAPER",
        auth_max=1,
        connection_max=2,
        reconnect_max=1,
        subscriptions_max=8,
        unsubscriptions_max=4,
        controls_max=2400,
        outgoing_max=2412,
        raw_bytes_cap=1073741824,
        total_bytes_cap=3221225472,
        orders=False,
        accounts=False,
        live=False,
        protocol_sha256=protocol_hash,
    )
    if (
        any(approval.get(k) != value for k, value in expected.items())
        or approval.get("human_approved") is not True
        or not evidence(approval, "human_approval_record")
    ):
        raise PermissionError("EXACT_NEW_HUMAN_APPROVAL_RECORD_REQUIRED")
    requirements = [
        "security_status",
        "exchange_calendar",
        "paper_service",
        "four_subscription_entitlement",
        "subscription_hours",
        "usage_terms_fees",
        "official_endpoint",
        "transport_protection",
    ]
    if preflight.get("protocol_sha256") != protocol_hash or any(
        not evidence(preflight, key) for key in requirements
    ):
        raise PermissionError("PREFLIGHT_EVIDENCE_INCOMPLETE")
    # A plaintext Internet risk acceptance checkbox cannot replace protection evidence.
    if (
        preflight.get("transport_mode") != "VERIFIED_PROTECTED_PATH"
        or preflight.get("endpoint") != ENDPOINT
    ):
        raise PermissionError("PLAINTEXT_APPROVAL_KEY_TRANSPORT_NOT_CLEARED")
    window(now)


class Budget:
    """Immutable reservation journal is authoritative, including interrupted attempts."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self.used = dict.fromkeys(CAPS, 0)
        self.sequence, self.previous = 0, "GENESIS"
        for path in sorted((root / "reservations").glob("*.json")):
            raw = path.read_bytes()
            record = json.loads(raw)
            if (
                path.name != f"{self.sequence + 1:06}-{digest(raw)}.json"
                or record["sequence"] != self.sequence + 1
                or record["previous"] != self.previous
                or record["kind"] not in CAPS
            ):
                raise ValueError("RESERVATION_JOURNAL_CONFLICT")
            self.sequence += 1
            self.used[record["kind"]] += 1
            self.previous = digest(raw)
        if any(self.used[k] > cap for k, cap in CAPS.items()) or self.outgoing > 2412:
            raise ValueError("RESERVATION_BUDGET_CORRUPT")

    @property
    def outgoing(self) -> int:
        return sum(self.used[k] for k in ("SUB", "UNSUB", "CONTROL"))

    def reserve(self, kind: str) -> int:
        with self.lock:
            return self._reserve(kind)

    def _reserve(self, kind: str) -> int:
        if (
            kind not in CAPS
            or self.used[kind] >= CAPS[kind]
            or (kind in {"SUB", "UNSUB", "CONTROL"} and self.outgoing >= 2412)
        ):
            raise PermissionError("PILOT_PERSISTENT_BUDGET_EXHAUSTED")
        self.sequence += 1
        record = dict(
            sequence=self.sequence,
            kind=kind,
            previous=self.previous,
            reserved_at=datetime.now(UTC).isoformat(),
        )
        payload = canonical(record)
        used_bytes = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        if used_bytes + len(payload) + 65536 > CONTROL_RESERVE:
            raise PermissionError("CONTROL_STORE_CAP")
        immutable_write(
            self.root / "reservations" / f"{self.sequence:06}-{digest(payload)}.json", payload
        )
        self.previous = digest(payload)
        self.used[kind] += 1
        return self.sequence

    def result(
        self,
        sequence: int,
        *,
        category: str,
        response_hash: str | None = None,
        code: str | None = None,
    ) -> None:
        # Callers pass only closed classifications and constrained provider codes.
        if category not in {
            "SUCCESS",
            "HTTP_DENIED",
            "IO_FAILED",
            "SOCKET_OPEN",
            "SENT",
            "MALFORMED",
        }:
            raise ValueError("CLOSED_RESULT_CATEGORY_REQUIRED")
        if response_hash is not None and not re.fullmatch(r"[a-f0-9]{64}", response_hash):
            raise ValueError("RESPONSE_HASH_REQUIRED_NOT_BODY")
        if code is not None and not re.fullmatch(r"[A-Z0-9_-]{1,32}", code):
            raise ValueError("SANITIZED_CODE_REQUIRED")
        record = dict(
            sequence=sequence, category=category, response_sha256=response_hash, provider_code=code
        )
        immutable_write(self.root / "results" / f"{sequence:06}.json", canonical(record))


class BoundedArchive:
    """Single-writer segmented FrameArchive, exact final bytes plus conservative peak guard.

    Store paths are internal ordinals, never supplied by incoming messages. The
    process lock must surround construction, writes and verification.
    """

    def __init__(self, root: Path, *, raw_cap: int = 1073741824, total_cap: int = 3221225472):
        self.root, self.raw_cap, self.limit = root, raw_cap, total_cap - CONTROL_RESERVE
        if root.exists() and any(
            p.name not in {"archive", "control", "process.lock"} for p in root.iterdir()
        ):
            raise ValueError("ISOLATED_PILOT_STORE_REQUIRED")
        self.data = root / "archive"
        self.used = sum(p.stat().st_size for p in self.data.rglob("*") if p.is_file())
        self.raw_used, self.frames = 0, 0
        self.segment: FrameArchive | None = None
        self.segment_number = -1
        self.verify()
        for path in sorted((self.data / "segments").glob("*/journal.json")):
            records = json.loads(path.read_bytes())
            self.frames += len(records)
            self.raw_used += sum(r["bytes"] for r in records)
        if self.used > self.limit or self.raw_used > self.raw_cap:
            raise ValueError("EXISTING_STORAGE_OVER_CAP")

    def append(
        self, raw: bytes, receipt: Receipt, context: Context, secrets: tuple[bytes, ...]
    ) -> None:
        number = self.frames // 128
        if self.segment_number != number:
            self.segment = FrameArchive(self.data / "segments" / f"{number:08}")
            self.segment_number = number
        assert self.segment is not None
        # This bounds transient raw, immutable receipt and atomic journal temps;
        # metadata writes have their own exact reservation below.
        peak = len(raw) * 2 + len(canonical(self.segment.records)) * 2 + 65536
        if self.raw_used + len(raw) > self.raw_cap or self.used + peak > self.limit:
            raise PermissionError("PILOT_STORAGE_CAP_BEFORE_WRITE")
        paths = [
            self.segment.journal,
            self.segment.folder / "wire" / (digest(raw) + ".bin"),
            self.segment.folder
            / "receipts"
            / (digest(f"{receipt.connection}:{receipt.sequence}".encode()) + ".json"),
        ]
        before = sum(p.stat().st_size for p in paths if p.exists())
        self.segment.append(raw, receipt, context, secrets)
        after = sum(p.stat().st_size for p in paths if p.exists())
        self.used += after - before
        self.raw_used += len(raw)
        self.frames += 1

    def metadata(self, record: dict[str, Any]) -> None:
        payload = canonical(record) + b"\n"
        if len(payload) > 8 * 1024 * 1024 or self.used + len(payload) + 65536 > self.limit:
            raise PermissionError("PILOT_METADATA_CAP_BEFORE_WRITE")
        path = self.data / "observations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        # An interrupted final JSONL line is an integrity failure on resume,
        # never silently dropped. Raw/receipt originals remain available.
        import os

        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self.used += len(payload)

    def verify(self) -> None:
        for folder in (self.data / "segments").glob("*"):
            if (
                folder.is_dir()
                and any(folder.rglob("*"))
                and not (folder / "journal.json").exists()
            ):
                raise ValueError("INTERRUPTED_ARCHIVE_WITHOUT_JOURNAL")
        for path in (self.data / "segments").glob("*/journal.json"):
            archive = FrameArchive(path.parent)
            archive.verify()
            expected_wires = {str(r["sha256"]) + ".bin" for r in archive.records}
            if expected_wires != {p.name for p in (path.parent / "wire").glob("*.bin")}:
                raise ValueError("INTERRUPTED_ARCHIVE_ORPHAN_WIRE")
            referenced = {digest(str(r["receipt_id"]).encode()) + ".json" for r in archive.records}
            actual = {p.name for p in (path.parent / "receipts").glob("*.json")}
            if referenced != actual:
                raise ValueError("INTERRUPTED_ARCHIVE_ORPHAN_RECEIPT")
        path = self.data / "observations.jsonl"
        if path.exists():
            with path.open("rb") as handle:
                for line in handle:
                    if not line.endswith(b"\n"):
                        raise ValueError("INTERRUPTED_METADATA_LINE")
                    json.loads(line)


def benchmark(root: Path, raw: bytes, context: Context, count: int = 256) -> dict[str, Any]:
    """Synthetic disk throughput only, not measured provider capacity or latency."""
    store = BoundedArchive(root)
    start = time.perf_counter()
    latencies = []
    for index in range(count):
        frame_start = time.perf_counter()
        prefix, channel, count_text, payload = raw.decode("ascii").split("|", 3)
        values = payload.split("^")
        columns = COLUMNS[channel]
        values[columns.index("ACML_VOL")] = str(index + 1)
        time_key = "STCK_CNTG_HOUR" if channel == "H0STCNT0" else "BSOP_HOUR"
        values[columns.index(time_key)] = (
            context.regular_open + timedelta(seconds=index)
        ).strftime("%H%M%S")
        unique = ("|".join([prefix, channel, count_text, "^".join(values)])).encode()
        receipt = Receipt(context.regular_open, index + 1, "SYNTHETIC-BENCHMARK", index + 1)
        store.append(unique, receipt, context, ())
        store.metadata(dict(origin="SYNTHETIC", sequence=index + 1, hash=digest(unique)))
        latencies.append(time.perf_counter() - frame_start)
    elapsed = time.perf_counter() - start
    store.verify()
    return dict(
        origin="SYNTHETIC",
        frames=count,
        elapsed_seconds=elapsed,
        frames_per_second=count / elapsed,
        logical_file_bytes=store.used,
        measured_provider_rate=None,
        unique_raw_frames=True,
        max_write_seconds=max(latencies),
        p95_write_seconds=sorted(latencies)[int((count - 1) * 0.95)],
    )
