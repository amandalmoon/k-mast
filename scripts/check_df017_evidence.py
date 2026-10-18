"""Independent DF017 frozen-scope, pending-real-data and synthetic engine checks."""

import argparse
import json
from pathlib import Path

from kmast.data.https_bar_gate import PROPOSAL_HASH, STORE, TRUSTED_REVIEWS
from kmast.data.https_bar_store import Journal
from kmast.data.store import canonical, digest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--private", action="store_true")
    args = p.parse_args()
    root = Path("artifacts/df017")
    protocol = json.loads((root / "DF017_PROTOCOL.json").read_bytes())
    result = json.loads((root / "results.json").read_bytes())
    proposal = Path("artifacts/df016/PILOT_PROPOSAL.json").read_bytes()
    assert (
        digest(proposal)
        == PROPOSAL_HASH
        == protocol["proposal_sha256"]
        == result["proposal_sha256"]
    )
    assert result["protocol_sha256"] == digest((root / "DF017_PROTOCOL.json").read_bytes())
    assert result["baseline_tests"] == 685 and result["registered_approval_count"] == 0
    assert not TRUSTED_REVIEWS and not protocol["execution_approved"]
    assert result["status"] in {
        "DF017_COLLECTION_PENDING_APPROVAL",
        "DF017_MISSED_COLLECTION_WINDOW",
    }
    for key in (
        "auth_attempts",
        "market_attempts",
        "websocket_approval_attempts",
        "websocket_connections",
        "accounts",
        "orders",
        "cancels",
        "live_authentication",
        "actual_retention_purges",
    ):
        assert result[key] == 0
    assert result["actual_metrics"] is None and result["actual_http_status_counts"] is None
    assert result["actual_raw_normalized_hashes"] is None and all(
        v is None for v in result["quality"].values()
    )
    assert not result["scheduled_execution"] and not result["retention_job_scheduled"]
    assert not result["tls_runtime_verified"] and not result["execution_verified"]
    assert result["actual_profit"] is None and result["rvol"] == "RVOL_NOT_READY"
    assert (
        result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and result["live_status"] == "LIVE_NOT_APPROVED"
    )
    assert result["tick_transport"] == "B_ORB_STREAM_TRANSPORT_BLOCKED"
    assert protocol["total_attempts_max"] == 45 and protocol["rest_auth_attempts_max"] == 1
    assert protocol["raw_bytes_cap"] == 134217728 and protocol["total_bytes_cap"] == 268435456
    assert protocol["response_completion_wait_seconds_min"] == 3.10
    model = json.loads((root / "synthetic-engine.json").read_bytes())
    assert model["origin"] == "SYNTHETIC" and model["model_attempts"] == 23
    assert model["minimum_response_end_to_next_request_seconds"] >= 3.10 - 1e-8
    assert model["exact_order"] and model["raw_lineage_verified"] and not model["token_persisted"]
    assert model["actual_authentication_attempts"] == model["actual_market_requests"] == 0
    if args.private:
        assert not (STORE / "binding.json").exists()
        folder = Path("data/data-first-private-df017-synthetic/pilot")
        binding = json.loads((folder / "binding.json").read_bytes())
        assert binding["origin"] == "SYNTHETIC"
        journal = Journal(folder, binding)
        ordered = [journal.outcomes[i] for i in sorted(journal.outcomes)]
        assert digest(canonical(ordered)) == model["journal_outcome_sha256"]
        assert len(journal.reservations) == 23 and len(journal.outcomes) == 23
    print("DF017 independent frozen HTTPS scope/budget/lineage/pending-data checks PASS")


if __name__ == "__main__":
    main()
