from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class ReplayClock:
    instant: datetime

    def __post_init__(self) -> None:
        self.advance(self.instant)

    def now(self) -> datetime:
        return self.instant

    def advance(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("clock must be timezone-aware")
        if instant < self.instant:
            raise ValueError("clock cannot move backwards")
        self.instant = instant
