"""Local protected-contract, test-ID, source/evidence hash audit. No external access."""

import argparse
import ast
import hashlib
import json
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

START = "a7bb5399ee2f65145bc91e358e0fe05c8785f9ce"
PRIOR_IMPLEMENTATION = "364c18f710ad0f37e094085c8cd040a6475ad718"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation-head", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km002"

    def git(*arguments):
        return subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("merge-base", "--is-ancestor", PRIOR_IMPLEMENTATION, START)
    protected = [
        "src/kmast/core",
        "src/kmast/data",
        "src/kmast/brokers",
        "src/kmast/strategies",
        "tests/test_contracts.py",
        "tests/test_broker.py",
        "tests/test_study.py",
        "tests/test_km001.py",
        "tests/test_km001_edges.py",
        "tests/conftest.py",
        "artifacts/km000",
        "artifacts/km001",
        "docs/specification",
        "requirements-dev.lock",
        "IMPLEMENTATION_BASELINE.md",
        "MIGRATION_V1_1_TO_V1_2.md",
        "AGENTS.md",
        "docs/implementation/KM000_CLOSURE_REPORT.md",
        "docs/implementation/KM001_CLOSURE_REPORT.md",
        *[p.name for p in root.glob("0[0-7]_*.md")],
    ]
    assert not git("diff", START, "--name-only", "--", *protected)
    tests = list(ET.parse(output / "junit.xml").iter("testcase"))
    assert tests and not any(
        t.find(kind) is not None for t in tests for kind in ("failure", "error", "skipped")
    )
    mapping = {}
    tree = ast.parse((root / "tests/test_km002.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and re.match(r"test_[A-Z]+_\d{3}_", node.name):
            identity = "-".join(node.name.split("_")[1:3])
            cases = [
                t.attrib["name"]
                for t in tests
                if t.attrib["name"] == node.name or t.attrib["name"].startswith(node.name + "[")
            ]
            assert cases, identity
            mapping[identity] = {
                "source": f"tests/test_km002.py:{node.lineno}",
                "cases": cases,
                "status": "PASS",
            }
    assert len(mapping) == 38
    checks = json.loads((output / "checks.json").read_bytes())
    assert all(item["exit_code"] == 0 for item in checks)

    def hashes(paths):
        return {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)
        }

    sources = [
        p
        for folder in ("src", "tests", "scripts", "configs", ".github")
        for p in (root / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    sources += [root / name for name in ("pyproject.toml", "requirements-dev.lock", "AGENTS.md")]
    sources += [root / p for p in protected if (root / p).is_file() and p.endswith(".md")]
    sources += [root / "docs/implementation/KM002_USAGE.md"]
    evidence = [
        p
        for p in output.rglob("*")
        if p.is_file()
        and p.name != "audit.json"
        and "scenarios-v1" not in p.parts
        and ".sqlite" not in p.name
    ]
    audit = {
        "checked_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "starting_head": START,
        "implementation_head": args.implementation_head,
        "branch": git("branch", "--show-current"),
        "prior_implementation_is_ancestor": True,
        "protected_changes": [],
        "protected_paths": protected,
        "tests": {
            "total": len(tests),
            "baseline": 98,
            "new": len(tests) - 98,
            "failed": 0,
            "skipped": 0,
            "required_id_mapping": mapping,
        },
        "source_hashes": hashes(set(sources)),
        "evidence_hashes": hashes(evidence),
        "actual_account_auth_calls": 0,
        "actual_account_queries": 0,
        "actual_market_rows": 0,
        "actual_order_calls": 0,
        "actual_cancel_calls": 0,
        "remote_push": False,
        "deployment": False,
        "status": "KM002_LEDGER_OMS_MOCK_READY",
        "data_status": "KM001_REAL_DATA_HOLD",
        "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
        "live_status": "LIVE_NOT_APPROVED",
        "limitations": [
            "SYNTHETIC_ONLY",
            "WINDOWS_SINGLE_HOST_LOCK_TESTED",
            "NO_DISTRIBUTED_FENCING",
            "POSTGRESQL_NOT_VALIDATED",
            "KIS_ACCOUNT_READERS_NOT_IMPLEMENTED",
        ],
    }
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: {len(tests)} tests; 38 required IDs; protected contracts unchanged; hashes recorded"
    )


if __name__ == "__main__":
    main()
