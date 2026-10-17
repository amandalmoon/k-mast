"""Independent Decimal accounting and scope audit. No strategy/ledger implementation imports."""

import argparse
import json
from decimal import Decimal as D
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/data-first"
    collected = json.loads((proof / "collection.json").read_bytes())
    report = json.loads((proof / "exploration-summary.json").read_bytes())
    assert collected["network"]["used"] <= 48
    assert (
        sum(collected["network"][k] for k in ("auth", "market", "master"))
        == collected["network"]["used"]
    )
    assert all(collected[k] == 0 for k in ("account_queries", "order_calls", "cancel_calls"))
    assert len(report["scenarios"]) == 18 and not report["errors"]
    assert report["scope"] == "EXPLORATORY_REAL_DATA"
    assert (
        report["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and report["confirmatory_status"] == "NOT_EXECUTED"
    )
    for result in report["scenarios"]:
        assert D(result["ending_nav"]) - D(result["capital"]) == D(
            result["scenario_project_net_pnl"]
        )
        assert D(result["price_pnl_including_embedded_slippage"]) - D(
            result["explicit_fees_taxes"]
        ) == D(result["trading_net_pnl"])
        assert D(result["trading_net_pnl"]) - D(result["recurring_operating_cost"]) == D(
            result["scenario_project_net_pnl"]
        )
        for baseline, field in (
            ("CASH", "cash_excess"),
            ("BUY_HOLD", "hold_excess"),
            ("HOLD_25", "hold25_excess"),
        ):
            assert D(result[field]) == D(result["scenario_project_net_pnl"]) - D(
                result["baselines"][baseline]["scenario_project_net_pnl"]
            )
    if args.private:
        folder = root / report["private_price_signal_fill_artifacts"]
        files = list(folder.glob("*.json"))
        assert len(files) == 72
        for path in files:
            r = json.loads(path.read_bytes())
            state = r["reference_state"]
            marks = {s: D(price) for s, price, _ in state["marks"]}
            nav = D(state["cash"]) + sum(
                D(lot["quantity"]) * marks[lot["symbol"]] for lot in state["lots"]
            )
            assert nav == D(r["ending_nav"])
            assert sum(D(e[5]) for e in state["executions"]) == D(r["explicit_fees_taxes"])
            assert all(s["input_last_date"] < s["day"] for s in r["signal_log"])
    print("Independent real-price exploratory accounting and scope audit: PASS")


if __name__ == "__main__":
    main()
