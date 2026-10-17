"""Conservative document evidence, without price inputs or current-master backfill."""

import io
import re
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from kmast.data.store import canonical, digest


def qualify_document(raw: bytes, receipt: str, corporate_id: str) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        receipt=receipt,
        raw_sha256=digest(raw),
        DOCUMENT_VERIFIED=None,
        CORPORATE_IDENTITY_VERIFIED=None,
        HISTORICAL_SYMBOL_MAPPING_VERIFIED=None,
        EVENT_FAMILY_VERIFIED=None,
        PRICE_AND_SESSION_QUALIFIED=None,
        published_at=None,
        publication_precision="DATE_ONLY",
        historical_stock_code=None,
        historical_listing_status=None,
        delisted_status=None,
        trading_halt_status=None,
        correction_parent_receipt=None,
        correction_parent_candidates=[],
        missing_evidence=[],
        members=[],
    )
    roots = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 100 or sum(m.file_size for m in members) > 64 * 1024 * 1024:
                raise ValueError("ZIP_EXPANSION_LIMIT")
            for member in members:
                if member.file_size > 32 * 1024 * 1024 or member.flag_bits & 1:
                    raise ValueError("ZIP_MEMBER_LIMIT")
                if not member.filename.lower().endswith(".xml"):
                    continue
                content = archive.read(member)
                if b"<!ENTITY" in content.upper() or b"<!DOCTYPE" in content.upper():
                    raise ValueError("XML_DECLARATION_BLOCKED")
                root = ET.fromstring(content)
                result["members"].append(
                    dict(name=member.filename, sha256=digest(content), bytes=len(content))
                )
                if member.filename.rsplit("/", 1)[-1] == receipt + ".xml":
                    roots.append(root)
    except (zipfile.BadZipFile, ET.ParseError, ValueError, RuntimeError):
        result["missing_evidence"].append("SAFE_RECEIPT_XML_UNAVAILABLE")
        return result | dict(normalized_sha256=digest(canonical(result)))
    if len(roots) != 1:
        result["missing_evidence"].append("UNIQUE_RECEIPT_XML_UNAVAILABLE")
        return result | dict(normalized_sha256=digest(canonical(result)))
    root = roots[0]
    result["DOCUMENT_VERIFIED"] = True
    companies = [e for e in root.iter() if e.tag.upper() == "COMPANY-NAME"]
    ids = sorted({e.attrib.get("AREGCIK", "") for e in companies} - {""})
    result["document_corporate_ids"] = ids
    result["corporate_legal_names"] = ["".join(e.itertext()).strip() for e in companies]
    if ids == [corporate_id]:
        result["CORPORATE_IDENTITY_VERIFIED"] = True
    else:
        result["missing_evidence"].append("CORPORATE_ID_MISSING_OR_CONFLICTING")
    # Only explicit named stock-code fields qualify. AREGCIK is never a stock code.
    symbols = set()
    for element in root.iter():
        if element.tag.upper() in {"STOCK-CODE", "STOCK_CODE", "STOCKCODE"}:
            value = "".join(element.itertext()).strip()
            if re.fullmatch(r"[0-9]{6}", value):
                symbols.add(value)
    if len(symbols) == 1 and result["CORPORATE_IDENTITY_VERIFIED"]:
        result["historical_stock_code"] = next(iter(symbols))
        result["HISTORICAL_SYMBOL_MAPPING_VERIFIED"] = True
    else:
        result["missing_evidence"].append("EXPLICIT_CONTEMPORANEOUS_STOCK_CODE_UNAVAILABLE")
    headings = [
        re.sub(r"\s+", "", "".join(e.itertext()))
        for e in root.iter()
        if e.tag.upper() in {"TITLE", "SUBTITLE", "DOCUMENT-NAME"}
    ]
    result["headings"] = headings
    direct = any("자기주식취득결정" in h and "신탁" not in h for h in headings)
    trust = any("신탁계약체결" in h for h in headings)
    text = re.sub(r"\s+", "", " ".join(root.itertext()))
    structured = all(term in text for term in ("취득예정주식", "취득예정금액", "취득예상기간"))
    result["direct_acquisition_heading"] = direct
    result["trust_heading"] = trust
    result["structured_acquisition_fields"] = structured
    result["title_body_mismatch"] = not direct or trust
    if direct and structured and not trust:
        result["EVENT_FAMILY_VERIFIED"] = True
    else:
        result["missing_evidence"].append("DIRECT_ACQUISITION_PRIMARY_BODY_NOT_CONFIRMED")
    # Explicit linked receipt IDs are candidates, not automatically verified parents.
    links = set()
    for e in root.iter():
        for value in e.attrib.values():
            links.update(re.findall(r"(?:rcpNo|rcept_no)=([0-9]{14})", value))
    result["correction_parent_candidates"] = sorted(links - {receipt})
    result["missing_evidence"] += [
        "HISTORICAL_LISTING_HALT_ACTION_EVIDENCE_UNAVAILABLE",
        "EXACT_PUBLICATION_TIME_UNAVAILABLE",
        "PRICE_SESSION_ACTION_QUALIFICATION_NOT_PERFORMED",
    ]
    return result | dict(normalized_sha256=digest(canonical(result)))
