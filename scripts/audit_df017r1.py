"""Preserve baseline results/private bytes and scan new evidence without secret output."""

import json
import subprocess
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest

BASELINE = "9bff5ddef584cb1ad85b86b45e133d2b6376aee7"
PERMITTED = {".github/workflows/ci.yml", "scripts/verify.py"}


def main():
    tracked = (
        subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE])
        .decode()
        .splitlines()
    )
    changed = (
        subprocess.check_output(["git", "diff", "--name-only", BASELINE]).decode().splitlines()
    )
    assert not [p for p in changed if p in tracked and p not in PERMITTED]
    snapshot = json.loads(
        Path("data/data-first-private-df017r1-audit/preexisting-files.json").read_bytes()
    )
    for name, expected in snapshot.items():
        path = Path(name)
        assert path.is_file() and digest(path.read_bytes()) == expected
    secrets = []
    for name in (".env", "opendart.env", "krx.env"):
        path = Path.home() / ".kmast-readonly" / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if (
                any(k in key.upper() for k in ("API_KEY", "APP_KEY", "APP_SECRET", "ACCOUNT_REF"))
                and len(value) >= 8
            ):
                secrets.append(value.encode())
    candidates = [
        p
        for root in (Path("artifacts/df017r1"), Path("docs/implementation"))
        for p in root.rglob("*")
        if p.is_file() and "df017r1" in p.as_posix().lower()
    ]
    candidates += [p for p in Path("data").glob("*df017r1*/**/*") if p.is_file()]
    names = set(changed) | set(
        subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"])
        .decode()
        .splitlines()
    )
    candidates += [Path(p) for p in names if Path(p).is_file()]
    assert not any(any(secret in path.read_bytes() for secret in secrets) for path in candidates)
    assert not list(Path("data/data-first-private-df016-pilot").rglob("*.json"))
    assert subprocess.check_output(
        ["git", "check-ignore", "data/data-first-private-df017r1-synthetic/summary.json"]
    ).strip()
    report = dict(
        baseline_sha=BASELINE,
        protected_tracked_files=len(tracked) - len(PERMITTED),
        protected_private_files=len(snapshot),
        protected_bytes_unchanged=True,
        permitted_existing_changes=sorted(PERMITTED),
        secret_matches=0,
        files_scanned=len(candidates),
        actual_authentication_records=0,
        old_protocols_results_unchanged=True,
        raw_private_data_git_excluded=True,
    )
    atomic_json(Path("artifacts/df017r1/preservation-audit.json"), report)
    print("DF017R1 originals/private bytes and secret audit PASS")


if __name__ == "__main__":
    main()
