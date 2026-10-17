"""Offline cache coverage and integrity audit; never authenticate or calculate PnL."""

import json
from datetime import date
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from scripts.run_df005 import load_histories


def main():
    protocol = json.loads(Path("artifacts/df010/DF010_PROTOCOL.json").read_bytes())
    source = Path("data/data-first-private-df005-panel")
    manifest = json.loads((source / "manifest.json").read_bytes())
    private = Path("data/data-first-private-df010-cache")
    results = []
    for target in protocol["targets"]:
        start, end = (date.fromisoformat(target[k]) for k in ("start", "end"))
        index = "1001" if target["then_market"] == "KOSDAQ" else "0001"
        histories = []
        for symbol, basis in [
            (target["symbol"], "RAW"),
            (target["symbol"], "ADJUSTED"),
            (index, "RAW"),
        ]:
            all_rows = load_histories(manifest, symbol, basis)
            rows = tuple(r for r in all_rows if start <= r.exchange_date <= end)
            # Range evidence is observation based; no artificial weekday rows.
            page_bounds = [
                p["request"]
                for p in manifest["pages"].values()
                if p["request"]["symbol"] == symbol and p["request"]["price_basis"] == basis
            ]
            range_covered = (
                bool(rows)
                and any(q["start"] <= target["start"] for q in page_bounds)
                and any(q["end"] >= target["end"] for q in page_bounds)
            )
            payload = canonical([r.model_dump(mode="json") for r in rows])
            name = f"{target['receipt']}-{symbol}-{basis}.json"
            immutable_write(private / name, payload)
            histories.append(
                dict(
                    symbol=symbol,
                    basis=basis,
                    rows=len(rows),
                    first=str(rows[0].exchange_date) if rows else None,
                    last=str(rows[-1].exchange_date) if rows else None,
                    request_range_covered=range_covered,
                    normalized_sha256=digest(payload),
                    private_file=name,
                )
            )
        results.append(
            dict(receipt=target["receipt"], symbol=target["symbol"], histories=histories)
        )
    # Inventory every existing normalized store manifest, retaining metadata only.
    inventory = []
    for path in sorted(Path("data").glob("*/normalized/*/manifest.json")):
        if "df010" in path.as_posix():
            continue
        value = json.loads(path.read_bytes())
        inventory.append(
            dict(
                path=path.as_posix(),
                sha256=digest(path.read_bytes()),
                start=value.get("obtained_start"),
                end=value.get("obtained_end"),
                rows=value.get("row_count"),
            )
        )
    immutable_write(private / "store-inventory.json", canonical(inventory))
    report = dict(
        protocol_sha256=digest(Path("artifacts/df010/DF010_PROTOCOL.json").read_bytes()),
        source_manifest_sha256=digest((source / "manifest.json").read_bytes()),
        histories=results,
        normalized_store_manifests=len(inventory),
        inventory_sha256=digest(canonical(inventory)),
        indices_complete=all(r["histories"][2]["request_range_covered"] for r in results),
        new_authentication=0,
        new_requests=0,
        price_outcomes_computed=0,
        limits="Observed index calendar, not complete halt/action or special-open history",
    )
    atomic_json(Path("artifacts/df010/cache-audit.json"), report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
