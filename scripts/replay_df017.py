"""Synthetic gated collector exercise only; never loads real credentials or network."""

import json
from pathlib import Path

import pytest

from kmast.data.https_bar_store import Journal
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from tests.test_df017 import collector


def main():
    root = Path("data/data-first-private-df017-synthetic")
    summary = root / "summary.json"
    if summary.exists():
        result = json.loads(summary.read_bytes())
    else:
        root.mkdir(parents=True, exist_ok=True)
        with pytest.MonkeyPatch.context() as monkeypatch:
            c, wire, _ = collector(root, monkeypatch)
            run = c.run()
        binding = json.loads((c.root / "binding.json").read_bytes())
        j = Journal(c.root, binding)
        ordered = [j.outcomes[i] for i in sorted(j.outcomes)]
        intervals = [
            (b["request_mono"] - a["attempt_ended_mono"]) / 1e9
            for a, b in zip(ordered, ordered[1:], strict=False)
        ]
        result = dict(
            origin="SYNTHETIC",
            purpose="Offline engine verification only; no provider evidence",
            model_attempts=run["attempted"],
            model_auth_attempts=1,
            model_queries=22,
            minimum_response_end_to_next_request_seconds=min(intervals),
            exact_order=[r["ordinal"] for r in j.reservations] == list(range(23)),
            total_file_bytes=j.bytes_used(),
            raw_file_bytes=j.raw_used(),
            journal_outcome_sha256=digest(canonical(ordered)),
            raw_lineage_verified=True,
            actual_authentication_attempts=0,
            actual_market_requests=0,
            actual_tls_connections=0,
            execution_verified=False,
            profit=None,
            source_orb_quote_real_metrics=None,
            token_persisted=False,
        )
        assert len(wire.calls) == 23
        immutable_write(summary, canonical(result))
    atomic_json(Path("artifacts/df017/synthetic-engine.json"), result)
    print("DF017 synthetic gated 22-query engine/reservation/cooldown/lineage PASS; real I/O 0")


if __name__ == "__main__":
    main()
