from typing import Literal

from pydantic import AwareDatetime

from kmast.core.base import Contract, Identifier
from kmast.core.clock import Clock
from kmast.core.events import MarketEvent
from kmast.data.normalization import content_hash


class ReplayPolicy(Contract):
    config_version: Identifier
    code_version: Identifier
    clock_policy: Literal["AVAILABILITY_ORDER_V1"] = "AVAILABILITY_ORDER_V1"
    correction_policy: Literal["APPEND_WITH_EXPLICIT_SUPERSESSION"] = (
        "APPEND_WITH_EXPLICIT_SUPERSESSION"
    )


class ReplayResult(Contract):
    policy: ReplayPolicy
    decision_at: AwareDatetime
    events: tuple[MarketEvent, ...]
    duplicate_ids: tuple[str, ...]
    input_hash: str
    result_hash: str


def replay(events: tuple[MarketEvent, ...], policy: ReplayPolicy, clock: Clock) -> ReplayResult:
    now = clock.now()
    unique: dict[tuple[str, str], MarketEvent] = {}
    duplicates = []
    for event in events:
        event.require_available(now)
        key = (event.source, event.event_id)
        old = unique.get(key)
        if old:
            if old != event:
                raise ValueError("conflicting duplicate id; explicit correction required")
            duplicates.append(f"{event.source}:{event.event_id}")
        else:
            unique[key] = event
    ordered = tuple(
        sorted(unique.values(), key=lambda e: (e.available_at, e.received_at, e.source, e.event_id))
    )
    processed: dict[tuple[str, str], MarketEvent] = {}
    children: set[tuple[str, str]] = set()
    for event in ordered:
        if event.supersedes_id:
            parent_key = (event.source, event.supersedes_id)
            parent = processed.get(parent_key)
            if (
                not parent
                or parent_key in children
                or event.revision <= parent.revision
                or (event.symbol, event.venue, event.session)
                != (parent.symbol, parent.venue, parent.session)
            ):
                raise ValueError("invalid correction lineage or availability ordering")
            children.add(parent_key)
        elif event.revision != 0:
            raise ValueError("revision requires explicit parent")
        processed[(event.source, event.event_id)] = event
    payload = [e.model_dump(mode="json") for e in ordered]
    input_hash = content_hash([e.model_dump(mode="json") for e in events])
    result_hash = content_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "events": payload,
            "duplicates": sorted(duplicates),
            "decision_at": now.isoformat(),
        }
    )
    return ReplayResult(
        policy=policy,
        decision_at=now,
        events=ordered,
        duplicate_ids=tuple(sorted(duplicates)),
        input_hash=input_hash,
        result_hash=result_hash,
    )
