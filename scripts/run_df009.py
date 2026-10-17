"""Read only prior DART evidence and actual KRX journal; no network or price access."""

import json
import subprocess
from collections import Counter
from pathlib import Path

from kmast.data.document_qualification import qualify_document
from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest

PUBLIC = Path("artifacts/df009")
PRIVATE = Path("data/data-first-private-df009-identity")


def main():
    protocol_bytes = (PUBLIC / "DF009_PROTOCOL.json").read_bytes()
    assert protocol_bytes == subprocess.check_output(
        ["git", "show", "fa0927a:artifacts/df009/DF009_PROTOCOL.json"]
    )
    protocol = json.loads(protocol_bytes)
    source = Path("data/data-first-private-df006-events")
    manifest = json.loads((source / "manifest.json").read_bytes())
    rows = {}
    for record in manifest["pages"].values():
        raw = (source / "wire" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
        for row in json.loads(raw)["list"]:
            assert row["rcept_no"] not in rows or rows[row["rcept_no"]] == row
            rows[row["rcept_no"]] = row
    assert len(rows) == 19319
    documents = Path("data/data-first-private-df008-documents")
    dossier, public_rows = [], []
    for target in protocol["targets"]:
        old = json.loads((documents / "qualified" / (target["receipt"] + ".json")).read_bytes())
        raw = (documents / "wire" / (old["raw_sha256"] + ".bin")).read_bytes()
        proof = qualify_document(raw, target["receipt"], target["corp_code"])
        assert proof["normalized_sha256"] == old["normalized_sha256"]
        assert proof["CORPORATE_IDENTITY_VERIFIED"] is True
        dart = rows[target["receipt"]]
        assert (
            dart["corp_code"] == target["corp_code"]
            and dart.get("stock_code", "") == target["stock_code"]
        )
        record = dict(
            receipt=target["receipt"],
            corp_code=target["corp_code"],
            dart_source_row=dart,
            dart_source_row_sha256=digest(canonical(dart)),
            document_sha256=proof["raw_sha256"],
            document_legal_names=proof["corporate_legal_names"],
            stock_code_candidate=target["stock_code"],
            source_market=target["source_market"],
            CORPORATE_IDENTITY_VERIFIED=True,
            HISTORICAL_SECURITY_PRESENT=None,
            CORP_STOCK_LINK_VERIFIED=None,
            THEN_LISTED_STATUS_VERIFIED=None,
            DELISTING_AND_HALT_PENDING=True,
            CORPORATE_ACTION_PENDING=True,
            PRICE_AND_SESSION_PENDING=True,
            actual_publication_time=None,
            historical_standard_code=None,
            historical_short_code=None,
            then_market=None,
            identity_conflict=None,
            missing_evidence=[
                "SUCCESSFUL_KRX_HISTORICAL_RESPONSE_UNAVAILABLE",
                "DATED_ISSUER_SECURITY_CORROBORATION_PENDING",
                "SECURITY_CHANGE_HISTORY_PENDING",
                "SAFE_RELEVANT_CORRECTION_LINEAGE_PENDING",
            ],
        )
        if not target["stock_code"]:
            record["missing_evidence"].append("DART_STOCK_CODE_CANDIDATE_UNAVAILABLE")
        if target["source_market"] not in {"Y", "K"}:
            record["missing_evidence"].append("SOURCE_MARKET_OUTSIDE_KOSPI_KOSDAQ_OR_UNKNOWN")
        dossier.append(record)
        public_rows.append(
            {
                k: v
                for k, v in record.items()
                if k not in {"dart_source_row", "document_legal_names"}
            }
        )
    atomic_json(PRIVATE / "corporate-dossier.json", dossier)
    atomic_json(PUBLIC / "event-linkage.json", public_rows)
    krx = Path("data/data-first-private-df009-krx")
    budget = json.loads((krx / "budget.json").read_bytes())
    assert budget["used"] == len(budget["events"]) == 1
    event = budget["events"][0]
    assert event["http_status"] == 401 and not event["success"]
    raw = (krx / "wire" / (event["sha256"] + ".bin")).read_bytes()
    assert digest(raw) == event["sha256"] and json.loads(raw)["respCode"] == "401"
    assert not list((krx / "normalized").glob("*.json"))
    result = dict(
        protocol_sha256=digest(protocol_bytes),
        preregistration_commit="fa0927a",
        query_plan_sha256=digest((PUBLIC / "KRX_QUERY_PLAN.json").read_bytes()),
        pilot_originals=12,
        distinct_corporations=12,
        years=dict(Counter(r["receipt"][:4] for r in protocol["targets"])),
        corporate_identity_verified=12,
        dart_numeric_code_candidates=sum(bool(r["stock_code"]) for r in protocol["targets"]),
        source_non_YK_events=sum(r["source_market"] not in {"Y", "K"} for r in protocol["targets"]),
        historical_security_present_verified=0,
        corp_stock_links_verified=0,
        then_listed_events_verified=0,
        additional_verified_mappings_since_DF008=0,
        observed_historical_rows=None,
        historical_date_service_available=None,
        successful_query_dates=0,
        successful_market_date_queries=0,
        attempted_market_date_queries=1,
        planned_unique_queries=46,
        unattempted_queries=45,
        authentication_issuance_calls=0,
        authenticated_requests=1,
        maximum_approved_requests=92,
        retries=0,
        response_http_status=401,
        response_provider_code="401",
        response_sha256=event["sha256"],
        provider_reason="Unauthorized API Call",
        collection_halted=True,
        observed_gap_pairs=0,
        minimum_gap_seconds=None,
        spacing_violations=0,
        classification="KRX_AUTH_OR_SERVICE_ACCESS_PENDING",
        historical_coverage_status="NOT_TESTED_AUTH_REJECTED",
        key_vs_service_cause="UNRESOLVED_GENERIC_401",
        identity_conflicts_observed=None,
        cost_requests_per_verified_event=None,
        price_pilot_qualified=False,
        next_price_companies=[],
        corporate_dossier_sha256=digest(canonical(dossier)),
        event_linkage_sha256=digest(canonical(public_rows)),
        new_KIS_requests=0,
        new_DART_requests=0,
        new_price_requests=0,
        new_economic_trials=0,
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    atomic_json(PUBLIC / "results.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
