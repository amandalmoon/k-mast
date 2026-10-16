import hashlib
import json
from typing import Any

from kmast.core.events import MarketEvent


def normalize(raw: dict[str, Any]) -> MarketEvent:
    """Validate explicit fields; never infer publication or acquisition timestamps."""
    return MarketEvent.model_validate(raw)


def content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
