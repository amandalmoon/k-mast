"""DF006 receipt-time contracts; no network, strategy migration or execution claims."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from kmast.core.base import Contract
from kmast.data.models import KST
from kmast.data.store import canonical, digest


class DecisionReceipt(Contract):
    receipt: Annotated[str, Field(pattern=r"^[0-9]{14}$")]
    corp_code: Annotated[str, Field(pattern=r"^[0-9]{8}$")]
    stock_code: Annotated[str, Field(pattern=r"^[0-9]{6}$")]
    receipt_date: date
    title: str
    acquired_at: AwareDatetime
    published_at: AwareDatetime | None = None
    parent_receipt: str | None = None
    original_document_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    raw_response_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    historical_identity_verified: bool = False
    document_family_verified: bool = False
    correction_kind: Literal["NONE", "CANCEL", "ADVERSE", "UNRESOLVED"] = "NONE"

    @model_validator(mode="after")
    def coherent(self) -> "DecisionReceipt":
        if self.parent_receipt == self.receipt:
            raise ValueError("SELF_CORRECTION")
        if self.correction_kind == "NONE" and self.parent_receipt is not None:
            raise ValueError("ORIGINAL_WITH_PARENT")
        if self.published_at is not None:
            if self.published_at.astimezone(KST).date() != self.receipt_date:
                raise ValueError("PUBLICATION_DATE_CONFLICT")
            if self.published_at > self.acquired_at:
                raise ValueError("PUBLICATION_AFTER_ACQUISITION")
        return self

    @property
    def normalized_sha256(self) -> str:
        return digest(canonical(self.model_dump(mode="json")))

    @property
    def entry_candidate(self) -> bool:
        title = "".join(self.title.split())
        return (
            title in {"주요사항보고서(자기주식취득결정)", "자기주식취득결정"}
            and self.correction_kind == "NONE"
            and self.parent_receipt is None
            and self.historical_identity_verified
            and self.document_family_verified
        )


def decision_boundary(
    receipt: DecisionReceipt, eligible_decisions: tuple[datetime, ...]
) -> datetime:
    """Counterfactual date-only boundary, never an assertion of historical receipt time."""
    end = datetime.combine(receipt.receipt_date + timedelta(days=1), time.min, KST)
    if any(t.tzinfo is None or t.utcoffset() is None for t in eligible_decisions):
        raise ValueError("AWARE_CALENDAR_REQUIRED")
    if any(t.astimezone(KST).time() != time(8) for t in eligible_decisions):
        raise ValueError("REGULAR_DECISION_CALENDAR_REQUIRED")
    if tuple(sorted(set(eligible_decisions))) != eligible_decisions:
        raise ValueError("UNIQUE_ORDERED_CALENDAR_REQUIRED")
    candidates = [t for t in eligible_decisions if t >= end]
    if not candidates:
        raise ValueError("NO_VERIFIED_NEXT_SESSION")
    return candidates[0]


def register_receipt(registry: dict[str, DecisionReceipt], event: DecisionReceipt) -> None:
    """Idempotent receipt storage; never infer correction parents from similar titles."""
    existing = registry.get(event.receipt)
    if existing is not None and existing != event:
        raise ValueError("CONFLICTING_RECEIPT")
    if event.parent_receipt is not None:
        parent = registry.get(event.parent_receipt)
        if (
            parent is None
            or parent.corp_code != event.corp_code
            or parent.stock_code != event.stock_code
            or parent.receipt_date > event.receipt_date
        ):
            raise ValueError("UNVERIFIED_CORRECTION_PARENT")
    registry[event.receipt] = event


def invalidated_at(
    original: DecisionReceipt,
    corrections: tuple[DecisionReceipt, ...],
    now: datetime,
    eligible_decisions: tuple[datetime, ...],
) -> bool:
    """A later linked correction cannot erase the original historical decision."""
    return any(
        correction.parent_receipt == original.receipt
        and correction.corp_code == original.corp_code
        and correction.stock_code == original.stock_code
        and correction.correction_kind != "NONE"
        and decision_boundary(correction, eligible_decisions) <= now
        for correction in corrections
    )
