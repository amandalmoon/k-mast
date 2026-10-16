"""Pre-publication audit. Optional local secret check reads one approved path only."""

import argparse
import ast
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from kmast.research.publication import require_public_file


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-secrets", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km005"
    baseline = json.loads((output / "preflight.json").read_bytes())
    changed = [p for p, h in baseline["starting_hashes"].items() if sha(root / p) != h]
    assert set(changed) <= {"scripts/verify.py", "README.md"}, changed
    authoritative = [root / "IMPLEMENTATION_BASELINE.md"] + [p for p in root.glob("0[0-7]_*.md")]
    for p in authoritative:
        original = subprocess.check_output(
            ["git", "show", baseline["starting_head"] + ":" + p.name], cwd=root
        )
        assert original == p.read_bytes(), "authoritative specification changed"
    paths = sorted(
        {
            p
            for directory in ("src", "tests", "scripts", "configs", "artifacts/km005")
            for p in (root / directory).rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".yaml", ".toml", ".json", ".xml", ".log"}
            and p.name != "audit.json"
        }
    )
    paths += authoritative
    paths += [root / ".github/workflows/ci.yml", root / "README.md"]
    paths += list((root / "docs/implementation").glob("KM005*.md"))
    for path in paths:
        relative = path.relative_to(root).as_posix()
        payload = json.loads(path.read_bytes()) if path.suffix == ".json" else None
        require_public_file(relative, payload)
    secrets_status = "NOT_REQUESTED"
    if args.local_secrets:
        from scripts.read_kis_env import load_env

        config = load_env(Path.home() / ".kmast-readonly/.env")
        secrets = [s.get_secret_value().encode() for s in (config.app_key, config.app_secret)]
        assert all(all(secret not in path.read_bytes() for secret in secrets) for path in paths), (
            "secret scan failed; values suppressed"
        )
        secrets_status = "PASS_VALUES_SUPPRESSED"
    tests = ET.parse(output / "junit.xml").findall(".//testcase")
    required = [
        node.name
        for node in ast.parse((root / "tests/test_km005.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(required) == 33 and all(any(t.attrib["name"] == n for t in tests) for n in required)
    assert not any(t.find("failure") is not None or t.find("error") is not None for t in tests)
    checks = json.loads((output / "checks.json").read_bytes())
    assert all(item["exit_code"] == 0 for item in checks)
    result = dict(
        starting_head=baseline["starting_head"],
        audited_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
        .decode()
        .strip(),
        prior_modified=changed,
        tests=len(tests),
        new_required_tests=len(required),
        test_ids=required,
        failures=0,
        skipped=sum(t.find("skipped") is not None for t in tests),
        secret_scan=secrets_status,
        public_file_policy="PASS",
        authoritative_specs="UNCHANGED",
        file_hashes={p.relative_to(root).as_posix(): sha(p) for p in paths},
        kis_auth_calls=0,
        market_calls=0,
        account_calls=0,
        actual_orders=0,
        actual_cancels=0,
        economy="ECON_NOT_EXECUTED",
        live="LIVE_NOT_APPROVED",
    )
    (output / "audit.json").write_bytes(json.dumps(result, indent=2).encode())
    print("KM005 audit: original contracts preserved; 33 required IDs; publication scan PASS")


if __name__ == "__main__":
    main()
