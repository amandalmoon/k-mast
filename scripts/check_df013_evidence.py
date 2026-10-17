"""Independent source/count/causal-boundary evidence checks; no producer execution."""

import argparse
import json
from pathlib import Path

from kmast.data.store import canonical, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path("artifacts/df013")
    result = json.loads((root / "results.json").read_bytes())
    for name, expected in result["source_hashes"].items():
        assert digest((root / name).read_bytes()) == expected
    protocol = json.loads((root / "DF013_PROTOCOL.json").read_bytes())
    for name, expected in protocol["source_hashes"].items():
        assert digest(Path(name).read_bytes()) == expected
    assert result["protocol_remote_sha"] == "6e779a140441e2d16731b48310efecd77d991a4a"
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    assert result["d1_status"] == "D1_COUNTERFACTUAL_DATA_DEPENDENCY_PENDING"
    assert result["orb_status"] == "B_ORB_OFFLINE_INFRASTRUCTURE_VERIFIED"
    for name in [
        "new_economic_trials",
        "new_authenticated_requests",
        "websocket_connections",
        "actual_subscriptions",
        "actual_orders",
        "account_queries",
        "actual_cancels",
        "live_authentication",
        "valid_non_event_control_sets",
    ]:
        assert result[name] == 0
    assert not result["pilot_execution_authorized"] and not result["frozen_d1_changed"]
    audit = json.loads((root / "d1-readiness.json").read_bytes())
    assert audit["matched_events"] == 0 and len(audit["events"]) == 6
    assert [e["receipt"] for e in audit["events"]] == [e["receipt"] for e in protocol["events"]]
    assert sum(e["exact_entry_snapshot_available"] for e in audit["events"]) == 2
    assert all(
        e["status"] == "UNMATCHED"
        and e["preselectable_controls"] == 0
        and not e["matching_executed"]
        for e in audit["events"]
    )
    assert all(
        e["verified_historical_feature_availability_candidates"] == 0 for e in audit["events"]
    )
    synthetic = json.loads((root / "synthetic-observation.json").read_bytes())
    assert synthetic["origin"] == "SYNTHETIC" and not synthetic["empirical_market_evidence"]
    assert synthetic["messages"] == 1802 and synthetic["rvol"] == "RVOL_NOT_READY"
    assert synthetic["opening5_high"] == "100" and synthetic["opening15_high"] == "200"
    supply = json.loads((root / "supply-assessment.json").read_bytes())
    assert supply["schemas"]["H0STCNT0"]["field_count"] == 47
    assert supply["schemas"]["H0STASP0"]["field_count"] == 63
    assert supply["subscription_limit_verified"] is None
    assert supply["actual_paper_permission"] is None
    proposal = json.loads((root / "pilot-proposal.json").read_bytes())
    assert not proposal["execution_authorized"] and proposal["subscriptions"] == 4
    assert proposal["auth_max"] == 1 and proposal["connection_max"] == 2
    assert [t["symbol"] for t in proposal["targets"]] == ["073240", "462860"]
    assert all(t["current_listing_and_tradability_verified"] is False for t in proposal["targets"])
    if args.private:
        private = Path("data/data-first-private-df013-readiness")
        snapshots = {}
        for path in Path("data/data-first-private-df009-krx-access-confirmed/normalized").glob(
            "*.json"
        ):
            record = json.loads(path.read_bytes())
            assert digest(canonical(record["rows"])) == record["normalized_rows_sha256"]
            snapshots[(record["query"]["basDd"], record["query"]["market"])] = record["rows"]
        for event in audit["events"]:
            detail = (private / event["private_detail_file"]).read_bytes()
            assert digest(detail) == event["private_detail_sha256"]
            rows = snapshots.get((event["entry_date"].replace("-", ""), event["then_market"]))
            assert (rows is not None) == event["exact_entry_snapshot_available"]
            codes = {r["ISU_SRT_CD"] for r in rows or [] if r["ISU_SRT_CD"] != event["symbol"]}
            assert len(codes) == event["exact_entry_pit_candidates"]
            assert (
                len(json.loads(detail)["prior20_codes"])
                == event["prior20_same_market_cached_candidates"]
            )
        synthetic_folder = Path("data/data-first-private-df013-synthetic")
        manifest = (synthetic_folder / "frame-hashes.json").read_bytes()
        assert digest(manifest) == synthetic["raw_hash_manifest_sha256"]
        for expected in json.loads(manifest):
            assert (
                digest((synthetic_folder / "frames" / (expected + ".bin")).read_bytes()) == expected
            )
        for source in supply["sources"].values():
            raw = Path("data/data-first-private-df013-sources/raw") / (source["sha256"] + ".bin")
            assert digest(raw.read_bytes()) == source["sha256"]
    print(
        "DF013 independent evidence checks PASS"
        + (" (private sources/counts)" if args.private else " (public aggregates)")
    )


if __name__ == "__main__":
    main()
