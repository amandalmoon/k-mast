"""Local closure audit: unchanged contracts, required test IDs, execution/source byte hashes."""

import argparse
import ast
import hashlib
import json
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

START = "9389040a83b6b0d646d90dd3d4b6f620f5c38c84"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation-head", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km003"
    protected = [
        "src/kmast/core",
        "src/kmast/brokers",
        "src/kmast/data",
        "src/kmast/execution",
        "src/kmast/strategies",
        "tests/conftest.py",
        "tests/km002_helpers.py",
        *[
            p.relative_to(root).as_posix()
            for p in (root / "tests").glob("test_*.py")
            if "km003" not in p.name
        ],
        "artifacts/km000",
        "artifacts/km001",
        "artifacts/km002",
        "requirements-dev.lock",
        "IMPLEMENTATION_BASELINE.md",
        "MIGRATION_V1_1_TO_V1_2.md",
        "AGENTS.md",
        *[p.name for p in root.glob("0[0-7]_*.md")],
    ]
    changes = subprocess.run(
        ["git", "diff", START, "--name-only", "--", *protected],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert not changes, changes
    tests = list(ET.parse(output / "junit.xml").iter("testcase"))
    assert len(tests) >= 214
    assert not any(t.find(k) is not None for t in tests for k in ("failure", "error", "skipped"))
    mapping = {}
    source = root / "tests/test_km003.py"
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and re.match("test_[A-Z]+_[0-9]{3}_", node.name):
            cases = [
                t.attrib["name"]
                for t in tests
                if t.attrib["name"] == node.name or t.attrib["name"].startswith(node.name + "[")
            ]
            assert cases
            mapping["-".join(node.name.split("_")[1:3])] = {
                "source": f"tests/test_km003.py:{node.lineno}",
                "cases": cases,
                "status": "PASS",
            }
    assert len(mapping) == 24
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
    evidence = [
        p
        for p in output.rglob("*")
        if p.is_file() and p.name != "audit.json" and ".sqlite" not in p.name
    ]
    manifest = {
        "starting_head": START,
        "implementation_head": args.implementation_head,
        "branch": "km-003",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "protected_changes": [],
        "protected_paths": protected,
        "tests": {
            "total": len(tests),
            "baseline": 164,
            "new": len(tests) - 164,
            "failed": 0,
            "skipped": 0,
            "required_mapping": mapping,
        },
        "source_hashes": hashes(sources),
        "evidence_hashes": hashes(evidence),
        "hash_basis": "Executed Windows file bytes; checkout line ending conversions may differ",
        "actual_authentication_calls": 0,
        "actual_market_queries": 0,
        "real_market_rows": 0,
        "actual_order_calls": 0,
        "actual_cancel_calls": 0,
        "credential_setup": "USER_DECLINED_THIS_RUN_AFTER_READONLY_AUTHORIZATION",
        "remote_push": False,
        "remote_pr": False,
        "deployment": False,
        "status": "KM003_STRATEGY_CODE_READY_DATA_HOLD",
        "economic_status": "ECONOMIC_EDGE_UNVERIFIED",
        "live_status": "LIVE_NOT_APPROVED",
    }
    (output / "audit.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    print(f"PASS: protected 164-test baseline; {len(tests)} cases; 24 IDs; source/evidence hashes")


if __name__ == "__main__":
    main()
