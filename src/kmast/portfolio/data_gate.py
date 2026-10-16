from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from kmast.core.base import Contract, Identifier, Positive
from kmast.data.models import Observation, SecurityStatus, universe_asof


class ResearchDataGate(Contract):
    strategy: Literal["A", "B", "C", "D"]
    real_rows: int = Field(ge=0)
    synthetic_rows: int = Field(ge=0)
    symbols: tuple[Identifier, ...]
    start: date | None = None
    end: date | None = None
    origin_verified: bool
    hashes_verified: bool
    source_verified: bool
    license_evidence: Identifier | None = None
    quality_evidence: Identifier | None = None
    pit_universe_evidence: Identifier | None = None
    historical_release_evidence: Identifier | None = None
    corporate_action_evidence: Identifier | None = None
    executable_market_evidence: Identifier | None = None
    cost_policy_evidence: Identifier | None = None
    expected_grid_evidence: Identifier | None = None

    def blockers(self) -> tuple[str, ...]:
        reasons = []
        if not self.real_rows or self.synthetic_rows:
            reasons.append("REAL_ONLY_NONEMPTY_DATA_REQUIRED")
        if not self.hashes_verified or not self.origin_verified:
            reasons.append("HASH_OR_ORIGIN_UNVERIFIED")
        if not self.symbols or self.start is None or self.end is None or self.start > self.end:
            reasons.append("PERIOD_SYMBOL_COVERAGE_UNVERIFIED")
        for field in (
            "license_evidence",
            "quality_evidence",
            "pit_universe_evidence",
            "historical_release_evidence",
            "corporate_action_evidence",
            "executable_market_evidence",
            "cost_policy_evidence",
            "expected_grid_evidence",
        ):
            if not getattr(self, field):
                reasons.append(field.upper() + "_MISSING")
        return tuple(reasons)

    @property
    def status(self) -> str:
        if not self.source_verified:
            return "SOURCE_UNVERIFIED"
        if not self.real_rows:
            return "DATA_BLOCKED"
        if not self.license_evidence:
            return "LICENSE_HOLD"
        return "DATA_PARTIAL" if self.blockers() else "DATA_READY_SCOPED"


def require_research(
    gate: ResearchDataGate,
    rows: tuple[Observation, ...],
    master: tuple[SecurityStatus, ...],
    decision_at: datetime,
) -> None:
    if gate.status != "DATA_READY_SCOPED" or len(rows) != gate.real_rows:
        raise PermissionError("qualified scoped research data required")
    if any(row.data_origin != "KIS_READONLY" or row.symbol not in gate.symbols for row in rows):
        raise PermissionError("real data origin/symbol mismatch")
    for row in rows:
        row.require_strategy_input(decision_at)
        if row.symbol not in universe_asof(master, row.exchange_date, decision_at):
            raise PermissionError("historical master missing, suspended or delisted")


class EvaluationScope(Contract):
    capital_krw: Positive
    start: AwareDatetime
    end: AwareDatetime
    calendar: Identifier
    capital_policy: Identifier
    cost_policy: Identifier
    origin: Literal["SYNTHETIC", "REAL"]
    ledger: Literal["REFERENCE", "ACCOUNT"]


def compare_scopes(first: EvaluationScope, second: EvaluationScope) -> None:
    if first != second:
        raise ValueError("capital/time/calendar/cost/origin/ledger comparison mismatch")


def economic_gate(data: ResearchDataGate, costs_verified: bool, locked_oos_verified: bool) -> str:
    if data.synthetic_rows or not data.real_rows:
        return "HOLD_SYNTHETIC_CANNOT_PASS_G2_G3"
    if data.status != "DATA_READY_SCOPED":
        return "HOLD_DATA"
    if not costs_verified:
        return "HOLD_COST_SCENARIO_NOT_PROVEN_EXECUTION_COST"
    if not locked_oos_verified:
        return "HOLD_CONFIRMATORY_EVIDENCE"
    return "HOLD_INDEPENDENT_ECONOMIC_APPROVAL_REQUIRED"


def policy_to_keep(incremental_value_verified: bool) -> str:
    # This milestone has no model promotion capability, even when a diagnostic input is positive.
    return "PBASE_FIXED"
