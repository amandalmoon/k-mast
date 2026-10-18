"""Aggregate actual supply separately from synthetic storage engineering evidence."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from kmast.data.models import KST
from kmast.data.orb_observation import COLUMNS, Context
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.paper_pilot import CHANNELS, TARGETS, Budget, benchmark
from kmast.data.store import canonical, digest


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return dict(
        count=len(ordered),
        minimum=ordered[0],
        median=ordered[len(ordered) // 2],
        p95=ordered[int((len(ordered) - 1) * 0.95)],
        maximum=ordered[-1],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-synthetic-benchmark", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df014")
    bench_root = Path("data/data-first-private-df014-benchmark-v2")
    bench_file = bench_root / "control/summary.json"
    if args.run_synthetic_benchmark and not bench_file.exists():
        opening = datetime(2026, 10, 19, 9, tzinfo=KST)
        context = Context(opening.date(), "KOSPI", opening, True, True, True, "SYNTHETIC_ONLY")
        row = dict.fromkeys(COLUMNS["H0STCNT0"], "0")
        row.update(
            MKSC_SHRN_ISCD="000000",
            BSOP_DATE="20261019",
            STCK_CNTG_HOUR="090000",
            STCK_PRPR="100",
            CNTG_VOL="1",
            ACML_VOL="1",
            ACML_TR_PBMN="100",
            TRHT_YN="N",
        )
        raw = ("0|H0STCNT0|001|" + "^".join(row[c] for c in COLUMNS["H0STCNT0"])).encode()
        result = benchmark(bench_root, raw, context, count=2048)
        immutable_write(bench_file, canonical(result))
    bench = json.loads(bench_file.read_bytes())
    atomic_json(
        public / "synthetic-storage.json",
        bench | dict(real_stream_evidence=False, actual_35_minute_stream_sustained_rate=None),
    )
    root = Path("data/data-first-private-df014-pilot")
    budget = Budget(root / "control")
    auth_success = None
    completed_sends = 0
    for reservation_path in (root / "control/reservations").glob("*.json"):
        reservation = json.loads(reservation_path.read_bytes())
        outcome_path = root / "control/results" / f"{reservation['sequence']:06}.json"
        if not outcome_path.exists():
            continue
        outcome = json.loads(outcome_path.read_bytes())
        if reservation["kind"] == "AUTH":
            auth_success = outcome["category"] == "SUCCESS"
        if reservation["kind"] in {"SUB", "UNSUB", "CONTROL"} and outcome["category"] == "SENT":
            completed_sends += 1
    channels = {
        (symbol, channel): dict(
            symbol=symbol,
            market=market,
            channel=channel,
            authentication_success=None,
            subscription_success=None,
            first_message=None,
            last_message=None,
            messages=0,
            bytes=0,
            message_rate_distribution=None,
            source_receipt_difference_distribution=None,
            validation_delay_distribution=None,
            provider_denials=[],
            quality_blocked=0,
            source_clock_missing=0,
            date_context_defects=0,
            inactivity_suspicions=0,
            cumulative_mismatches=0,
            duplicates_or_inversions=0,
            unknown_market_state=0,
            actual_network_latency=None,
        )
        for symbol, market in TARGETS.items()
        for channel in sorted(CHANNELS)
    }
    bins, lags, validation = {}, {}, {}
    raw_hashes, normalized_ids = [], set()
    retained_inbound = 0
    path = root / "archive/observations.jsonl"
    if path.exists():
        with path.open("rb") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("origin") != "OBSERVED":
                    raise ValueError("SYNTHETIC_DATA_IN_ACTUAL_PILOT_NAMESPACE")
                retained_inbound += 1
                key = (record.get("symbol"), record.get("channel"))
                if key not in channels:
                    continue
                summary = channels[key]
                category = record["category"]
                if category == "SUBSCRIPTION_ACK":
                    summary["subscription_success"] = True
                if category == "SUBSCRIPTION_DENIED":
                    summary["subscription_success"] = False
                    summary["provider_denials"].append(record.get("provider_code"))
                if category != "QUOTATION":
                    continue
                summary["messages"] += 1
                summary["bytes"] += record["bytes"]
                received = record["received_at"]
                summary["first_message"] = summary["first_message"] or received
                summary["last_message"] = received
                bins.setdefault(key, Counter())[received[:19]] += 1
                stamp = datetime.fromisoformat(received)
                for source_time in record["exchange_times"]:
                    if source_time is None:
                        summary["source_clock_missing"] += 1
                    else:
                        lags.setdefault(key, []).append(
                            (stamp - datetime.fromisoformat(source_time)).total_seconds()
                        )
                validation.setdefault(key, []).append(
                    (record["validated_monotonic_ns"] - record["received_monotonic_ns"]) / 1e9
                )
                defects = set(record["defects"])
                summary["quality_blocked"] += int(bool(defects))
                summary["date_context_defects"] += int(
                    bool(defects & {"SOURCE_DATE_UNKNOWN", "BUSINESS_DATE_MISMATCH"})
                )
                summary["inactivity_suspicions"] += int(
                    "INACTIVITY_OR_MISSING_SUSPECTED" in defects
                )
                summary["cumulative_mismatches"] += int(
                    any("CUMULATIVE" in flag for flag in defects)
                )
                summary["duplicates_or_inversions"] += int(
                    any("DUPLICATE" in flag or "INVERSION" in flag for flag in defects)
                )
                summary["unknown_market_state"] += int("MARKET_STATE_UNKNOWN" in defects)
                raw_hashes.append(record["raw_sha256"])
                normalized_ids.add((record["connection"], record["sequence"]))
    for key, summary in channels.items():
        summary["authentication_success"] = auth_success
        if key in bins:
            # Include zero-frame seconds over the fixed 35-minute planned window.
            values = list(bins[key].values()) + [0] * max(0, 2100 - len(bins[key]))
            summary["message_rate_distribution"] = distribution(values)
        summary["source_receipt_difference_distribution"] = distribution(lags.get(key, []))
        summary["validation_delay_distribution"] = distribution(validation.get(key, []))
    raw_hash_payload = canonical(raw_hashes)
    attempts = budget.used
    terminal_path = root / "control/collection-result.json"
    terminal = json.loads(terminal_path.read_bytes()) if terminal_path.exists() else {}
    authorization_path = root / "control/authorization.json"
    authorization = (
        json.loads(authorization_path.read_bytes()) if authorization_path.exists() else {}
    )
    actual = sum(row["messages"] for row in channels.values())
    preflight = json.loads((public / "preflight.json").read_bytes())
    now = datetime.now(UTC)
    missed = now.astimezone(KST).isoformat()[:19] >= "2026-10-19T09:25:00"
    status = (
        ("DF014_PARTIAL_STREAM_QUALITY" if actual else "DF014_PAPER_ACCESS_BLOCKED")
        if attempts["AUTH"] or authorization
        else ("DF014_MISSED_OBSERVATION_WINDOW" if missed else "DF014_PILOT_PENDING_APPROVAL")
    )
    result = dict(
        milestone="DF014",
        status=status,
        assessed_at=now.isoformat(),
        protocol_remote_sha="d76a35ae5e43458412e8e57500ce1b5b63cfc3ce",
        parent_proposal_sha256=digest(Path("artifacts/df013/pilot-proposal.json").read_bytes()),
        protocol_sha256=digest((public / "DF014_PROTOCOL.json").read_bytes()),
        preflight_sha256=digest((public / "preflight.json").read_bytes()),
        synthetic_storage_sha256=digest((public / "synthetic-storage.json").read_bytes()),
        actual_authentication_attempts=attempts["AUTH"],
        actual_connection_attempts=attempts["CONNECT"],
        actual_reconnections=max(0, attempts["CONNECT"] - 1),
        outgoing_message_attempts=budget.outgoing,
        outgoing_send_calls_completed=completed_sends,
        wire_delivery_confirmed=None,
        actual_received_quote_frames=actual,
        retained_inbound_metadata_records=retained_inbound,
        actual_total_application_frames=terminal.get(
            "actual_total_application_frames", 0 if attempts["CONNECT"] == 0 else None
        ),
        actual_total_application_bytes=terminal.get(
            "actual_total_application_bytes", 0 if attempts["CONNECT"] == 0 else None
        ),
        observed_raw_hash_manifest_sha256=digest(raw_hash_payload) if actual else None,
        channels=list(channels.values()),
        opening=[
            dict(
                symbol=symbol,
                orb5_restored=None,
                orb15_restored=None,
                vwap_observable=None,
                post_signal_quote_observable=None,
                rvol="RVOL_NOT_READY",
                source_hashes=None,
                reasons=["NOT_OBSERVED"]
                if not actual
                else ["INDEPENDENT_MARKET_STATE_AND_CORRECTION_QUALIFICATION_REQUIRED"],
            )
            for symbol in TARGETS
        ],
        real_source_coverage=None,
        measured_provider_fees=None,
        real_operator_cost=None,
        network_latency_verified=False,
        clock_sync_verified=preflight["clock_sync_verified"],
        transport_protection_verified=authorization.get("transport_evidence_gate_passed", False),
        human_streaming_execution_approval=authorization.get("human_scope_gate_passed", False),
        runtime_authorization_binding_sha256=digest(authorization_path.read_bytes())
        if authorization
        else None,
        actual_account_queries=0,
        actual_orders=0,
        actual_cancels=0,
        live_authentication=0,
        scheduled_execution=False,
        multi_session_collection_authorized=False,
        next_data_decision=(
            "No 20-session collection until actual approved supply and opening quality "
            "evidence; current observability unmeasured"
        ),
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    atomic_json(public / "results.json", result)
    print(
        json.dumps(
            dict(
                status=status,
                actual_authentication=attempts["AUTH"],
                actual_connections=attempts["CONNECT"],
                actual_quote_frames=actual,
                synthetic_frames=bench["frames"],
            )
        )
    )


if __name__ == "__main__":
    main()
