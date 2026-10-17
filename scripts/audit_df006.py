"""Private preservation, byte lineage, cumulative budget and local-key leak checks."""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest
from scripts.collect_df006 import FOLDER, PROTOCOL_SHA, ROOT, load_key, months


def main():
    manifest = json.loads((FOLDER / "manifest.json").read_bytes())
    budget = json.loads((FOLDER / "budget.json").read_bytes())
    events = budget["events"]
    assert budget["maximum"] == 600 and budget["used"] == len(events) <= 600
    assert [e["number"] for e in events] == list(range(1, len(events) + 1))
    gaps = []
    for a, b in zip(events[:-1], events[1:], strict=True):
        assert "completed_at" in a
        gap = (
            datetime.fromisoformat(b["started_at"]) - datetime.fromisoformat(a["completed_at"])
        ).total_seconds()
        gaps.append(gap)
    for event in events:
        if "sha256" in event:
            raw = (FOLDER / "wire" / (event["sha256"] + ".bin")).read_bytes()
            assert len(raw) == event["bytes"] and digest(raw) == event["sha256"]
        assert event["path"] in {"/api/list.json", "/api/document.xml"}
    assert manifest["complete"]
    parsed_rows = {}
    page_hashes = set()
    covered_months = set()
    for name, record in manifest["pages"].items():
        raw = (FOLDER / "wire" / (record["sha256"] + ".bin")).read_bytes()
        body = json.loads(raw)
        assert body["status"] in {"000", "013"}
        page_hashes.add(record["sha256"])
        covered_months.add(name.split(":")[0])
        if body["status"] == "000":
            for row in body["list"]:
                old = parsed_rows.get(row["rcept_no"])
                assert old is None or old == row
                parsed_rows[row["rcept_no"]] = row
        for page in range(1, int(body.get("total_page", 0)) + 1):
            assert record["params"]["bgn_de"] + ":" + str(page) in manifest["pages"]
    assert covered_months == {b for b, _ in months()}
    selected = json.loads((FOLDER / "selected-disclosures.json").read_bytes())
    assert digest(canonical(selected["rows"])) == selected["normalized_sha256"]
    selection = json.loads((ROOT / "artifacts/df005/DF005_PROTOCOL.json").read_bytes())
    symbols = set(selection["kospi"] + selection["kosdaq"])
    expected = {k: r for k, r in parsed_rows.items() if r.get("stock_code") in symbols}
    assert set(expected) == set(selected["rows"])
    for receipt, value in selected["rows"].items():
        assert value["row"] == expected[receipt]
        assert value["raw_response_sha256"] in page_hashes
        raw = json.loads((FOLDER / "wire" / (value["raw_response_sha256"] + ".bin")).read_bytes())
        assert value["row"] in raw["list"]
    snapshot_path = ROOT / "data/data-first-private-df006-audit/preexisting-files.json"
    protected = json.loads(snapshot_path.read_bytes())
    for filename, expected_hash in protected.items():
        assert digest(Path(filename).read_bytes()) == expected_hash
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=MDR",
            "cc016ac7d86807eae0553e186ec25ad9ed194707",
            "--",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    allowed = {"scripts/verify.py", ".github/workflows/ci.yml"}
    assert set(changed) <= allowed
    frozen = subprocess.check_output(
        ["git", "show", PROTOCOL_SHA + ":artifacts/df006/DF006_PROTOCOL.json"], cwd=ROOT
    )
    assert frozen == (ROOT / "artifacts/df006/DF006_PROTOCOL.json").read_bytes()
    key = load_key(Path.home() / ".kmast-readonly/opendart.env").encode()
    files = [p for p in (ROOT / "artifacts/df006").rglob("*") if p.is_file()]
    files += [p for p in FOLDER.rglob("*") if p.is_file()]
    for p in files:
        assert key not in p.read_bytes(), "SECRET_SCAN_FAILED"
    public = {
        "executed_collector_sha256": digest(
            (
                ROOT
                / "data/data-first-private-df006-audit/executed-sources/scripts/collect_df006.py"
            ).read_bytes()
        ),
        "post_launch_hardening": "PERF_CLOCK_WAIT_RECHECK_CACHE_AND_RETRY_RECOVERY_OFFLINE_ONLY",
        "request_count": budget["used"],
        "budget": 600,
        "minimum_response_completion_gap_seconds": min(gaps) if gaps else None,
        "approved_minimum_gap_seconds": 3.05,
        "strict_spacing_compliant": all(g >= 3.05 for g in gaps),
        "spacing_shortfall_count": sum(g < 3.05 for g in gaps),
        "maximum_spacing_shortfall_seconds": max((3.05 - g for g in gaps if g < 3.05), default=0),
        "spacing_deviation_preserved_not_waived": True,
        "wire_events_hashed": sum("sha256" in e for e in events),
        "complete_months": len(covered_months),
        "all_list_pages_complete": True,
        "all_selected_rows_lineage_verified": True,
        "protected_prior_private_files": len(protected),
        "protected_bytes_unchanged": True,
        "baseline_tracked_code_and_specs_unchanged_except_verify_ci": True,
        "secret_matches": 0,
        "raw_git_excluded": True,
        "protocol_sha256": digest(frozen),
        "protocol_commit": PROTOCOL_SHA,
        "actual_orders": 0,
        "actual_cancels": 0,
        "account_queries": 0,
        "kis_requests": 0,
    }
    for p in (FOLDER / "manifest.json", snapshot_path):
        assert subprocess.run(["git", "check-ignore", "-q", str(p)], cwd=ROOT).returncode == 0
    atomic_json(ROOT / "artifacts/df006/collection-and-preservation-audit.json", public)
    print("DF006 private byte-lineage, budget, preservation and secret audit: PASS")


if __name__ == "__main__":
    main()
