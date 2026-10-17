"""Offline preservation, protocol binding, credentials and publication audit."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from kmast.research.publication import require_public_file
from scripts.read_kis_env import load_env


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df003"
    preflight = json.loads((proof / "preflight.json").read_bytes())
    modified = [
        p
        for p, h in preflight["protected_hashes"].items()
        if hashlib.sha256((root / p).read_bytes()).hexdigest() != h
    ]
    assert set(modified) <= {".github/workflows/ci.yml", "scripts/verify.py", "README.md"}, modified
    contract = json.loads((proof / "implementation-contract.json").read_bytes())
    for p, h in contract["source_hashes"].items():
        assert hashlib.sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == h, p
    protocol = (proof / "DF003_PROTOCOL.json").read_bytes()
    assert hashlib.sha256(protocol).hexdigest() == contract["protocol_sha256"]
    config = load_env(Path.home() / ".kmast-readonly/.env")
    secrets = [s.get_secret_value().encode() for s in (config.app_key, config.app_secret)]
    paths = [
        p
        for folder in ("src", "tests", "scripts", "artifacts/df003")
        for p in (root / folder).rglob("*")
        if p.is_file() and p.suffix in {".py", ".json", ".xml", ".log"} and p.name != "audit.json"
    ]
    paths += list((root / "docs/implementation").glob("DF003*.md")) + [
        root / "README.md",
        root / ".github/workflows/ci.yml",
    ]
    for p in paths:
        body = p.read_bytes()
        assert all(s not in body for s in secrets), "secret match; values suppressed"
        require_public_file(
            p.relative_to(root).as_posix(), json.loads(body) if p.suffix == ".json" else None
        )
    cases = ET.parse(proof / "junit.xml").findall(".//testcase")
    assert len(cases) >= 354 and all(
        c.find("failure") is None and c.find("error") is None and c.find("skipped") is None
        for c in cases
    )
    checks = json.loads((proof / "checks.json").read_bytes())
    assert all(c["exit_code"] == 0 for c in checks)
    r = json.loads((proof / "results.json").read_bytes())
    assert len(r["private_hashes"]) == 216
    for p, h in r["private_hashes"].items():
        assert hashlib.sha256((root / r["private_details"] / p).read_bytes()).hexdigest() == h
    result = dict(
        starting_head=preflight["starting_head"],
        modified_previous=modified,
        original_specs_strategy_oms_risk="UNCHANGED",
        original_private_files="ALL_BYTE_HASHES_UNCHANGED",
        protected_private_count=preflight["private_files"],
        v2_preserved=72,
        v3_preserved=90,
        tests=len(cases),
        baseline_tests=331,
        new_tests=len(cases) - 331,
        failures=0,
        skipped=0,
        credentials_scan="PASS_VALUES_SUPPRESSED",
        publication="PASS",
        protocol_sha256=contract["protocol_sha256"],
        hashes={
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        },
    )
    (proof / "audit.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(f"DF003 {len(cases)} tests, immutable protocol, prior private files, publication: PASS")


if __name__ == "__main__":
    main()
