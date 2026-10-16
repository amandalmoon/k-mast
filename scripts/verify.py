"""Run local checks and retain byte-exact subprocess output; no broker/network operations."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--milestone", choices=("km000", "km001", "km002"), default="km000")
    args = parser.parse_args()
    evidence = ROOT / "artifacts" / args.milestone
    evidence.mkdir(parents=True, exist_ok=True)
    checks = {
        "pytest": ["-m", "pytest", "-q", f"--junitxml=artifacts/{args.milestone}/junit.xml"],
        "ruff": ["-m", "ruff", "check", "."],
        "format": ["-m", "ruff", "format", "--check", "."],
        "mypy": ["-m", "mypy", "src"],
        "build": ["-m", "build", "--no-isolation"],
        "demo": ["-m", "kmast.demo"],
    }
    if args.milestone == "km001":
        checks["regression"] = [
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_broker.py",
            "tests/test_study.py",
        ]
        checks["data-demo"] = [
            "-m",
            "kmast.data.cli",
            "fixture",
            "--output",
            "artifacts/km001/fixture-data-v1",
        ]
    if args.milestone == "km002":
        checks["regression"] = [
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_broker.py",
            "tests/test_study.py",
            "tests/test_km001.py",
            "tests/test_km001_edges.py",
        ]
        checks["mock-demo"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["mock-replay"] = checks["mock-demo"].copy()
        checks["independent-accounting"] = [
            "scripts/check_km002_evidence.py",
            "artifacts/km002/scenarios-v2",
        ]
        checks["wheel-smoke"] = ["scripts/wheel_smoke_km002.py"]
    results = []
    for name, args in checks.items():
        result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True)
        (evidence / f"{name}.stdout.log").write_bytes(result.stdout)
        (evidence / f"{name}.stderr.log").write_bytes(result.stderr)
        results.append(
            {
                "name": name,
                "command": [sys.executable, *args],
                "exit_code": result.returncode,
                "status": "PASS" if result.returncode == 0 else "FAIL",
            }
        )
        print(f"{name}: {results[-1]['status']}")
    (evidence / "checks.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    sys.exit(int(any(r["exit_code"] != 0 for r in results)))


if __name__ == "__main__":
    main()
