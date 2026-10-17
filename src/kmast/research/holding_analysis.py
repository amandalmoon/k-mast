"""DF-003 descriptive economics and fixed research decisions, never allocations."""

from decimal import Decimal as D
from typing import Any

from kmast.research.attribution import attribute
from kmast.research.hypotheses import reduction_status


def beta(y: list[D], x: list[D]) -> str | None:
    ym, xm = sum(y, D(0)) / len(y), sum(x, D(0)) / len(x)
    variance = sum(((v - xm) ** 2 for v in x), D(0))
    return (
        str(sum(((a - ym) * (b - xm) for a, b in zip(y, x, strict=True)), D(0)) / variance)
        if variance
        else None
    )


def analyze_holding(result: dict[str, Any], candidate: str) -> dict[str, Any]:
    analysis = attribute(result)
    summary = analysis["summary"]
    summary["candidate"] = candidate
    executions = result["reference_state"]["executions"]
    summary["buy_notional"] = str(sum((e[3] * D(e[4]) for e in executions if e[3] > 0), D(0)))
    summary["sell_notional"] = str(sum((-e[3] * D(e[4]) for e in executions if e[3] < 0), D(0)))
    returns = [D(r["daily_return"]) for r in analysis["daily"]]
    stock = [D(r["close"]) / D(r["prior_close"]) - 1 for r in result["observed_price_log"]]
    index = [
        D(r["index_close"]) / D(r["index_prior_close"]) - 1 for r in result["observed_price_log"]
    ]
    mean = sum(returns, D(0)) / len(returns)
    variance = sum(((v - mean) ** 2 for v in returns), D(0)) / (len(returns) - 1)
    summary.update(
        annualized_nav_volatility=str(variance.sqrt() * D(252).sqrt()),
        worst_close_day_return=str(min(returns)),
        nav_beta_to_stock=beta(returns, stock),
        nav_beta_to_index=beta(returns, index),
        instrument_beta_to_index=beta(stock, index),
        volatility_scope="SAMPLE_DAILY_NAV_252_CONVENTION_NOT_RISK_TARGET",
        cash_excess=str(D(summary["project_net"]) + D(summary["operating_cost"])),
    )
    buckets: dict[str, dict[str, Any]] = {}
    for trade in analysis["fifo_trades"]:
        days = D(trade["calendar_holding_seconds"]) / 86400
        label = (
            "LE_5_CALENDAR"
            if days <= 5
            else "LE_10_CALENDAR"
            if days <= 10
            else "LE_20_CALENDAR"
            if days <= 20
            else "GT_20_CALENDAR"
        )
        b = buckets.setdefault(label, dict(fifo_matches=0, quantity=0, net=D(0)))
        b["fifo_matches"] += 1
        b["quantity"] += trade["quantity"]
        b["net"] += D(trade["net_pnl"])
    summary["holding_duration_buckets"] = buckets
    unfulfilled = []
    streak = maximum = 0
    for sig in result["signal_log"]:
        unfilled = sig["post_quantity"] > 0 and D(sig["target_weight"]) == 0
        streak = streak + 1 if unfilled else 0
        maximum = max(maximum, streak)
        if unfilled:
            unfulfilled.append(sig["day"])
    final = result["signal_log"][-1]
    pending = sum(
        o["quantity"] - o["filled"]
        for o in result["reference_state"]["orders"]
        if o["status"] in {"OPEN", "PARTIAL"}
    )
    summary["execution_safety"] = dict(
        **reduction_status(
            D(final["target_weight"]) == 0, result["final_quantity"], pending, "UNKNOWN"
        ),
        unfulfilled_reduction_days=len(unfulfilled),
        maximum_consecutive_days=maximum,
        interpretation="MODEL_RESIDUAL_NOT_ACTUAL_HALT_OR_FORCE_ORDER_PROOF",
    )
    return analysis


def exposure_pair(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    x, y = D(a["average_close_exposure"]), D(b["average_close_exposure"])
    common = min(x, y)
    return dict(
        label="POSTHOC_DIAGNOSTIC",
        common_mean_exposure=str(common),
        a_cash_excess_scaled=str(D(a["cash_excess"]) * common / x) if x else None,
        b_cash_excess_scaled=str(D(b["cash_excess"]) * common / y) if y else None,
        actual_tradable_pnl=None,
        equal_full_risk=False,
        allocation_feedback=False,
    )


def classify(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def lookup(symbol: str, scenario: str, candidate: str) -> dict[str, Any]:
        return next(
            s
            for s in summaries
            if (s["symbol"], s["scenario"], s["candidate"]) == (symbol, scenario, candidate)
        )

    symbols = ("005930", "000660", "035420", "247540", "086520", "028300")
    base = "BASE_3FEE_20TAX_5SLIP_100OPEX"
    stress = "STRESS_10FEE_30TAX_20SLIP_100OPEX"
    findings = []
    for candidate in ("A1", "A2", "A3"):
        improvements = {}
        for scenario in (base, stress):
            improvements[scenario] = [
                s
                for s in symbols
                if D(lookup(s, scenario, candidate)["project_net"])
                > D(lookup(s, scenario, "A0")["project_net"])
            ]
        mdd_ok = [
            s
            for s in symbols
            if D(lookup(s, base, candidate)["mdd"]) <= D(lookup(s, base, "A0")["mdd"]) + D(".02")
        ]
        entry_wins = [
            s
            for s in symbols
            if D(lookup(s, base, candidate)["project_net"])
            > D(lookup(s, base, "T" + candidate[-1])["project_net"])
        ]
        nonsemi = [s for s in improvements[base] if s in symbols[2:]]
        if len(improvements[base]) <= 1 and len(improvements[stress]) <= 1:
            status = "RESEARCH_CANDIDATE_REJECT"
        elif (
            len(improvements[base]) >= 4
            and len(improvements[stress]) >= 4
            and len(mdd_ok) >= 5
            and len(entry_wins) >= 4
            and len(nonsemi) >= 2
        ):
            status = "RESEARCH_CANDIDATE_RETAIN"
        else:
            status = "RESEARCH_CANDIDATE_REVISE"
        findings.append(
            dict(
                candidate=candidate,
                status=status,
                improvement_symbols=improvements,
                mdd_within_2pp_symbols=mdd_ok,
                paired_entry_win_symbols=entry_wins,
                nonsemiconductor_improvement_symbols=nonsemi,
                economic_status="ECONOMIC_EDGE_UNVERIFIED",
                live_status="LIVE_NOT_APPROVED",
            )
        )
    return findings
