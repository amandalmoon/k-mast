from typing import Self

from pydantic import AwareDatetime, model_validator

from kmast.core.base import Contract, Identifier, Nonnegative
from kmast.core.enums import AvailabilityMethod


class PointInTime(Contract):
    acquired_at: AwareDatetime | None = None
    availability_method: AvailabilityMethod
    availability_evidence: Identifier | None = None
    training_cutoff: AwareDatetime | None = None
    label_known_at: AwareDatetime | None = None
    fold_id: Identifier | None = None

    @model_validator(mode="after")
    def historical_evidence(self) -> Self:
        if self.availability_method != AvailabilityMethod.OBSERVED_LIVE:
            if self.acquired_at is None or self.availability_evidence is None:
                raise ValueError(
                    "historical availability requires acquisition and release evidence"
                )
        return self

    def require_mature_label(self) -> None:
        if self.training_cutoff is None or self.label_known_at is None or self.fold_id is None:
            raise ValueError("training lineage incomplete")
        if self.label_known_at > self.training_cutoff:
            raise ValueError("label not known at training cutoff")


class MarketEvent(PointInTime):
    event_id: Identifier
    symbol: Identifier
    venue: Identifier
    session: Identifier
    event_time: AwareDatetime
    received_at: AwareDatetime
    available_at: AwareDatetime
    source: Identifier
    quality_flags: tuple[str, ...] = ()
    revision: int = 0
    supersedes_id: Identifier | None = None
    price: Nonnegative | None = None

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if self.revision < 0:
            raise ValueError("negative revision")
        if self.available_at < self.event_time:
            raise ValueError("availability precedes event")
        if (
            self.availability_method == AvailabilityMethod.OBSERVED_LIVE
            and self.available_at < self.received_at
        ):
            raise ValueError("live availability precedes receipt")
        return self

    def require_available(self, decision_at: AwareDatetime) -> None:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("decision time must be aware")
        if self.available_at > decision_at:
            raise ValueError("future information unavailable")


class PublicEvent(PointInTime):
    event_id: Identifier
    event_type: Identifier
    published_at: AwareDatetime | None = None
    published_lower: AwareDatetime | None = None
    published_upper: AwareDatetime | None = None
    first_seen_at: AwareDatetime
    usable_at: AwareDatetime
    revision_id: Identifier

    @model_validator(mode="after")
    def publication(self) -> Self:
        exact = self.published_at is not None
        bounds = self.published_lower is not None and self.published_upper is not None
        if exact == bounds or (exact and (self.published_lower or self.published_upper)):
            raise ValueError("provide exact publication OR complete bounds")
        if bounds:
            assert self.published_lower is not None and self.published_upper is not None
            if self.published_lower > self.published_upper:
                raise ValueError("inverted publication bounds")
        release = self.published_at if exact else self.published_upper
        assert release is not None
        if self.usable_at < release:
            raise ValueError("usable before conservative publication boundary")
        if (
            self.availability_method == AvailabilityMethod.OBSERVED_LIVE
            and self.usable_at < self.first_seen_at
        ):
            raise ValueError("usable before observed receipt")
        return self

    def require_available(self, decision_at: AwareDatetime) -> None:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("decision time must be aware")
        if self.usable_at > decision_at:
            raise ValueError("public event unavailable")
