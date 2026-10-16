"""Offline audit of explicitly collected private data; never authenticate here."""

import json
from pathlib import Path

from kmast.data.store import DataStore, canonical
from kmast.portfolio.data_gate import ResearchDataGate, economic_gate, require_research


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / "artifacts/km004"
    collected = json.loads((folder / "real-collection.json").read_bytes())
    store = DataStore(root / collected["private_store"])
    datasets = [store.load_dataset(item["dataset_id"]) for item in collected["datasets"]]
    rows = tuple(row for dataset in datasets for row in dataset)
    assert len(rows) == 180 and all(row.data_origin == "KIS_READONLY" for row in rows)
    dates = [{row.exchange_date for row in dataset} for dataset in datasets]
    assert dates[0] == dates[1] == dates[2] | dates[3]
    assert not dates[2] & dates[3]
    gate = ResearchDataGate(
        strategy="A",
        real_rows=len(rows),
        synthetic_rows=0,
        symbols=("005930", "0001"),
        start=min(dates[0]),
        end=max(dates[0]),
        origin_verified=True,
        hashes_verified=True,
        source_verified=True,
    )
    blocked = False
    try:
        require_research(gate, rows, (), max(row.available_at for row in rows))
    except PermissionError:
        blocked = True
    assert blocked
    result = dict(
        status=gate.status,
        blockers=gate.blockers(),
        verified_real_rows=len(rows),
        unique_stock_dates=60,
        unique_index_dates=60,
        expected_grid_missing_rate=None,
        backtest_blocked=blocked,
        actual_data_pnl=None,
        actual_trades=0,
        alpha_status={
            "A": "DATA_PARTIAL_LICENSE_HOLD",
            "B": "DATA_BLOCKED",
            "C": "DATA_BLOCKED",
            "D": "DATA_BLOCKED",
        },
        economic_status=economic_gate(gate, False, False),
        live_status="LIVE_NOT_APPROVED",
        gate=gate.model_dump(mode="json"),
    )
    (folder / "data-diagnostic.json").write_bytes(canonical(result))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
