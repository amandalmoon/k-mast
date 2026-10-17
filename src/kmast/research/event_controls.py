"""DF011 preregistered non-event matching; no outcome or strategy optimization inputs."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from math import isfinite
from statistics import median


@dataclass(frozen=True)
class MatchingObservation:
    standard_code: str
    market: str
    decision_day: date
    feature_end: date
    feature_available_on: date
    features: tuple[float, float, float]
    pit_identity_verified: bool
    feature_availability_verified: bool
    non_event_verified: bool | None
    non_event_available_on: date | None = None

    def predecision_eligible(self) -> bool:
        return (
            self.pit_identity_verified
            and self.feature_availability_verified
            and self.feature_end < self.decision_day
            and self.feature_available_on < self.decision_day
            and all(isfinite(value) for value in self.features)
        )


def match_non_events(
    receipt: str,
    treatment: MatchingObservation,
    candidates: tuple[MatchingObservation, ...],
) -> tuple[str, ...]:
    """Three nearest same-date/market PIT controls, otherwise explicitly unmatched.

    Features: log median turnover, prior return, prior realized volatility. The
    non-event filter here covers only information available before decision.
    Future contamination is audited on this fixed selection, without rematching.
    Missing industry evidence is not replaced with current classification.
    """
    if not treatment.predecision_eligible():
        raise ValueError("TREATMENT_FEATURES_NOT_AVAILABLE_BEFORE_DECISION")
    if len({c.standard_code for c in candidates}) != len(candidates):
        raise ValueError("DUPLICATE_CONTROL_SECURITY")
    pool = tuple(
        c
        for c in candidates
        if c.predecision_eligible()
        and c.standard_code != treatment.standard_code
        and c.market == treatment.market
        and c.decision_day == treatment.decision_day
        and c.non_event_verified is True
        and c.non_event_available_on is not None
        and c.non_event_available_on < treatment.decision_day
    )
    if len(pool) < 3:
        return ()
    centers = [median(c.features[i] for c in pool) for i in range(3)]
    scales = [median(abs(c.features[i] - centers[i]) for c in pool) for i in range(3)]

    def rank(candidate: MatchingObservation) -> tuple[float, str]:
        distance = sum(
            ((candidate.features[i] - treatment.features[i]) / scales[i]) ** 2
            for i in range(3)
            if scales[i] > 0
        )
        tie = sha256((receipt + ":" + candidate.standard_code).encode()).hexdigest()
        return distance, tie

    return tuple(c.standard_code for c in sorted(pool, key=rank)[:3])


def audit_fixed_controls(
    selected: tuple[str, ...], post_event_clean: dict[str, bool | None]
) -> bool:
    """Post-entry contamination can invalidate a fixed set, never select replacements."""
    return len(selected) == 3 and all(post_event_clean.get(code) is True for code in selected)


def statistical_sample_admissible(
    events: int, firms: int, entry_days: int, declining_market_events: int, matched_fraction: float
) -> bool:
    """Frozen DF006 minimum; meeting it alone never establishes independent evidence."""
    return (
        events >= 30
        and firms >= 10
        and entry_days >= 20
        and declining_market_events >= 5
        and isfinite(matched_fraction)
        and 0.8 <= matched_fraction <= 1
    )
