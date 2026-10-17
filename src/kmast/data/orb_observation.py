"""Offline quotation observations. No authentication, socket, broker or order capabilities."""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Literal

from kmast.data.models import KST
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest

COLUMNS: dict[str, list[str]] = json.loads(
    files("kmast.brokers.kis").joinpath("ws_columns.json").read_bytes()
)


@dataclass(frozen=True)
class Receipt:
    received_at: datetime
    monotonic_ns: int
    connection: str
    sequence: int
    origin: Literal["SYNTHETIC", "OBSERVED"] = "SYNTHETIC"

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            raise ValueError("AWARE_RECEIPT_TIME_REQUIRED")
        object.__setattr__(self, "received_at", self.received_at.astimezone(UTC))


@dataclass(frozen=True)
class Context:
    day: date
    market: str
    regular_open: datetime
    calendar_verified: bool = False
    continuous_verified: bool = False
    corrections_verified: bool = False
    evidence: str = "UNKNOWN"


@dataclass(frozen=True)
class Tick:
    channel: str
    symbol: str
    exchange_time: datetime | None
    receipt: Receipt
    raw_sha256: str
    row_identity: str
    fields: dict[str, str]
    flags: tuple[str, ...]
    context: Context

    def number(self, key: str) -> Decimal:
        value = Decimal(self.fields[key])
        if not value.is_finite() or value < 0:
            raise ValueError("INVALID_QUOTATION_NUMBER")
        return value


def parse(raw: bytes, receipt: Receipt, context: Context) -> tuple[Tick, ...]:
    """Quotes have no business date; bind only with independently verified context."""
    if (
        receipt.received_at.tzinfo is None
        or receipt.monotonic_ns < 0
        or receipt.sequence < 1
        or not receipt.connection
        or receipt.origin not in {"SYNTHETIC", "OBSERVED"}
        or context.regular_open.tzinfo is None
        or context.regular_open.astimezone(KST).date() != context.day
        or context.market not in {"KOSPI", "KOSDAQ"}
        or len(raw) > 1024 * 1024
    ):
        raise ValueError("INVALID_RECEIPT_CONTEXT")
    try:
        prefix, channel, count_text, payload = raw.decode("ascii").split("|", 3)
        if prefix != "0" or channel not in COLUMNS:
            raise ValueError
        count = int(count_text)
        values, columns = payload.split("^"), COLUMNS[channel]
        if not 1 <= count <= 100 or len(values) != count * len(columns):
            raise ValueError
        ticks = []
        if receipt.origin == "OBSERVED" and context.evidence == "SYNTHETIC_ONLY":
            raise ValueError
        for index in range(count):
            row = dict(
                zip(columns, values[index * len(columns) : (index + 1) * len(columns)], strict=True)
            )
            symbol = row["MKSC_SHRN_ISCD"]
            if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
                raise ValueError
            flags = ["PROVIDER_SEQUENCE_UNAVAILABLE", "VI_RESUMPTION_UNKNOWN"]
            trade = channel == "H0STCNT0"
            day = datetime.strptime(row["BSOP_DATE"], "%Y%m%d").date() if trade else context.day
            clock = row["STCK_CNTG_HOUR"] if trade else row["BSOP_HOUR"]
            stamp = datetime.strptime(day.strftime("%Y%m%d") + clock, "%Y%m%d%H%M%S").replace(
                tzinfo=KST
            )
            if day != context.day:
                flags.append("BUSINESS_DATE_MISMATCH")
            if not trade and not context.calendar_verified:
                flags.append("QUOTE_DATE_UNKNOWN")
                event_time = None
            else:
                event_time = stamp
            if not context.calendar_verified or not context.continuous_verified:
                flags.append("MARKET_STATE_UNKNOWN")
            if not context.corrections_verified:
                flags.append("CORRECTION_CANCEL_UNKNOWN")
            if trade and row["TRHT_YN"] != "N":
                flags.append("HALT_OR_STATE_UNKNOWN")
            tick = Tick(
                channel,
                symbol,
                event_time,
                receipt,
                digest(raw),
                digest(canonical([channel, row])),
                row,
                tuple(flags),
                context,
            )
            keys = (
                ["STCK_PRPR", "CNTG_VOL", "ACML_VOL", "ACML_TR_PBMN"]
                if trade
                else [
                    f"{side}{level}"
                    for side in ("ASKP", "BIDP", "ASKP_RSQN", "BIDP_RSQN")
                    for level in range(1, 11)
                ]
            )
            for key in keys:
                tick.number(key)
            if trade and (tick.number("STCK_PRPR") <= 0 or tick.number("CNTG_VOL") <= 0):
                raise ValueError
            ticks.append(tick)
        return tuple(ticks)
    except (ValueError, KeyError, ArithmeticError, UnicodeError):
        raise ValueError("INVALID_PUBLIC_QUOTATION_FRAME_INPUT_SUPPRESSED") from None


