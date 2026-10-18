"""Independent DF016 contract, source/actual separation and causal trace checks."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from kmast.data.store import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path("artifacts/df016")
    protocol = json.loads((root / "DF016_PROTOCOL.json").read_bytes())
    result = json.loads((root / "results.json").read_bytes())
    proposal = json.loads((root / "PILOT_PROPOSAL.json").read_bytes())
    assert (
        result["protocol_sha256"]
        == proposal["protocol_sha256"]
        == digest((root / "DF016_PROTOCOL.json").read_bytes())
    )
    assert result["pilot_proposal_sha256"] == digest((root / "PILOT_PROPOSAL.json").read_bytes())
    assert result["baseline_tests"] == protocol["baseline_tests"] == 637
    assert result["baseline_sha"] == "cd39690d1fde4cc714b40494049d5b27bf5a3317"
    assert result["source_status"] == "BAR_ORB_HTTPS_SOURCE_DOCUMENTED"
    assert result["status"] == "BAR_ORB_COLLECTION_PENDING_APPROVAL"
    assert result["prior_tick_transport_status"] == "B_ORB_STREAM_TRANSPORT_BLOCKED"
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    for key in (
        "authenticated_market_requests",
        "rest_authentication_attempts",
        "websocket_approval_attempts",
        "websocket_connections",
        "account_queries",
        "orders",
        "cancels",
        "live_authentication",
    ):
        assert result[key] == 0
    assert (
        not result["scheduled_execution"] and not proposal["executed"] and not proposal["scheduled"]
    )
    assert not proposal["executor_implemented"]
    for key in (
        "actual_raw_prices",
        "actual_orb5",
        "actual_orb15",
        "actual_signal_available_at",
        "actual_later_quote",
        "actual_fill",
        "actual_profit",
        "exact_bar_label_semantics",
    ):
        assert result[key] is None
    assert result["rvol"] == "RVOL_NOT_READY" and result["prior_qualified_sessions"] == 0
    trs = {"FHKST03010200", "FHPST01060000", "FHKST01010200"}
    assert {c["tr_id"] for c in result["capabilities"]} == trs
    assert all(
        c["paper_documented"]
        and c["actual_paper_support"] is None
        and c["actual_returned_fields"] is None
        and not c["tr_cont_pagination_supported"]
        for c in result["capabilities"]
    )
    scope = proposal["scope"]
    assert scope == protocol["pilot_proposal"]
    assert scope["date"] == "2026-10-20" and scope["environment"] == "PAPER"
    assert scope["symbols"] == ["073240", "462860"] and not scope["execution_approved"]
    assert len(proposal["calls"]) == scope["logical_price_queries_max"] == 22
    assert 1 + len(proposal["calls"]) * 2 == scope["total_requests_including_failures_max"] == 45
    assert scope["response_complete_wait_seconds_min"] == 3.10
    assert scope["raw_bytes_cap"] == 134217728 and scope["total_bytes_cap"] == 268435456
    for c in proposal["calls"]:
        assert c["method"] == "GET" and c["tr_id"] in trs
        assert c["url"].startswith(
            "https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/quotations/"
        )
        assert c["parameters"]["FID_COND_MRKT_DIV_CODE"] == "J"
        assert c["symbol"] in scope["symbols"]
    trace = json.loads((root / "synthetic-trace.json").read_bytes())
    assert trace["origin"] == "SYNTHETIC" and not trace["actual_market_evidence"]
    assert trace["actual_profit"] is None
    assert datetime.fromisoformat(trace["request_at"]) < datetime.fromisoformat(
        trace["response_complete_at"]
    )
    assert datetime.fromisoformat(trace["response_complete_at"]) < datetime.fromisoformat(
        trace["validation_complete_at"]
    )
    for c in trace["cases"]:
        assert c["signal_available_at"] == trace["validation_complete_at"]
        assert c["signal_blocked_before_validation"] and c["later_snapshot"] and not c["fill"]
        assert datetime.fromisoformat(c["signal_available_at"]) < datetime.fromisoformat(
            trace["quote_request_at"]
        )
    if args.private:
        private = Path("data/data-first-private-df016-sources/raw")
        for source in result["sources"].values():
            raw = (private / (source["sha256"] + ".bin")).read_bytes()
            assert digest(raw) == source["sha256"]
        base = Path("data/data-first-private-df016-synthetic")
        for c in trace["cases"]:
            for name, key in (
                ("opening-range.bin", "range_source_sha256"),
                ("breakout.bin", "price_source_sha256"),
                ("quote.bin", "quote_source_sha256"),
            ):
                assert digest((base / name).read_bytes()) == c[key]
    print("DF016 independent HTTPS documentation/causality/zero-market-I/O evidence PASS")


if __name__ == "__main__":
    main()
