from collections.abc import Callable
from typing import Any

from kmast.brokers.kis.requests import MarketRequest
from kmast.data.models import Observation, Provenance
from kmast.data.parsers import parse_rest
from kmast.data.store import DataStore


def collect_rest(
    store: DataStore,
    identity: str,
    request: MarketRequest,
    acquire: Callable[[], tuple[dict[str, Any], Provenance]],
    secrets: tuple[str, ...] = (),
) -> tuple[str, tuple[Observation, ...]]:
    cached = store.cached(identity)
    if cached is None:
        body, meta = acquire()
        cached = store.put_raw(identity, body, meta, secrets)
    metadata = Provenance.model_validate(cached["metadata"])
    rows = parse_rest(cached["payload"], request, metadata)
    dataset = store.put_dataset(rows, identity)
    return dataset, store.load_dataset(dataset)
