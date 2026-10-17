"""Review pinned official examples privately; publish hashes, never vendor code."""

import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    proof = Path("artifacts/data-first")
    tree = json.loads((proof / "upstream-tree.json").read_bytes())
    commit = tree["sha"]
    folder = Path("data/data-first-private-upstream")
    paths = [
        "backtester/README.md",
        "backtester/kis_backtest/providers/kis/data.py",
        "backtester/kis_backtest/lean/data_converter.py",
        "strategy_builder/core/data_fetcher.py",
        "stocks_info/kis_kospi_code_mst.py",
        "stocks_info/kis_kosdaq_code_mst.py",
        "examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py",
        "examples_llm/domestic_stock/inquire_daily_indexchartprice/inquire_daily_indexchartprice.py",
        "examples_user/domestic_stock/domestic_stock_functions.py",
    ]
    records = []
    for path in paths:
        url = f"https://raw.githubusercontent.com/koreainvestment/open-trading-api/{commit}/{path}"
        body = urllib.request.urlopen(url, timeout=25).read()
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        records.append(dict(path=path, url=url, sha256=hashlib.sha256(body).hexdigest()))
    (proof / "upstream-review.json").write_bytes(
        json.dumps(dict(commit=commit, files=records), indent=2).encode()
    )
    print("Pinned official sources reviewed privately:", len(records))


if __name__ == "__main__":
    main()
