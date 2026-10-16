"""Local existing-data re-audit and purpose-grant evidence binding; no broker/network imports."""

import hashlib
import json
from pathlib import Path

from kmast.alpha.readiness import observation_bar
from kmast.data.store import DataStore
from kmast.research.qualification import quality_summary
from kmast.research.rights import PurposeGrant, RightsDocument, rights_decision


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km005r1"
    sources = json.loads((output / "official-documents.json").read_bytes())
    proof = next(p for p in sources if p["identity"] == "KIS_DATA_POLICY_20261006")
    private = root / "data/km005r1-private-documents/KIS_DATA_POLICY_20261006.source"
    body = private.read_bytes()
    assert hashlib.sha256(body).hexdigest() == proof["response_sha256"]
    assert (
        hashlib.sha256(json.loads(body)["content"].encode()).hexdigest() == proof["content_sha256"]
    )
    document = RightsDocument(
        identity=proof["identity"],
        title=proof["title"],
        official_url=proof["official_url"],
        checked_at=proof["checked_at"],
        published_at=proof["published_at"],
        content_sha256=proof["content_sha256"],
        body_obtained=True,
        applicable_scope="PERSONAL_OWN_INVESTMENT",
    )
    definitions = (
        ("TRANSIENT_QUOTE", "ALLOWED", "DIRECT_TEXT", "OWN_INVESTMENT_ONLY"),
        ("MEMORY_ANALYSIS", "ALLOWED", "DIRECT_TEXT", "OWN_INVESTMENT_ONLY"),
        (
            "PRIVATE_BACKTEST",
            "RESTRICTED",
            "INTERPRETATION",
            "HISTORICAL_BACKTEST_SCOPE_CONFIRMATION",
        ),
        (
            "RAW_RETENTION",
            "RESTRICTED",
            "DIRECT_TEXT",
            "LOCAL_STORAGE_ALLOWED_DURATION_AND_TERMINATION_UNSPECIFIED",
        ),
        (
            "NORMALIZED_RETENTION",
            "RESTRICTED",
            "DIRECT_TEXT",
            "LOCAL_PROCESSING_ALLOWED_DURATION_AND_TERMINATION_UNSPECIFIED",
        ),
        (
            "AGGREGATE_PUBLICATION",
            "UNVERIFIED",
            "UNVERIFIED",
            "CONTENT_UPLOAD_RESTRICTED_NONRECONSTRUCTABLE_METRICS_REQUIRE_CONFIRMATION",
        ),
        ("THIRD_PARTY_DATA", "PROHIBITED", "DIRECT_TEXT", "NO_DATA_OR_PUBLIC_SERVICE_DISTRIBUTION"),
        ("PERSONAL_DECISION", "ALLOWED", "DIRECT_TEXT", "NOT_TRADING_AUTHORIZATION"),
    )
    grants = [
        PurposeGrant(
            purpose=p,
            status=s,
            basis=b,
            limitation=limitation,
            document_ref=document.identity,
            clause="FAQ_BODY_AND_CUSTOMER_TERMS_5_3",
        )
        for p, s, b, limitation in definitions
    ]
    collection = json.loads((root / "artifacts/km004/real-collection.json").read_bytes())
    store = DataStore(root / collection["private_store"])
    rows = tuple(r for d in collection["datasets"] for r in store.load_dataset(d["dataset_id"]))
    before = {
        d["dataset_id"]: hashlib.sha256(
            (store.root / "normalized" / d["dataset_id"] / "observations.parquet").read_bytes()
        ).hexdigest()
        for d in collection["datasets"]
    }
    rejected = 0
    for row in rows:
        if row.kind == "DAILY" and row.price_basis == "RAW":
            try:
                observation_bar(row, row.record_id)
            except ValueError:
                rejected += 1
    result = dict(
        status="KM005R1_EXTERNAL_EVIDENCE_PENDING",
        economy="ECON_NOT_EXECUTED",
        live="LIVE_NOT_APPROVED",
        document=document.model_dump(mode="json"),
        rights=[
            dict(
                grant=g.model_dump(mode="json"),
                decision=rights_decision(g, (document,), own_investment=True, local_only=True),
            )
            for g in grants
        ],
        quality=quality_summary(rows).model_dump(mode="json"),
        raw_alpha_rejections=rejected,
        existing_parquet_hashes=before,
        data_gate="HOLD_PIT_SESSION_ACTIONS_CALENDAR_COST",
        additional_market_rows=0,
        authenticated_calls=0,
        account_calls=0,
        orders=0,
        cancels=0,
        oos_opened=False,
        pnl=None,
        legacy_license_scope="UNCHANGED_CONSERVATIVE_G1",
        resolved="OFFICIAL_FAQ_BODY_AND_PERSONAL_LOCAL_STORAGE_ANALYSIS_SCOPE",
        unresolved=(
            "RETENTION_DURATION_AND_TERMINATION",
            "PRIVATE_BACKTEST_EXACT_SCOPE",
            "PIT_UNIVERSE_DELISTINGS_HALTS",
            "ACTIONS_CALENDAR_RELEASE",
            "COST_CAPITAL_RISK_G0",
        ),
    )
    assert len(rows) == 180 and rejected == 60
    (output / "assessment.json").write_bytes(json.dumps(result, indent=2).encode())
    print(
        "FAQ body verified; personal local analysis/storage basis established; 180 rows unchanged;"
    )
    print(
        "60 RAW alpha rejections persist; external PIT/cost evidence pending; "
        "no new authentication."
    )


if __name__ == "__main__":
    main()
