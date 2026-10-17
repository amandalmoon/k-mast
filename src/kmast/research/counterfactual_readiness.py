"""Input sufficiency only; no outcome fields and no new matching algorithm."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlEvidence:
    standard_code: str
    pit_at_decision: bool
    prior_sessions: int
    historical_feature_availability: bool
    tradability_liquidity: bool
    safe_corporate_link: bool
    decision_time_census: bool
    correction_lineage: bool
    future_contamination_coverage: bool

    def preselectable(self) -> bool:
        return (
            self.pit_at_decision
            and self.prior_sessions >= 20
            and self.historical_feature_availability
            and self.tradability_liquidity
            and self.safe_corporate_link
            and self.decision_time_census
            and self.correction_lineage
        )


def readiness(rows: tuple[ControlEvidence, ...]) -> dict[str, int | str]:
    if len({r.standard_code for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_SECURITY_NOT_INDEPENDENT_CANDIDATE")
    preselected = sum(r.preselectable() for r in rows)
    # A future audit cannot determine the predecision candidate pool.
    return dict(
        status="READY_FOR_FROZEN_MATCHING" if preselected >= 3 else "UNMATCHED",
        pit_candidates=sum(r.pit_at_decision for r in rows),
        prior20_candidates=sum(r.prior_sessions >= 20 for r in rows),
        safe_dart_candidates=sum(
            r.safe_corporate_link and r.decision_time_census and r.correction_lineage for r in rows
        ),
        preselectable_candidates=preselected,
        future_auditable_candidates=sum(
            r.preselectable() and r.future_contamination_coverage for r in rows
        ),
    )
