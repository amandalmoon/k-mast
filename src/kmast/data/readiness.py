from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from kmast.core.base import Contract, Identifier, Nonnegative
from kmast.data.models import Observation

REQUIREMENTS: dict[str, frozenset[str]] = {
    "A": frozenset(
        {"daily_history", "pit_universe", "index_sector", "corporate_actions", "delisted"}
    ),
    "B": frozenset({"opening_range", "vwap_rvol", "latency", "spread", "fill_evidence"}),
    "C": frozenset({"intraday", "vwap", "bid_ask", "liquidity", "adverse_selection"}),
    "D": frozenset(
        {"dart", "publication_pit", "correction_lineage", "event_mapping", "exante_baseline"}
    ),
}


class AvailabilityEntry(Contract):
    source: Identifier
    symbols: tuple[str, ...]
    obtained_start: date | None
    obtained_end: date | None
    resolution: Identifier
    venues: tuple[str, ...]
    sessions: tuple[str, ...]
    expected_observations: int | None = Field(default=None, ge=1)
    observed_unique: int = Field(ge=0)
    missing_rate: Nonnegative | None
    valid_observation_days: int = Field(ge=0)
    actual_lag_seconds: tuple[Nonnegative, ...]
    pit_reconstructable: bool | None = None
    corporate_action_ready: bool | None = None
    delisted_included: bool | None = None
    license_ref: Identifier | None = None
    acquisition_cost_krw: Nonnegative | None = None
    data_origin: Literal["SYNTHETIC_FIXTURE", "KIS_READONLY", "DART_READONLY"]
    evidence: tuple[tuple[Identifier, Identifier], ...] = ()
    quality_passed: bool = False
    period_precision_approved_by: Identifier | None = None

    @model_validator(mode="after")
    def evidence_consistency(self) -> Self:
        if self.expected_observations is None:
            if self.missing_rate is not None:
                raise ValueError("unknown denominator cannot have zero missing rate")
        else:
            if self.observed_unique > self.expected_observations:
                raise ValueError("observations exceed expected coverage grid")
            expected = Decimal(1) - Decimal(self.observed_unique) / Decimal(
                self.expected_observations
            )
            if self.missing_rate != expected:
                raise ValueError("incorrect coverage arithmetic")
        return self


def coverage(
    records: tuple[Observation, ...], expected_keys: frozenset[tuple[str, date]] | None = None
) -> dict[str, int | Decimal | None]:
    valid = {(r.symbol, r.exchange_date) for r in records if r.complete and not r.quality_flags}
    if expected_keys is None:
        return {"expected": None, "observed": len(valid), "missing_rate": None}
    if not expected_keys:
        raise ValueError("empty expected coverage grid")
    observed = len(valid & expected_keys)
    return {
        "expected": len(expected_keys),
        "observed": observed,
        "missing_rate": Decimal(1) - Decimal(observed) / Decimal(len(expected_keys)),
    }


def strategy_status(strategy: str, entries: tuple[AvailabilityEntry, ...]) -> dict[str, object]:
    required = REQUIREMENTS[strategy]
    # Synthetic fixtures never supply readiness evidence for a real strategy.
    real = tuple(
        e for e in entries if e.data_origin != "SYNTHETIC_FIXTURE" and e.observed_unique > 0
    )
    evidence = {
        key
        for e in real
        for key, ref in e.evidence
        if ref and e.license_ref and e.quality_passed and e.period_precision_approved_by
    }
    missing = sorted(required - evidence)
    ready = (
        bool(real)
        and not missing
        and all(
            e.pit_reconstructable is True
            and e.obtained_start is not None
            and e.obtained_end is not None
            and e.expected_observations is not None
            and e.missing_rate == 0
            for e in real
        )
    )
    status = "DATA_READY" if ready else ("DATA_PARTIAL" if real else "DATA_BLOCKED")
    return {
        "strategy": strategy,
        "status": status,
        "missing": missing,
        "economic_approval": False,
        "live_approved": False,
    }


def build_matrix(
    entries: tuple[AvailabilityEntry, ...], generated_at: datetime
) -> dict[str, object]:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("aware matrix timestamp required")
    return {
        "name": "DATA_AVAILABILITY_MATRIX",
        "generated_at": generated_at.isoformat(),
        "sources": [e.model_dump(mode="json") for e in entries],
        "strategies": [strategy_status(s, entries) for s in REQUIREMENTS],
    }
