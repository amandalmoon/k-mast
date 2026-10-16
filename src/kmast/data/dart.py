from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from kmast.core.base import Contract, Identifier
from kmast.core.events import PublicEvent
from kmast.data.models import KST, utc
from kmast.data.store import canonical, digest, scrub


class Disclosure(Contract):
    corp_code: Annotated[str, Field(pattern=r"^\d{8}$")]
    stock_code: Annotated[str, Field(pattern=r"^\d{6}$")] | None
    rcept_no: Annotated[str, Field(pattern=r"^\d{14}$")]
    rcept_dt: date
    report_nm: Identifier
    disclosure_type: Identifier
    correction: bool
    supersedes_receipt: Identifier | None = None
    lineage_status: Literal["ORIGINAL", "LINKED", "UNRESOLVED"]
    original_ref: Identifier
    source_hash: Identifier
    acquired_at: AwareDatetime
    public_event: PublicEvent


class DisclosureRegistry:
    def __init__(self) -> None:
        self.items: dict[str, Disclosure] = {}

    def add(self, event: Disclosure) -> None:
        old = self.items.get(event.rcept_no)
        if old is not None and old != event:
            raise ValueError("conflicting disclosure receipt")
        if event.supersedes_receipt:
            parent = self.items.get(event.supersedes_receipt)
            if (
                parent is None
                or parent.corp_code != event.corp_code
                or parent.stock_code != event.stock_code
                or parent.rcept_dt > event.rcept_dt
            ):
                raise ValueError("invalid disclosure correction parent")
        self.items[event.rcept_no] = event


def parse_disclosure(
    row: dict[str, str],
    acquired_at: datetime,
    next_session: datetime,
    calendar_evidence: str,
    supersedes_receipt: str | None = None,
) -> Disclosure:
    day = datetime.strptime(row["rcept_dt"], "%Y%m%d").date()
    lower = datetime.combine(day, time.min, KST)
    upper = lower + timedelta(days=1)
    if next_session < upper or next_session.astimezone(KST).time() < time(9):
        raise ValueError("explicit next-session calendar boundary required")
    correction = any(marker in row["report_nm"] for marker in ("정정", "첨부추가"))
    receipt = row["rcept_no"]
    if supersedes_receipt == receipt:
        raise ValueError("self-referencing disclosure correction")
    event = PublicEvent(
        event_id=receipt,
        event_type=row.get("pblntf_ty", "UNVERIFIED"),
        published_lower=utc(lower),
        published_upper=utc(upper),
        first_seen_at=utc(acquired_at),
        usable_at=utc(next_session),
        revision_id=receipt,
        acquired_at=utc(acquired_at),
        availability_method="CONSERVATIVE_BOUND",
        availability_evidence=calendar_evidence,
    )
    return Disclosure(
        corp_code=row["corp_code"],
        stock_code=row.get("stock_code") or None,
        rcept_no=receipt,
        rcept_dt=day,
        report_nm=row["report_nm"],
        disclosure_type=row.get("pblntf_ty", "UNVERIFIED"),
        correction=correction,
        supersedes_receipt=supersedes_receipt,
        lineage_status="LINKED"
        if supersedes_receipt
        else ("UNRESOLVED" if correction else "ORIGINAL"),
        original_ref="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + receipt,
        source_hash=digest(canonical(scrub(row))),
        acquired_at=utc(acquired_at),
        public_event=event,
    )
