"""Local preservation and secret scan; never print configuration values."""

import json
import subprocess
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest


def main():
    baseline = "d36f4c40706521686ddd486928c20640a61e7208"
    paths = (
        subprocess.check_output(["git", "ls-tree", "-r", "--name-only", baseline])
        .decode()
        .splitlines()
    )
    permitted = {"scripts/verify.py", ".github/workflows/ci.yml"}
    changed = (
        subprocess.check_output(["git", "diff", "--name-only", baseline]).decode().splitlines()
    )
    protected_changes = [p for p in changed if p in paths and p not in permitted]
    assert not protected_changes
    snapshot = json.loads(
        Path("data/data-first-private-df014-audit/preexisting-files.json").read_bytes()
    )
    assert all(Path(p).exists() and digest(Path(p).read_bytes()) == h for p, h in snapshot.items())
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
        for root in (Path("artifacts/df014"), Path("docs/implementation"))
        for p in root.rglob("*")
        if p.is_file() and ("df014" in p.as_posix().lower())
    ]
    candidates += [p for p in Path("data").glob("*df014*/**/*") if p.is_file()]
    for path in (
        "scripts/collect_df014.py",
        "scripts/preflight_df014.py",
        "scripts/report_df014.py",
        "scripts/check_df014_evidence.py",
        "scripts/audit_df014.py",
        "src/kmast/data/paper_collector.py",
        "src/kmast/data/paper_pilot.py",
        "tests/test_df014.py",
        "scripts/verify.py",
        ".github/workflows/ci.yml",
    ):
        candidates.append(Path(path))
    hits = sum(any(secret in p.read_bytes() for secret in secrets) for p in candidates)
    assert hits == 0
    report = dict(
        baseline_sha=baseline,
        protected_tracked_files=len(paths) - len(permitted),
        protected_private_files=len(snapshot),
        protected_bytes_unchanged=True,
        secret_matches=hits,
        files_scanned=len(candidates),
        permitted_existing_changes=sorted(permitted),
        raw_prices_and_detail_trades_git_excluded=True,
    )
    ignored = subprocess.check_output(
        [
            "git",
            "check-ignore",
            "data/data-first-private-df014-benchmark-v2/control/summary.json",
        ]
    )
    assert ignored.strip()
    atomic_json(Path("artifacts/df014/preservation-audit.json"), report)
    print("DF014 preservation/secret checks PASS")


if __name__ == "__main__":
    main()
