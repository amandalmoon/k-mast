"""DF017 trusted-review and exact frozen request gates. No credentials or I/O transport."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kmast.data.models import KST
from kmast.data.store import canonical, digest

PROPOSAL_HASH = "f1e5a852caebcb383fc947e75136a2ae3f88b87bc91f2d728310e4a301304d0b"
HOST = "openapivts.koreainvestment.com"
ROOT_URL = "https://" + HOST + ":29443"
START = datetime(2026, 10, 20, 8, 55, tzinfo=KST)
END = START.replace(hour=9, minute=22)
STORE = Path(__file__).resolve().parents[3] / "data/data-first-private-df016-pilot"
# A file's self-asserted verified=True is not independent service/rights/human review.
# Registration is an explicit later reviewed code change, never a CLI or JSON option.
TRUSTED_REVIEWS: frozenset[tuple[str, str]] = frozenset()


def window(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise PermissionError("AWARE_COLLECTION_CLOCK_REQUIRED")
    if now >= END:
        raise PermissionError("DF017_MISSED_COLLECTION_WINDOW")
    if now < START:
        raise PermissionError("DF017_EXACT_COLLECTION_WINDOW_REQUIRED")


def proposal(raw: bytes) -> dict[str, Any]:
    if digest(raw) != PROPOSAL_HASH:
        raise PermissionError("FROZEN_22_PROPOSAL_HASH_REQUIRED")
    data: dict[str, Any] = json.loads(raw)
    return data


def earliest(call: dict[str, Any]) -> datetime:
    ordinal = call["ordinal"]
    if ordinal <= 6:
        return START.replace(hour=9, minute=1, second=20)
    # Quote ordinals share their immediately preceding bar's not-before floor.
    group = (ordinal - 7) // 4
    return START.replace(hour=9, minute=(5, 6, 15, 16)[group], second=10)


def checked_call(plan: dict[str, Any], ordinal: int, supplied: dict[str, Any]) -> None:
    if not 1 <= ordinal <= 22 or canonical(supplied) != canonical(plan["calls"][ordinal - 1]):
        raise PermissionError("EXACT_ORDERED_QUERY_REQUIRED")


def authorize(
    raw_plan: bytes,
    approval: dict[str, Any],
    preflight: dict[str, Any],
    now: datetime,
    *,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        raise PermissionError("NETWORK_DISABLED")
    window(now)
    plan = proposal(raw_plan)
    if (digest(canonical(approval)), digest(canonical(preflight))) not in TRUSTED_REVIEWS:
        raise PermissionError("INDEPENDENT_REGISTERED_HUMAN_AND_PREFLIGHT_REVIEW_REQUIRED")
    if (
        approval.get("proposal_sha256") != PROPOSAL_HASH
        or approval.get("scope") != plan["scope"]
        or approval.get("approved") is not True
        or approval.get("environment") != "PAPER"
    ):
        raise PermissionError("EXACT_FRESH_HUMAN_SCOPE_REQUIRED")
    try:
        issued = datetime.fromisoformat(approval["issued_at"])
        expires = datetime.fromisoformat(approval["expires_at"])
        if issued.tzinfo is None or expires.tzinfo is None or not issued <= now < expires <= END:
            raise ValueError
        statement = Path(approval["statement_path"]).read_bytes()
        if digest(statement) != approval["statement_sha256"] or not statement:
            raise ValueError
        for key in ("service", "rate", "rights", "calendar", "security_status", "clock", "https"):
            proof = preflight[key]
            if (
                proof["reviewed"] is not True
                or digest(Path(proof["path"]).read_bytes()) != proof["sha256"]
            ):
                raise ValueError
        if (
            preflight["environment"] != "PAPER"
            or preflight["host"] != ROOT_URL
            or preflight["day"] != "2026-10-20"
            or preflight["symbols"] != ["073240", "462860"]
            or preflight["venue"] != "J"
            or preflight["retention_days"] != 30
            or preflight["storage_research_allowed"] is not True
            or preflight["hash_retention_allowed"] is not True
            or not 0 <= preflight["clock_error_bound_seconds"] <= 0.5
            or not 3.10 <= preflight["provider_interval_seconds"] <= 3600
        ):
            raise ValueError
        if now - issued > timedelta(hours=72):
            raise ValueError
    except (KeyError, TypeError, ValueError, OSError):
        raise PermissionError("SERVICE_RIGHTS_MARKET_CLOCK_HTTPS_EVIDENCE_INCOMPLETE") from None
    return plan
