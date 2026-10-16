"""Capture local preflight, historical baseline and prior data integrity without secrets."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from kmast.data.store import DataStore


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km004"
    output.mkdir(exist_ok=True)
    old = json.loads((root / "artifacts/km003/audit.json").read_bytes())
    differences = [
        p
        for p, h in old["source_hashes"].items()
        if hashlib.sha256((root / p).read_bytes()).hexdigest() != h
    ]
    assert not differences
    proof = json.loads((root / "artifacts/readonly-check-20261016/read-check.json").read_bytes())
    folder = root / "data/km003-readonly-20261016T140017954455Z"
    rows = DataStore(folder).load_dataset(proof["dataset_id"])
    assert len(rows) == 4 and all(row.data_origin == "KIS_READONLY" for row in rows)
    commands = {
        "regression214": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--ignore=tests/test_kis_env.py",
            "--junitxml=artifacts/km004/baseline214.xml",
        ],
        "regression220": [sys.executable, "-m", "pytest", "-q"],
        "mypy": [sys.executable, "-m", "mypy", "src"],
        "ruff": [sys.executable, "-m", "ruff", "check", "."],
        "remote": ["git", "ls-remote", "--heads", "origin"],
        "head": ["git", "rev-parse", "HEAD"],
        "ancestry": [
            "git",
            "merge-base",
            "--is-ancestor",
            "d6198b88c23233f5a483735e4e8841534535d76b",
            "HEAD",
        ],
    }
    results = []
    for name, command in commands.items():
        result = subprocess.run(command, capture_output=True, cwd=root)
        (output / f"baseline-{name}.stdout.log").write_bytes(result.stdout)
        (output / f"baseline-{name}.stderr.log").write_bytes(result.stderr)
        results.append({"name": name, "command": command, "exit_code": result.returncode})
        assert result.returncode == 0, name
    sources = [
        p
        for folder in ("src", "tests", "configs")
        for p in (root / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    manifest = {
        "checks": results,
        "km003_source_mismatches": [],
        "prior_real_rows_verified": 4,
        "starting_hashes": {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
    }
    (output / "baseline.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    print(
        "PASS: 214 milestone + 6 env regressions; prior four real rows verified; lineage preserved"
    )


if __name__ == "__main__":
    main()
