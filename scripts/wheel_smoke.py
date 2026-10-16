"""Install the built wheel into a temp directory and run outside the checkout, without network."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = Path(tempfile.mkdtemp(prefix="kmast-km001-wheel-"))
    wheel = root / "dist/kmast-1.2.0-py3-none-any.whl"
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        capture_output=True,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            "import kmast; print(kmast.__file__); from kmast.data.cli import main; main()",
        ],
        cwd=target,
        env=env,
        capture_output=True,
    )
    evidence = root / "artifacts/km001"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "wheel-smoke.log").write_bytes(
        install.stdout + install.stderr + run.stdout + run.stderr
    )
    assert install.returncode == run.returncode == 0
    assert str(target).encode() in run.stdout
    result = json.loads((target / "data/km001/run_summary.json").read_bytes())
    expected = json.loads((evidence / "fixture-data-v1/run_summary.json").read_bytes())
    assert result == expected
    print("PASS: wheel import, package data, Parquet and fixture replay outside checkout")


if __name__ == "__main__":
    main()
