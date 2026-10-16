"""Local evidence manifest and original-contract audit. No credentials or network."""

import hashlib
import json
import platform
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km001"
    implementation = "c464c80e1d4426c010d3feec9667df7712b7b5fc"

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    protected = (
        "src/kmast/core",
        "tests/test_contracts.py",
        "tests/test_broker.py",
        "tests/test_study.py",
    )
    changes = git("diff", implementation, "--name-only", "--", *protected)
    assert not changes
    sources = []
    for folder in ("src", "tests", "scripts", "configs", ".github"):
        sources.extend(
            p for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    sources.extend(root / name for name in ("pyproject.toml", "requirements-dev.lock", "AGENTS.md"))
    hashes = {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(sources)
    }
    artifacts = {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file() and p.name != "audit.json" and "fixture-data" not in p.parts
    }
    audit = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "starting_head": "27ca35ee29639a3e3f05780da9210515cb3667ae",
        "km000_implementation": implementation,
        "km000_starting_hash_mismatches": [],
        "protected_contract_changes": changes,
        "branch": git("branch", "--show-current"),
        "remote": git("remote", "-v"),
        "source_hashes": hashes,
        "evidence_hashes": artifacts,
        "actual_broker_auth_calls": 0,
        "actual_market_queries": 0,
        "actual_order_calls": 0,
        "actual_cancel_calls": 0,
        "status": "KM001_ADAPTER_READY_DATA_HOLD",
    }
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print("PASS: protected contracts unchanged; source and evidence hashes recorded")


if __name__ == "__main__":
    main()
