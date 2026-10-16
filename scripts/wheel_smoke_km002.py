"""Install the wheel without network and execute Mock OMS outside the checkout."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    target = Path(tempfile.mkdtemp(prefix="kmast-km002-wheel-"))
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
            str(root / "dist/kmast-1.2.0-py3-none-any.whl"),
        ],
        capture_output=True,
    )
    assert install.returncode == 0, install.stderr
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    program = (
        "import kmast, pathlib; "
        "assert pathlib.Path(kmast.__file__).is_relative_to(pathlib.Path.cwd()); "
        "from kmast.execution.demo import main; main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, "--output", "wheel-scenarios"],
        cwd=target,
        env=env,
        capture_output=True,
    )
    evidence = root / "artifacts/km002"
    (evidence / "wheel-detail.log").write_bytes(
        install.stdout + install.stderr + result.stdout + result.stderr
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    expected = [
        json.loads((evidence / "scenarios-v2" / case / "manifest.json").read_bytes())
        for case in "ABCDEF"
    ]
    assert summary["scenarios"] == expected
    print("PASS: installed wheel, outside-checkout imports and all six deterministic Mock hashes")


if __name__ == "__main__":
    main()
