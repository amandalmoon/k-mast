"""Audit access continuation without changing any previous milestone evidence."""

import json
import subprocess
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest
from scripts.collect_df006 import load_key as dart_key
from scripts.collect_df009 import load_key


def main():
    snapshot = json.loads(
        Path("data/data-first-private-df009r1-audit/preexisting-files.json").read_bytes()
    )
    for name, expected in snapshot.items():
        assert digest(Path(name).read_bytes()) == expected, "PRIOR_PRIVATE_CHANGED"
    tracked_bytes = json.loads(
        Path("data/data-first-private-df009-audit/tracked-files.json").read_bytes()
    )
    for name, expected in tracked_bytes.items():
        if name not in {"scripts/verify.py", ".github/workflows/ci.yml"}:
            assert digest(Path(name).read_bytes()) == expected, "PRIOR_TRACKED_BYTES_CHANGED"
    baseline = "1df749114f4bc69b6b9bb37a3643cd1bde5c427e"
    entries = [
        r.split(b"\t", 1)
        for r in subprocess.check_output(["git", "ls-tree", "-rz", baseline]).split(b"\0")
        if r
    ]
    payload = subprocess.check_output(
        ["git", "cat-file", "--batch"],
        input=b"\n".join(meta.split()[-1] for meta, name in entries) + b"\n",
    )
    cursor = 0
    git_worktree_line_endings = 0
    for _meta, name in entries:
        end = payload.index(b"\n", cursor)
        size = int(payload[cursor:end].split()[-1])
        content = payload[end + 1 : end + 1 + size]
        cursor = end + size + 2
        filename = name.decode("utf-8")
        if filename not in {"scripts/verify.py", ".github/workflows/ci.yml"}:
            working = Path(filename).read_bytes()
            if working != content:
                assert working.replace(b"\r\n", b"\n") == content.replace(b"\r\n", b"\n"), (
                    "PRIOR_GIT_CONTENT_CHANGED"
                )
                git_worktree_line_endings += 1
    keys = (load_key().encode(), dart_key(Path.home() / ".kmast-readonly/opendart.env").encode())
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
        .decode()
        .split("\0")
    )
    paths = [Path(n) for n in names if n and Path(n).is_file()]
    folder = Path("data/data-first-private-df009-krx-access-confirmed")
    paths += [p for p in folder.rglob("*") if p.is_file()]
    for path in paths:
        content = path.read_bytes()
        assert all(k not in content for k in keys), "SECRET_SCAN_FAILED"
    for version in (folder / "executed-versions").iterdir():
        hashes = {
            p.relative_to(version).as_posix(): digest(p.read_bytes()) for p in version.rglob("*.py")
        }
        assert digest(canonical(hashes)) == version.name
    old = Path("data/data-first-private-df009-krx")
    assert json.loads((old / "budget.json").read_bytes())["used"] == 1
    assert (old / "events/0001.json").read_bytes() == (folder / "events/0001.json").read_bytes()
    atomic_json(
        Path("artifacts/df009r1/preservation-audit.json"),
        dict(
            protected_private_files=len(snapshot),
            protected_tracked_files=len(entries),
            prior_raw_tracked_snapshot_files=len(tracked_bytes),
            existing_git_worktree_line_ending_variants=git_worktree_line_endings,
            prior_bytes_unchanged=True,
            original_401_unchanged=True,
            original_budget_not_refunded=True,
            executed_versions_hashed=True,
            secret_matches=0,
            previous_D1_economics_unchanged=True,
        ),
    )
    print("DF009R1 original 401/budget, prior bytes, versioned execution and secrets: PASS")


if __name__ == "__main__":
    main()
