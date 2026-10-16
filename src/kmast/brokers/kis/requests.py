"""Closed, parameter-validated market-data capability; no arbitrary URL/TR inputs."""

from datetime import date, datetime, time
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kmast.core.base import Contract
from kmast.core.enums import Environment

UPSTREAM_COMMIT = "2077773a69a428daf63e148182511f068cc45de3"
Operation = Literal["daily", "minute_today", "minute_history", "price", "quote", "index"]
Venue = Literal["KRX", "NXT", "CONSOLIDATED"]
SYMBOL = Annotated[str, Field(pattern=r"^\d{6}$")]
ROUTES: dict[str, tuple[str, str]] = {
    "daily": ("inquire-daily-itemchartprice", "FHKST03010100"),
    "minute_today": ("inquire-time-itemchartprice", "FHKST03010200"),
    "minute_history": ("inquire-time-dailychartprice", "FHKST03010230"),
    "price": ("inquire-price", "FHKST01010100"),
    "quote": ("inquire-asking-price-exp-ccn", "FHKST01010200"),
    "index": ("inquire-index-price", "FHPUP02100000"),
}


class MarketRequest(Contract):
    operation: Operation
    symbol: Annotated[str, Field(pattern=r"^(\d{6}|0001|1001)$")]
    venue: Venue = "KRX"
    start: date | None = None
    end: date | None = None
    at: time | None = None
    price_basis: Literal["RAW", "ADJUSTED"] = "RAW"
    continuation: Literal["", "N"] = ""

    @model_validator(mode="after")
    def fields(self) -> Self:
        if self.operation == "index":
            if self.symbol not in {"0001", "1001"} or self.venue != "KRX":
                raise ValueError("only KOSPI/KOSDAQ index contracts supported")
        elif len(self.symbol) != 6:
            raise ValueError("six-digit stock code required")
        if self.operation == "daily":
            if self.start is None or self.end is None or self.end < self.start:
                raise ValueError("daily date bounds required")
        elif self.start is not None:
            raise ValueError("unexpected start date")
        if self.operation in {"minute_today", "minute_history"}:
            if self.at is None or self.at.microsecond or self.at.tzinfo is not None:
                raise ValueError("explicit exchange-local second required")
            if self.operation == "minute_history" and self.end is None:
                raise ValueError("history date required")
        elif self.at is not None:
            raise ValueError("unexpected intraday time")
        if self.operation not in {"daily", "minute_history"} and self.end is not None:
            raise ValueError("unexpected end date")
        if self.operation != "daily" and self.price_basis != "RAW":
            raise ValueError("only daily adjusted prices supported")
        if self.operation != "index" and self.continuation:
            raise ValueError("continuation not established for this route")
        return self

    @property
    def path(self) -> str:
        return "/uapi/domestic-stock/v1/quotations/" + ROUTES[self.operation][0]

    @property
    def tr_id(self) -> str:
        return ROUTES[self.operation][1]

    def require_environment(self, environment: Environment) -> None:
        if self.operation in {"minute_history", "index"} and environment != Environment.LIVE:
            raise ValueError("paper support unverified; request blocked")

    def params(self) -> dict[str, str]:
        params = {
            "FID_COND_MRKT_DIV_CODE": {"KRX": "J", "NXT": "NX", "CONSOLIDATED": "UN"}[self.venue],
            "FID_INPUT_ISCD": self.symbol,
        }
        if self.operation == "index":
            params["FID_COND_MRKT_DIV_CODE"] = "U"
        if self.operation == "daily":
            assert self.start is not None and self.end is not None
            params |= {
                "FID_INPUT_DATE_1": self.start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": self.end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "1" if self.price_basis == "RAW" else "0",
            }
        if self.at is not None:
            params |= {"FID_INPUT_HOUR_1": self.at.strftime("%H%M%S"), "FID_PW_DATA_INCU_YN": "N"}
            if self.operation == "minute_today":
                params["FID_ETC_CLS_CODE"] = ""
            else:
                assert self.end is not None
                params |= {
                    "FID_INPUT_DATE_1": self.end.strftime("%Y%m%d"),
                    "FID_FAKE_TICK_INCU_YN": "N",
                }
        return params

    def require_nonfuture(self, exchange_now: datetime) -> None:
        if self.end and self.end > exchange_now.date():
            raise ValueError("future date request blocked")
        if (
            self.operation == "minute_today"
            and self.at
            and self.at > exchange_now.time().replace(tzinfo=None)
        ):
            raise ValueError("future minute cursor blocked")
        if (
            self.operation == "minute_history"
            and self.end == exchange_now.date()
            and self.at
            and self.at > exchange_now.time().replace(tzinfo=None)
        ):
            raise ValueError("future historical cursor blocked")
