"""Independent B_BAR_ORB_V1 offline research. No auth, network, orders or fill model."""

import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from kmast.data.models import KST
from kmast.data.store import digest


def aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AWARE_BAR_CLOCK_REQUIRED")


@dataclass(frozen=True)
class Receipt:
    symbol: str
    tr_id: str
    request_at: datetime
    response_at: datetime
    validated_at: datetime
    query_at: datetime
    origin: Literal["SYNTHETIC", "OBSERVED"] = "SYNTHETIC"

    def __post_init__(self) -> None:
        for stamp in (self.request_at, self.response_at, self.validated_at, self.query_at):
            aware(stamp)
        if self.request_at > self.response_at or self.response_at > self.validated_at:
            raise ValueError("INVALID_HTTP_CHRONOLOGY")
        if len(self.symbol) != 6 or not self.symbol.isascii() or not self.symbol.isdigit():
            raise ValueError("BAR_SYMBOL_REQUIRED")
        if self.origin not in {"SYNTHETIC", "OBSERVED"}:
            raise ValueError("BAR_ORIGIN_REQUIRED")


@dataclass(frozen=True)
class Session:
    day: date
    opening: datetime
    closing: datetime
    venue: str = "KRX"
    label: Literal["START", "END", "UNKNOWN"] = "UNKNOWN"
    calendar_verified: bool = False
    label_verified: bool = False
    continuous_verified: bool = False
    corrections_verified: bool = False
    first_trade_at: datetime | None = None
    clock_verified: bool = False
    closed_bar_price_verified: bool = False
    volume_verified: bool = False
    evidence_kind: Literal["SYNTHETIC_ORACLE", "INDEPENDENT"] = "INDEPENDENT"

    def __post_init__(self) -> None:
        aware(self.opening)
        aware(self.closing)
        if self.opening >= self.closing or self.opening.astimezone(KST).date() != self.day:
            raise ValueError("INVALID_EXCHANGE_SESSION")
        if self.first_trade_at is not None:
            aware(self.first_trade_at)
            if not self.opening <= self.first_trade_at < self.closing:
                raise ValueError("FIRST_TRADE_OUTSIDE_SESSION")


@dataclass(frozen=True)
class Bar:
    symbol: str
    label_at: datetime | None
    start: datetime | None
    end: datetime | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    available_at: datetime
    response_sha256: str
    flags: tuple[str, ...]
    receipt: Receipt


@dataclass(frozen=True)
class Range:
    symbol: str
    minutes: int
    start: datetime
    end: datetime
    high: Decimal
    low: Decimal
    volume: Decimal
    available_at: datetime
    source_hashes: tuple[str, ...]
    origin: Literal["SYNTHETIC", "OBSERVED"]


@dataclass(frozen=True)
class Candidate:
    symbol: str
    minutes: int
    observed_close: Decimal
    available_at: datetime
    breakout_bar_end: datetime
    source_hashes: tuple[str, ...]
    origin: Literal["SYNTHETIC", "OBSERVED"]
    execution_verified: bool = False


def number(row: dict[str, object], name: str, *, positive: bool = True) -> Decimal:
    try:
        value = Decimal(str(row[name]))
        if not value.is_finite() or value < 0 or (positive and value == 0):
            raise ValueError
        return value
    except (KeyError, InvalidOperation, ValueError):
        raise ValueError("INVALID_BAR_NUMBER_INPUT_SUPPRESSED") from None


def body(raw: bytes) -> dict[str, object]:
    try:
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("rt_cd") != "0":
            raise ValueError
        # Only allow quotation-shaped bodies, never auth/account material.
        if any(k in raw.lower() for k in (b"access_token", b"approval_key", b"account_no")):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise ValueError("INVALID_BAR_RESPONSE_INPUT_SUPPRESSED") from None


def context_flags(session: Session, receipt: Receipt) -> set[str]:
    flags = set()
    if session.venue != "KRX":
        flags.add("VENUE_NOT_KRX")
    if not session.calendar_verified:
        flags.add("CALENDAR_UNKNOWN")
    if not session.continuous_verified:
        flags.add("MARKET_STATE_UNKNOWN")
    if not session.corrections_verified:
        flags.add("CORRECTION_COVERAGE_UNKNOWN")
    if not session.clock_verified:
        flags.add("CLOCK_BOUND_UNKNOWN")
    if receipt.origin == "OBSERVED" and session.evidence_kind == "SYNTHETIC_ORACLE":
        flags.add("SYNTHETIC_CONTEXT_CANNOT_QUALIFY_OBSERVED_DATA")
    if receipt.query_at > receipt.request_at:
        flags.add("FUTURE_QUERY")
    if receipt.request_at.astimezone(KST).date() != session.day:
        flags.add("HTTP_SESSION_DATE_MISMATCH")
    return flags


