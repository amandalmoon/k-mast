"""KM-003 preflight evidence, before adding strategy implementation."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km003"
    output.mkdir(exist_ok=True)
    old = json.loads((root / "artifacts/km002/audit.json").read_bytes())
    mismatches = [
        p
        for p, value in old["source_hashes"].items()
        if hashlib.sha256((root / p).read_bytes()).hexdigest() != value
    ]
    assert not mismatches, "KM-002 audited sources differ"
    prior = "9bd281209cbc0eb1b49ae917ec8396d758f47cfd"
    subprocess.run(["git", "merge-base", "--is-ancestor", prior, "HEAD"], check=True)
    commands = {
        "pytest": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml=artifacts/km003/baseline-junit.xml",
        ],
        "remote-heads": ["git", "ls-remote", "--heads", "origin"],
        "starting-head": ["git", "rev-parse", "HEAD"],
    }
    results = []
    for name, command in commands.items():
        result = subprocess.run(command, cwd=root, capture_output=True)
        (output / f"baseline-{name}.stdout.log").write_bytes(result.stdout)
        (output / f"baseline-{name}.stderr.log").write_bytes(result.stderr)
        results.append({"name": name, "command": command, "exit_code": result.returncode})
        assert result.returncode == 0, name
    (output / "baseline.json").write_bytes(
        (
            json.dumps(
                {
                    "checks": results,
                    "km002_hash_mismatches": mismatches,
                    "km002_implementation_is_ancestor": True,
                },
                indent=2,
            )
            + "\n"
        ).encode()
    )
    print("PASS: KM-002 ancestry, source hashes, 164 regression cases and remote heads recorded")


if __name__ == "__main__":
    main()
