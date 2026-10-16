"""Offline source/evidence audit; scan only the explicitly approved local configuration."""

import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.read_kis_env import load_env


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km004"
    baseline = json.loads((output / "baseline.json").read_bytes())
    source_keys = [key for key in baseline if "hash" in key]
    previous = baseline[source_keys[0]]
    changed = [p for p, h in previous.items() if sha(root / p) != h]
    allowed = {
        "src/kmast.egg-info/SOURCES.txt",
        "src/kmast/brokers/kis/requests.py",
        "src/kmast/brokers/kis/wire_contract.py",
        "src/kmast/data/parsers.py",
        "src/kmast/execution/events.py",
        "src/kmast/execution/ledger.py",
    }
    assert set(changed) <= allowed, changed
    files = sorted(
        {
            p
            for prefix in ("src", "tests", "scripts", "configs")
            for p in (root / prefix).rglob("*")
            if p.is_file() and p.suffix in {".py", ".toml", ".yaml"}
        }
    )
    files += [root / "README.md", root / "docs/implementation/KM004_CLOSURE_REPORT.md"]
    evidence = sorted(
        p
        for p in output.rglob("*")
        if p.is_file()
        and p.name != "audit.json"
        and p.suffix not in {".sqlite", ".db", ".wal", ".shm"}
        and "sqlite" not in p.name
    )
    config = load_env(Path.home() / ".kmast-readonly/.env")
    # The read-only loader creates this public constant, never an account identifier.
    assert config.account_ref is not None
    assert config.account_ref.get_secret_value() == "READONLY_MARKET_ALIAS"
    secrets = [s.get_secret_value().encode() for s in (config.app_key, config.app_secret) if s]
    for path in files + evidence:
        payload = path.read_bytes()
        assert all(secret not in payload for secret in secrets), (
            "credential scan failed; details suppressed"
        )
    tree = ET.parse(output / "junit.xml")
    tests = tree.findall(".//testcase")
    required = re.findall(
        r"def test_((?:REALDATA|PORT|REBAL|ECON|SAFE)_\d+)\(",
        (root / "tests/test_km004.py").read_text(encoding="utf-8"),
    )
    assert len(required) == 25
    assert all(any(t.attrib["name"] == "test_" + name for t in tests) for name in required)
    checks = json.loads((output / "checks.json").read_bytes())
    assert all(check["exit_code"] == 0 for check in checks)
    result = dict(
        implementation_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
        .decode()
        .strip(),
        tests=len(tests),
        failures=len(tree.findall(".//failure")),
        skipped=len(tree.findall(".//skipped")),
        required_test_ids=required,
        baseline_modified_files=changed,
        credentials_scan="PASS_VALUES_SUPPRESSED",
        source_hashes={p.relative_to(root).as_posix(): sha(p) for p in files},
        evidence_hashes={p.relative_to(root).as_posix(): sha(p) for p in evidence},
        remote_ci="NOT_EXECUTED",
        push="NOT_EXECUTED",
        live="NOT_APPROVED",
    )
    (output / "audit.json").write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
    print("KM004 source, test, evidence and credential audit: PASS")


if __name__ == "__main__":
    main()
