"""DF015 transport interlock. No broker I/O and no document-controlled enable switch.

No encrypted provider route is approved in this version. A future route needs
reviewed code binding its exact endpoint, TLS policy and service evidence. Neither
JSON booleans nor a self-authored evidence file can register such a route.
"""

from datetime import datetime

from kmast.data.models import KST


def pilot_disposition(now: datetime) -> str:
    """Clock input is explicit; the frozen DF014 protocol is never rewritten."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise PermissionError("AWARE_PILOT_CLOCK_REQUIRED")
    end = datetime(2026, 10, 19, 9, 25, tzinfo=KST)
    if now >= end:
        return "DF014_MISSED_OBSERVATION_WINDOW"
    start = end.replace(hour=8, minute=50)
    if now < start:
        return "DF014_FROZEN_WINDOW_NOT_OPEN"
    return "DF014_PILOT_PENDING_APPROVAL"


def require_secure_transport(endpoint: str, environment: str, now: datetime) -> None:
    """Deny before key loading/issuance/socket/send; do not echo untrusted inputs.

    This is deliberately a closed interlock, not a generic TLS connector. Merely
    replacing ws with wss, using a VPN, or asserting certificate validity cannot
    establish official service support or a protected final provider hop.
    """
    if environment != "PAPER":
        raise PermissionError("PAPER_ONLY_NO_LIVE_FALLBACK")
    disposition = pilot_disposition(now)
    if disposition == "DF014_MISSED_OBSERVATION_WINDOW":
        raise PermissionError(disposition)
    if not endpoint.startswith("wss://"):
        raise PermissionError("B_ORB_STREAM_TRANSPORT_BLOCKED_PLAINTEXT_OR_UNKNOWN")
    raise PermissionError("B_ORB_STREAM_TRANSPORT_BLOCKED_NO_APPROVED_SECURE_ROUTE")
