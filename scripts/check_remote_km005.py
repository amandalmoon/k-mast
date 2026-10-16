"""Read public Actions status for an exact SHA; no account/broker credentials."""

import argparse
import json
import urllib.request
from pathlib import Path


def public(url):
    request = urllib.request.Request(url, headers={"User-Agent": "kmast-exact-sha-ci-audit"})
    return json.load(urllib.request.urlopen(request, timeout=25))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert len(args.sha) == 40 and all(c in "0123456789abcdef" for c in args.sha)
    base = "https://api.github.com/repos/amandalmoon/k-mast/actions"
    runs = public(base + "/runs?branch=km-005&head_sha=" + args.sha)["workflow_runs"]
    exact = [run for run in runs if run["head_sha"] == args.sha and run["event"] == "push"]
    result = {"head_sha": args.sha, "status": "NOT_EXECUTED", "jobs": []}
    if exact:
        run = max(exact, key=lambda r: r["id"])
        jobs = public(base + "/runs/" + str(run["id"]) + "/jobs")["jobs"]
        result = dict(
            head_sha=run["head_sha"],
            run_id=run["id"],
            url=run["html_url"],
            status=run["status"],
            conclusion=run["conclusion"],
            jobs=[
                {key: job[key] for key in ("id", "name", "status", "conclusion", "steps")}
                for job in jobs
            ],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json.dumps(result, indent=2).encode())
    print(json.dumps({k: v for k, v in result.items() if k != "jobs"}, indent=2))
    print([(j["name"], j["conclusion"]) for j in result["jobs"]])


if __name__ == "__main__":
    main()
