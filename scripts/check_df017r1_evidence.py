"""Offline consistency and preservation checks; never grants execution approval."""

import hashlib
import json
from pathlib import Path

from kmast.data.https_bar_gate import PROPOSAL_HASH, TRUSTED_REVIEWS


def main():
    root = Path(__file__).resolve().parents[1]
    result = json.loads((root / "artifacts/df017r1/preflight.json").read_bytes())
    proposal = (root / "artifacts/df016/PILOT_PROPOSAL.json").read_bytes()
    assert hashlib.sha256(proposal).hexdigest() == PROPOSAL_HASH == result["proposal_sha256"]
    assert len(json.loads(proposal)["calls"]) == 22
    assert not TRUSTED_REVIEWS
    assert result["status"] == "DF017R1_PREFLIGHT_INCOMPLETE"
    assert result["human_approval"] == "ABSENT"
    assert result["registered_reviews"] == 0
    assert result["actual_supply"] is None
    assert all(value == 0 for value in result["execution_counts"].values())
    assert all(value == "UNKNOWN" for value in result["mandatory_evidence"].values())
    assert result["clock_error_bound_seconds"] is None
    assert result["clock_synchronization_observed"] == "UNSYNCHRONIZED_LOCAL_CMOS"
    assert result["documented_domain_is_runtime_tls_verification"] is False
    routes = json.loads((root / "artifacts/df017r1/documented-routes.json").read_bytes())
    assert {r["virtualTrId"] for r in routes} == {
        "FHKST03010200",
        "FHPST01060000",
        "FHKST01010200",
    }
    assert all(r["virtualDomain"] == "https://openapivts.koreainvestment.com:29443" for r in routes)
    assert result["scheduled"] is False
    assert result["retained_statuses"] == [
        "RVOL_NOT_READY",
        "ECONOMIC_EDGE_UNVERIFIED",
        "LIVE_NOT_APPROVED",
        "B_ORB_STREAM_TRANSPORT_BLOCKED",
    ]
    for name, expected in result["protected_files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    print("DF017R1 independent preflight consistency PASS (not provider verification)")


if __name__ == "__main__":
    main()
