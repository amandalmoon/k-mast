"""No-network wheel install and complete functional replay outside checkout."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    target = Path(tempfile.mkdtemp(prefix="kmast-km003-wheel-"))
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
    assert install.returncode == 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    program = (
        "import pathlib, kmast; "
        "assert pathlib.Path(kmast.__file__).is_relative_to(pathlib.Path.cwd()); "
        "from kmast.simulation.cli import main; main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, "--output", "proof"],
        cwd=target,
        env=env,
        capture_output=True,
    )
    (root / "artifacts/km003/wheel-detail.log").write_bytes(
        install.stdout + install.stderr + result.stdout + result.stderr
    )
    assert result.returncode == 0, result.stderr
    expected = json.loads((root / "artifacts/km003/functional-v1/summary.json").read_bytes())
    assert json.loads(result.stdout) == expected
    print("PASS: wheel outside checkout; reference states and Mock journal hashes identical")


if __name__ == "__main__":
    main()
