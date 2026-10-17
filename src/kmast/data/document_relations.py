"""Official correction-target dates resolve identity only, never past information sets."""

import re
from datetime import date
from typing import Any


def correction_relation(
    text: str, receipt: str, corporate_id: str, originals: list[dict[str, Any]]
) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", text)
    result: dict[str, Any] = dict(
        parent_receipt=None,
        relation_verified=None,
        initial_submission_date=None,
        effective_publication_time=None,
        earlier_original_information_changed=False,
        reason="EXPLICIT_INITIAL_SUBMISSION_DATE_UNAVAILABLE",
    )
    if "정정대상공시서류:" not in compact or "자기주식취득결정" not in compact:
        return result
    matches = re.findall(
        r"정정대상공시서류의최초제출일[:：](\d{4})년(\d{1,2})월(\d{1,2})일", compact
    )
    if len(set(matches)) != 1:
        return result
    try:
        initial = date(*map(int, matches[0])).isoformat()
    except ValueError:
        return result
    result["initial_submission_date"] = initial
    if initial.replace("-", "") > receipt[:8]:
        result["reason"] = "INITIAL_SUBMISSION_DATE_AFTER_CORRECTION"
        return result
    candidates = [
        r["receipt"]
        for r in originals
        if r["corp_code"] == corporate_id and r["receipt"][:8] == initial.replace("-", "")
    ]
    result["candidate_parent_receipts"] = sorted(candidates)
    if len(candidates) == 1:
        result.update(
            parent_receipt=candidates[0],
            relation_verified=True,
            reason="OFFICIAL_LABELED_INITIAL_DATE_UNIQUE_CORPORATE_ORIGINAL",
        )
    else:
        result["reason"] = "MISSING_OR_AMBIGUOUS_SAME_CORPORATE_DATE_ORIGINAL"
    return result
