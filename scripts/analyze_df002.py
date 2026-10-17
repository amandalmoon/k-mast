"""Additional offline opportunity/partial-fill and exact benchmark-gap diagnostics."""

import json
from collections import Counter, defaultdict
from decimal import Decimal as D
from pathlib import Path

from kmast.data.store import canonical, immutable_write


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/df002"
    results = json.loads((proof / "results.json").read_bytes())
    private = root / results["private_details"]
    analysis = []
    for symbol in ("005930", "000660", "035420", "247540", "086520", "028300"):
        for scenario in (
            "BASE_3FEE_20TAX_5SLIP_100OPEX",
            "STRESS_10FEE_30TAX_20SLIP_100OPEX",
            "PARTIAL_HALF_FILL",
        ):
            r = json.loads((private / f"{symbol}-{scenario}-ALPHA_A.json").read_bytes())
            alpha = r["replay"]
            a = r["attribution"]["summary"]
            counts = Counter()
            opportunities = defaultdict(lambda: D(0))
            quantity = 0
            for sig, row in zip(alpha["signal_log"], alpha["observed_price_log"], strict=True):
                f = sig["filters"]
                # Mutually exclusive ordered labels for a descriptive close-to-close
                # 25%-reference opportunity proxy. Overlapping filters kept separately.
                if not f["breakout"]:
                    reason = "NO_20_DAY_BREAKOUT"
                elif not f["relative_strength"]:
                    reason = "RELATIVE_STRENGTH"
                elif not f["turnover"]:
                    reason = "TURNOVER"
                elif f["deadline_due"]:
                    reason = "CALENDAR_DEADLINE"
                elif f["stop_due"]:
                    reason = "STOP"
                else:
                    reason = "OTHER_OR_ACTIVE"
                counts[reason] += 1
                d = D(row["close"]) - D(row["prior_close"])
                previous_nav = D(sig["pre_nav"])
                shortfall = max(D(0), D(".25") * previous_nav - quantity * D(row["prior_close"]))
                opportunities[reason] += shortfall * d / D(row["prior_close"])
                if d > 0 and quantity == 0:
                    counts["POSITIVE_CLOSE_DAY_STARTING_FLAT"] += 1
                if sig["filters"]["deadline_due"] and sig["filters"]["breakout"]:
                    counts["DEADLINE_WITH_BREAKOUT"] += 1
                quantity = row["quantity"]
            gaps = {}
            for mode in ("HOLD_25", "BUY_HOLD", "TREND_25", "CASH"):
                b = json.loads((private / f"{symbol}-{scenario}-{mode}.json").read_bytes())[
                    "attribution"
                ]["summary"]
                terms = {
                    k: str(D(a[k]) - D(b[k]))
                    for k in (
                        "close_inventory_pnl",
                        "fill_to_close_change_pnl",
                        "commission",
                        "tax",
                        "operating_cost",
                    )
                }
                gap = D(a["project_net"]) - D(b["project_net"])
                assert gap == D(terms["close_inventory_pnl"]) + D(
                    terms["fill_to_close_change_pnl"]
                ) - D(terms["commission"]) - D(terms["tax"]) - D(terms["operating_cost"])
                gaps[mode] = dict(alpha_minus_benchmark=str(gap), exact_bridge_terms=terms)
            signals = alpha["signal_log"]
            one_share = [
                s for s in signals if s["pre_quantity"] == 1 and D(s["target_weight"]) == 0
            ]
            orders = alpha["reference_state"]["orders"]
            analysis.append(
                dict(
                    symbol=symbol,
                    scenario=scenario,
                    filter_priority_day_counts=dict(counts),
                    opportunity_proxy_by_priority={k: str(v) for k, v in opportunities.items()},
                    opportunity_scope="POSTHOC_25PCT_CLOSE_RETURN_PROXY_NOT_REALIZABLE_PNL_NOT_ADDED_TO_CASH",
                    benchmark_gap_bridges=gaps,
                    one_share_zero_target_days=len(one_share),
                    one_share_zero_capacity_days=sum(
                        s["prior_volume_capacity"] == 0 for s in one_share
                    ),
                    expired_orders=sum(o["status"] == "EXPIRED" for o in orders),
                    rejected_orders=sum(o["status"] == "REJECTED" for o in orders),
                    expired_unfilled_shares=sum(
                        o["quantity"] - o["filled"] for o in orders if o["status"] == "EXPIRED"
                    ),
                    final_open_orders=sum(o["status"] in {"OPEN", "PARTIAL"} for o in orders),
                    below_one_share_days=sum(
                        s["submission_constraints"]["below_one_share"] for s in signals
                    ),
                    unsettled_cash_days=sum(
                        s["submission_constraints"]["unsettled_cash"] for s in signals
                    ),
                    stock_price_return=str(
                        D(alpha["observed_price_log"][-1]["close"])
                        / D(alpha["observed_price_log"][0]["prior_close"])
                        - 1
                    ),
                    market_index_return=str(
                        D(alpha["observed_price_log"][-1]["index_close"])
                        / D(alpha["observed_price_log"][0]["index_prior_close"])
                        - 1
                    ),
                    sector_return=None,
                )
            )
    immutable_write(
        proof / "diagnostics.json",
        canonical(
            dict(
                analysis=analysis,
                interpretation="ARITHMETIC_ATTRIBUTION_NOT_CAUSAL_PREDICTIVE_SKILL",
            )
        ),
    )
    print("DF002 opportunity and exact benchmark-gap diagnostics PASS")


if __name__ == "__main__":
    main()
