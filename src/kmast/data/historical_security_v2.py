"""Observed-schema v2: retain alphanumeric KRX securities without code coercion.

No transport or authentication is implemented here. A snapshot date in a request
is not proof that the provider honored historical-date semantics.
"""

import json
import re
import unicodedata
from datetime import date
from typing import Any

from kmast.data.store import canonical, digest

BASIC_FIELDS = (
    "ISU_CD",
    "ISU_SRT_CD",
    "ISU_NM",
    "ISU_ABBRV",
    "LIST_DD",
    "MKT_TP_NM",
    "SECUGRP_NM",
    "KIND_STKCERT_TP_NM",
)


def day(value: str) -> date:
    if not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("INVALID_BASDD")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def normalized_name(value: str) -> str:
    # Do not strip corporate suffixes, punctuation or preferred-share suffixes.
    return "".join(unicodedata.normalize("NFC", value).split())


def snapshot_rows(
    raw: bytes, expected_hash: str, requested_day: str, market: str
) -> list[dict[str, str]]:
    if digest(raw) != expected_hash:
        raise ValueError("KRX_RAW_HASH_CONFLICT")
    day(requested_day)
    if market not in {"KOSPI", "KOSDAQ"}:
        raise ValueError("KRX_MARKET_OUTSIDE_PILOT")
    body = json.loads(raw)
    if not isinstance(body, dict) or not isinstance(body.get("OutBlock_1"), list):
        raise ValueError("KRX_RESPONSE_SCHEMA_UNKNOWN")
    rows: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    for row in body["OutBlock_1"]:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in BASIC_FIELDS):
            raise ValueError("KRX_BASIC_FIELDS_MISSING")
        standard, short = row["ISU_CD"], row["ISU_SRT_CD"]
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", standard) or not re.fullmatch(
            r"[0-9A-Z]{6}", short
        ):
            raise ValueError("KRX_STANDARD_SHORT_CODE_INVALID")
        if row["MKT_TP_NM"] not in (
            {"KOSPI", "유가증권"} if market == "KOSPI" else {"KOSDAQ", "코스닥"}
        ):
            raise ValueError("KRX_RESPONSE_MARKET_CONFLICT")
        if row.get("BAS_DD") is not None and row["BAS_DD"] != requested_day:
            raise ValueError("KRX_RESPONSE_DATE_CONFLICT")
        if row["LIST_DD"]:
            day(row["LIST_DD"])
        if short in seen and seen[short] != row:
            raise ValueError("KRX_SHORT_CODE_COLLISION")
        if short not in seen:
            rows.append(row)
            seen[short] = row
    return rows


def qualify_link(
    event: dict[str, Any],
    rows: list[dict[str, str]],
    *,
    snapshot_day: str,
    historical_date_evidence_sha256: str | None,
    issuer_corroboration_sha256: str | None = None,
    security_history_resolved: bool = False,
) -> dict[str, Any]:
    """Require dated provider and issuer corroboration; never approve names alone."""
    day(snapshot_day)
    result: dict[str, Any] = dict(
        receipt=event["receipt"],
        corp_code=event["corp_code"],
        CORPORATE_IDENTITY_VERIFIED=event.get("corporate_identity_verified"),
        HISTORICAL_SECURITY_PRESENT=None,
        CORP_STOCK_LINK_VERIFIED=None,
        THEN_LISTED_STATUS_VERIFIED=None,
        DELISTING_AND_HALT_PENDING=True,
        CORPORATE_ACTION_PENDING=True,
        PRICE_AND_SESSION_PENDING=True,
        standard_code=None,
        historical_short_code=None,
        then_market=None,
        listed_date=None,
        actual_publication_time=None,
        conflicts=[],
        missing_evidence=[],
    )
    if not historical_date_evidence_sha256 or not re.fullmatch(
        r"[a-f0-9]{64}", historical_date_evidence_sha256
    ):
        result["missing_evidence"].append("HISTORICAL_DATE_SEMANTICS_NOT_ATTESTED")
        return result
    if snapshot_day != event["receipt"][:8]:
        result["missing_evidence"].append("EXACT_EVENT_DATE_SNAPSHOT_UNAVAILABLE")
        return result
    code = event.get("stock_code", "")
    if not re.fullmatch(r"[0-9]{6}", code):
        result["missing_evidence"].append("DART_STOCK_CODE_CANDIDATE_UNAVAILABLE")
        return result
    matched = [row for row in rows if row["ISU_SRT_CD"] == code]
    if not matched:
        result["missing_evidence"].append("SECURITY_NOT_OBSERVED_NOT_PROVEN_DELISTED")
        return result
    if len(matched) != 1:
        result["conflicts"].append("MULTIPLE_SECURITY_ROWS")
        return result
    row = matched[0]
    result.update(
        HISTORICAL_SECURITY_PRESENT=True,
        standard_code=row["ISU_CD"],
        historical_short_code=code,
        then_market=row["MKT_TP_NM"],
        listed_date=row["LIST_DD"] or None,
    )
    if not row["LIST_DD"]:
        result["missing_evidence"].append("LISTING_DATE_UNAVAILABLE")
    elif day(row["LIST_DD"]) > day(event["receipt"][:8]):
        result["conflicts"].append("LISTING_AFTER_EVENT")
    else:
        result["THEN_LISTED_STATUS_VERIFIED"] = True
    names = {normalized_name(n) for n in event.get("document_legal_names", []) if n}
    if not names or normalized_name(row["ISU_NM"]) not in names:
        result["conflicts"].append("ISSUER_NAME_CHANGE_OR_MISMATCH_UNRESOLVED")
    if row["KIND_STKCERT_TP_NM"] not in {"보통주", "보통주권"}:
        result["conflicts"].append("STOCK_CLASS_REQUIRES_SEPARATE_REVIEW")
    if not issuer_corroboration_sha256 or not re.fullmatch(
        r"[a-f0-9]{64}", issuer_corroboration_sha256
    ):
        result["missing_evidence"].append("DATED_ISSUER_SECURITY_CORROBORATION_UNAVAILABLE")
    if not security_history_resolved:
        result["missing_evidence"].append("RENAME_TRANSFER_MERGER_CODE_CLASS_HISTORY_UNRESOLVED")
    if (
        result["CORPORATE_IDENTITY_VERIFIED"] is True
        and result["THEN_LISTED_STATUS_VERIFIED"] is True
        and not result["conflicts"]
        and not result["missing_evidence"]
    ):
        result["CORP_STOCK_LINK_VERIFIED"] = True
    result["normalized_sha256"] = digest(canonical(result))
    return result
