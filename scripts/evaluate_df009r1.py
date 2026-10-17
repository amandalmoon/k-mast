"""Actual dated basics corroboration only; preserve prior access-pending report."""

import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from kmast.data.cross_source_identity import corroborate
from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest

SOURCE = Path("data/data-first-private-df009-krx-access-confirmed")
PUBLIC = Path("artifacts/df009r1")
PRIVATE = Path("data/data-first-private-df009r1-identity")


def main():
    plan_raw = Path("artifacts/df009/KRX_QUERY_PLAN.json").read_bytes()
    plan = json.loads(plan_raw)
    state = json.loads((SOURCE / "budget.json").read_bytes())
    assert state["used"] == len(state["events"]) == 47 and not state["halted"]
    snapshots, lineage = {}, []
    for query in plan["queries"]:
        identity = digest(canonical(query))
        record = json.loads((SOURCE / "normalized" / (identity + ".json")).read_bytes())
        assert record["query"] == query and record["request_identity"] == identity
        assert digest(canonical(record["rows"])) == record["normalized_rows_sha256"]
        raw = (SOURCE / "wire" / (record["raw_sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["raw_sha256"]
        assert json.loads(raw)["OutBlock_1"] == record["rows"]
        snapshots[(query["basDd"], query["market"])] = record["rows"]
        lineage.append(
            {k: v for k, v in record.items() if k != "rows"} | dict(rows=len(record["rows"]))
        )
    dossier = json.loads(
        Path("data/data-first-private-df009-identity/corporate-dossier.json").read_bytes()
    )
    targets = json.loads(Path("artifacts/df009/DF009_PROTOCOL.json").read_bytes())["targets"]
    existing = {r["receipt"]: r for r in dossier}
    census = json.loads(
        Path("data/data-first-private-df007-census-v2/all-normalized-disclosures.json").read_bytes()
    )["records"]
    corrections = json.loads(
        Path("data/data-first-private-df008-documents/identity-diagnostics.json").read_bytes()
    )
    parent_links = {r["receipt"]: r.get("official_relation", {}) for r in corrections}
    records = []
    for target in targets:
        old = existing[target["receipt"]]
        official_day = old["dart_source_row"]["rcept_dt"]
        assert target["receipt_date"].replace("-", "") == official_day
        event_day = date(int(official_day[:4]), int(official_day[4:6]), int(official_day[6:]))
        previous_day = (event_day - timedelta(days=1)).strftime("%Y%m%d")
        current = [r for market in ("KOSPI", "KOSDAQ") for r in snapshots[(official_day, market)]]
        previous = [r for market in ("KOSPI", "KOSDAQ") for r in snapshots[(previous_day, market)]]
        event = dict(
            receipt=target["receipt"],
            corp_code=target["corp_code"],
            event_date=event_day.isoformat(),
            corporate_verified=old["CORPORATE_IDENTITY_VERIFIED"],
            stock_code_candidate=old["stock_code_candidate"],
            document_legal_names=old["document_legal_names"],
            document_raw_sha256=old["document_sha256"],
            dart_row_sha256=old["dart_source_row_sha256"],
        )
        result = corroborate(event, current, previous)
        revisions = [
            r
            for r in census
            if r["row"]["corp_code"] == target["corp_code"]
            and r["family"] == "D1"
            and r["revision"] != "ORIGINAL"
        ]
        unrelated_verified = all(
            parent_links.get(r["row"]["rcept_no"], {}).get("relation_verified") is True
            and parent_links[r["row"]["rcept_no"]]["parent_receipt"] != target["receipt"]
            for r in revisions
        )
        covered = date(2022, 10, 17) <= event_day and event_day + timedelta(days=30) <= date(
            2025, 10, 8
        )
        safe_correction = bool(covered and unrelated_verified)
        result.update(
            document_raw_sha256=event["document_raw_sha256"],
            dart_row_sha256=event["dart_row_sha256"],
            queried_dates=[official_day, previous_day],
            receipt_prefix_differs_from_official_date=target["receipt"][:8] != official_day,
            safe_relevant_correction_lineage_verified=safe_correction,
            correction_evidence_scope=(
                "Complete existing B001 census through 2025-10-08; original throu"
                "gh event+30 days only"
            ),
            same_corporate_revision_receipts=[r["row"]["rcept_no"] for r in revisions],
            price_pilot_eligible=result["CORP_STOCK_LINK_VERIFIED"] is True and safe_correction,
            identity_basis=(
                "DART code candidate plus explicit original corporate ID/legal na"
                "me, exact-day official KRX security and adjacent-snapshot corrob"
                "oration; not name-only"
            ),
        )
        result["normalized_sha256"] = digest(canonical(result))
        records.append(result)
    atomic_json(PRIVATE / "linkage.json", records)
    atomic_json(PUBLIC / "event-linkage.json", records)
    atomic_json(PUBLIC / "snapshot-lineage.json", lineage)
    events = state["events"]
    gaps = [
        (
            datetime.fromisoformat(b["started_at"]) - datetime.fromisoformat(a["completed_at"])
        ).total_seconds()
        for a, b in zip(events, events[1:], strict=False)
    ]
    successes = [e for e in events if e["success"]]
    total_rows = sum(len(rows) for rows in snapshots.values())
    unique_standards = {row["ISU_CD"] for rows in snapshots.values() for row in rows}
    verified = [r for r in records if r["CORP_STOCK_LINK_VERIFIED"] is True]
    eligible = {r["receipt"] for r in records if r["price_pilot_eligible"]}
    selected = sorted(
        (t for t in targets if t["receipt"] in eligible), key=lambda t: t["rank_sha256"]
    )[:3]
    proposal = []
    if len(eligible) >= 5 and len(selected) == 3:
        for target in selected:
            linked = next(r for r in records if r["receipt"] == target["receipt"])
            event_day = date.fromisoformat(linked["event_date"])
            proposal.append(
                dict(
                    receipt=target["receipt"],
                    corp_code=target["corp_code"],
                    symbol=linked["historical_short_code"],
                    then_market=linked["then_market"],
                    frozen_rank=target["rank_sha256"],
                    start=(event_day - timedelta(days=60)).isoformat(),
                    end=(event_day + timedelta(days=30)).isoformat(),
                )
            )
    atomic_json(
        PUBLIC / "next-price-proposal.json",
        dict(
            proposal_only=True,
            execution_authorized=False,
            targets=proposal,
            data=(
                "RAW/adjusted daily prices, matching index, real sessions/action/"
                "halt checks; frozen DF006 D1 and 21 warmup sessions"
            ),
            stock_path="/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            stock_tr="FHKST03010100",
            index_path="/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            index_tr="FHKUP03500100",
            expected_stock_pages=6 if proposal else None,
            expected_index_pages=3 if proposal else None,
            proposed_authentication_ceiling=2,
            proposed_retry_inclusive_total_ceiling=20,
            proposed_wait_after_completion_seconds=3.10,
            requires_new_price_scope_approval=True,
            actual_price_requests=0,
            actual_economic_trials=0,
        ),
    )
    result = dict(
        classification="KRX_HISTORICAL_IDENTITY_PARTIALLY_RECOVERED",
        prior_result_preserved="artifacts/df009/results.json",
        query_plan_sha256=digest(plan_raw),
        frozen_originals=12,
        distinct_corporations=12,
        corporate_identity_verified=12,
        historical_security_present_verified=sum(
            r["HISTORICAL_SECURITY_PRESENT"] is True for r in records
        ),
        then_listed_events_verified=sum(r["THEN_LISTED_STATUS_VERIFIED"] is True for r in records),
        corp_stock_links_verified=len(verified),
        independently_named_corporations=len({r["corp_code"] for r in verified}),
        additional_verified_mappings_since_DF008=len(verified),
        identity_conflict_events=sum(bool(r["conflicts"]) for r in records),
        missing_identity_events=sum(r["HISTORICAL_SECURITY_PRESENT"] is None for r in records),
        missing_reasons=dict(Counter(reason for r in records for reason in r["missing_evidence"])),
        receipt_prefix_date_differences=sum(
            r["receipt_prefix_differs_from_official_date"] for r in records
        ),
        cumulative_authenticated_requests=len(events),
        original_401_requests=1,
        post_approval_successful_requests=len(successes),
        successful_market_date_queries=len(snapshots),
        successful_query_dates=len({q[0] for q in snapshots}),
        observed_security_rows=total_rows,
        distinct_standard_codes=len(unique_standards),
        maximum_approved_requests=92,
        request_counts=dict(Counter(e["http_status"] for e in events)),
        minimum_observed_utc_gap_seconds=min(gaps),
        spacing_violations=sum(g < 3.05 for g in gaps),
        resumed_collection_elapsed_seconds=(
            datetime.fromisoformat(events[-1]["completed_at"])
            - datetime.fromisoformat(events[1]["started_at"])
        ).total_seconds(),
        average_cumulative_requests_per_verified_event=len(events) / len(verified)
        if verified
        else None,
        no_independent_experiment_count_claim=True,
        name_normalization_reviewed_after_payload=True,
        full_security_change_history_verified=None,
        full_delisting_halt_history_verified=None,
        safe_relevant_correction_lineage_verified=sum(
            r["safe_relevant_correction_lineage_verified"] for r in records
        ),
        price_and_session_qualified=0,
        price_pilot_qualified=bool(proposal),
        price_pilot_status="PROPOSAL_ONLY_PRICE_QUALITY_PENDING",
        next_price_companies=[r["corp_code"] for r in proposal],
        decision=(
            "Continue D1 identity/lineage qualification; no forced ORB switch after resolved access"
        ),
        snapshot_lineage_sha256=digest(canonical(lineage)),
        event_linkage_sha256=digest(canonical(records)),
        new_price_requests=0,
        new_KIS_requests=0,
        new_DART_requests=0,
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
