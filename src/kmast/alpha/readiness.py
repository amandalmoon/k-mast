from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from kmast.alpha.models import AlphaConfig, Bar
from kmast.core.base import Contract, Identifier
from kmast.data.models import Observation
from kmast.data.normalization import content_hash


class DataEvidence(Contract):
    strategy: Literal["A", "B", "C", "D"]
    source: Identifier
    origin: Literal["SYNTHETIC", "REAL"]
    rows: int = Field(ge=0)
    start: date | None = None
    end: date | None = None
    symbols: tuple[Identifier, ...] = ()
    resolution: Identifier
    license_ref: Identifier | None = None
    period_coverage_ref: Identifier | None = None
    pit_universe_ref: Identifier | None = None
    corporate_actions_ref: Identifier | None = None
    missing_halts_delistings_ref: Identifier | None = None
    availability_ref: Identifier | None = None
    executable_market_ref: Identifier | None = None
    cost_ref: Identifier | None = None
    raw_hashes: tuple[Identifier, ...] = ()

    def blockers(self) -> tuple[str, ...]:
        missing = [
            name
            for name in (
                "license_ref",
                "period_coverage_ref",
                "pit_universe_ref",
                "corporate_actions_ref",
                "missing_halts_delistings_ref",
                "availability_ref",
                "executable_market_ref",
                "cost_ref",
            )
            if getattr(self, name) is None
        ]
        if self.origin != "REAL" or self.rows == 0:
            missing.append("REAL_ROWS_REQUIRED")
        if self.start is None or self.end is None or self.start > self.end or not self.symbols:
            missing.append("COVERAGE_REQUIRED")
        if not self.raw_hashes:
            missing.append("RAW_HASHES_REQUIRED")
        return tuple(missing)

    @property
    def status(self) -> str:
        return "DATA_BLOCKED" if self.blockers() else "DATA_READY_SCOPED"


class ResearchPlan(Contract):
    trial_id: Identifier
    config_hash: Identifier
    data_hash: Identifier
    research_start: AwareDatetime
    research_end: AwareDatetime
    validation_start: AwareDatetime
    validation_end: AwareDatetime
    locked_oos_start: AwareDatetime
    locked_oos_end: AwareDatetime
    registered_at: AwareDatetime
    exposures: tuple[Identifier, ...] = ()
    primary_metric: Literal["NET_OPERATING_PNL_KRW"] = "NET_OPERATING_PNL_KRW"
    oos_authorized: Literal[False] = False

    @model_validator(mode="after")
    def disjoint(self) -> "ResearchPlan":
        if not (
            self.research_start
            < self.research_end
            < self.validation_start
            < self.validation_end
            < self.locked_oos_start
            < self.locked_oos_end
        ):
            raise ValueError("research/validation/locked OOS overlap")
        return self

    def require_version(self, config: AlphaConfig, data_hash: str) -> None:
        if (
            self.config_hash != content_hash(config.model_dump(mode="json"))
            or self.data_hash != data_hash
        ):
            raise PermissionError("new strategy/data version requires a new registered study")


def observation_bar(row: Observation, identity: str) -> Bar:
    if (
        row.kind not in {"DAILY", "MINUTE"}
        or not row.complete
        or row.quality_flags
        or row.price_basis != "RAW"
        or row.venue != "KRX"
        or row.session != "REGULAR"
        or row.bar_start is None
        or row.bar_end is None
    ):
        raise ValueError("observation not eligible for alpha input")
    return Bar.model_validate(
        dict(
            identity=identity,
            symbol=row.symbol,
            start=row.bar_start,
            end=row.bar_end,
            available_at=row.available_at,
            resolution=row.kind,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            turnover=row.turnover,
            source_ref=row.source_hash,
            origin="REAL" if row.data_origin != "SYNTHETIC_FIXTURE" else "SYNTHETIC",
        )
    )


def economic_status(evidence: DataEvidence) -> str:
    # Readiness is necessary, never sufficient for an economic or OOS approval.
    return "HOLD_DATA" if evidence.blockers() else "HOLD_CONFIRMATORY_ECONOMICS_REQUIRED"
