"""Independent arithmetic and publication checks; no strategy, broker or ledger imports."""

import argparse
import json
from decimal import Decimal as D
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "artifacts/df002/results.json").read_bytes())
    assert report["v2_reproduced"] == 72 and report["v3_replays"] == 90
    assert len(report["summaries"]) == 90 and len(report["comparisons"]) == 72
    assert len(report["lineage"]) == 90
    assert all(r["v2_exact_reproduction"] for r in report["comparisons"])
    assert all(
        report[k] == 0 for k in ("auth_calls", "market_calls", "order_calls", "cancel_calls")
    )
    for r in report["summaries"]:
        assert r["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        assert (
            r["confirmatory_status"] == "NOT_EXECUTED" and r["live_status"] == "LIVE_NOT_APPROVED"
        )
        assert D(r["commission"]) + D(r["tax"]) == D(r["explicit_cost"])
        assert D(r["close_inventory_pnl"]) + D(r["fill_to_close_change_pnl"]) - D(
            r["explicit_cost"]
        ) - D(r["operating_cost"]) == D(r["project_net"])
        assert abs(
            D(r["realized_net_allocated_cost"])
            + D(r["unrealized_net_entry_fee"])
            - D(r["operating_cost"])
            - D(r["project_net"])
        ) < D("1e-18")
        assert abs(D(r["time_weighted_return"]) - D(r["total_return"])) < D("1e-24")
    for d in report["exposure_diagnostics"]:
        assert not d["used_in_signal"] and d["risk_equivalence"] == "NOT_PROVEN"
    if args.private:
        files = list((root / report["private_details"]).glob("*.json"))
        assert len(files) == 90
        for path in files:
            saved = json.loads(path.read_bytes())
            r, a = saved["replay"], saved["attribution"]
            cash, qty = D(r["capital"]), 0
            fees = traded = D(0)
            for sig, day, attr in zip(
                r["signal_log"], r["observed_price_log"], a["daily"], strict=True
            ):
                assert sig["input_last_date"] < sig["day"]
                assert sig["lineage"]["last_available_at"] <= sig["decision_at"]
                for e in sig["executions"]:
                    assert sig["decision_at"] < e[1]
                    q, price, fee = e[3], D(e[4]), D(e[5])
                    cash -= q * price + fee
                    qty += q
                    fees += fee
                    traded += abs(q) * price
                cash -= D(r["policy"]["daily_operating_cost"])
                assert qty == day["quantity"] == attr["quantity"]
                assert cash == D(day["valuation"]["cash"]) == D(attr["cash"])
                assert cash + qty * D(day["close"]) == D(day["valuation"]["nav"]) == D(attr["nav"])
                assert D(attr["cumulative_commission"]) + D(attr["cumulative_tax"]) == fees
            assert fees == D(r["explicit_fees_taxes"])
            assert traded / D(r["capital"]) == D(r["turnover"])
            assert cash + qty * D(r["observed_price_log"][-1]["close"]) - D(r["capital"]) == D(
                r["scenario_project_net_pnl"]
            )
    print("DF002 independent 90-replay accounting, 72 V2 proofs, lineage and scope: PASS")


if __name__ == "__main__":
    main()
