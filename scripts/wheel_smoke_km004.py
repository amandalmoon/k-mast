"""Install the wheel offline and replay joint accounting outside the checkout."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    target = Path(tempfile.mkdtemp(prefix="km004-wheel-"))
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
        "from pathlib import Path; import kmast; "
        "assert Path(kmast.__file__).is_relative_to(Path.cwd()); "
        "from kmast.portfolio.demo import run; run(Path('proof'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=target, env=env, capture_output=True
    )
    (root / "artifacts/km004/wheel-detail.log").write_bytes(
        install.stdout + install.stderr + result.stdout + result.stderr
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((target / "proof/summary.json").read_bytes()) == json.loads(
        (root / "artifacts/km004/joint-v1/summary.json").read_bytes()
    )
    print("Offline installed wheel joint replay: PASS")


if __name__ == "__main__":
    main()
