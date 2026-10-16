from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from kmast.core.base import Contract, Identifier, Weight
from kmast.data.models import Observation, SecurityStatus, universe_asof
from kmast.portfolio.data_gate import ResearchDataGate

Permission = Literal["CONFIRMED", "PROHIBITED", "UNVERIFIED"]


class LicenseScope(Contract):
    provider: Identifier
    document_title: Identifier
    document_version: Identifier | None = None
    official_url: Identifier
    checked_at: AwareDatetime
    personal_program_use: Permission = "UNVERIFIED"
    private_analysis: Permission = "UNVERIFIED"
    strategy_development: Permission = "UNVERIFIED"
    internal_backtest: Permission = "UNVERIFIED"
    long_term_storage: Permission = "UNVERIFIED"
    raw_publication: Permission = "UNVERIFIED"
    derived_publication: Permission = "UNVERIFIED"
    commercial_service: Permission = "UNVERIFIED"
    third_party_data: Permission = "UNVERIFIED"
    applicable_agreement_ref: Identifier | None = None

    def research_allowed(self) -> bool:
        return bool(self.applicable_agreement_ref) and all(
            getattr(self, name) == "CONFIRMED"
            for name in (
                "private_analysis",
                "strategy_development",
                "internal_backtest",
                "long_term_storage",
            )
        )


class QualitySummary(Contract):
    total_rows: int = Field(ge=0)
    real_rows: int = Field(ge=0)
    synthetic_rows: int = Field(ge=0)
    unique_stock_days: int = Field(ge=0)
    raw_stock_days: int = Field(ge=0)
    adjusted_stock_days: int = Field(ge=0)
    index_days: int = Field(ge=0)
    conflicting_keys: int = Field(ge=0)
    duplicate_keys: int = Field(ge=0)
    missing_turnover_rows: int = Field(ge=0)
    quality_flags: tuple[Identifier, ...]
    expected_grid_verified: bool = False
    missing_rate: Weight | None = None
    denominator_status: Literal["VERIFIED", "UNVERIFIED"] = "UNVERIFIED"


def quality_summary(rows: tuple[Observation, ...]) -> QualitySummary:
    keys: dict[tuple[str, date, str, str, str], set[tuple[object, ...]]] = {}
    stock: set[tuple[str, date, str]] = set()
    raw: set[tuple[str, date, str]] = set()
    adjusted: set[tuple[str, date, str]] = set()
    index: set[tuple[str, date, str]] = set()
    for row in rows:
        key = (row.symbol, row.exchange_date, row.kind, row.venue, row.price_basis)
        keys.setdefault(key, set()).add(
            (row.open, row.high, row.low, row.close, row.price, row.volume, row.turnover)
        )
        identity = (row.symbol, row.exchange_date, row.venue)
        if row.kind == "DAILY":
            stock.add(identity)
            (raw if row.price_basis == "RAW" else adjusted).add(identity)
        elif row.kind == "INDEX":
            index.add(identity)
    synthetic = sum(r.data_origin == "SYNTHETIC_FIXTURE" for r in rows)
    return QualitySummary(
        total_rows=len(rows),
        real_rows=len(rows) - synthetic,
        synthetic_rows=synthetic,
        unique_stock_days=len(stock),
        raw_stock_days=len(raw),
        adjusted_stock_days=len(adjusted),
        index_days=len(index),
        conflicting_keys=sum(len(values) > 1 for values in keys.values()),
        duplicate_keys=len(rows) - len(keys),
        missing_turnover_rows=sum(r.kind == "DAILY" and r.turnover is None for r in rows),
        quality_flags=tuple(sorted({flag for row in rows for flag in row.quality_flags})),
    )


def g1(gate: ResearchDataGate, license_scope: LicenseScope, quality: QualitySummary) -> str:
    if not license_scope.research_allowed():
        return "HOLD_LICENSE_UNVERIFIED"
    if (
        gate.status != "DATA_READY_SCOPED"
        or quality.real_rows == 0
        or quality.synthetic_rows
        or quality.conflicting_keys
        or quality.duplicate_keys
        or quality.quality_flags
        or quality.missing_turnover_rows
        or quality.total_rows != gate.real_rows
        or not quality.expected_grid_verified
        or quality.denominator_status != "VERIFIED"
        or quality.missing_rate is None
    ):
        return "HOLD_DATA_QUALITY_PIT_EXECUTION_COST"
    return "DATA_READY_SCOPED"


def day_status(
    symbol: str,
    day: date,
    decision_at: datetime,
    calendar: tuple[date, ...] | None,
    master: tuple[SecurityStatus, ...],
    observed: bool,
) -> str:
    if calendar is None:
        return "UNKNOWN_CALENDAR"
    if day not in calendar:
        return "CLOSED"
    states = [
        row.state
        for row in master
        if row.symbol == symbol
        and row.available_at <= decision_at
        and row.valid_from <= day
        and (row.valid_to is None or day < row.valid_to)
    ]
    if len(states) == 1 and states[0] in {"SUSPENDED", "DELISTED"}:
        return states[0]
    eligible = universe_asof(master, day, decision_at)
    if symbol not in eligible:
        return "INELIGIBLE_OR_MASTER_UNKNOWN"
    return "OBSERVED" if observed else "MISSING_EXPECTED"


def corporate_action_basis(price_basis: str, book_actions: bool) -> None:
    if price_basis != "RAW" and book_actions:
        raise ValueError("adjusted prices and book actions would double count")
