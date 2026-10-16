"""Conservative public evidence filter, in addition to .gitignore and local secret scanning."""

from pathlib import PurePosixPath
from typing import Any


def require_public_file(path: str, payload: Any = None) -> None:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if (
        any(
            p.startswith(".env") or p.startswith("km005-private") or p.startswith("km004-private")
            for p in parts
        )
        or "data" == parts[0]
        or path.endswith((".sqlite", ".parquet"))
    ):
        raise PermissionError("private data or credential file cannot be published")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("data_origin") in {"KIS_READONLY", "DART_READONLY"} and any(
                value.get(k) is not None for k in ("open", "close", "price", "bid", "ask")
            ):
                raise PermissionError("raw market observations cannot be published")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
