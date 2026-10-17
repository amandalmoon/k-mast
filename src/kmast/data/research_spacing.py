"""Offline-testable future collector guard; not integrated into frozen DF006.

No HTTP, credentials or broker imports. A future approved adapter must supply
actual high-resolution completion/start observations and persist the records.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ResearchGapGuard:
    minimum: float = 3.05
    wait_seconds: float = 3.10
    completed_at: float | None = None
    stopped: bool = False
    in_flight: bool = False
    started_at: float | None = None
    observations: list[dict[str, float | bool | None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.minimum)
            or not math.isfinite(self.wait_seconds)
            or self.minimum < 3.05
            or self.wait_seconds < max(self.minimum, 3.10)
        ):
            raise ValueError("APPROVED_SPACING_CANNOT_BE_RELAXED")

    def response_completed(self, at: float) -> None:
        if (
            not math.isfinite(at)
            or (self.completed_at is not None and at < self.completed_at)
            or (self.started_at is not None and at < self.started_at)
        ):
            self.stopped = True
            raise ValueError("INVALID_COMPLETION_CLOCK")
        self.completed_at = at
        self.in_flight = False

    def wait(self, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        if self.stopped:
            raise PermissionError("COLLECTION_STOPPED")
        if self.in_flight:
            self.stopped = True
            raise PermissionError("PREVIOUS_RESPONSE_NOT_OBSERVED")
        if self.completed_at is None:
            return
        deadline = self.completed_at + self.wait_seconds
        while True:
            now = clock()
            if not math.isfinite(now) or now < self.completed_at:
                self.stopped = True
                raise ValueError("INVALID_WAIT_CLOCK")
            if now >= deadline:
                return
            sleep(deadline - now)

    def authorize_next_request(self, at: float) -> None:
        if self.stopped:
            raise PermissionError("COLLECTION_STOPPED")
        if self.in_flight:
            self.stopped = True
            raise PermissionError("PREVIOUS_RESPONSE_NOT_OBSERVED")
        gap = at - self.completed_at if self.completed_at is not None else None
        compliant = math.isfinite(at) and (gap is None or gap >= self.minimum)
        self.observations.append(
            {
                "start_observed": at,
                "completion_observed": self.completed_at,
                "gap": gap,
                "compliant": compliant,
            }
        )
        if not compliant:
            self.stopped = True
            raise PermissionError("OBSERVED_GAP_BELOW_APPROVED_MINIMUM")
        self.started_at = at
        self.in_flight = True
