"""Aggregate sealed DF005 references; date clusters are diagnostics, not a joint account."""

import json
import random
from collections import Counter, defaultdict
from decimal import Decimal as D
from pathlib import Path

from kmast.data.store import canonical, immutable_write
from kmast.research.holding_analysis import exposure_pair

ROOT = Path("data/data-first-private-df005-replays-v3")


def mean(values):
    return sum(values, D(0)) / len(values) if values else None


def bootstrap(values):
    if not values:
        return dict(observed=None, ci95=None, p=None, dates=0)
    values = [float(v) for v in values]
    n, rng = len(values), random.Random(505)
    observed = sum(values) / n
    samples = []
    for _ in range(2000):
        picked = []
        while len(picked) < n:
            start = rng.randrange(n)
            picked.extend(values[(start + k) % n] for k in range(20))
        samples.append(sum(picked[:n]) / n)
    samples.sort()
    return dict(
        observed=observed,
        ci95=[samples[49], samples[1949]],
        p=(1 + sum(abs(v - observed) >= abs(observed) for v in samples)) / 2001,
        dates=n,
    )


def regime_metrics(value, summary):
    """Condition on known-prior labels; retain the actual uninterrupted NAV peak."""
    buckets = defaultdict(list)
    peak = D(summary["capital"])
    previous = {
        k: D(0) for k in ("cumulative_commission", "cumulative_tax", "cumulative_embedded_slippage")
    }
    for day, signal in zip(value["analysis"]["daily"], value["replay"]["signal_log"], strict=True):
        nav = D(day["nav"])
        peak = max(peak, nav)
        row = dict(
            day,
            drawdown=str(1 - nav / peak),
            executions=len(signal["executions"]),
            reduction_unfulfilled=signal["post_quantity"] > 0 and D(signal["target_weight"]) == 0,
        )
        for k in previous:
            row[k + "_increment"] = str(D(day[k]) - previous[k])
            previous[k] = D(day[k])
        for dim in ("trend", "volatility", "liquidity"):
            buckets[dim, day["regime"][dim]].append(row)
    results = []
    for (dim, label), rr in sorted(buckets.items()):
        returns = sorted(D(d["daily_return"]) for d in rr)
        tail = returns[: max(1, (len(returns) + 19) // 20)]
        net = sum((D(d["nav_change"]) for d in rr), D(0))
        results.append(
            dict(
                symbol=summary["symbol"],
                window=summary["window"],
                scenario=summary["scenario"],
                model=summary["model"],
                dimension=dim,
                label=label,
                days=len(rr),
                net=str(net),
                cash_excess=str(net + 100 * len(rr)),
                mean_close_exposure=str(mean([D(d["actual_close_weight"]) for d in rr])),
                capital_occupancy_fraction=str(
                    sum((D(d["occupied_capital"]) for d in rr), D(0))
                    / D(summary["capital"])
                    / len(rr)
                ),
                worst_day_return=str(min(returns)),
                ES5_daily_loss=str(max(D(0), -sum(tail, D(0)) / len(tail))),
                max_actual_global_drawdown_while_in_regime=str(max(D(d["drawdown"]) for d in rr)),
                turnover=str(sum((D(d["turnover"]) for d in rr), D(0))),
                commission=str(sum((D(d["cumulative_commission_increment"]) for d in rr), D(0))),
                tax=str(sum((D(d["cumulative_tax_increment"]) for d in rr), D(0))),
                slippage=str(
                    sum((D(d["cumulative_embedded_slippage_increment"]) for d in rr), D(0))
                ),
                executions=sum(d["executions"] for d in rr),
                unfulfilled_reduction_days=sum(d["reduction_unfulfilled"] for d in rr),
                scope="CONDITIONAL_DIAGNOSTIC_NOT_RESTARTED_OR_TRADED_REGIME_STRATEGY",
            )
        )
    return results


def main():
    proof = Path("artifacts/df005")
    saved = json.loads((ROOT / "research-manifest.json").read_bytes())
    protocol = json.loads((proof / "DF005_PROTOCOL.json").read_bytes())
    # Apply the protocol's literal nonconstant-factor gate, including tiny rounding
    # differences: an implementation tolerance in the preliminary runner grants no waiver.
    strict_quarantine = []
    preliminary = Path("data/data-first-private-df005-replays-v2")
    for path in sorted((preliminary / "inputs").glob("*.json")):
        item = json.loads(path.read_bytes())
        if D(item["eligibility"]["adjustment_factor_span"]) != 0:
            strict_quarantine.append(
                dict(
                    symbol=item["symbol"],
                    window=item["window"],
                    status="DATA_INSUFFICIENT",
                    reason="STRICT_NONCONSTANT_FACTOR_LINEAGE_HOLD",
                )
            )
    blocked = {(e["symbol"], e["window"]) for e in strict_quarantine}
    rows = [r for r in saved["summaries"] if (r["symbol"], r["window"]) not in blocked]
    table = {(r["symbol"], r["window"], r["scenario"], r["model"]): r for r in rows}
    assert len(table) == len(rows)
    comparisons = []
    for sy, w, sc, model in table:
        if model != "A1":
            continue
        a, b, t = table[sy, w, sc, "A1"], table[sy, w, sc, "A0"], table[sy, w, sc, "T"]
        ae, be = D(a["average_close_exposure"]), D(b["average_close_exposure"])
        av, bv = D(a["annualized_nav_volatility"]), D(b["annualized_nav_volatility"])
        matched = abs(ae - be) <= D(".02") and bv > 0 and D(".9") <= av / bv <= D("1.1")
        risk = D(a["mdd"]) <= D(b["mdd"]) and D(a["ES5_daily_loss"]) <= D(b["ES5_daily_loss"])
        comparisons.append(
            dict(
                symbol=sy,
                window=w,
                scenario=sc,
                net_A1_minus_A0=str(D(a["project_net"]) - D(b["project_net"])),
                net_A1_minus_T=str(D(a["project_net"]) - D(t["project_net"])),
                risk_no_worse=risk,
                observed_exposure_volatility_matched=matched,
                equal_full_risk=False,
                exposure_diagnostic=exposure_pair(a, b),
            )
        )
    validation_set = set(protocol["kospi"][15:] + protocol["kosdaq"][15:])
    eligible_validation = sorted(s for s in validation_set if (s, 3, "BASE", "A1") in table)
    daily = {}
    pair_daily = {}
    market_regimes = defaultdict(set)
    regimes = defaultdict(lambda: dict(reference_days=0, net=D(0)))
    concentration = {}
    reference_regimes = []
    # Only aggregated money is public; prices, fills, date-level signal traces stay private.
    for r in rows:
        path = ROOT / "references" / r["private_file"]
        value = json.loads(path.read_bytes())
        reference_regimes.extend(regime_metrics(value, r))
        days = value["analysis"]["daily"]
        key = (r["symbol"], r["window"], r["scenario"], r["model"])
        if r["model"] in {"A0", "A1"}:
            pair_daily[key] = {d["day"]: d for d in days}
        if r["window"] == 3 and r["scenario"] == "BASE" and r["symbol"] in eligible_validation:
            daily[key] = {d["day"]: D(d["nav_change"]) for d in days}
            market = "KOSPI" if r["symbol"] in protocol["kospi"] else "KOSDAQ"
            for d in days:
                market_regimes[market + ":" + d["regime"]["trend"]].add(d["day"])
        for d in days:
            for dimension in ("trend", "volatility", "liquidity"):
                k = (
                    f"W{r['window']}:{r['scenario']}:{r['model']}:"
                    f"{dimension}:{d['regime'][dimension]}"
                )
                regimes[k]["reference_days"] += 1
                regimes[k]["net"] += D(d["nav_change"])
    for c in comparisons:
        aa = pair_daily[c["symbol"], c["window"], c["scenario"], "A1"]
        bb = pair_daily[c["symbol"], c["window"], c["scenario"], "A0"]
        assert set(aa) == set(bb)
        extra = [d for d in aa if aa[d]["quantity"] > 0 and bb[d]["quantity"] == 0]
        c["continued_holding_vs_A0_flat"] = dict(
            days=len(extra),
            incremental_nav_change=str(
                sum((D(aa[d]["nav_change"]) - D(bb[d]["nav_change"]) for d in extra), D(0))
            ),
            A1_minus_A0_observed_holding_days=sum(v["quantity"] > 0 for v in aa.values())
            - sum(v["quantity"] > 0 for v in bb.values()),
            unrealized_alternative_opportunity_cost=None,
            scope="PATH_DEPENDENT_POSTHOC_FROZEN_A0_COMPARISON_NOT_CAUSAL_HOLDING_ALPHA",
        )
    dates = sorted(set.intersection(*(set(v) for v in daily.values()))) if daily else []
    endpoints = []
    for a, b in (("A0", "CASH"), ("A1", "A0"), ("A1", "T")):
        cluster = [
            mean(
                [
                    daily[sy, 3, "BASE", a][d] - daily[sy, 3, "BASE", b][d]
                    for sy in eligible_validation
                ]
            )
            for d in dates
        ]
        endpoints.append(dict(name=a + "_MINUS_" + b, **bootstrap(cluster)))
    corrected = 0
    for n, k in enumerate(
        sorted(range(3), key=lambda k: endpoints[k]["p"] if endpoints[k]["p"] is not None else 1)
    ):
        p = endpoints[k]["p"]
        if p is None:
            endpoints[k].update(holm_p=None, reject=False)
        else:
            corrected = max(corrected, min(1, (3 - n) * p))
            endpoints[k].update(holm_p=corrected, reject=corrected <= 0.05)
    for model in ("A0", "A1", "T"):
        contributions = {
            d: mean(
                [
                    daily[sy, 3, "BASE", model][d] - daily[sy, 3, "BASE", "CASH"][d]
                    for sy in eligible_validation
                ]
            )
            for d in dates
        }
        positive = sum((max(D(0), v) for v in contributions.values()), D(0))
        top5 = sum(sorted((max(D(0), v) for v in contributions.values()), reverse=True)[:5], D(0))
        stocks = [
            max(D(0), D(table[sy, 3, "BASE", model]["cash_excess"])) for sy in eligible_validation
        ]
        concentration[model] = dict(
            top5_positive_dates_share=str(top5 / positive) if positive else None,
            top5_positive_symbols_share=str(
                sum(sorted(stocks, reverse=True)[:5], D(0)) / sum(stocks, D(0))
            )
            if sum(stocks, D(0))
            else None,
            leave_one_month_cluster_cash_excess={
                m: str(sum((v for d, v in contributions.items() if d[:7] != m), D(0)))
                for m in sorted({d[:7] for d in contributions})
            },
            leave_one_symbol_mean_cash_excess={
                sy: str(
                    mean(
                        [
                            D(table[o, 3, "BASE", model]["cash_excess"])
                            for o in eligible_validation
                            if o != sy
                        ]
                    )
                )
                for sy in eligible_validation
            },
        )
    groups = []
    for w in (1, 2, 3):
        for sc in ("BASE", "STRESS", "PARTIAL"):
            for model in ("A0", "A1", "T", "CASH", "BUY_HOLD"):
                rr = [r for r in rows if (r["window"], r["scenario"], r["model"]) == (w, sc, model)]
                groups.append(
                    dict(
                        window=w,
                        scenario=sc,
                        model=model,
                        references=len(rr),
                        mean_independent_net=str(mean([D(r["project_net"]) for r in rr])),
                        positive_cash_excess=sum(D(r["cash_excess"]) > 0 for r in rr),
                        mean_observed_close_exposure=str(
                            mean([D(r["average_close_exposure"]) for r in rr])
                        ),
                        worst_reference_mdd=str(max((D(r["mdd"]) for r in rr), default=D(0))),
                        mean_ES5=str(mean([D(r["ES5_daily_loss"]) for r in rr])),
                    )
                )
    locked_criteria = {}
    for sc in ("BASE", "STRESS"):
        pairs = [
            c
            for c in comparisons
            if c["symbol"] in eligible_validation and c["window"] == 3 and c["scenario"] == sc
        ]
        locked_criteria[sc] = dict(
            references=len(pairs),
            A1_increment_100000_over_A0=sum(D(c["net_A1_minus_A0"]) >= 100000 for c in pairs),
            A1_increment_100000_over_T=sum(D(c["net_A1_minus_T"]) >= 100000 for c in pairs),
            A1_risk_no_worse=sum(c["risk_no_worse"] for c in pairs),
            observed_exposure_volatility_matched=sum(
                c["observed_exposure_volatility_matched"] for c in pairs
            ),
            A0_cash_excess_positive=sum(
                D(table[sy, 3, sc, "A0"]["cash_excess"]) > 0 for sy in eligible_validation
            ),
        )
    report = dict(
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        protocol_commit="342ddff2c811b20fbcad39dd85384a1787b25ce1",
        protocol_sha256=saved["contract"]["protocol_sha256"],
        candidate_decisions={
            m: "EXPLORATORY_ONLY" if any(r["model"] == m for r in rows) else "DATA_INSUFFICIENT"
            for m in ("A0", "A1", "T")
        },
        independent_qualifying_data=False,
        confirmatory_status="NOT_EXECUTED",
        survivors_only=True,
        PIT_universe=False,
        delisting_history=False,
        halt_event_history=False,
        corporate_action_event_history=False,
        historical_publication_verified=False,
        sector_leadership=None,
        semiconductor_exclusion=None,
        semiconductor_note=(
            "Original005930/000660 absent by preregistration; historical sectors "
            "for new50 unverified, so no broader nonsemiconductor classification claimed"
        ),
        symbols_reviewed=saved["symbols_processed"],
        scheduled_windows=saved["scheduled_windows"],
        preliminary_references=json.loads((preliminary / "research-manifest.json").read_bytes())[
            "references"
        ],
        strict_quarantined_reference_count=len(strict_quarantine) * 15,
        strict_quarantined_windows=strict_quarantine,
        references=len(rows),
        validation_symbols=eligible_validation,
        validation_distinct_dates=len(dates),
        validation_market_regime_distinct_dates={
            k: len(v) for k, v in sorted(market_regimes.items())
        },
        independent_market_experiment_count=1,
        primary_endpoints=endpoints,
        validation_criteria=locked_criteria,
        regime_reference_day_totals_are_not_independent_samples=True,
        regimes={
            k: dict(
                reference_days=v["reference_days"],
                sum_independent_reference_net=str(v["net"]),
                actual_joint_account_net=None,
            )
            for k, v in sorted(regimes.items())
        },
        concentration=concentration,
        groups=groups,
        comparisons=comparisons,
        summaries=rows,
        reference_regime_metrics=reference_regimes,
        exclusions=saved["exclusions"],
        exclusions_by_reason=dict(Counter(r["reason"] for r in saved["exclusions"])),
        risk_match_status="DESCRIPTIVE_ONLY_NOT_ACTUAL_RISK_MATCHED_STRATEGY",
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        failed_attempt_v1=(
            "Original frozen attribution supports only6 sector labels; KeyError, "
            "preserved. V2 nullable-sector derivative has identical arithmetic for known symbols; "
            "no candidate rules changed."
        ),
    )
    immutable_write(proof / "results.json", canonical(report))
    print(
        json.dumps(
            dict(
                references=len(rows),
                validation_symbols=len(eligible_validation),
                validation_dates=len(dates),
                decisions=report["candidate_decisions"],
            )
        )
    )


if __name__ == "__main__":
    main()
