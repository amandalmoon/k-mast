"""DF008-only audit outputs; prior evidence is read without rewriting."""

import json
import subprocess
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest
from scripts.collect_df006 import load_key


def main():
    folder = Path("data/data-first-private-df008-audit")
    private = json.loads((folder / "preexisting-files.json").read_bytes())
    tracked = json.loads((folder / "tracked-files.json").read_bytes())
    for name, expected in private.items():
        assert digest(Path(name).read_bytes()) == expected, "PRIOR_PRIVATE_BYTES_CHANGED"
    allowed = {"scripts/verify.py", ".github/workflows/ci.yml"}
    for name, expected in tracked.items():
        if name not in allowed:
            assert digest(Path(name).read_bytes()) == expected, "PRIOR_TRACKED_BYTES_CHANGED"
    key = load_key(Path.home() / ".kmast-readonly/opendart.env").encode()
    files = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
        .decode()
        .split("\0")
    )
    for name in files:
        if name and Path(name).is_file():
            assert key not in Path(name).read_bytes(), "SECRET_SCAN_FAILED"
    current = Path("data/data-first-private-df008-documents")
    for path in current.rglob("*"):
        if path.is_file():
            assert key not in path.read_bytes(), "PRIVATE_SECRET_SCAN_FAILED"
    for name, expected in json.loads(
        (current / "executed-source-hashes.json").read_bytes()
    ).items():
        assert digest((current / "executed-sources" / name).read_bytes()) == expected
        assert digest(Path(name).read_bytes()) == expected, "EXECUTED_SOURCE_CHANGED"
    assert (
        json.loads(Path("data/data-first-private-df006-events/budget.json").read_bytes())["used"]
        == 212
    )
    atomic_json(
        Path("artifacts/df008/preservation-audit.json"),
        dict(
            protected_private_files=len(private),
            protected_tracked_files=len(tracked),
            protected_bytes_unchanged=True,
            allowed_changes=sorted(allowed),
            secret_matches=0,
            original_D1_ledgers_unchanged=True,
            DF006_spacing_failure_preserved=True,
            executed_source_verified=True,
        ),
    )
    print("DF008 preservation, immutable executed source and secret audit: PASS")


if __name__ == "__main__":
    main()
