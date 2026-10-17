"""Publication and frozen-contract audit; no network requests."""

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from kmast.data.normalization import content_hash
from kmast.research.publication import require_public_file
from scripts.read_kis_env import load_env


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/data-first"
    baseline = json.loads((proof / "preflight.json").read_bytes())
    changed = [
        p
        for p, h in baseline["hashes"].items()
        if hashlib.sha256((root / p).read_bytes()).hexdigest() != h
    ]
    assert set(changed) <= {"scripts/verify.py"}, changed
    for p in [root / "IMPLEMENTATION_BASELINE.md", *root.glob("0[0-7]_*.md")]:
        assert p.read_bytes() == subprocess.check_output(
            ["git", "show", baseline["starting_head"] + ":" + p.name], cwd=root
        )
    config = load_env(Path.home() / ".kmast-readonly/.env")
    secrets = [s.get_secret_value().encode() for s in (config.app_key, config.app_secret)]
    paths = sorted(
        p
        for folder in ("src", "tests", "scripts", "artifacts/data-first")
        for p in (root / folder).rglob("*")
        if p.is_file() and p.suffix in {".py", ".json", ".xml", ".log"} and p.name != "audit.json"
    )
    paths += [root / "README.md", root / "docs/implementation/DATA_FIRST_EXPLORATORY_REPORT.md"]
    for p in paths:
        payload = p.read_bytes()
        assert all(secret not in payload for secret in secrets), "secret match; suppressed"
        require_public_file(
            p.relative_to(root).as_posix(), json.loads(payload) if p.suffix == ".json" else None
        )
    cases = ET.parse(proof / "junit.xml").findall(".//testcase")
    assert len(cases) == 312
    assert all(
        c.find("failure") is None and c.find("error") is None and c.find("skipped") is None
        for c in cases
    )
    assert all(c["exit_code"] == 0 for c in json.loads((proof / "checks.json").read_bytes()))
    contract = json.loads((proof / "exploration-contract-v2.json").read_bytes())
    assert contract["code_hash"] == content_hash(
        (root / "src/kmast/research/exploratory.py").read_text(encoding="utf-8")
    )
    assert json.loads((proof / "optimization-equivalence.json").read_bytes())[
        "all_aggregate_metrics_equal"
    ]
    result = dict(
        starting_head=baseline["starting_head"],
        modified_previous=changed,
        tests=312,
        baseline_tests=296,
        new_tests=16,
        failures=0,
        skipped=0,
        credentials_scan="PASS_VALUES_SUPPRESSED",
        public_file_policy="PASS",
        original_specs="UNCHANGED",
        hashes={
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        },
    )
    (proof / "audit.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print("Data-first audit PASS: 312 tests; frozen contracts; public files; credentials")


if __name__ == "__main__":
    main()