class FrameArchive:
    """Append-only public quotation receipts; controls/auth/account frames are rejected."""

    def __init__(self, folder: Path, *, cap: int = 1024 * 1024 * 1024):
        self.folder, self.cap = folder, cap
        self.journal = folder / "journal.json"
        self.records: list[dict[str, object]] = (
            json.loads(self.journal.read_bytes()) if self.journal.exists() else []
        )

    def append(
        self, raw: bytes, receipt: Receipt, context: Context, secrets: tuple[bytes, ...] = ()
    ) -> tuple[Tick, ...]:
        if any(secret and secret in raw for secret in secrets):
            raise PermissionError("SENSITIVE_MESSAGE_NOT_RETAINED")
        ticks = parse(raw, receipt, context)
        if sum(int(str(r["bytes"])) for r in self.records) + len(raw) > self.cap:
            raise PermissionError("RAW_STORAGE_CAP")
        key = f"{receipt.connection}:{receipt.sequence}"
        if any(r["receipt_id"] == key for r in self.records):
            raise ValueError("RECEIPT_ID_ALREADY_RETAINED")
        immutable_write(self.folder / "wire" / (digest(raw) + ".bin"), raw)
        record = dict(
            receipt_id=key,
            sha256=digest(raw),
            bytes=len(raw),
            received_at=receipt.received_at.isoformat(),
            monotonic_ns=receipt.monotonic_ns,
            origin=receipt.origin,
        )
        immutable_write(
            self.folder / "receipts" / (digest(key.encode()) + ".json"), canonical(record)
        )
        self.records.append(record)
        atomic_json(self.journal, self.records)
        return ticks

    def verify(self) -> None:
        assert len({r["receipt_id"] for r in self.records}) == len(self.records)
        for record in self.records:
            raw = (self.folder / "wire" / (str(record["sha256"]) + ".bin")).read_bytes()
            assert digest(raw) == record["sha256"] and len(raw) == record["bytes"]
            receipt_path = (
                self.folder / "receipts" / (digest(str(record["receipt_id"]).encode()) + ".json")
            )
            assert receipt_path.read_bytes() == canonical(record)


