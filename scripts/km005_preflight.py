"""Pre-change KM004 byte audit, offline regression and public CI verification."""

import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from kmast.data.store import DataStore


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km005"
    output.mkdir(exist_ok=True)
    old = json.loads((root / "artifacts/km004/audit.json").read_bytes())
    for key in ("source_hashes", "evidence_hashes"):
        assert all(
            hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in old[key].items()
        ), "KM004 audited bytes differ"
    collected = json.loads((root / "artifacts/km004/real-collection.json").read_bytes())
    store = DataStore(root / collected["private_store"])
    datasets = [store.load_dataset(d["dataset_id"]) for d in collected["datasets"]]
    assert sum(map(len, datasets)) == 180
    prior = json.loads((root / "artifacts/readonly-check-20261016/read-check.json").read_bytes())
    older = DataStore(root / "data/km003-readonly-20261016T140017954455Z").load_dataset(
        prior["dataset_id"]
    )
    assert len(older) == 4
    dates = {(r.symbol, r.exchange_date) for rows in datasets for r in rows if r.kind == "DAILY"}
    assert len(dates) == 60
    assert all((r.symbol, r.exchange_date) in dates for r in older)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--junitxml=artifacts/km005/baseline252.xml"],
        cwd=root,
        capture_output=True,
    )
    (output / "baseline252.stdout.log").write_bytes(run.stdout)
    (output / "baseline252.stderr.log").write_bytes(run.stderr)
    assert run.returncode == 0
    base = "https://api.github.com/repos/amandalmoon/k-mast/actions/runs/38929653134"

    def public(url):
        request = urllib.request.Request(url, headers={"User-Agent": "kmast-public-ci-audit"})
        return json.load(urllib.request.urlopen(request, timeout=25))

    ci = public(base)
    jobs = public(base + "/jobs")
    assert ci["head_sha"] == "d9e0778d31b45947316b50438b5515263ee037c8"
    (output / "prior-remote-ci.json").write_bytes(
        json.dumps(dict(run=ci, jobs=jobs), indent=2).encode()
    )
    result = dict(
        starting_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
        .decode()
        .strip(),
        remote_base=subprocess.check_output(["git", "rev-parse", "origin/km-004"], cwd=root)
        .decode()
        .strip(),
        baseline_tests=252,
        baseline_exit=run.returncode,
        km004_bytes="MATCH",
        real_rows=180,
        independent_stock_days=60,
        prior_rows=4,
        prior_rows_overlap=True,
        prior_ci_conclusion=ci["conclusion"],
        starting_hashes={
            p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in old["source_hashes"]
        },
    )
    (output / "preflight.json").write_bytes(json.dumps(result, indent=2).encode())
    print("Preflight: 252 PASS; data 180 verified; prior 4 overlap; prior CI", ci["conclusion"])


if __name__ == "__main__":
    main()
