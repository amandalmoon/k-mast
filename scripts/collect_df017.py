"""Manual default-off DF017 entry. No scheduling, custom URL, auth or LIVE switches."""

import argparse
import json
from pathlib import Path

from kmast.data.https_bar_collector import Collector, SystemClock
from kmast.data.https_bar_gate import STORE, authorize
from kmast.data.https_bar_store import Journal
from kmast.data.panel_acquisition import immutable_write, process_lock
from kmast.data.store import canonical, digest
from scripts.read_kis_env import load_env


def main():
    class RedactedParser(argparse.ArgumentParser):
        def error(self, message):
            raise SystemExit("DF017 invalid options; inputs suppressed") from None

    parser = RedactedParser()
    parser.add_argument("--execute-approved-paper", action="store_true")
    parser.add_argument("--approval-record", type=Path)
    parser.add_argument("--preflight-record", type=Path)
    parser.add_argument("--retention-plan", action="store_true")
    parser.add_argument("--purge-expired-plan", type=Path)
    args = parser.parse_args()
    try:
        if args.retention_plan or args.purge_expired_plan:
            if args.execute_approved_paper or args.approval_record or args.preflight_record:
                raise PermissionError
            if not (STORE / "binding.json").is_file():
                raise PermissionError("NO_EXISTING_PILOT_TO_RETAIN_OR_PURGE")
            if STORE.resolve() != STORE.absolute():
                raise PermissionError("EXACT_NEW_PILOT_RETENTION_ROOT_REQUIRED")
            with process_lock(STORE / "process.lock"):
                binding = json.loads((STORE / "binding.json").read_bytes())
                journal = Journal(STORE, binding)
                plan = journal.retention_plan(SystemClock().now())
                # Audit manifest outside only the exact new pilot store; hashes, never raw prices.
                audit = Path("data/data-first-private-df017-retention-audit")
                if args.purge_expired_plan:
                    approved = json.loads(args.purge_expired_plan.read_bytes())
                    if approved != plan:
                        raise PermissionError
                    immutable_write(audit / (digest(canonical(plan)) + ".json"), canonical(plan))
                    journal.purge_expired(SystemClock().now(), approved)
                    print("DF017 expired pilot files removed under exact hash plan")
                else:
                    target = audit / (digest(canonical(plan)) + ".json")
                    immutable_write(target, canonical(plan))
                    print("DF017 private retention plan created; no files removed")
            return
        if not args.execute_approved_paper or not args.approval_record or not args.preflight_record:
            raise PermissionError("NETWORK_DISABLED")
        approval = json.loads(args.approval_record.read_bytes())
        preflight = json.loads(args.preflight_record.read_bytes())
        raw = Path("artifacts/df016/PILOT_PROPOSAL.json").read_bytes()
        authorize(raw, approval, preflight, SystemClock().now(), enabled=True)
        # Only the previously authorized records can reach even this lazy key loader.
        collector = Collector(
            STORE,
            raw,
            approval,
            preflight,
            lambda: load_env(Path.home() / ".kmast-readonly/.env"),
            enabled=True,
        )
        result = collector.run()
        print(json.dumps(dict(status=result["status"], attempted=result["attempted"])))
    except Exception:
        raise SystemExit(
            "DF017 stopped: approval/preflight/window/budget/integrity gate; inputs suppressed"
        ) from None


if __name__ == "__main__":
    main()