@dataclass
class OpeningResearch:
    """Observed-data diagnostics, not a strategy or execution simulator."""

    context: Context
    symbol: str
    trades: list[Tick] = field(default_factory=list)
    quotes: list[Tick] = field(default_factory=list)
    defects: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    connection: str | None = None
    last_monotonic: int = -1
    last_sequence: int = 0
    last_frame_hash: str | None = None
    last_received: datetime | None = None
    last_by_channel: dict[str, datetime] = field(default_factory=dict)
    validated_availability: dict[str, datetime] = field(default_factory=dict)
    expected: set[str] = field(default_factory=lambda: set(COLUMNS))
    acknowledged: set[str] = field(default_factory=set)
    acknowledgement_times: dict[str, datetime] = field(default_factory=dict)

    def acknowledge(self, channel: str, available_at: datetime) -> None:
        if channel not in self.expected:
            raise PermissionError("PUBLIC_QUOTE_CHANNELS_ONLY")
        if available_at.tzinfo is None:
            raise ValueError("ACKNOWLEDGEMENT_RECEIPT_REQUIRED")
        self.acknowledged.add(channel)
        self.acknowledgement_times[channel] = available_at

    def subscribed_at(self, asof: datetime) -> bool:
        return self.acknowledged == self.expected and all(
            self.acknowledgement_times.get(channel, asof + timedelta(seconds=1)) <= asof
            for channel in self.expected
        )

    def disconnect(self) -> None:
        self.defects.add("DISCONNECTED_NO_BACKFILL")
        self.acknowledged.clear()
        self.acknowledgement_times.clear()

    def ingest(self, tick: Tick, *, validated_at: datetime | None = None) -> None:
        if tick.symbol != self.symbol or tick.context != self.context:
            raise ValueError("OBSERVATION_CONTEXT_MISMATCH")
        r = tick.receipt
        if validated_at is None:
            if r.origin != "SYNTHETIC":
                self.defects.add("VALIDATED_AVAILABILITY_UNKNOWN")
                return
            # Explicit zero parse-delay assumption for test fixtures only.
            validated_at = r.received_at
        if validated_at.tzinfo is None or validated_at < r.received_at:
            raise ValueError("VALIDATION_CANNOT_PRECEDE_RECEIPT")
        if self.connection is not None and r.connection != self.connection:
            self.defects.add("RECONNECTED_WINDOW_INCOMPLETE")
            self.acknowledged.clear()
            self.acknowledgement_times.clear()
            self.last_sequence = 0
        self.connection = r.connection
        # Local receipt sequence is not a provider exchange sequence.
        if r.monotonic_ns < self.last_monotonic or (
            self.last_received and r.received_at < self.last_received
        ):
            self.defects.add("RECEIPT_ORDER_INVERSION")
        if r.sequence < self.last_sequence or r.sequence > self.last_sequence + 1:
            self.defects.add("LOCAL_RECEIPT_GAP_OR_INVERSION")
        if r.sequence == self.last_sequence and tick.raw_sha256 != self.last_frame_hash:
            self.defects.add("LOCAL_RECEIPT_SEQUENCE_REUSED")
        self.last_frame_hash = tick.raw_sha256
        self.last_monotonic, self.last_sequence, self.last_received = (
            r.monotonic_ns,
            r.sequence,
            r.received_at,
        )
        if tick.row_identity in self.seen:
            self.defects.add("DUPLICATE_SUSPECTED_NO_PROVIDER_ID")
            return
        self.seen.add(tick.row_identity)
        self.validated_availability[tick.row_identity] = validated_at
        if tick.exchange_time is None:
            self.defects.add("SOURCE_DATE_UNKNOWN")
            return
        stamp = tick.exchange_time
        if "BUSINESS_DATE_MISMATCH" in tick.flags:
            self.defects.add("BUSINESS_DATE_MISMATCH")
            return
        if stamp < self.context.regular_open and self.context.calendar_verified:
            return  # Excluded auction/preopen inactivity is not a continuous-session gap.
        previous = self.last_by_channel.get(tick.channel)
        if previous and stamp < previous:
            self.defects.add("EXCHANGE_ORDER_INVERSION")
        if previous and stamp - previous > timedelta(seconds=5):
            self.defects.add("INACTIVITY_OR_MISSING_SUSPECTED")
        self.last_by_channel[tick.channel] = stamp
        lag = (r.received_at - stamp).total_seconds()
        if not 0 <= lag <= 2:
            self.defects.add("SOURCE_RECEIPT_LAG_UNSAFE")
        blocking = set(tick.flags) - {"PROVIDER_SEQUENCE_UNAVAILABLE", "VI_RESUMPTION_UNKNOWN"}
        if blocking:
            self.defects.update(blocking)
            return
        if stamp < self.context.regular_open:
            return  # Auction policy: excluded, never reset cumulative baseline into VWAP.
        if tick.channel == "H0STCNT0":
            if self.trades and tick.number("ACML_VOL") < self.trades[-1].number("ACML_VOL"):
                self.defects.add("CUMULATIVE_REGRESSION_CORRECTION_OR_GAP")
            if self.trades and tick.number("ACML_VOL") - self.trades[-1].number(
                "ACML_VOL"
            ) != tick.number("CNTG_VOL"):
                self.defects.add("CUMULATIVE_VOLUME_GAP")
            if self.trades and tick.number("ACML_TR_PBMN") < self.trades[-1].number("ACML_TR_PBMN"):
                self.defects.add("CUMULATIVE_TURNOVER_REGRESSION")
            self.trades.append(tick)
        else:
            if tick.number("ASKP1") <= tick.number("BIDP1") or tick.number("BIDP1") <= 0:
                self.defects.add("LOCKED_CROSSED_OR_EMPTY_QUOTE")
            if tick.number("ASKP_RSQN1") <= 0 or tick.number("BIDP_RSQN1") <= 0:
                self.defects.add("NO_OBSERVED_TOP_QUOTE_LIQUIDITY")
            self.quotes.append(tick)

    def range_high(self, minutes: Literal[5, 15], asof: datetime) -> Decimal | None:
        end = self.context.regular_open + timedelta(minutes=minutes)
        if minutes not in {5, 15} or asof.tzinfo is None:
            raise ValueError("FROZEN_RANGE_CONTEXT_REQUIRED")
        available = [t for t in self.trades if self.validated_availability[t.row_identity] <= asof]
        if (
            self.defects
            or not self.subscribed_at(asof)
            or asof < end + timedelta(seconds=2)
            or not available
            or available[0].exchange_time != self.context.regular_open
            or not any(t.exchange_time is not None and t.exchange_time >= end for t in available)
        ):
            return None
        selected = [
            t
            for t in available
            if t.exchange_time is not None and self.context.regular_open <= t.exchange_time < end
        ]
        return max((t.number("STCK_PRPR") for t in selected), default=None)

    def vwap(self, asof: datetime) -> Decimal | None:
        if self.defects or not self.subscribed_at(asof):
            return None
        rows = [t for t in self.trades if self.validated_availability[t.row_identity] <= asof]
        volume = sum((t.number("CNTG_VOL") for t in rows), Decimal(0))
        return (
            sum((t.number("STCK_PRPR") * t.number("CNTG_VOL") for t in rows), Decimal(0)) / volume
            if volume
            else None
        )

    def later_quote(self, signal_received_at: datetime, asof: datetime) -> Tick | None:
        if self.defects or not self.subscribed_at(signal_received_at):
            return None
        rows = [
            q
            for q in self.quotes
            if signal_received_at < q.receipt.received_at <= asof
            and self.validated_availability[q.row_identity] <= asof
            and (asof - q.receipt.received_at).total_seconds() <= 1
            and q.exchange_time is not None
            and signal_received_at <= q.exchange_time <= asof
            and (asof - q.exchange_time).total_seconds() <= 1
        ]
        return rows[-1] if rows else None

    def rvol_status(self) -> str:
        return "RVOL_NOT_READY"  # No historical same-elapsed-time baseline implemented here.


def require_pilot_permission(
    *, approved: bool, environment: str, entitlement_verified: bool
) -> None:
    if not approved or environment != "PAPER" or not entitlement_verified:
        raise PermissionError("EXPLICIT_PAPER_PILOT_AND_ENTITLEMENT_REQUIRED")
    # This milestone intentionally has no network collector entry point.
