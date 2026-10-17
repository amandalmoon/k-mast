"""One confirmed access-change waiver; original failure and cumulative budget retained."""

import argparse
import json
from pathlib import Path

from kmast.data.historical_security_v2 import snapshot_rows
from kmast.data.krx_acquisition import KRXBasicsWire
from kmast.data.panel_acquisition import atomic_json, immutable_write, process_lock
from kmast.data.store import canonical, digest
from scripts.collect_df009 import load_key

OLD = Path("data/data-first-private-df009-krx")
NEW = Path("data/data-first-private-df009-krx-access-confirmed")


class ConfirmedAccessWire(KRXBasicsWire):
    def __init__(self, *args, **kwargs):
        previous_halt = json.loads((Path(args[0]) / "budget.json").read_bytes()).get("halted")
        super().__init__(*args, **kwargs)
        waiver = json.loads((self.folder / "access-confirmation.json").read_bytes())
        first = self.state["events"][0]
        assert waiver["scope_sha256"] == self.scope
        assert waiver["waived_through_request"] == first["number"] == 1
        assert first["http_status"] == 401 and first["sha256"] == waiver["original_response_sha256"]
        fatal = [e for e in self.state["events"] if e.get("fatal")]
        if all(e["number"] <= 1 for e in fatal) and previous_halt in {
            None,
            "KRX_AUTH_PERMISSION_OR_QUOTA_FAILURE",
            "KRX_BASIC_NORMALIZATION_REQUIRES_REVIEW",
        }:
            self.state["halted"] = None
            atomic_json(self.path, self.state)
        elif previous_halt:
            self.state["halted"] = previous_halt
            atomic_json(self.path, self.state)

    def cached(self, identity):
        prior = [e for e in self.state["events"] if e["request_identity"] == identity]
        if len(prior) == 1 and prior[0]["number"] == 1 and prior[0].get("http_status") == 401:
            # Consume the original query's one remaining attempt, never a fresh budget.
            return None
        return super().cached(identity)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    plan_bytes = Path("artifacts/df009/KRX_QUERY_PLAN.json").read_bytes()
    plan = json.loads(plan_bytes)
    assert digest(plan_bytes) == "9b715ffe7fd659456ef22d4314f2072dbc5aaa8c4f8a22cadd645aded9c92640"
    with process_lock(OLD / "collector.lock"), process_lock(NEW / "collector.lock"):
        if not (NEW / "budget.json").exists():
            budget_bytes = (OLD / "budget.json").read_bytes()
            budget = json.loads(budget_bytes)
            assert budget["used"] == 1 and len(budget["events"]) == 1
            first = budget["events"][0]
            assert first["http_status"] == 401
            for name in ("budget.json", "events/0001.json", "wire/" + first["sha256"] + ".bin"):
                immutable_write(NEW / name, (OLD / name).read_bytes())
            immutable_write(
                NEW / "access-confirmation.json",
                canonical(
                    dict(
                        scope_sha256=digest(plan_bytes),
                        waived_through_request=1,
                        original_budget_sha256=digest(budget_bytes),
                        original_response_sha256=first["sha256"],
                        source=(
                            "Human screenshot: both basics services approved "
                            "2026-10-17 through 2027-10-16"
                        ),
                        maximum_cumulative_requests=92,
                        maximum_attempts_per_query=2,
                        original_failure_not_refunded=True,
                    )
                ),
            )
        sources = (
            "scripts/resume_df009.py",
            "src/kmast/data/krx_acquisition.py",
            "src/kmast/data/historical_security_v2.py",
        )
        version = digest(canonical({name: digest(Path(name).read_bytes()) for name in sources}))
        for name in sources:
            immutable_write(NEW / "executed-versions" / version / name, Path(name).read_bytes())
        immutable_write(NEW / "query-plan.json", plan_bytes)
        wire = ConfirmedAccessWire(
            NEW,
            tuple(plan["queries"]),
            digest(plan_bytes),
            load_key() if args.execute_approved else "",
            enabled=args.execute_approved,
        )
        for index, query in enumerate(
            plan["queries"][:2] if args.probe_only else plan["queries"], 1
        ):
            identity = digest(canonical(query))
            record = wire.get(identity)
            if record["success"]:
                raw = (NEW / "wire" / (record["sha256"] + ".bin")).read_bytes()
                try:
                    rows = snapshot_rows(raw, record["sha256"], query["basDd"], query["market"])
                except (ValueError, TypeError, KeyError):
                    wire.halt("KRX_BASIC_NORMALIZATION_REQUIRES_REVIEW")
                immutable_write(
                    NEW / "normalized" / (identity + ".json"),
                    canonical(
                        dict(
                            query=query,
                            request_identity=identity,
                            raw_sha256=record["sha256"],
                            rows=rows,
                            normalized_rows_sha256=digest(canonical(rows)),
                        )
                    ),
                )
                print(
                    json.dumps(
                        dict(
                            completed=index,
                            cumulative_used=wire.state["used"],
                            query=query,
                            rows=len(rows),
                        )
                    ),
                    flush=True,
                )
                if any(r["LIST_DD"] > query["basDd"] for r in rows if r["LIST_DD"]):
                    wire.halt("HISTORICAL_DATE_SEMANTICS_CONFLICT")


if __name__ == "__main__":
    main()
