from typing import Protocol

from kmast.core.contracts import TargetSnapshot
from kmast.core.events import MarketEvent


class Strategy(Protocol):
    def targets(self, events: tuple[MarketEvent, ...]) -> TargetSnapshot: ...
