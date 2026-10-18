"""Independent frozen-scope/pending-supply and private archival evidence checks."""

import argparse
import json
from pathlib import Path

from kmast.data.paper_pilot import BoundedArchive, Budget
from kmast.data.store import canonical, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df014")
    protocol = json.loads((public / "DF014_PROTOCOL.json").read_bytes())
    result = json.loads((public / "results.json").read_bytes())
    proposal_bytes = Path("artifacts/df013/pilot-proposal.json").read_bytes()
    proposal = json.loads(proposal_bytes)
    assert protocol["parent_proposal_sha256"] == digest(proposal_bytes)
    assert result["protocol_sha256"] == digest((public / "DF014_PROTOCOL.json").read_bytes())
    assert [r["symbol"] for r in protocol["targets"]] == [r["symbol"] for r in proposal["targets"]]
    assert (
        protocol["day"] == "2026-10-19"
        and protocol["start"] == "08:50:00"
        and protocol["end"] == "09:25:00"
    )
    assert protocol["environment"] == "PAPER"
    assert all(v == proposal[k] for k, v in protocol["caps"].items())
    assert protocol["quality"]["source_receipt_gap_seconds"] == [0, 2]
    assert protocol["quality"]["inactivity_hold_seconds"] == 5
    assert protocol["quality"]["quote_age_max_seconds"] == 1
    assert not protocol["execution_authorized"]
    assert result["status"] == "DF014_PILOT_PENDING_APPROVAL"
    assert result["protocol_remote_sha"] == "d76a35ae5e43458412e8e57500ce1b5b63cfc3ce"
    for name in [
        "actual_authentication_attempts",
        "actual_connection_attempts",
        "actual_received_quote_frames",
        "actual_account_queries",
        "actual_orders",
        "actual_cancels",
        "live_authentication",
        "outgoing_message_attempts",
    ]:
        assert result[name] == 0
    assert not result["scheduled_execution"] and not result["multi_session_collection_authorized"]
    assert (
        not result["human_streaming_execution_approval"]
        and not result["transport_protection_verified"]
    )
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    assert len(result["channels"]) == 4
    for row in result["channels"]:
        assert row["messages"] == 0 and row["bytes"] == 0
        assert row["subscription_success"] is None and row["first_message"] is None
        assert row["message_rate_distribution"] is None and row["actual_network_latency"] is None
    assert all(
        row["orb5_restored"] is None
        and row["orb15_restored"] is None
        and row["rvol"] == "RVOL_NOT_READY"
        for row in result["opening"]
    )
    preflight = json.loads((public / "preflight.json").read_bytes())
    assert digest((public / "preflight.json").read_bytes()) == result["preflight_sha256"]
    assert preflight["official_paper_endpoint"] == "ws://ops.koreainvestment.com:31000"
    assert (
        preflight["encryption"] == "NONE_ON_WS_TRANSPORT"
        and not preflight["transport_protection_verified"]
    )
    assert preflight["actual_four_subscription_capacity"] is None
    assert not preflight["regular_open_for_pilot_verified"]
    bench = json.loads((public / "synthetic-storage.json").read_bytes())
    assert (
        digest((public / "synthetic-storage.json").read_bytes())
        == result["synthetic_storage_sha256"]
    )
    assert bench["origin"] == "SYNTHETIC" and bench["unique_raw_frames"]
    assert not bench["real_stream_evidence"] and bench["measured_provider_rate"] is None
    assert bench["frames"] == 2048 and bench["logical_file_bytes"] < 3 * 1024**3
    if args.private:
        root = Path("data/data-first-private-df014-pilot")
        assert Budget(root / "control").used["AUTH"] == 0
        assert not (root / "archive/observations.jsonl").exists()
        source = preflight["source"]
        raw = Path("data/data-first-private-df014-sources/raw") / (source["sha256"] + ".bin")
        assert digest(raw.read_bytes()) == source["sha256"]
        old = Path("data/data-first-private-df014-benchmark/archive")
        new = Path("data/data-first-private-df014-benchmark-v2/archive")
        for folder in [old.parent, new.parent]:
            store = BoundedArchive(folder)
            assert store.frames == 2048 and store.used == bench["logical_file_bytes"]
        previous = {
            p.relative_to(old).as_posix(): digest(p.read_bytes())
            for p in old.rglob("*")
            if p.is_file()
        }
        current = {
            p.relative_to(new).as_posix(): digest(p.read_bytes())
            for p in new.rglob("*")
            if p.is_file()
        }
        assert digest(canonical(previous)) == digest(canonical(current))
        assert len(list(new.glob("segments/*/wire/*.bin"))) == 2048
    print(
        "DF014 independent evidence checks PASS"
        + (" (private storage/zero-auth)" if args.private else " (public pending approval)")
    )


if __name__ == "__main__":
    main()
