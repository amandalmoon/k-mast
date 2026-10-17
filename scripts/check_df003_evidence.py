"""Independent public/private Decimal checks, no strategy or execution implementation imports."""

import argparse
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df003"
    protocol = (proof / "DF003_PROTOCOL.json").read_bytes()
    r = json.loads((proof / "results.json").read_bytes())
    assert hashlib.sha256(protocol).hexdigest() == r["protocol_sha256"]
    assert r["independent_references"] == 216 and len(r["summaries"]) == 216
    assert len(r["comparisons"]) == 144 and len(r["a0_exact_v3_matches"]) == 18
    assert all(x["exact"] for x in r["a0_exact_v3_matches"])
    assert all(
        r[k] == 0
        for k in (
            "authentication_calls",
            "market_calls",
            "account_calls",
            "order_calls",
            "cancel_calls",
        )
    )
    assert (
        r["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and r["live_status"] == "LIVE_NOT_APPROVED"
    )
    assert (
        r["confirmatory_status"] == "NOT_EXECUTED"
        and not r["df004_started"]
        and r["ewy_performance"] is None
    )
    for s in r["summaries"]:
        assert s["days"] == 223 and D(s["capital"]) == 10000000
        assert D(s["close_inventory_pnl"]) + D(s["fill_to_close_change_pnl"]) - D(
            s["explicit_cost"]
        ) - D(s["operating_cost"]) == D(s["project_net"])
        assert D(s["commission"]) + D(s["tax"]) == D(s["explicit_cost"])
        assert D(s["cash_excess"]) == D(s["project_net"]) + D(s["operating_cost"])
        assert D(s["buy_notional"]) + D(s["sell_notional"]) == D(s["turnover"]) * D(s["capital"])
        assert abs(
            D(s["realized_net_allocated_cost"])
            + D(s["unrealized_net_entry_fee"])
            - D(s["operating_cost"])
            - D(s["project_net"])
        ) < D("1e-17")
        assert abs(
            sum((D(b["net"]) for b in s["holding_duration_buckets"].values()), D(0))
            - D(s["realized_net_allocated_cost"])
        ) < D("1e-17")
    for c in r["comparisons"]:
        p = c["exposure_control"]
        assert (
            p["label"] == "POSTHOC_DIAGNOSTIC"
            and not p["allocation_feedback"]
            and not p["equal_full_risk"]
        )
        assert p["actual_tradable_pnl"] is None
    for p in r["forced_reduction_probes"]:
        assert p["status"] == "RISK_REDUCTION_HOLD" and not p["automatic_residual_fill"]
    # Recompute the sealed research decision independently of classify().
    symbols = json.loads(protocol)["symbols"]
    base = "BASE_3FEE_20TAX_5SLIP_100OPEX"
    stress = "STRESS_10FEE_30TAX_20SLIP_100OPEX"
    rows = {(s["symbol"], s["scenario"], s["candidate"]): s for s in r["summaries"]}
    assert len(rows) == 216
    deltas = json.loads((proof / "benchmark-deltas.json").read_bytes())
    assert len(deltas["deltas"]) == 216 and deltas["new_trials"] == 0
    for d in deltas["deltas"]:
        s = rows[d["symbol"], d["scenario"], d["candidate"]]
        for name, excess in d["net_excess"].items():
            b = rows[d["symbol"], d["scenario"], name]
            assert D(excess) == D(s["project_net"]) - D(b["project_net"])
        assert D(d["net_excess"]["CASH"]) == D(s["cash_excess"])
    for finding in r["candidate_findings"]:
        candidate = finding["candidate"]
        wins = []
        for scenario in (base, stress):
            wins.append(
                sum(
                    D(rows[s, scenario, candidate]["project_net"])
                    > D(rows[s, scenario, "A0"]["project_net"])
                    for s in symbols
                )
            )
        risk = sum(
            D(rows[s, base, candidate]["mdd"]) <= D(rows[s, base, "A0"]["mdd"]) + D(".02")
            for s in symbols
        )
        control = sum(
            D(rows[s, base, candidate]["project_net"])
            > D(rows[s, base, "T" + candidate[-1]]["project_net"])
            for s in symbols
        )
        nonsemi = sum(
            D(rows[s, base, candidate]["project_net"]) > D(rows[s, base, "A0"]["project_net"])
            for s in symbols[2:]
        )
        expected = (
            "RESEARCH_CANDIDATE_REJECT"
            if max(wins) <= 1
            else "RESEARCH_CANDIDATE_RETAIN"
            if min(wins) >= 4 and risk >= 5 and control >= 4 and nonsemi >= 2
            else "RESEARCH_CANDIDATE_REVISE"
        )
        assert finding["status"] == expected
    if args.private:
        folder = root / r["private_details"]
        files = list(folder.glob("*.json"))
        assert len(files) == 216
        for path in files:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == r["private_hashes"][path.name]
            saved = json.loads(path.read_bytes())
            v = saved["replay"]
            cash = D(v["capital"])
            quantity = 0
            for sig, day in zip(v["signal_log"], v["observed_price_log"], strict=True):
                assert sig["input_last_date"] < sig["day"]
                assert sig["lineage"]["last_available_at"] <= sig["decision_at"]
                for e in sig["executions"]:
                    assert sig["decision_at"] < e[1]
                    quantity += e[3]
                    cash -= e[3] * D(e[4]) + D(e[5])
                cash -= D(v["policy"]["daily_operating_cost"])
                assert quantity == day["quantity"] and cash == D(day["valuation"]["cash"])
                assert cash + quantity * D(day["close"]) == D(day["valuation"]["nav"])
            assert cash + quantity * D(v["observed_price_log"][-1]["close"]) - D(v["capital"]) == D(
                v["scenario_project_net_pnl"]
            )
    print("DF003 independent 216-reference accounting, protocol, 18 A0 matches and safety: PASS")


if __name__ == "__main__":
    main()
