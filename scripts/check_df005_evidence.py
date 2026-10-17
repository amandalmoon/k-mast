"""Independent public/private arithmetic and protocol qualification; no strategy imports."""

import argparse
import json
from collections import defaultdict
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    proof = Path("artifacts/df005")
    r = json.loads((proof / "results.json").read_bytes())
    assert sha256((proof / "DF005_PROTOCOL.json").read_bytes()).hexdigest() == r["protocol_sha256"]
    assert r["protocol_commit"] == "342ddff2c811b20fbcad39dd85384a1787b25ce1"
    assert r["references"] == len(r["summaries"]) == 1770
    assert r["preliminary_references"] == 1905 and r["strict_quarantined_reference_count"] == 135
    blocked = {(v["symbol"], v["window"]) for v in r["strict_quarantined_windows"]}
    assert len(blocked) == 9
    expected = json.loads((proof / "strict-factor-qualification.json").read_bytes())
    assert blocked == set(map(tuple, expected["quarantined_windows"]))
    table = {(s["symbol"], s["window"], s["scenario"], s["model"]): s for s in r["summaries"]}
    assert len(table) == 1770 and not any(
        (s["symbol"], s["window"]) in blocked for s in table.values()
    )
    assert set(r["candidate_decisions"].values()) == {"EXPLORATORY_ONLY"}
    assert not r["independent_qualifying_data"] and r["confirmatory_status"] == "NOT_EXECUTED"
    assert (
        r["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and r["live_status"] == "LIVE_NOT_APPROVED"
    )
    assert all(r[k] == 0 for k in ("actual_orders", "actual_cancels", "account_queries"))
    for s in table.values():
        assert D(s["capital"]) == 10000000 and D(s["operating_cost"]) == 100 * s["days"]
        assert abs(
            D(s["gross_before_modeled_slippage"])
            - D(s["embedded_slippage"])
            - D(s["explicit_cost"])
            - D(s["operating_cost"])
            - D(s["project_net"])
        ) < D("1e-14")
        assert D(s["commission"]) + D(s["tax"]) == D(s["explicit_cost"])
        assert D(s["project_net"]) + D(s["operating_cost"]) == D(s["cash_excess"])
        assert s["sector_proxy"] is None and s["sector_contribution"] is None
        if s["model"] == "CASH":
            assert D(s["cash_excess"]) == 0 and s["executions"] == 0
        if args.private:
            root = Path("data/data-first-private-df005-replays-v3")
            path = root / "references" / s["private_file"]
            assert sha256(path.read_bytes()).hexdigest() == s["private_sha256"]
            saved = json.loads(path.read_bytes())
            input_path = root / "inputs" / f"{s['symbol']}-W{s['window']}.json"
            assert sha256(input_path.read_bytes()).hexdigest() == saved["input_sha256"]
            assert (
                D(json.loads(input_path.read_bytes())["eligibility"]["adjustment_factor_span"]) == 0
            )
            v = saved["replay"]
            cash, quantity, last_sale = D(s["capital"]), 0, -99
            for n, (sig, day) in enumerate(
                zip(v["signal_log"], v["observed_price_log"], strict=True)
            ):
                assert sig["input_last_date"] < sig["day"]
                assert sig["lineage"]["last_available_at"] <= sig["decision_at"]
                for _, t, symbol, qty, price, fee in sig["executions"]:
                    assert symbol == s["symbol"] and sig["decision_at"] < t
                    if qty > 0:
                        assert n >= last_sale + 2
                    else:
                        last_sale = n
                    quantity += qty
                    cash -= qty * D(price) + D(fee)
                    assert quantity >= 0
                cash -= 100
                assert quantity == day["quantity"] and cash == D(day["valuation"]["cash"])
                assert cash + quantity * D(day["close"]) == D(day["valuation"]["nav"])
            assert cash + quantity * D(v["observed_price_log"][-1]["close"]) - D(s["capital"]) == D(
                s["project_net"]
            )
            returns = sorted(D(d["daily_return"]) for d in saved["analysis"]["daily"])
            tail = returns[: max(1, (len(returns) + 19) // 20)]
            assert D(s["ES5_daily_loss"]) == max(D(0), -sum(tail, D(0)) / len(tail))
    for c in r["comparisons"]:
        a, b, t = (table[c["symbol"], c["window"], c["scenario"], m] for m in ("A1", "A0", "T"))
        assert D(c["net_A1_minus_A0"]) == D(a["project_net"]) - D(b["project_net"])
        assert D(c["net_A1_minus_T"]) == D(a["project_net"]) - D(t["project_net"])
        risk = D(a["mdd"]) <= D(b["mdd"]) and D(a["ES5_daily_loss"]) <= D(b["ES5_daily_loss"])
        assert c["risk_no_worse"] == risk and not c["equal_full_risk"]
        assert c["exposure_diagnostic"]["label"] == "POSTHOC_DIAGNOSTIC"
    totals = defaultdict(lambda: dict(net=D(0), commission=D(0), days=0))
    for s in r["reference_regime_metrics"]:
        key = (s["symbol"], s["window"], s["scenario"], s["model"], s["dimension"])
        totals[key]["net"] += D(s["net"])
        totals[key]["commission"] += D(s["commission"])
        totals[key]["days"] += s["days"]
    for key, v in totals.items():
        s = table[key[:4]]
        assert abs(v["net"] - D(s["project_net"])) < D("1e-14") and v["days"] == s["days"]
        assert v["commission"] == D(s["commission"])
    for g in r["groups"]:
        ss = [
            s
            for s in table.values()
            if (s["window"], s["scenario"], s["model"]) == (g["window"], g["scenario"], g["model"])
        ]
        assert len(ss) == g["references"]
        assert D(g["mean_independent_net"]) == sum((D(s["project_net"]) for s in ss), D(0)) / len(
            ss
        )
        assert g["positive_cash_excess"] == sum(D(s["cash_excess"]) > 0 for s in ss)
    maximum = 0
    for rank, e in enumerate(sorted(r["primary_endpoints"], key=lambda e: e["p"])):
        maximum = max(maximum, min(1, (3 - rank) * e["p"]))
        assert e["holm_p"] == maximum and e["reject"] == (maximum <= 0.05)
    a = json.loads((proof / "collection-and-preservation-audit.json").read_bytes())
    assert a["preserved"] and a["secret_leaks"] == 0 and a["derivative_only_nullable_sector_lookup"]
    assert (
        a["requests"] == 803
        and a["authentication"] == 1
        and a["minimum_response_complete_to_request_seconds"] >= 3.05
    )
    assert a["wire_market_responses_retained"] == 802
    print(
        "DF005 independent1770-reference accounting, strict eligibility,ES,regimes and safety: PASS"
    )


if __name__ == "__main__":
    main()
