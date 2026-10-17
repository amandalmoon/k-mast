"""Preserve DF001–008 bytes, actual failed request lineage, and credential boundaries."""

import json
import subprocess
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest
from scripts.collect_df006 import load_key as dart_key
from scripts.collect_df009 import load_key as krx_key


def main():
    audit = Path("data/data-first-private-df009-audit")
    private = json.loads((audit / "preexisting-files.json").read_bytes())
    tracked = json.loads((audit / "tracked-files.json").read_bytes())
    allowed = {"scripts/verify.py", ".github/workflows/ci.yml"}
    for name, expected in private.items():
        assert digest(Path(name).read_bytes()) == expected, "PRIOR_PRIVATE_BYTES_CHANGED"
    for name, expected in tracked.items():
        if name not in allowed:
            assert digest(Path(name).read_bytes()) == expected, "PRIOR_TRACKED_BYTES_CHANGED"
    keys = (dart_key(Path.home() / ".kmast-readonly/opendart.env").encode(), krx_key().encode())
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
        .decode()
        .split("\0")
    )
    paths = [Path(name) for name in names if name and Path(name).is_file()]
    for folder in Path("data").glob("data-first-private-df009-*"):
        paths.extend(p for p in folder.rglob("*") if p.is_file())
    for path in paths:
        content = path.read_bytes()
        assert all(key not in content for key in keys), "SECRET_SCAN_FAILED"
    krx = Path("data/data-first-private-df009-krx")
    for path in (krx / "executed-sources").rglob("*.py"):
        relative = path.relative_to(krx / "executed-sources")
        assert path.read_bytes() == Path(relative).read_bytes(), "EXECUTED_SOURCE_CHANGED"
    state = json.loads((krx / "budget.json").read_bytes())
    assert state["used"] == 1 and state["halted"] == "KRX_AUTH_PERMISSION_OR_QUOTA_FAILURE"
    assert (
        json.loads(Path("data/data-first-private-df006-events/budget.json").read_bytes())["used"]
        == 212
    )
    assert (
        json.loads(Path("data/data-first-private-df008-documents/budget.json").read_bytes())["used"]
        == 89
    )
    atomic_json(
        Path("artifacts/df009/preservation-audit.json"),
        dict(
            protected_private_files=len(private),
            protected_baseline_tracked_files=len(tracked),
            protected_bytes_unchanged=True,
            allowed_baseline_changes=sorted(allowed),
            secret_matches=0,
            executed_source_preserved=True,
            original_D1_ledgers_unchanged=True,
            DF006_budget_unchanged=212,
            DF008_budget_unchanged=89,
            KRX_budget_used=1,
            no_automatic_auth_retry=True,
        ),
    )
    print("DF009 prior bytes, D1, executed source, auth halt and secret audit: PASS")


if __name__ == "__main__":
    main()
