"""Purpose-specific rights evidence. Does not replace or relax the existing G1 gate."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field

from kmast.core.base import Contract, Identifier

Purpose = Literal[
    "TRANSIENT_QUOTE",
    "MEMORY_ANALYSIS",
    "PRIVATE_BACKTEST",
    "RAW_RETENTION",
    "NORMALIZED_RETENTION",
    "AGGREGATE_PUBLICATION",
    "THIRD_PARTY_DATA",
    "PERSONAL_DECISION",
]


class RightsDocument(Contract):
    identity: Identifier
    title: Identifier
    official_url: Identifier
    checked_at: AwareDatetime
    published_at: AwareDatetime | None = None
    version: Identifier | None = None
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    body_obtained: bool
    applicable_scope: Literal["PERSONAL_OWN_INVESTMENT"]

    def trusted(self) -> bool:
        url = urlsplit(self.official_url)
        return (
            self.body_obtained
            and url.scheme == "https"
            and url.hostname == "apiportal.koreainvestment.com"
        )


class PurposeGrant(Contract):
    purpose: Purpose
    status: Literal["ALLOWED", "RESTRICTED", "PROHIBITED", "UNVERIFIED"]
    document_ref: Identifier
    basis: Literal["DIRECT_TEXT", "INTERPRETATION", "UNVERIFIED"]
    clause: Identifier
    limitation: Identifier


def rights_decision(
    grant: PurposeGrant,
    documents: tuple[RightsDocument, ...],
    *,
    own_investment: bool,
    local_only: bool,
) -> str:
    sources = [d for d in documents if d.identity == grant.document_ref]
    if len(sources) != 1 or not sources[0].trusted():
        return "EXTERNAL_EVIDENCE_PENDING_SOURCE"
    if grant.status == "PROHIBITED":
        return "PROHIBITED"
    if not own_investment or not local_only:
        return "OUTSIDE_PERSONAL_LOCAL_SCOPE"
    if grant.status != "ALLOWED" or grant.basis != "DIRECT_TEXT":
        return "EXTERNAL_EVIDENCE_PENDING_PURPOSE_OR_DURATION"
    return "ALLOWED_SCOPED_NOT_G1_APPROVAL"
