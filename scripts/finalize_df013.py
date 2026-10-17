"""Aggregate offline evidence without running an economic experiment."""

import json
import subprocess
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest


def main():
    folder = Path("artifacts/df013")
    names = [
        "DF013_PROTOCOL.json",
        "d1-readiness.json",
        "pilot-proposal.json",
        "supply-assessment.json",
        "synthetic-observation.json",
    ]
    records = {name: json.loads((folder / name).read_bytes()) for name in names}
    assert records["d1-readiness.json"]["matched_events"] == 0
    assert records["synthetic-observation.json"]["origin"] == "SYNTHETIC"
    atomic_json(
        folder / "results.json",
        dict(
            milestone="DF013",
            protocol_remote_sha="6e779a140441e2d16731b48310efecd77d991a4a",
            baseline_sha="1f6ef645a4f72152363110538088f0061bafbeb2",
            source_hashes={name: digest((folder / name).read_bytes()) for name in names},
            d1_status="D1_COUNTERFACTUAL_DATA_DEPENDENCY_PENDING",
            orb_status="B_ORB_OFFLINE_INFRASTRUCTURE_VERIFIED",
            research_direction=(
                "Prepare a separately approved small B supply pilot; "
                "defer broad new D1 collection while controls remain incomplete"
            ),
            information_value_comparison=(
                "Conditional experimental design judgment, "
                "not measured monetary value or B profitability"
            ),
            full_research_eligible_events=0,
            valid_non_event_control_sets=0,
            existing_technical_replays=6,
            new_economic_trials=0,
            new_d1_price_or_document_downloads=0,
            new_authenticated_requests=0,
            websocket_connections=0,
            actual_subscriptions=0,
            actual_orders=0,
            account_queries=0,
            actual_cancels=0,
            live_authentication=0,
            measured_stream_latency=None,
            measured_message_rate=None,
            provider_cost=None,
            measured_operating_cost=None,
            real_stream_coverage=None,
            rvol="RVOL_NOT_READY",
            pilot_execution_authorized=False,
            frozen_d1_changed=False,
            prior_results_changed=False,
            economic_status="ECONOMIC_EDGE_UNVERIFIED",
            live_status="LIVE_NOT_APPROVED",
            working_branch=subprocess.check_output(["git", "branch", "--show-current"])
            .decode()
            .strip(),
        ),
    )
    print("DF013 cached control dependency and synthetic-only ORB evidence aggregated")


if __name__ == "__main__":
    main()
