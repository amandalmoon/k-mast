from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from kmast.core.base import Contract, Identifier, Nonnegative, Positive
from kmast.core.enums import AvailabilityMethod
from kmast.data.normalization import content_hash

# Fixed offset: Asia/Seoul has no DST for the supported modern KIS date range.
KST = timezone(timedelta(hours=9), "Asia/Seoul")
Kind = Literal["DAILY", "MINUTE", "TRADE", "QUOTE", "INDEX"]
Venue = Literal["KRX", "NXT", "CONSOLIDATED"]
Session = Literal["REGULAR", "AUCTION", "AFTER_HOURS", "UNKNOWN"]


class Provenance(Contract):
    source: Identifier
    endpoint: Identifier
    tr_id: Identifier
    symbol: Annotated[str, Field(pattern=r"^\d{4}(\d{2})?$")]
    venue: Venue
    session: Session
    request_time: AwareDatetime
    received_at: AwareDatetime
    acquired_at: AwareDatetime
    source_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    parser_version: Identifier = "kis-v12-km001-1"
    ingestion_run_id: Identifier
    request_fingerprint: Identifier | None = None
    data_origin: Literal["SYNTHETIC_FIXTURE", "KIS_READONLY", "DART_READONLY"]

    @model_validator(mode="after")
    def times(self) -> Self:
        if self.received_at < self.request_time or self.acquired_at < self.received_at:
            raise ValueError("invalid acquisition chronology")
        return self


class Observation(Contract):
    record_id: Identifier
    kind: Kind
    symbol: Annotated[str, Field(pattern=r"^\d{4}(\d{2})?$")]
    venue: Venue
    session: Session
    exchange_date: date
    exchange_date_basis: Literal["SOURCE_BUSINESS_DATE", "RECEIPT_DATE_UNVERIFIED"] = (
        "SOURCE_BUSINESS_DATE"
    )
    source_time_of_day: str | None = None
    event_time: AwareDatetime | None = None
    bar_start: AwareDatetime | None = None
    bar_end: AwareDatetime | None = None
    received_at: AwareDatetime
    acquired_at: AwareDatetime
    available_at: AwareDatetime
    availability_method: AvailabilityMethod
    availability_evidence: Identifier
    open: Positive | None = None
    high: Positive | None = None
    low: Positive | None = None
    close: Positive | None = None
    price: Positive | None = None
    bid: Nonnegative | None = None
    ask: Nonnegative | None = None
    bid_size: Nonnegative | None = None
    ask_size: Nonnegative | None = None
    volume: Nonnegative | None = None
    turnover: Nonnegative | None = None
    price_basis: Literal["RAW", "ADJUSTED"] = "RAW"
    adjustment_asof: AwareDatetime | None = None
    complete: bool = False
    quality_flags: tuple[str, ...] = ()
    price_unit: Literal["KRW", "INDEX_POINTS"] = "KRW"
    volume_unit: Literal["SHARES", "UNVERIFIED"] = "SHARES"
    timestamp_precision: Literal["DATE_ONLY", "SECOND", "RECEIPT_ONLY"]
    source_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    parser_version: Identifier
    data_origin: Literal["SYNTHETIC_FIXTURE", "KIS_READONLY", "DART_READONLY"]

    @model_validator(mode="after")
    def semantics(self) -> Self:
        if self.acquired_at < self.received_at:
            raise ValueError("acquisition before receipt")
        if self.event_time and self.event_time.astimezone(KST).date() != self.exchange_date:
            raise ValueError("exchange date mismatch")
        if self.event_time and self.available_at < self.event_time:
            raise ValueError("availability before event")
        if self.availability_method == AvailabilityMethod.OBSERVED_LIVE:
            if self.available_at < self.received_at:
                raise ValueError("live availability before receipt")
        if self.kind in {"DAILY", "MINUTE"}:
            if None in (self.open, self.high, self.low, self.close):
                raise ValueError("OHLC required")
            assert self.open is not None and self.high is not None
            assert self.low is not None and self.close is not None
            if (
                not self.low
                <= min(self.open, self.close)
                <= max(self.open, self.close)
                <= self.high
            ):
                raise ValueError("invalid OHLC range")
            if self.volume is None:
                raise ValueError("missing volume is not zero volume")
        if self.kind == "MINUTE":
            if self.bar_start is None or self.bar_end is None or self.bar_end <= self.bar_start:
                raise ValueError("explicit bar interval required")
            if self.complete and self.available_at < self.bar_end:
                raise ValueError("complete bar cannot be available before interval end")
        if self.kind == "QUOTE" and (self.bid is None or self.ask is None):
            raise ValueError("bid/ask required")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("crossed quote")
        if self.kind in {"TRADE", "INDEX"} and self.price is None:
            raise ValueError("price required")
        if self.price_basis == "ADJUSTED" and self.adjustment_asof is None:
            raise ValueError("adjusted data requires adjustment knowledge time")
        return self

    def require_strategy_input(
        self, decision_at: datetime, *, executable_price: bool = False
    ) -> None:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("aware decision time required")
        if self.available_at > decision_at or self.quality_flags or not self.complete:
            raise ValueError("observation unavailable or quality locked")
        if self.adjustment_asof and self.adjustment_asof > decision_at:
            raise ValueError("future adjustment factors")
        if executable_price and self.price_basis != "RAW":
            raise ValueError("execution requires raw price")


