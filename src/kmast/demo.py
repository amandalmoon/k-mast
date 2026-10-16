import json
from datetime import UTC, datetime

from kmast.brokers.interfaces import MockBroker
from kmast.core.clock import ReplayClock
from kmast.core.config import RuntimeConfig
from kmast.core.events import MarketEvent
from kmast.core.study import StudyContract
from kmast.data.replay import ReplayPolicy, replay


def main() -> None:
    now = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    event = MarketEvent(
        event_id="synthetic-1",
        symbol="SYNTHETIC",
        venue="KRX",
        session="REGULAR",
        event_time=now,
        received_at=now,
        available_at=now,
        source="fixture",
        availability_method="OBSERVED_LIVE",
    )
    result = replay(
        (event, event),
        ReplayPolicy(config_version="km000-v12", code_version="1.2.0"),
        ReplayClock(now),
    )
    print(
        json.dumps(
            {
                "mode": RuntimeConfig().mode,
                "order_enabled": False,
                "live_enabled": False,
                "events": len(result.events),
                "duplicates": len(result.duplicate_ids),
                "replay_hash": result.result_hash,
                "G3": StudyContract().g3_status(),
                "broker": MockBroker().read("quote"),
                "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
                "live_status": "LIVE_NOT_APPROVED",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
