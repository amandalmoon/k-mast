"""Offline design consistency; does not validate a deployed cloud host."""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from kmast.data.https_bar_gate import TRUSTED_REVIEWS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    public = root / "artifacts/gcp-seoul"
    decision = json.loads((public / "decision.json").read_bytes())
    assert decision["status"] == "GCP_HOST_NOT_JUSTIFIED"
    assert decision["design_only"] and not decision["spending_approved"]
    assert not TRUSTED_REVIEWS
    for key in (
        "resources_created",
        "gcp_authentication",
        "broker_authentication",
        "market_requests",
        "websocket_requests",
    ):
        assert decision[key] == 0
    assert decision["actual_clock_error_seconds"] is None
    assert decision["actual_latency_ms"] is None
    assert decision["actual_monthly_bill_usd"] is None
    for name, expected in decision["protected_files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    baseline = json.loads((public / "r1-remote-verification.json").read_bytes())
    assert baseline["sha"] == "2421129aae6157eaadac13bc0093348a1b3892f2"
    assert baseline["conclusion"] == "success" and len(baseline["jobs"]) == 2
    assert {j["name"] for j in baseline["jobs"]} == {
        "offline-contracts (3.11)",
        "offline-contracts (3.12)",
    }
    assert all(j["conclusion"] == "success" for j in baseline["jobs"])
    cost = json.loads((public / "cost-scenarios.json").read_bytes())
    assert len(cost["scenarios"]) == 16
    proposal = json.loads((public / "RESOURCE_APPROVAL_PROPOSAL.json").read_bytes())
    assert proposal["status"] == "PROPOSAL_ONLY_NOT_AUTHORIZED"
    assert proposal["vm"]["count"] == 1 and proposal["network"]["cloud_nat_count"] == 0
    assert sum(d["count"] * d["size_gib"] for d in proposal["disks"]) == 30
    assert not proposal["cloud_authentication_performed"] and not proposal["resources_created"]
    assert not proposal["automatic_collection"]
    candidate = next(
        c
        for c in cost["scenarios"]
        if c["machine"] == "e2-medium"
        and c["vm_hours"] == 176
        and c["disk_gib"] == 30
        and c["network"] == "ephemeral_ipv4"
    )
    assert Decimal(proposal["budget"]["shared_free_allowance_available_estimate_usd"]) == Decimal(
        candidate["monthly_if_shared_free_allowances_available_usd"]
    )
    assert Decimal(proposal["budget"]["shared_free_allowance_exhausted_estimate_usd"]) == Decimal(
        candidate["monthly_if_shared_free_allowances_exhausted_usd"]
    )
    for scenario in cost["scenarios"]:
        components = {k: Decimal(v) for k, v in scenario["components_usd"].items()}
        gross = sum(components.values())
        assert gross == Decimal(scenario["monthly_if_shared_free_allowances_exhausted_usd"])
        net = gross - components["shared_services_without_free_allowance"]
        assert net == Decimal(scenario["monthly_if_shared_free_allowances_available_usd"])
        assert scenario["actual_cash_usd"] is None
        if scenario["network"] == "private_vm_nat":
            assert components["ip"] == Decimal("3.650")
    if args.private:
        private = root / "data/data-first-private-gcp-seoul-audit"
        ref = json.loads((private / "r1-ref.bin").read_bytes())
        run = json.loads((private / "r1-run.bin").read_bytes())
        assert ref["object"]["sha"] == run["head_sha"] == baseline["sha"]
        assert run["conclusion"] == "success"
    print("GCP Seoul independent design/cost/preservation PASS; no host validation claimed")


if __name__ == "__main__":
    main()
