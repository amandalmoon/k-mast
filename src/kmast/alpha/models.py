from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from kmast.core.base import Contract, Identifier, Nonnegative, Positive, Weight
from kmast.core.contracts import TargetSnapshot


class Bar(Contract):
    identity: Identifier
    symbol: Identifier
    start: AwareDatetime
    end: AwareDatetime
    available_at: AwareDatetime
    resolution: Literal["DAILY", "MINUTE"]
    open: Positive
    high: Positive
    low: Positive
    close: Positive
    volume: Nonnegative
    turnover: Nonnegative
    # Actual eligible trade notional, never typical-price * volume presented as exact VWAP.
    source_ref: Identifier
    origin: Literal["SYNTHETIC", "REAL"] = "SYNTHETIC"
    raw_prices: Literal[True] = True

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.start < self.end <= self.available_at:
            raise ValueError("bar completion/availability invalid")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC inconsistent")
        if (self.volume == 0) != (self.turnover == 0):
            raise ValueError("volume/notional inconsistency")
        return self


class UniverseRecord(Contract):
    symbol: Identifier
    listed_at: AwareDatetime
    delisted_at: AwareDatetime | None = None
    known_at: AwareDatetime
    halted: bool = False
    sector: Identifier
    source_ref: Identifier

    def eligible(self, now: AwareDatetime) -> bool:
        return (
            self.known_at <= now
            and self.listed_at <= now
            and (self.delisted_at is None or now < self.delisted_at)
            and not self.halted
        )


class BookQuote(Contract):
    symbol: Identifier
    at: AwareDatetime
    available_at: AwareDatetime
    bid: Positive
    ask: Positive
    last_trade: Positive
    recovering_liquidity: bool
    information_shock: bool
    source_ref: Identifier

    @model_validator(mode="after")
    def spread(self) -> Self:
        if self.bid > self.ask or self.available_at < self.at:
            raise ValueError("crossed or noncausal quote")
        return self

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2


class EventFeature(Contract):
    event_id: Identifier
    family: Identifier
    symbol: Identifier
    mechanism: Literal["EARNINGS_SEASONAL", "BUYBACK_EXECUTED", "INDEX_DEMAND"]
    receipt_date: date
    published_at: AwareDatetime | None = None
    conservative_next_session: AwareDatetime
    available_at: AwareDatetime
    baseline_known_at: AwareDatetime
    observed: Decimal = Field(allow_inf_nan=False)
    prior_baseline: Decimal = Field(allow_inf_nan=False)
    revision: int = Field(ge=0, strict=True)
    supersedes_id: Identifier | None = None
    source_ref: Identifier

    @model_validator(mode="after")
    def release(self) -> Self:
        if self.published_at is None:
            if self.conservative_next_session.date() <= self.receipt_date:
                raise ValueError("date-only event requires a later eligible session")
            release = self.conservative_next_session
        else:
            release = self.published_at
        if self.available_at < release or self.baseline_known_at >= release:
            raise ValueError("event or comparison baseline is noncausal")
        return self


class PositionView(Contract):
    symbol: Identifier
    weight: Weight
    entry_price: Positive
    exit_deadline: AwareDatetime


class VolumeBaseline(Contract):
    symbol: Identifier
    session_date: date
    elapsed_minutes: int = Field(gt=0)
    cumulative_volume: Positive
    known_at: AwareDatetime


class Context(Contract):
    now: AwareDatetime
    session_open: AwareDatetime
    session_close: AwareDatetime
    next_session_open: AwareDatetime
    universe: tuple[UniverseRecord, ...]
    bars: tuple[Bar, ...]
    benchmark: tuple[Bar, ...] = ()
    quotes: tuple[BookQuote, ...] = ()
    events: tuple[EventFeature, ...] = ()
    consumed_event_families: tuple[Identifier, ...] = ()
    volume_baselines: tuple[VolumeBaseline, ...] = ()
    positions: tuple[PositionView, ...] = ()
    # Explicit PIT grid. Missing observations are never silently compressed into N days/minutes.
    expected_daily_ends: tuple[AwareDatetime, ...] = ()
    source_version: Identifier
    scope: Literal["SYNTHETIC", "REAL_UNVERIFIED"] = "SYNTHETIC"
    corporate_action_discontinuities: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def identity(self) -> Self:
        if not self.session_open < self.session_close < self.next_session_open:
            raise ValueError("invalid session calendar")
        if len({u.symbol for u in self.universe}) != len(self.universe):
            raise ValueError("duplicate PIT universe row")
        if len({b.identity for b in self.bars + self.benchmark}) != len(self.bars + self.benchmark):
            raise ValueError("duplicate bar identity")
        if len({(b.symbol, b.start, b.resolution) for b in self.bars}) != len(self.bars):
            raise ValueError("ambiguous bars")
        if len({p.symbol for p in self.positions}) != len(self.positions):
            raise ValueError("duplicate strategy position")
        if len({q.symbol for q in self.quotes}) != len(self.quotes):
            raise ValueError("duplicate quote")
        if len({b.end for b in self.benchmark}) != len(self.benchmark) or any(
            b.resolution != "DAILY" for b in self.benchmark
        ):
            raise ValueError("benchmark must be an unambiguous daily series")
        if tuple(sorted(set(self.expected_daily_ends))) != self.expected_daily_ends:
            raise ValueError("daily grid must be ordered and unique")
        return self


class AlphaConfig(Contract):
    strategy: Literal["A", "B", "C", "D"]
    version: Identifier = "candidate-v1"
    lookback: int = Field(default=20, ge=2, le=252)
    max_weight: Weight = Decimal(".25")
    volatility_budget: Positive = Decimal(".01")
    min_turnover: Nonnegative = Decimal(1000)
    min_relative_strength: Decimal = Field(default=Decimal(0), allow_inf_nan=False)
    range_minutes: Literal[5, 15] = 5
    min_rvol: Positive = Decimal("1.2")
    reversion_gap: Weight = Decimal(".01")
    max_spread: Weight = Decimal(".005")
    stop_fraction: Weight = Decimal(".05")
    order_lifetime: timedelta = Field(default=timedelta(minutes=1), gt=timedelta(0))
    max_holding: timedelta = Field(default=timedelta(days=5), gt=timedelta(0))
    quote_age: timedelta = Field(default=timedelta(seconds=10), gt=timedelta(0))
    event_mechanism: Literal["EARNINGS_SEASONAL", "BUYBACK_EXECUTED", "INDEX_DEMAND"] = (
        "EARNINGS_SEASONAL"
    )
    live_capital_weight: Literal[0] = 0


class AlphaResult(Contract):
    snapshot: TargetSnapshot
    exit_deadlines: tuple[tuple[Identifier, AwareDatetime], ...]
    earliest_execution_at: AwareDatetime
    execution_window_end: AwareDatetime | None = None
    feature_evidence: tuple[tuple[Identifier, tuple[Identifier, ...]], ...]
    reasons: tuple[tuple[Identifier, Identifier], ...]
    data_status: Literal["DATA_BLOCKED"] = "DATA_BLOCKED"
    live_approved: Literal[False] = False
