"""Frozen-source, data preservation, publication and credentials audit; offline only."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from kmast.data.normalization import content_hash
from kmast.research.publication import require_public_file
from scripts.read_kis_env import load_env


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df002"
    preflight = json.loads((proof / "preflight.json").read_bytes())
    modified = [
        p
        for p, h in preflight["hashes"].items()
        if hashlib.sha256((root / p).read_bytes()).hexdigest() != h
    ]
    assert set(modified) <= {
        "src/kmast/research/exploratory.py",
        "scripts/verify.py",
        ".github/workflows/ci.yml",
        "README.md",
    }, modified
    contract = json.loads((proof / "contract-final.json").read_bytes())
    for p, h in contract["code_hashes"].items():
        assert content_hash((root / p).read_text(encoding="utf-8")) == h, p
    cases = ET.parse(proof / "junit.xml").findall(".//testcase")
    assert len(cases) >= 330 and all(
        c.find("failure") is None and c.find("error") is None and c.find("skipped") is None
        for c in cases
    )
    assert all(c["exit_code"] == 0 for c in json.loads((proof / "checks.json").read_bytes()))
    config = load_env(Path.home() / ".kmast-readonly/.env")
    secrets = [v.get_secret_value().encode() for v in (config.app_key, config.app_secret)]
    paths = [
        p
        for folder in ("src", "tests", "scripts", "artifacts/df002")
        for p in (root / folder).rglob("*")
        if p.is_file() and p.suffix in {".py", ".json", ".xml", ".log"} and p.name != "audit.json"
    ]
    paths += list((root / "docs/implementation").glob("DF002*.md")) + [
        root / "README.md",
        root / ".github/workflows/ci.yml",
    ]
    for p in paths:
        body = p.read_bytes()
        assert all(secret not in body for secret in secrets), "secret match; values suppressed"
        require_public_file(
            p.relative_to(root).as_posix(), json.loads(body) if p.suffix == ".json" else None
        )
    private = root / "data/data-first-private-market-v1/df002-v3-reviewed"
    v3 = list(private.glob("*.json"))
    assert len(v3) == 90
    (proof / "audit.json").write_bytes(
        (
            json.dumps(
                dict(
                    starting_head=preflight["starting_head"],
                    modified_previous=modified,
                    specs_and_frozen_strategy_oms_risk="UNCHANGED",
                    v2_originals="72_BYTE_HASHES_UNCHANGED",
                    tests=len(cases),
                    new_tests=len(cases) - 312,
                    failures=0,
                    skipped=0,
                    credentials_scan="PASS_VALUES_SUPPRESSED",
                    publication="PASS",
                    hashes={
                        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in paths
                    },
                    private_v3_hashes={
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in v3
                    },
                ),
                indent=2,
            )
            + "\n"
        ).encode()
    )
    print(f"DF002 publication, secrets, frozen contracts, original V2 and {len(cases)} tests: PASS")


if __name__ == "__main__":
    main()
