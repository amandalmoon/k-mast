from datetime import datetime, timedelta

from kmast.brokers.kis.network import DataError, HttpReply, MarketClient
from kmast.brokers.kis.requests import MarketRequest


def daily_pages(
    client: MarketClient, request: MarketRequest, max_pages: int = 3
) -> tuple[tuple[MarketRequest, HttpReply], ...]:
    """Bounded backward date cursor. Coverage is never inferred from response length."""
    if request.operation != "daily" or not 1 <= max_pages <= 5:
        raise ValueError("bounded daily request required")
    pages = []
    current = request
    for _ in range(max_pages):
        reply = client.read(current)
        pages.append((current, reply))
        rows = reply.body.get("output2")
        if not isinstance(rows, list):
            raise DataError("DAILY_RESPONSE_INVALID")
        if not rows:
            break
        try:
            earliest = min(
                datetime.strptime(row["stck_bsop_date"], "%Y%m%d").date() for row in rows
            )
        except (KeyError, ValueError, TypeError):
            raise DataError("DAILY_CURSOR_INVALID") from None
        assert request.start is not None and current.end is not None
        if earliest < request.start or earliest > current.end:
            raise DataError("DAILY_CURSOR_OUT_OF_SCOPE")
        if earliest == request.start:
            break
        current = MarketRequest.model_validate(
            current.model_dump() | {"end": earliest - timedelta(days=1)}
        )
    return tuple(pages)
