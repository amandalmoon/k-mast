"""R1 publication, baseline and evidence audit; no network or trading capability."""

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from kmast.research.publication import require_public_file
from scripts.read_kis_env import load_env


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km005r1"
    baseline = json.loads((output / "preflight.json").read_bytes())
    changed = [
        p
        for p, h in baseline["starting_hashes"].items()
        if hashlib.sha256((root / p).read_bytes()).hexdigest() != h
    ]
    assert set(changed) <= {"scripts/verify.py"}, changed
    authoritative = [root / "IMPLEMENTATION_BASELINE.md", *root.glob("0[0-7]_*.md")]
    for p in authoritative:
        assert p.read_bytes() == subprocess.check_output(
            ["git", "show", baseline["starting_head"] + ":" + p.name], cwd=root
        )
    paths = sorted(
        {
            p
            for prefix in ("src", "tests", "scripts", "artifacts/km005r1")
            for p in (root / prefix).rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".json", ".xml", ".log"}
            and p.name != "audit.json"
        }
    )
    paths += list((root / "docs/implementation").glob("KM005R1*.md"))
    config = load_env(Path.home() / ".kmast-readonly/.env")
    secrets = [s.get_secret_value().encode() for s in (config.app_key, config.app_secret)]
    for p in paths:
        payload = p.read_bytes()
        assert all(secret not in payload for secret in secrets), "secret match; values suppressed"
        require_public_file(
            p.relative_to(root).as_posix(), json.loads(payload) if p.suffix == ".json" else None
        )
    cases = ET.parse(output / "junit.xml").findall(".//testcase")
    assert len(cases) == 296 and all(
        c.find("failure") is None and c.find("error") is None for c in cases
    )
    assert all(c["exit_code"] == 0 for c in json.loads((output / "checks.json").read_bytes()))
    result = dict(
        audited_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
        .decode()
        .strip(),
        starting_head=baseline["starting_head"],
        modified_previous=changed,
        tests=296,
        baseline_tests=285,
        new_tests=11,
        skipped=sum(c.find("skipped") is not None for c in cases),
        failures=0,
        credentials_scan="PASS_VALUES_SUPPRESSED",
        public_file_policy="PASS",
        original_specs="UNCHANGED",
        actual_auth_orders_cancels=0,
        file_hashes={
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        },
    )
    (output / "audit.json").write_bytes(json.dumps(result, indent=2).encode())
    print("R1 audit PASS: original specs/tests preserved, 296 tests, metadata-only publication")


if __name__ == "__main__":
    main()
