from datetime import datetime

from kmast.brokers.kis.requests import ROUTES, MarketRequest
from kmast.core.config import BrokerConfig


def validate_read_payload(config: BrokerConfig, path: str, params: dict[str, str]) -> MarketRequest:
    operation = next(
        (
            key
            for key, value in ROUTES.items()
            if path == "/uapi/domestic-stock/v1/quotations/" + value[0]
        ),
        None,
    )
    if operation is None:
        raise PermissionError("unknown read route")
    venues = {"J": "KRX", "NX": "NXT", "UN": "CONSOLIDATED", "U": "KRX"}
    try:
        request = MarketRequest(
            operation=operation,
            symbol=params["FID_INPUT_ISCD"],
            venue=venues[params["FID_COND_MRKT_DIV_CODE"]],
            start=datetime.strptime(params["FID_INPUT_DATE_1"], "%Y%m%d").date()
            if operation == "daily"
            else None,
            end=datetime.strptime(
                params["FID_INPUT_DATE_2" if operation == "daily" else "FID_INPUT_DATE_1"], "%Y%m%d"
            ).date()
            if operation in {"daily", "minute_history"}
            else None,
            at=datetime.strptime(params["FID_INPUT_HOUR_1"], "%H%M%S").time()
            if operation in {"minute_today", "minute_history"}
            else None,
            price_basis="ADJUSTED" if params.get("FID_ORG_ADJ_PRC") == "0" else "RAW",
        )
        if request.params() != params:
            raise ValueError
        request.require_environment(config.environment)
    except (KeyError, ValueError, TypeError):
        raise PermissionError("invalid read parameters") from None
    return request