def parse_bars(raw: bytes, receipt: Receipt, session: Session) -> tuple[Bar, ...]:
    if receipt.tr_id != "FHKST03010200":
        raise PermissionError("ONLY_DOCUMENTED_TODAY_BAR_SCHEMA")
    data = body(raw)
    rows = data.get("output2")
    if not isinstance(rows, list) or not rows or len(rows) > 30:
        raise ValueError("BAR_ROWS_REQUIRED")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_BAR_ROW")
        flags = context_flags(session, receipt)
        label_at = start = end = None
        try:
            if not re.fullmatch(r"[0-9]{8}", str(row["stck_bsop_date"])) or not re.fullmatch(
                r"[0-9]{6}", str(row["stck_cntg_hour"])
            ):
                raise ValueError
            label_at = datetime.strptime(
                str(row["stck_bsop_date"]) + str(row["stck_cntg_hour"]), "%Y%m%d%H%M%S"
            ).replace(tzinfo=KST)
            if label_at.date() != session.day:
                flags.add("SOURCE_DATE_MISMATCH")
            if label_at.second or label_at.microsecond:
                flags.add("NON_MINUTE_BOUNDARY")
        except (KeyError, ValueError):
            flags.add("SOURCE_DATE_TIME_UNKNOWN")
        if label_at is not None and session.label_verified and session.label in {"START", "END"}:
            start = label_at if session.label == "START" else label_at - timedelta(minutes=1)
            end = start + timedelta(minutes=1)
            if start < session.opening or end > session.closing:
                flags.add("OUTSIDE_REGULAR_SESSION")
            if end > receipt.request_at:
                flags.add("INCOMPLETE_AT_REQUEST")
            if label_at > receipt.request_at:
                flags.add("FUTURE_BAR")
        else:
            flags.add("BAR_LABEL_SEMANTICS_UNKNOWN")
        op, hi, lo, cl = (
            number(row, k) for k in ("stck_oprc", "stck_hgpr", "stck_lwpr", "stck_prpr")
        )
        volume = number(row, "cntg_vol", positive=False)
        if not session.closed_bar_price_verified:
            flags.add("CLOSED_BAR_PRICE_MAPPING_UNKNOWN")
        if not session.volume_verified:
            flags.add("BAR_VOLUME_MAPPING_UNKNOWN")
        if hi < max(op, cl, lo) or lo > min(op, cl, hi):
            raise ValueError("INVALID_BAR_OHLC")
        if volume == 0:
            flags.add("ZERO_VOLUME_GHOST_OR_NO_TRADE")
        if session.first_trade_at is None:
            flags.add("FIRST_TRADE_UNKNOWN")
        elif end is not None and end <= session.first_trade_at and volume > 0:
            flags.add("PRE_FIRST_TRADE_VOLUME")
        if row.get("revised") or row.get("synthetic"):
            flags.add("CORRECTED_OR_SYNTHETIC_ROW")
        result.append(
            Bar(
                receipt.symbol,
                label_at,
                start,
                end,
                op,
                hi,
                lo,
                cl,
                volume,
                receipt.validated_at,
                digest(raw),
                tuple(sorted(flags)),
                receipt,
            )
        )
    labels = [b.label_at for b in result]
    return tuple(
        replace(b, flags=tuple(sorted(set(b.flags) | {"DUPLICATE_RESPONSE_ROW"})))
        if labels.count(b.label_at) > 1
        else b
        for b in result
    )


class BarLedger:
    """Append every version; as-of views never learn about a later correction early."""

    def __init__(self) -> None:
        self.observations: list[Bar] = []

    def append(self, bars: tuple[Bar, ...]) -> None:
        self.observations.extend(bars)

    def view(self, asof: datetime) -> tuple[Bar, ...]:
        aware(asof)
        grouped: dict[tuple[str, datetime | None], list[Bar]] = {}
        for bar in self.observations:
            if bar.available_at <= asof:
                grouped.setdefault((bar.symbol, bar.label_at), []).append(bar)
        result = []
        for versions in grouped.values():
            first = min(versions, key=lambda b: b.available_at)
            states = {
                (b.open, b.high, b.low, b.close, b.volume, b.flags, b.receipt.origin)
                for b in versions
            }
            if len(states) > 1:
                first = replace(
                    first, flags=tuple(sorted(set(first.flags) | {"CORRECTION_OBSERVED"}))
                )
            result.append(first)
        return tuple(result)


