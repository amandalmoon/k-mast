"""Independent public security/decision evidence checks; optional cached/private hashes."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from kmast.data.models import KST
from kmast.data.paper_pilot import ENDPOINT, BoundedArchive, Budget
from kmast.data.paper_security import pilot_disposition, require_secure_transport
from kmast.data.store import digest

OPEN = datetime(2026, 10, 19, 9, tzinfo=KST)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path("artifacts/df015")
    protocol = json.loads((root / "DF015_PROTOCOL.json").read_bytes())
    result = json.loads((root / "results.json").read_bytes())
    assert result["baseline_sha"] == protocol["baseline_sha"]
    assert result["protocol_sha256"] == digest((root / "DF015_PROTOCOL.json").read_bytes())
    assert result["status"] == "DF015_TRANSPORT_PROTECTION_PENDING"
    assert result["pilot_disposition"] == pilot_disposition(
        datetime.fromisoformat(result["assessed_at"])
    )
    assert result["supply_status"] == "B_ORB_STREAM_TRANSPORT_BLOCKED"
    assert result["documented_plaintext_endpoint"] == ENDPOINT
    assert result["documented_official_secure_paper_endpoint"] is None
    assert not result["secure_provider_path_nonexistence_proven"]
    assert (
        result["runtime_secure_route_registry_empty"]
        and result["document_json_cannot_enable_transport"]
    )
    for key in (
        "authentication_attempts",
        "websocket_connections",
        "actual_market_frames",
        "actual_subscriptions",
        "account_queries",
        "orders",
        "cancels",
        "live_authentication",
        "network_document_fetches",
        "tls_test_connections",
    ):
        assert result[key] == 0
    for key in (
        "runtime_tls_established",
        "runtime_tls_certificate_verified",
        "scheduled_execution",
        "human_streaming_approval",
        "automatic_reschedule",
    ):
        assert result[key] is False
    assert all(
        result[k] is None for k in ("actual_orb5", "actual_orb15", "actual_vwap", "actual_returns")
    )
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    assert result["cheapest_verified_eligible_source"] is None
    assert all(
        r["fee"] is None
        and r["secure_authentication"] is None
        and r["retention_analysis_rights"] is None
        and not r["source_switch_authorized"]
        for r in result["alternative_sources"]
    )
    context = result["market_context"]
    assert not context["continuous_verified"] and not context["corrections_verified"]
    assert not context["clock_sync_verified"] and context["clock_error_bound_seconds"] is None
    assert context["research_status"] == "HOLD" and context["rvol"] == "RVOL_NOT_READY"
    stress = json.loads((root / "stress.json").read_bytes())
    assert digest((root / "stress.json").read_bytes()) == result["stress_sha256"]
    assert stress["origin"] == "SYNTHETIC" and stress["actual_market_frames"] == 0
    assert len(stress["cases"]) == result["stress_cases"] == 10
    assert stress["raw_cap"] == protocol["frozen_pilot"]["raw_bytes_cap"] == 1073741824
    assert stress["total_cap"] == protocol["frozen_pilot"]["total_bytes_cap"] == 3221225472
    cases = {r["case"]: r for r in stress["cases"]}
    assert cases["BURST_QUEUE_256"]["overflow_hold"]
    assert cases["BURST_QUEUE_256"]["received"] == 257
    assert cases["DISK_FULL"]["accepted_frames"] == 0
    assert cases["RESTARTED_RECONNECT_BUDGET"]["third_denied"]
    assert cases["FORCED_EXIT_PARTIAL"]["quality"] == "HOLD"
    assert cases["ORPHAN_RAW"]["bytes_preserved"]
    assert pilot_disposition(OPEN.replace(minute=25)) == "DF014_MISSED_OBSERVATION_WINDOW"
    for endpoint in (ENDPOINT, "wss://unregistered.invalid"):
        try:
            require_secure_transport(endpoint, "PAPER", OPEN)
        except PermissionError:
            pass
        else:
            raise AssertionError("Production interlock open")
    if args.private:
        prior = json.loads(Path("artifacts/df014/preflight.json").read_bytes())["source"]
        raw = Path("data/data-first-private-df014-sources/raw") / (prior["sha256"] + ".bin")
        assert digest(raw.read_bytes()) == prior["sha256"]
        manifest = json.loads(
            Path("data/data-first-private-df013-sources/manifest.json").read_bytes()
        )
        for record in manifest.values():
            raw = Path("data/data-first-private-df013-sources/raw") / (record["sha256"] + ".bin")
            assert digest(raw.read_bytes()) == record["sha256"]
        s = Path("data/data-first-private-df015-stress/run-v1")
        for name in ("slow-disk", "large-quote", "crash-complete", "metadata"):
            BoundedArchive(s / name).verify()
        assert Budget(s / "reconnect").used["CONNECT"] == 2
        assert Budget(Path("data/data-first-private-df014-pilot/control")).used["AUTH"] == 0
    print("DF015 independent security/zero-I/O evidence PASS")


if __name__ == "__main__":
    main()
