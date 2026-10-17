"""Independent public arithmetic and optional byte/timing checks for DF008."""

import argparse
import json
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df008")
    results = json.loads((public / "results.json").read_bytes())
    rows_bytes = (public / "document-qualification.json").read_bytes()
    rows = json.loads(rows_bytes)
    targets = json.loads((public / "document-targets.json").read_bytes())
    assert (
        results["protocol_sha256"]
        == sha256((public / "DF008_PROTOCOL.json").read_bytes()).hexdigest()
    )
    assert (
        results["target_sha256"]
        == sha256((public / "document-targets.json").read_bytes()).hexdigest()
    )

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    assert results["public_event_hash"] == sha256(canonical(rows)).hexdigest()
    assert len(rows) == 89 and len({r["receipt"] for r in rows}) == 89
    for group in ("originals", "revisions"):
        selected = [r for r in rows if r["group"] == group]
        summary = results["summary"][group]
        assert {r["receipt"] for r in selected} == {r["receipt"] for r in targets[group]}
        assert len(selected) == summary["targets"]
        assert sum(r["attempted"] for r in selected) == summary["attempted"]
        for flag in selected[0]["states"]:
            assert sum(r["states"][flag] is True for r in selected) == summary[flag]
        assert all(r["states"]["PRICE_AND_SESSION_QUALIFIED"] is None for r in selected)
    assert results["authenticated_requests"] <= results["maximum_approved_requests"] == 178
    assert results["spacing_violations"] == 0
    assert results["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert results["live_status"] == "LIVE_NOT_APPROVED"
    assert all(
        results[k] == 0
        for k in (
            "new_price_requests",
            "new_economic_trials",
            "actual_orders",
            "actual_cancels",
            "account_queries",
            "price_linkable_independent_events",
            "authentication_endpoint_calls",
        )
    )
    assert results["full_population_conversion_rate"] is None
    assert not results["iid_market_inference"]
    preservation = json.loads((public / "preservation-audit.json").read_bytes())
    assert preservation["protected_bytes_unchanged"] and preservation["secret_matches"] == 0
    if args.private:
        private = Path("data/data-first-private-df008-documents")
        state = json.loads((private / "budget.json").read_bytes())
        events = state["events"]
        assert len(events) == state["used"] == results["authenticated_requests"]
        assert max(Counter(e["receipt"] for e in events).values()) <= 2
        for before, after in zip(events, events[1:], strict=False):
            gap = (
                datetime.fromisoformat(after["started_at"])
                - datetime.fromisoformat(before["completed_at"])
            ).total_seconds()
            assert gap >= 3.05 and abs(gap - after["completion_gap_utc"]) < 1e-6
            if before["run_id"] == after["run_id"]:
                assert after["start_perf"] - before["response_completed_perf"] >= 3.05
        for event in events:
            assert event["receipt"] in {r["receipt"] for r in rows}
            final = json.loads((private / "events" / f"{event['number']:04}.json").read_bytes())
            assert final == event
            if event["wire_stored"]:
                assert (
                    sha256((private / "wire" / (event["sha256"] + ".bin")).read_bytes()).hexdigest()
                    == event["sha256"]
                )
        for row in rows:
            if row["normalized_sha256"]:
                parsed = json.loads(
                    (private / "qualified" / (row["receipt"] + ".json")).read_bytes()
                )
                expected = parsed.pop("normalized_sha256")
                assert sha256(canonical(parsed)).hexdigest() == expected == row["normalized_sha256"]
                assert any(
                    e["receipt"] == row["receipt"] and e.get("sha256") == row["raw_sha256"]
                    for e in events
                )
        diagnostics = json.loads((private / "identity-diagnostics.json").read_bytes())
        assert sha256(canonical(diagnostics)).hexdigest() == results["identity_diagnostics_sha256"]
        relations = [r.get("official_relation", {}) for r in diagnostics]
        assert (
            sum(r.get("relation_verified") is True for r in relations)
            == results["correction_verified_parent_links"]
        )
        assert all(r.get("effective_publication_time") is None for r in relations)
        for row in rows:
            matches = [
                r.get("official_relation", {})
                for r in diagnostics
                if r["receipt"] == row["receipt"]
            ]
            relation = matches[0]
            assert row["correction_parent_receipt"] == relation.get("parent_receipt")
            if row["relation_sha256"]:
                assert sha256(canonical(relation)).hexdigest() == row["relation_sha256"]
        assert not state["halted"]
    print("DF008 independent counts, receipt lineage, timing and frozen gates: PASS")


if __name__ == "__main__":
    main()