class SecurityStatus(Contract):
    symbol: Annotated[str, Field(pattern=r"^\d{6}$")]
    name: Identifier
    listing_market: Literal["KOSPI", "KOSDAQ", "KONEX"]
    valid_from: date
    valid_to: date | None = None
    available_at: AwareDatetime
    state: Literal["LISTED", "SUSPENDED", "DELISTED"]
    managed: bool
    sector: Identifier | None = None
    classification_version: Identifier
    source_ref: Identifier

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("empty security interval")
        return self


def universe_asof(
    rows: tuple[SecurityStatus, ...], day: date, decision_at: datetime
) -> tuple[str, ...]:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("aware decision time required")
    selected = [
        r
        for r in rows
        if r.valid_from <= day
        and (r.valid_to is None or day < r.valid_to)
        and r.available_at <= decision_at
    ]
    if len({r.symbol for r in selected}) != len(selected):
        raise ValueError("ambiguous PIT security master")
    return tuple(sorted(r.symbol for r in selected if r.state == "LISTED" and not r.managed))


class CorporateAction(Contract):
    action_id: Identifier
    symbol: Annotated[str, Field(pattern=r"^\d{6}$")]
    kind: Literal[
        "SPLIT",
        "REVERSE_SPLIT",
        "CASH_DIVIDEND",
        "BONUS_ISSUE",
        "RIGHTS_ISSUE",
        "DELISTING",
        "SUSPENSION",
    ]
    announced_at: AwareDatetime
    effective_date: date
    payment_date: date | None = None
    quantity_multiplier: Positive | None = None
    cash_per_share: Nonnegative | None = None
    source_ref: Identifier

    @model_validator(mode="after")
    def effects(self) -> Self:
        if (
            self.kind in {"SPLIT", "REVERSE_SPLIT", "BONUS_ISSUE"}
            and self.quantity_multiplier is None
        ):
            raise ValueError("quantity action requires explicit multiplier")
        if self.kind == "CASH_DIVIDEND" and self.cash_per_share is None:
            raise ValueError("dividend requires explicit per-share cash")
        return self

    def require_single_recognition(
        self, price_basis: str, add_cash_or_quantity_effect: bool
    ) -> None:
        if price_basis not in {"RAW", "ADJUSTED"}:
            raise ValueError("unknown price basis")
        if price_basis != "RAW" and add_cash_or_quantity_effect:
            raise ValueError("adjusted prices and action effects would double count")


class EconomicSource(Contract):
    category: Literal[
        "COMMISSION",
        "TAX",
        "SPREAD",
        "LIQUIDITY",
        "LOT_SIZE",
        "BUYING_POWER",
        "SETTLED_CASH",
        "RECEIVABLES",
        "PAYABLES",
        "CASH_INTEREST",
        "SERVER_COST",
        "DATA_COST",
        "SERVICE_COST",
    ]
    status: Literal["VERIFIED", "UNVERIFIED", "SCENARIO"] = "UNVERIFIED"
    value: Decimal | None = Field(default=None, allow_inf_nan=False)
    unit: Identifier
    effective_from: date | None = None
    effective_to: date | None = None
    source_ref: Identifier | None = None
    version: Identifier

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("invalid economic schedule interval")
        if self.status == "VERIFIED" and (
            self.value is None or self.effective_from is None or self.source_ref is None
        ):
            raise ValueError("verified economics require source and effective date")
        if self.status == "UNVERIFIED" and self.value is not None:
            raise ValueError("unverified values must remain unknown")
        return self


def observation_id(kind: str, symbol: str, venue: str, time_key: str) -> str:
    return content_hash([kind, symbol, venue, time_key])


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(UTC)
