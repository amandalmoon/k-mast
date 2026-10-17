"""Dated issuer corroboration: never approve names or current codes alone."""

import re
from datetime import date
from typing import Any

from kmast.data.historical_security import normalized_name


def legal_core(value: str) -> str:
    value = normalized_name(value)
    for marker in ("주식회사", "(주)", "㈜"):
        if value.startswith(marker):
            value = value[len(marker) :]
        if value.endswith(marker):
            value = value[: -len(marker)]
    return value


def corroborate(
    event: dict[str, Any], current: list[dict[str, str]], previous: list[dict[str, str]]
) -> dict[str, Any]:
    event_day = date.fromisoformat(event["event_date"])
    result: dict[str, Any] = dict(
        receipt=event["receipt"],
        corp_code=event["corp_code"],
        event_date=event["event_date"],
        CORPORATE_IDENTITY_VERIFIED=event["corporate_verified"],
        HISTORICAL_SECURITY_PRESENT=None,
        CORP_STOCK_LINK_VERIFIED=None,
        THEN_LISTED_STATUS_VERIFIED=None,
        DELISTING_AND_HALT_PENDING=True,
        CORPORATE_ACTION_PENDING=True,
        PRICE_AND_SESSION_PENDING=True,
        full_security_change_history_verified=None,
        standard_code=None,
        historical_short_code=None,
        then_market=None,
        listing_date=None,
        previous_snapshot_identity_agrees=None,
        dated_issuer_name_corroborated=None,
        name_rule=("NFC/whitespace and outer Korean corporate-form markers; preserve originals"),
        conflicts=[],
        missing_evidence=[],
        actual_publication_time=None,
    )
    code = event["stock_code_candidate"]
    if not re.fullmatch(r"[0-9]{6}", code):
        result["missing_evidence"].append("NO_DART_CODE_CANDIDATE_NO_NAME_ONLY_JOIN")
        return result
    matched = [r for r in current if r["ISU_SRT_CD"] == code]
    if not matched:
        result["missing_evidence"].append(
            "NOT_PRESENT_IN_TWO_APPROVED_MARKETS_NOT_PROOF_OF_DELISTING"
        )
        return result
    if len(matched) != 1:
        result["conflicts"].append("CROSS_MARKET_CODE_COLLISION")
        return result
    row = matched[0]
    result.update(
        HISTORICAL_SECURITY_PRESENT=True,
        standard_code=row["ISU_CD"],
        historical_short_code=code,
        then_market=row["MKT_TP_NM"],
        listing_date=row["LIST_DD"],
    )
    listed = date(int(row["LIST_DD"][:4]), int(row["LIST_DD"][4:6]), int(row["LIST_DD"][6:]))
    if listed > event_day:
        result["conflicts"].append("LISTING_AFTER_OFFICIAL_FILING_DATE")
    else:
        result["THEN_LISTED_STATUS_VERIFIED"] = True
    legal_names = {legal_core(n) for n in event["document_legal_names"] if n}
    abbr, full = normalized_name(row["ISU_ABBRV"]), normalized_name(row["ISU_NM"])
    corroborated = abbr in legal_names and full in {abbr, abbr + "보통주", abbr + "보통주식"}
    result["dated_issuer_name_corroborated"] = corroborated
    if not corroborated:
        result["conflicts"].append("DATED_LEGAL_ISSUER_NAME_UNRESOLVED")
    if row["KIND_STKCERT_TP_NM"] not in {"보통주", "보통주권"}:
        result["conflicts"].append("NON_ORDINARY_STOCK_CLASS_REVIEW")
    prior = [r for r in previous if r["ISU_SRT_CD"] == code]
    fields = (
        "ISU_CD",
        "ISU_SRT_CD",
        "ISU_NM",
        "ISU_ABBRV",
        "LIST_DD",
        "MKT_TP_NM",
        "KIND_STKCERT_TP_NM",
    )
    agrees = len(prior) == 1 and all(prior[0][k] == row[k] for k in fields)
    result["previous_snapshot_identity_agrees"] = agrees
    if not agrees:
        result["conflicts"].append("ADJACENT_SNAPSHOT_IDENTITY_CHANGE_OR_MISSING")
    if (
        event["corporate_verified"] is True
        and event["document_raw_sha256"]
        and event["dart_row_sha256"]
        and result["THEN_LISTED_STATUS_VERIFIED"]
        and not result["conflicts"]
    ):
        result["CORP_STOCK_LINK_VERIFIED"] = True
    return result
