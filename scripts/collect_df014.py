"""Manual exact-window collector; this command never schedules or waits for another day."""

import argparse
import json
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, process_lock
from kmast.data.paper_collector import PaperCollector
from kmast.data.paper_pilot import authorize
from kmast.data.store import digest
from scripts.read_kis_env import load_env


def main():
    class RedactedParser(argparse.ArgumentParser):
        def error(self, message):
            raise SystemExit("DF014 invalid command options; inputs suppressed") from None

    parser = RedactedParser()
    parser.add_argument("--execute-approved-paper", action="store_true")
    parser.add_argument("--approval-record", type=Path)
    parser.add_argument("--preflight-record", type=Path)
    args = parser.parse_args()
    if (
        not args.execute_approved_paper
        or args.approval_record is None
        or args.preflight_record is None
    ):
        parser.error(
            "DF014 exact new human approval and preflight records required; default network OFF"
        )
    root = Path("data/data-first-private-df014-pilot")
    try:
        from datetime import UTC, datetime

        approval = json.loads(args.approval_record.read_bytes())
        preflight = json.loads(args.preflight_record.read_bytes())
        protocol_hash = digest(Path("artifacts/df014/DF014_PROTOCOL.json").read_bytes())
        # Reject before loading key material or constructing a transport.
        authorize(
            approval, preflight, protocol_hash, datetime.now(UTC), enabled=True, environment="PAPER"
        )
        config = load_env(Path.home() / ".kmast-readonly/.env")
        with process_lock(root / "process.lock"):
            collector = PaperCollector(
                root, config, approval, preflight, protocol_hash, enabled=True
            )
            result = collector.collect()
            atomic_json(root / "control/collection-result.json", result)
        print(json.dumps({k: result[k] for k in ["status", "actual_quote_frames"]}))
    except Exception:
        # Never print exception arguments, config, response bodies or traceback.
        raise SystemExit(
            "DF014 stopped: approval/preflight/window/budget/integrity gate; inputs suppressed"
        ) from None


if __name__ == "__main__":
    main()
