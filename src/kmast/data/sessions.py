from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, model_validator

from kmast.core.base import Contract, Identifier
from kmast.data.models import Session, Venue


class SessionInterval(Contract):
    venue: Venue
    session: Session
    start: AwareDatetime
    end: AwareDatetime
    available_at: AwareDatetime
    calendar_version: Identifier
    source_ref: Identifier

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("invalid market session interval")
        return self


def classify_session(
    intervals: tuple[SessionInterval, ...],
    venue: Venue,
    event_time: datetime,
    decision_at: datetime,
) -> Session:
    if any(t.tzinfo is None or t.utcoffset() is None for t in (event_time, decision_at)):
        raise ValueError("aware session query required")
    matches = [
        s
        for s in intervals
        if s.venue == venue and s.start <= event_time < s.end and s.available_at <= decision_at
    ]
    if len(matches) > 1:
        raise ValueError("ambiguous session calendar")
    return matches[0].session if matches else "UNKNOWN"
