"""Offline cache revalidation before any new authenticated DF012 request."""

import json
from datetime import date
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from scripts.run_df005 import load_histories


def main():
    public = Path("artifacts/df012")
    protocol = json.loads((public / "DF012_PROTOCOL.json").read_bytes())
    parent_bytes = Path("artifacts/df011/next-price-proposal.json").read_bytes()
    assert digest(parent_bytes) == protocol["parent_proposal_sha256"]
    parent = json.loads(parent_bytes)
    panel = json.loads(Path("data/data-first-private-df005-panel/manifest.json").read_bytes())
    private = Path("data/data-first-private-df012-cache")
    records = []
    for entry in parent["targets"]:
        target = entry["target"]
        lo, hi = (date.fromisoformat(target[k]) for k in ("start", "end"))
        rows = tuple(
            r
            for r in load_histories(panel, entry["index_symbol"], "RAW")
            if lo <= r.exchange_date <= hi
        )
        payload = canonical([r.model_dump(mode="json") for r in rows])
        assert digest(payload) == entry["index_sha256"]
        old = Path("data/data-first-private-df011-cache") / entry["private_index_file"]
        assert old.read_bytes() == payload
        immutable_write(private / entry["private_index_file"], payload)
        stock_rows = {
            basis: len(
                tuple(
                    r
                    for r in load_histories(panel, target["historical_short_code"], basis)
                    if lo <= r.exchange_date <= hi
                )
            )
            for basis in ("RAW", "ADJUSTED")
        }
        assert stock_rows == entry["cached_stock_rows"]
        records.append(
            dict(
                target=target,
                index_symbol=entry["index_symbol"],
                cached_index_rows=len(rows),
                cached_stock_rows=stock_rows,
                index_sha256=digest(payload),
                private_index_file=entry["private_index_file"],
                missing_index_request=entry["missing_index_request"],
            )
        )
    atomic_json(
        public / "cache-audit.json",
        dict(
            protocol_sha256=digest((public / "DF012_PROTOCOL.json").read_bytes()),
            prior_cache_unchanged=True,
            targets=records,
            actual_new_requests=0,
            actual_new_authentication=0,
            uncovered_pages=protocol["requests"],
        ),
    )
    print("DF012 exact prior cache/hash checks PASS; 10 stock pages and 1 index gap remain")


if __name__ == "__main__":
    main()
