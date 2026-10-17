"""Independent Decimal accounting and evidence checks; no research/broker imports."""

import argparse
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    proof = Path("artifacts/df004")
    report = json.loads((proof / "results.json").read_bytes())
    protocol = (proof / "DF004_PROTOCOL.json").read_bytes()
    assert hashlib.sha256(protocol).hexdigest() == report["protocol_sha256"]
    assert report["protocol_commit"] == "52c0838d5837d3b6116c0165806658b911ef2c64"
    assert report["independent_references"] == len(report["summaries"]) == 96
    assert report["positive_dates"] + report["nonpositive_dates"] == report["common_dates"]
    assert report["strict_publication_dates"] == 0
    assert report["nav_performance"] is report["performance_0905"] is None
    assert report["network_requests"] <= 12 and report["authentication_calls"] <= 2
    assert all(report[k] == 0 for k in ("order_calls", "cancel_calls", "account_calls"))
    assert report["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert report["live_status"] == "LIVE_NOT_APPROVED"
    assert report["confirmatory_status"] == "NOT_EXECUTED"
    table = {(s["symbol"], s["scenario"], s["model"]): s for s in report["summaries"]}
    assert len(table) == 96
    for s in report["summaries"]:
        assert s["days"] == report["valuation_days"]
        assert s["common_days"] == report["common_dates"]
        assert D(s["capital"]) == 10000000
        assert abs(
            D(s["gross_before_slippage"])
            - D(s["slippage"])
            - D(s["explicit_cost"])
            - D(s["operating_cost"])
            - D(s["net"])
        ) < D("1e-14")
        assert D(s["commission"]) + D(s["tax"]) == D(s["explicit_cost"])
        assert D(s["net"]) + D(s["operating_cost"]) == D(s["cash_excess"])
        assert D(s["metrics"]["NET_OPERATING_PNL_KRW"]) == D(s["net"])
        if s["model"] == "CASH":
            assert s["execution_count"] == 0 and D(s["cash_excess"]) == 0
        if args.private:
            private = Path("data/data-first-private-df004-results") / (
                "-".join((s["symbol"], s["scenario"], s["model"])) + ".json"
            )
            r = json.loads(private.read_bytes())
            assert {k: v for k, v in r.items() if k != "trace"} == s
            cash, quantity, last_nav, latest_sale = D(10000000), 0, D(10000000), -99
            for n, day in enumerate(r["trace"]):
                for _, _, symbol, qty, price, fee in day["executions"]:
                    assert symbol == s["symbol"]
                    if qty > 0:
                        assert n >= latest_sale + 2 and day["common"]
                    else:
                        latest_sale = n
                    quantity += qty
                    assert quantity >= 0
                    cash -= qty * D(price) + D(fee)
                cash -= 100
                assert quantity == day["quantity"] and cash == D(day["cash"])
                assert D(day["nav"]) - last_nav == D(day["net"])
                last_nav = D(day["nav"])
                assert abs(
                    D(day["gross"]) - D(day["slippage"]) - D(day["fee"]) - 100 - D(day["net"])
                ) < D("1e-14")
                assert D(day["overnight_gap_pnl"]) + D(day["intraday_body_pnl"]) == D(day["gross"])
            assert last_nav - 10000000 == D(s["net"])
    for c in report["comparisons"]:
        a, b = (table[c["symbol"], c["scenario"], c[k]] for k in ("model", "baseline"))
        assert D(c["net_increment"]) == D(a["net"]) - D(b["net"])
        assert c["exposure_label"] == "POSTHOC_DIAGNOSTIC"
        assert not c["allocation_feedback"] and not c["equal_full_risk"]
    endpoints = report["endpoints"]
    max_p = 0
    for rank, e in enumerate(sorted(endpoints, key=lambda e: e["p"])):
        max_p = max(max_p, min(1, (3 - rank) * e["p"]))
        assert e["adjusted_p"] == max_p and e["reject"] == (max_p <= 0.05)
    symbols = sorted({s["symbol"] for s in report["summaries"]})
    wins = [
        sum(D(table[sy, sc, "H1_EWY"]["cash_excess"]) > 0 for sy in symbols)
        for sc in ("BASE", "STRESS")
    ]
    improve = sum(
        D(table[sy, "BASE", "EWY_AND_DOM_INDEX"]["net"]) > D(table[sy, "BASE", "DOM_INDEX"]["net"])
        for sy in symbols
    )
    enough = (
        report["common_dates"] >= 80
        and min(report["positive_dates"], report["nonpositive_dates"]) >= 20
    )
    supported = (
        enough
        and endpoints[0]["observed"] > 0
        and endpoints[0]["reject"]
        and any(e["observed"] > 0 and e["reject"] for e in endpoints[1:])
        and min(wins) >= 4
        and improve >= 4
        and D(report["top5_positive_date_share"]) <= D(".5")
    )
    expected = (
        "EWY_EXPLORATORY_SIGNAL_SUPPORTED"
        if supported
        else "EWY_EXPLORATORY_SIGNAL_NOT_SUPPORTED"
        if enough
        else "EWY_INSUFFICIENT_EVIDENCE"
    )
    assert report["decision"] == expected
    print("DF004 independent 96-reference accounting, common dates, Holm and safety: PASS")


if __name__ == "__main__":
    main()
