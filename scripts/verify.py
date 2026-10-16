"""Run local checks and retain byte-exact subprocess output; no broker/network operations."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "km000"


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    checks = {
        "pytest": ["-m", "pytest", "-q", "--junitxml=artifacts/km000/junit.xml"],
        "ruff": ["-m", "ruff", "check", "."],
        "format": ["-m", "ruff", "format", "--check", "."],
        "mypy": ["-m", "mypy", "src"],
        "build": ["-m", "build", "--no-isolation"],
        "demo": ["-m", "kmast.demo"],
    }
    results = []
    for name, args in checks.items():
        result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True)
        (EVIDENCE / f"{name}.stdout.log").write_bytes(result.stdout)
        (EVIDENCE / f"{name}.stderr.log").write_bytes(result.stderr)
        results.append(
            {
                "name": name,
                "command": [sys.executable, *args],
                "exit_code": result.returncode,
                "status": "PASS" if result.returncode == 0 else "FAIL",
            }
        )
        print(f"{name}: {results[-1]['status']}")
    (EVIDENCE / "checks.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    sys.exit(int(any(r["exit_code"] != 0 for r in results)))


if __name__ == "__main__":
    main()
