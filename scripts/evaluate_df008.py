"""Aggregate preregistered document conversions, never price outcomes."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest

PRIVATE = Path("data/data-first-private-df008-documents")
PUBLIC = Path("artifacts/df008")
FLAGS = (
    "DOCUMENT_VERIFIED",
    "CORPORATE_IDENTITY_VERIFIED",
    "HISTORICAL_SYMBOL_MAPPING_VERIFIED",
    "EVENT_FAMILY_VERIFIED",
    "PRICE_AND_SESSION_QUALIFIED",
)


def main():
    target_bytes = (PUBLIC / "document-targets.json").read_bytes()
    targets = json.loads(target_bytes)
    budget = json.loads((PRIVATE / "budget.json").read_bytes())
    events = budget["events"]
    assert budget["used"] == len(events) <= 178
    allowed = {r["receipt"] for r in targets["originals"] + targets["revisions"]}
    attempts = Counter(e["receipt"] for e in events)
    assert set(attempts) <= allowed and max(attempts.values(), default=0) <= 2
    records = {}
    diagnostics = json.loads((PRIVATE / "identity-diagnostics.json").read_bytes())
    relations = {r["receipt"]: r.get("official_relation", {}) for r in diagnostics}
    for path in (PRIVATE / "qualified").glob("*.json"):
        row = json.loads(path.read_bytes())
        expected = row.pop("normalized_sha256")
        assert digest(canonical(row)) == expected
        row["normalized_sha256"] = expected
        assert (
            digest((PRIVATE / "wire" / (row["raw_sha256"] + ".bin")).read_bytes())
            == row["raw_sha256"]
        )
        records[row["receipt"]] = row
    summary = {}
    public_events = []
    for group in ("originals", "revisions"):
        selected = targets[group]
        summary[group] = dict(
            targets=len(selected),
            attempted=sum(r["receipt"] in attempts for r in selected),
            **{
                flag: sum(records.get(r["receipt"], {}).get(flag) is True for r in selected)
                for flag in FLAGS
            },
        )
        for target in selected:
            row = records.get(target["receipt"])
            responses = [e for e in events if e["receipt"] == target["receipt"]]
            response = responses[-1] if responses else {}
            public_events.append(
                dict(
                    receipt=target["receipt"],
                    group=group,
                    attempted=target["receipt"] in attempts,
                    states={flag: row.get(flag) if row else None for flag in FLAGS},
                    raw_sha256=row["raw_sha256"] if row else response.get("sha256"),
                    normalized_sha256=row["normalized_sha256"] if row else None,
                    missing_evidence=row["missing_evidence"]
                    if row
                    else [response.get("error_category", "NOT_OBSERVED")],
                    api_status=response.get("api_status"),
                    title_body_mismatch=row.get("title_body_mismatch") if row else None,
                    correction_parent_receipt=relations.get(target["receipt"], {}).get(
                        "parent_receipt"
                    ),
                    correction_relation_verified=relations.get(target["receipt"], {}).get(
                        "relation_verified"
                    ),
                    correction_effective_time=None,
                    relation_sha256=digest(canonical(relations[target["receipt"]]))
                    if relations.get(target["receipt"])
                    else None,
                )
            )
    gaps = [e["completion_gap_utc"] for e in events if e.get("completion_gap_utc") is not None]
    perf = [e["completion_gap_perf"] for e in events if e.get("completion_gap_perf") is not None]
    elapsed = (
        datetime.fromisoformat(events[-1]["completed_at"])
        - datetime.fromisoformat(events[0]["started_at"])
    ).total_seconds()
    o = summary["originals"]
    # Mapping failure blocks A/B regardless of document conversion.
    # Never relax a preregistered threshold after observing results.
    assert o["HISTORICAL_SYMBOL_MAPPING_VERIFIED"] == 0, "REQUIRES_EXPLICIT_A_B_REVIEW"
    early = (PRIVATE / "early-stop.json").exists()
    complete = len(attempts) == 89
    decision = "C_DEPENDENCY_BLOCK" if complete or early else "PENDING"
    result = dict(
        protocol_sha256=digest((PUBLIC / "DF008_PROTOCOL.json").read_bytes()),
        target_sha256=digest(target_bytes),
        summary=summary,
        document_status="DF008_HISTORICAL_IDENTITY_BLOCKED"
        if decision != "PENDING"
        else "DF008_DOCUMENT_COLLECTION_PENDING",
        decision=decision,
        complete=complete,
        early_stopped=early,
        authenticated_requests=budget["used"],
        transmitted_requests=sum(e.get("transmitted", False) for e in events),
        authentication_endpoint_calls=0,
        maximum_approved_requests=178,
        retries=sum(v - 1 for v in attempts.values()),
        elapsed_seconds=elapsed,
        minimum_utc_gap_seconds=min(gaps) if gaps else None,
        minimum_perf_gap_seconds=min(perf) if perf else None,
        spacing_violations=sum(g < 3.05 for g in gaps + perf),
        successful_zip_responses=sum(bool(e.get("success")) for e in events),
        failure_statuses=dict(
            Counter(
                e.get("api_status") or e.get("error_category") or "UNKNOWN"
                for e in events
                if not e.get("success")
            )
        ),
        wire_bytes=sum(e.get("bytes", 0) for e in events),
        active_response_seconds=sum(
            (
                datetime.fromisoformat(e["completed_at"]) - datetime.fromisoformat(e["started_at"])
            ).total_seconds()
            for e in events
        ),
        correction_verified_parent_links=sum(
            r.get("relation_verified") is True for r in relations.values()
        ),
        correction_links_to_selected_originals=sum(
            r.get("relation_verified") is True
            and r.get("parent_receipt") in {t["receipt"] for t in targets["originals"]}
            for r in relations.values()
        ),
        correction_linkage_rate=None,
        correction_linkage_status="PARTIAL_OFFICIAL_INITIAL_DATE_RELATIONS_APPLICABILITY_INCOMPLETE",
        identity_diagnostics_sha256=digest(canonical(diagnostics)),
        full_population_conversion_rate=None,
        iid_market_inference=False,
        price_linkable_independent_events=0,
        new_price_requests=0,
        new_economic_trials=0,
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        public_event_hash=digest(canonical(public_events)),
        source_budget_unchanged=212,
    )
    atomic_json(PUBLIC / "document-qualification.json", public_events)
    atomic_json(PUBLIC / "results.json", result)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