def opening_range(
    bars: tuple[Bar, ...], minutes: int, session: Session, asof: datetime
) -> Range | None:
    aware(asof)
    if minutes not in {5, 15}:
        raise ValueError("ONLY_ORB5_ORB15")
    end = session.opening + timedelta(minutes=minutes)
    selected = [b for b in bars if b.start is not None and session.opening <= b.start < end]
    if len(selected) != minutes or len({b.start for b in selected}) != minutes:
        return None  # Duplicates and correction versions cannot silently replace prior rows.
    if any(b.flags or b.available_at > asof for b in selected) or end > asof:
        return None
    if len({b.symbol for b in selected}) != 1:
        return None
    if len({b.receipt.origin for b in selected}) != 1:
        return None
    expected = {session.opening + timedelta(minutes=i) for i in range(minutes)}
    if {b.start for b in selected} != expected:
        return None
    return Range(
        selected[0].symbol,
        minutes,
        session.opening,
        end,
        max(b.high for b in selected),
        min(b.low for b in selected),
        sum((b.volume for b in selected), Decimal(0)),
        max(b.available_at for b in selected),
        tuple(sorted({b.response_sha256 for b in selected})),
        selected[0].receipt.origin,
    )


def breakout(window: Range, bar: Bar, asof: datetime) -> Candidate | None:
    aware(asof)
    if (
        bar.flags
        or bar.receipt.origin != window.origin
        or bar.symbol != window.symbol
        or bar.start is None
        or bar.end is None
        or bar.start < window.end
        or bar.close <= window.high
    ):
        return None
    available = max(window.available_at, bar.available_at)
    if available > asof:
        return None
    return Candidate(
        window.symbol,
        window.minutes,
        bar.close,
        available,
        bar.end,
        tuple(sorted(set(window.source_hashes) | {bar.response_sha256})),
        bar.receipt.origin,
    )


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    provider_at: datetime | None
    receipt: Receipt
    response_sha256: str
    flags: tuple[str, ...]
    date_basis: str = "INDEPENDENT_SESSION_CONTEXT_NOT_SOURCE_DATE"
    is_fill: bool = False


def parse_quote(raw: bytes, receipt: Receipt, session: Session) -> Quote:
    if receipt.tr_id != "FHKST01010200":
        raise PermissionError("ONLY_DOCUMENTED_QUOTE_SCHEMA")
    data = body(raw)
    row = data.get("output1")
    if not isinstance(row, dict):
        raise ValueError("QUOTE_ROW_REQUIRED")
    bid, ask = number(row, "bidp1"), number(row, "askp1")
    if bid > ask:
        raise ValueError("CROSSED_QUOTE")
    flags = context_flags(session, receipt)
    if receipt.request_at < session.opening or receipt.request_at >= session.closing:
        flags.add("QUOTE_OUTSIDE_REGULAR_SESSION")
    details = data.get("output2")
    if isinstance(details, dict) and details.get("stck_shrn_iscd") not in {None, receipt.symbol}:
        flags.add("QUOTE_SYMBOL_MISMATCH")
    provider = None
    try:
        provider = datetime.strptime(
            session.day.strftime("%Y%m%d") + str(row["aspr_acpt_hour"]), "%Y%m%d%H%M%S"
        ).replace(tzinfo=KST)
        if provider > receipt.response_at:
            flags.add("QUOTE_FUTURE_OR_CLOCK_UNKNOWN")
        if receipt.response_at - provider > timedelta(seconds=2):
            flags.add("QUOTE_AGE_EXCEEDS_RESEARCH_BOUND")
    except (ValueError, KeyError):
        flags.add("QUOTE_SOURCE_TIME_UNKNOWN")
    return Quote(receipt.symbol, bid, ask, provider, receipt, digest(raw), tuple(sorted(flags)))


def later_snapshot(signal: Candidate, quote: Quote) -> bool:
    return (
        quote.symbol == signal.symbol
        and quote.receipt.origin == signal.origin
        and not quote.flags
        and quote.receipt.request_at > signal.available_at
        and quote.receipt.validated_at >= quote.receipt.response_at
        and quote.provider_at is not None
        and quote.provider_at > signal.available_at
    )


@dataclass(frozen=True)
class Baseline:
    day: date
    symbol: str
    minutes: int
    volume: Decimal
    qualified: bool
    source_sha256: str


def rvol(
    volume: Decimal, previous: tuple[Baseline, ...], current_day: date, *, symbol: str, minutes: int
) -> Decimal | None:
    if (
        len(previous) != 20
        or minutes not in {5, 15}
        or len({b.day for b in previous}) != 20
        or any(
            b.day >= current_day
            or b.volume <= 0
            or not b.volume.is_finite()
            or not b.qualified
            or b.symbol != symbol
            or b.minutes != minutes
            or not re.fullmatch(r"[a-f0-9]{64}", b.source_sha256)
            for b in previous
        )
        or volume < 0
        or not volume.is_finite()
    ):
        return None
    return volume / (sum((b.volume for b in previous), Decimal(0)) / 20)
