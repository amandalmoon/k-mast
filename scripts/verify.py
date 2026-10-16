"""Run local checks and retain byte-exact subprocess output; no broker/network operations."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--milestone",
        choices=("km000", "km001", "km002", "km003", "km004", "km005", "km005r1"),
        default="km000",
    )
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
    if args.milestone == "km003":
        checks["regression"] = [
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_broker.py",
            "tests/test_study.py",
            "tests/test_km001.py",
            "tests/test_km001_edges.py",
            "tests/test_km002.py",
            "tests/test_km002_edges.py",
        ]
        checks["alpha-functional"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["alpha-replay"] = checks["alpha-functional"].copy()
        checks["independent-reference"] = [
            "scripts/check_km003_evidence.py",
            "artifacts/km003/functional-v1",
        ]
        checks["wheel-smoke"] = ["scripts/wheel_smoke_km003.py"]
    if args.milestone == "km004":
        checks["risk-diagnostic"] = ["scripts/risk_diagnostic_km004.py"]
        checks["regression220"] = [
            "-m",
            "pytest",
            "-q",
            "--ignore=tests/test_km004.py",
            "--ignore=tests/test_km004_edges.py",
        ]
        checks["joint-demo"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["joint-replay"] = checks["joint-demo"].copy()
        checks["independent-accounting"] = ["scripts/check_km004_evidence.py"]
        checks["wheel-smoke"] = ["scripts/wheel_smoke_km004.py"]
        checks["old-mock-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["old-alpha-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
    if args.milestone == "km005":
        checks["regression252"] = ["-m", "pytest", "-q", "--ignore=tests/test_km005.py"]
        checks["km005-new"] = ["-m", "pytest", "-q", "tests/test_km005.py"]
        checks["data-absent-hold"] = [
            "-m",
            "kmast.research.cli",
            "--output",
            "artifacts/km005/offline",
        ]
        checks["km002-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["km003-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["km004-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["economic-evidence"] = ["scripts/check_km005_evidence.py"]
    if args.milestone == "km005r1":
        checks["regression285"] = ["-m", "pytest", "-q", "--ignore=tests/test_km005r1.py"]
        checks["new-rights-contracts"] = ["-m", "pytest", "-q", "tests/test_km005r1.py"]
        checks["km002-replay"] = [
            "-m",
            "kmast.execution.demo",
            "--output",
            "artifacts/km002/scenarios-v2",
        ]
        checks["km003-replay"] = [
            "-m",
            "kmast.simulation.cli",
            "--output",
            "artifacts/km003/functional-v1",
        ]
        checks["km004-replay"] = [
            "-m",
            "kmast.portfolio.demo",
            "--output",
            "artifacts/km004/joint-v1",
        ]
        checks["data-absent-hold"] = [
            "-m",
            "kmast.research.cli",
            "--output",
            "artifacts/km005r1/offline",
        ]
        checks["economic-evidence"] = [
            "scripts/check_km005_evidence.py",
            "--report",
            "artifacts/km005r1/offline/qualification.json",
        ]
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
    (evidence / "checks.json").write_bytes((json.dumps(results, indent=2) + "\n").encode("utf-8"))
    sys.exit(int(any(r["exit_code"] != 0 for r in results)))


if __name__ == "__main__":
    main()
