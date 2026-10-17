from datetime import date, datetime

import pytest

from kmast.data.models import KST
from kmast.research.event_flow import (
    DecisionReceipt,
    decision_boundary,
    invalidated_at,
    register_receipt,
)


def receipt(**changes: object) -> DecisionReceipt:
    fields = {
        "receipt": "20231006000001",
        "corp_code": "00123456",
        "stock_code": "014790",
        "receipt_date": date(2023, 10, 6),
        "title": "주요사항보고서(자기주식취득결정)",
        "acquired_at": datetime(2026, 10, 17, tzinfo=KST),
        "raw_response_sha256": "a" * 64,
        "original_document_sha256": "b" * 64,
        "historical_identity_verified": True,
        "document_family_verified": True,
    }
    return DecisionReceipt.model_validate(fields | changes)


def test_date_only_after_weekend_and_holiday() -> None:
    event = receipt()
    calendar = (datetime(2023, 10, 6, 8, tzinfo=KST), datetime(2023, 10, 10, 8, tzinfo=KST))
    assert decision_boundary(event, calendar) == calendar[1]
    assert event.published_at is None
    assert event.acquired_at.year == 2026


@pytest.mark.parametrize(
    "title",
    [
        "자기주식처분결정",
        "자기주식취득결과보고서",
        "자기주식취득신탁계약체결결정",
        "[기재정정]자기주식취득결정",
    ],
)
def test_decision_is_not_execution_or_other_family(title: str) -> None:
    assert not receipt(title=title).entry_candidate


def test_document_and_historical_mapping_required() -> None:
    assert receipt().entry_candidate
    assert not receipt(document_family_verified=False).entry_candidate
    assert not receipt(historical_identity_verified=False).entry_candidate


def test_receipt_dedup_and_conflict() -> None:
    event = receipt()
    registry: dict[str, DecisionReceipt] = {}
    register_receipt(registry, event)
    register_receipt(registry, event)
    assert len(registry) == 1
    with pytest.raises(ValueError, match="CONFLICTING_RECEIPT"):
        register_receipt(registry, receipt(stock_code="014440"))


def test_correction_is_prospective_not_backfilled() -> None:
    event = receipt()
    correction = receipt(
        receipt="20231011000001",
        receipt_date=date(2023, 10, 11),
        parent_receipt=event.receipt,
        correction_kind="CANCEL",
    )
    calendar = tuple(datetime(2023, 10, day, 8, tzinfo=KST) for day in (10, 11, 12))
    assert not invalidated_at(event, (correction,), calendar[0], calendar)
    assert invalidated_at(event, (correction,), calendar[2], calendar)
    assert event.entry_candidate
    assert not correction.entry_candidate


def test_correction_mapping_conflict_rejected() -> None:
    event = receipt()
    with pytest.raises(ValueError, match="UNVERIFIED_CORRECTION_PARENT"):
        register_receipt(
            {event.receipt: event},
            receipt(
                receipt="20231011000001",
                stock_code="014440",
                parent_receipt=event.receipt,
                correction_kind="ADVERSE",
            ),
        )


def test_hash_and_calendar_precision() -> None:
    assert len(receipt().normalized_sha256) == 64
    assert receipt().normalized_sha256 != receipt(title="other").normalized_sha256
    with pytest.raises(ValueError, match="REGULAR_DECISION"):
        decision_boundary(receipt(), (datetime(2023, 10, 10, 9, tzinfo=KST),))
    with pytest.raises(ValueError, match="NO_VERIFIED"):
        decision_boundary(receipt(), ())
