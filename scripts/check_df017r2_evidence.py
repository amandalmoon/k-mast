"""Offline evidence consistency; never certifies provider rights or clock accuracy."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from kmast.data.https_bar_gate import PROPOSAL_HASH, TRUSTED_REVIEWS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    public = root / "artifacts/df017r2"
    result = json.loads((public / "blockers.json").read_bytes())
    r1 = json.loads((public / "r1-remote-verification.json").read_bytes())
    assert r1["sha"] == "2421129aae6157eaadac13bc0093348a1b3892f2"
    assert r1["remote_ref_verified"] and r1["conclusion"] == "success"
    assert {j["name"] for j in r1["jobs"]} == {
        "offline-contracts (3.11)",
        "offline-contracts (3.12)",
    }
    assert all(j["conclusion"] == "success" for j in r1["jobs"])
    assert not TRUSTED_REVIEWS and result["registry_entries"] == 0
    assert result["clock_status"] == "CLOCK_HOLD"
    assert not result["clock_synchronized_and_measured"]
    assert result["clock_error_bound_seconds"] is None
    assert result["provider_status"] == "PROVIDER_RIGHTS_PENDING"
    assert result["approval_status"] == "COLLECTION_APPROVAL_PENDING"
    assert result["provider_reply"] is None and result["inquiry_sent"] is False
    assert all(result[k] is None for k in ("source_metrics", "orb_metrics", "quote_metrics"))
    assert all(v == 0 for v in result["execution_counts"].values())
    for name, expected in result["protected_files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    assert result["proposal_sha256"] == PROPOSAL_HASH
    assert (
        len(json.loads((root / "artifacts/df016/PILOT_PROPOSAL.json").read_bytes())["calls"]) == 22
    )
    probe_bytes = (public / "CAPABILITY_PROBE_PROPOSAL.json").read_bytes()
    assert hashlib.sha256(probe_bytes).hexdigest() == result["capability_proposal_sha256"]
    probe = json.loads(probe_bytes)
    assert probe["total_requests_max"] == 4 and probe["retries"] == 0
    assert probe["authentication_max"] == 1 and len(probe["calls"]) == 3
    assert not probe["execution_approved"] and not probe["scheduled"]
    assert probe["date"] == "2026-10-20" and probe["symbols"] == ["073240"]
    assert probe["environment"] == "PAPER" and probe["venue"] == "J"
    assert all(c["method"] == "GET" and c["symbol"] == "073240" for c in probe["calls"])
    assert result["eligibility"]["independent_execution_review"] == "NOT_STARTED"
    assert result["eligibility"]["new_human_broker_approval"] == "ABSENT"
    observations = json.loads((public / "ntp-observations.json").read_bytes())
    assert observations["total_requested_samples"] == 12
    assert observations["total_valid_samples"] == observations["total_failed_samples"] == 6
    assert observations["absolute_clock_error_bound_seconds"] is None
    assert observations["post_measurement_synchronization"] == "UNSYNCHRONIZED_LOCAL_CMOS"
    offsets = []
    for ref in observations["references"]:
        assert ref["valid_samples"] + ref["failed_samples"] == 6
        for sample in ref["samples"]:
            assert sample["roundtrip_seconds"] >= 0
            expected = abs(sample["ntp_offset_seconds"]) + sample["roundtrip_seconds"] / 2
            assert abs(sample["offset_plus_half_rtt_seconds"] - expected) < 1e-12
            offsets.append(sample["ntp_offset_seconds"])
    assert offsets == result["measured_ntp_offsets_seconds"]
    if args.private:
        private = root / "data/data-first-private-df017r2-audit"
        raw_offsets = []
        for i, ref in enumerate(observations["references"]):
            payload = (private / f"ntp-{i}-stdout.bin").read_bytes()
            assert hashlib.sha256(payload).hexdigest() == ref["stdout_sha256"]
            parsed = []
            errors = []
            for line in payload.decode("cp949").splitlines():
                if not re.match(r"^\d+,", line):
                    continue
                fields = [v.strip() for v in line.split(",")]
                if len(fields) == 5:
                    parsed.append(tuple(map(float, fields[-2:])))
                else:
                    errors.extend(re.findall(r"0x[0-9A-Fa-f]+", line))
            assert parsed == [
                (s["roundtrip_seconds"], s["ntp_offset_seconds"]) for s in ref["samples"]
            ]
            assert errors == ref["error_codes"]
            raw_offsets.extend(offset for _, offset in parsed)
        assert raw_offsets == offsets
        clock = (private / "after-ntp-clock-stdout.bin").read_bytes()
        assert hashlib.sha256(clock).hexdigest() == observations["post_measurement_status_sha256"]
        assert b"Local CMOS Clock" in clock
    assert result["retained_statuses"] == [
        "RVOL_NOT_READY",
        "ECONOMIC_EDGE_UNVERIFIED",
        "LIVE_NOT_APPROVED",
        "B_ORB_STREAM_TRANSPORT_BLOCKED",
    ]
    print("DF017R2 independent consistency PASS; CLOCK_HOLD, rights/approval pending")


if __name__ == "__main__":
    main()
