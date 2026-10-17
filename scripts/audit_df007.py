"""Byte preservation and no-secret/no-auth audit, without rewriting prior artifacts."""

import json
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest
from scripts.collect_df006 import load_key


def main():
    root = Path("data/data-first-private-df007-audit")
    private = json.loads((root / "preexisting-files.json").read_bytes())
    tracked = json.loads((root / "tracked-files.json").read_bytes())
    for p, value in private.items():
        assert digest(Path(p).read_bytes()) == value
    allowed = {"scripts/verify.py", ".github/workflows/ci.yml"}
    for p, value in tracked.items():
        if p not in allowed:
            assert digest(Path(p).read_bytes()) == value
    key = load_key(Path.home() / ".kmast-readonly/opendart.env").encode()
    files = [p for p in Path("artifacts/df007").rglob("*") if p.is_file()]
    files += [p for p in Path("data/data-first-private-df007-census-v2").rglob("*") if p.is_file()]
    for p in files:
        assert key not in p.read_bytes(), "SECRET_SCAN_FAILED"
    assert (
        json.loads(Path("data/data-first-private-df006-events/budget.json").read_bytes())["used"]
        == 212
    )
    old = json.loads(Path("artifacts/df006/collection-and-preservation-audit.json").read_bytes())
    assert not old["strict_spacing_compliant"] and old["spacing_shortfall_count"] == 70
    atomic_json(
        Path("artifacts/df007/preservation-audit.json"),
        dict(
            protected_private_files=len(private),
            protected_baseline_tracked_files=len(tracked),
            protected_bytes_unchanged=True,
            allowed_baseline_changes=sorted(allowed),
            DF006_budget_unchanged=212,
            new_authenticated_requests=0,
            secret_matches=0,
            original_DF006_spacing_failure_preserved=True,
            original_D1_ledgers_unchanged=True,
            actual_network_spacing_verification="NOT_EXECUTED",
            offline_guard_only=True,
        ),
    )
    print("DF007 prior specs/code/private bytes, original D1, no-auth and secret audit: PASS")


if __name__ == "__main__":
    main()
