"""Exact, separately approved KRX basics only. No key issuance or broker calls."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from kmast.data.historical_security import snapshot_rows
from kmast.data.krx_acquisition import KRXBasicsWire
from kmast.data.panel_acquisition import atomic_json, immutable_write, process_lock
from kmast.data.store import canonical, digest

FOLDER = Path("data/data-first-private-df009-krx")


def load_key():
    path = Path.home() / ".kmast-readonly/krx.env"
    values = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            if "=" not in line:
                raise ValueError("INVALID_KRX_LOCAL_KEY_FILE")
            field, value = line.split("=", 1)
            if field.strip() != "KRX_API_KEY":
                raise ValueError("UNEXPECTED_KRX_LOCAL_KEY_FIELD")
            values.append(value.strip().strip('"').strip("'"))
    if len(values) != 1 or not re.fullmatch(r"[a-zA-Z0-9]{40}", values[0]):
        raise ValueError("KRX_LOCAL_KEY_NOT_READY")
    return values[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    plan_path = Path("artifacts/df009/KRX_QUERY_PLAN.json")
    raw = plan_path.read_bytes()
    # A separately pushed exact plan is required, not merely a local modification.
    assert raw == subprocess.check_output(
        [
            "git",
            "show",
            "origin/codex/df009-pit-identity-recovery:artifacts/df009/KRX_QUERY_PLAN.json",
        ]
    )
    plan = json.loads(raw)
    assert plan["unique_requests"] == len(plan["queries"]) == 46
    assert plan["maximum_total_requests"] == 92 and plan["data_queries_exclude_prices"]
    scope = digest(raw)
    with process_lock(FOLDER / "collector.lock"):
        sources = [
            "scripts/collect_df009.py",
            "src/kmast/data/krx_acquisition.py",
            "src/kmast/data/historical_security.py",
        ]
        for name in sources:
            immutable_write(FOLDER / "executed-sources" / name, Path(name).read_bytes())
        immutable_write(FOLDER / "query-plan.json", raw)
        wire = KRXBasicsWire(
            FOLDER,
            tuple(plan["queries"]),
            scope,
            load_key() if args.execute_approved else "",
            enabled=args.execute_approved,
        )
        if args.execute_approved:
            immutable_write(
                FOLDER / "approval.json",
                canonical(
                    dict(
                        scope_sha256=scope,
                        source="Human approval of exact 46-query/92-attempt scope in this chat",
                    )
                ),
            )
        queries = plan["queries"][:2] if args.probe_only else plan["queries"]
        for index, query in enumerate(queries, 1):
            identity = digest(canonical(query))
            record = wire.get(identity)
            if record["success"]:
                raw_response = (FOLDER / "wire" / (record["sha256"] + ".bin")).read_bytes()
                try:
                    rows = snapshot_rows(
                        raw_response, record["sha256"], query["basDd"], query["market"]
                    )
                except (ValueError, TypeError, KeyError):
                    wire.halt("KRX_BASIC_NORMALIZATION_REQUIRES_REVIEW")
                normalized = dict(
                    query=query,
                    request_identity=identity,
                    raw_sha256=record["sha256"],
                    rows=rows,
                    normalized_rows_sha256=digest(canonical(rows)),
                )
                immutable_write(FOLDER / "normalized" / (identity + ".json"), canonical(normalized))
                print(
                    json.dumps(
                        dict(
                            completed=index,
                            used=wire.state["used"],
                            market=query["market"],
                            basDd=query["basDd"],
                            rows=len(rows),
                        )
                    ),
                    flush=True,
                )
                if any(row["LIST_DD"] > query["basDd"] for row in rows if row["LIST_DD"]):
                    wire.halt("HISTORICAL_DATE_SEMANTICS_CONFLICT")
        atomic_json(
            FOLDER / "progress.json", dict(completed_queries=len(queries), used=wire.state["used"])
        )


if __name__ == "__main__":
    main()
