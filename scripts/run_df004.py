"""Offline actual-price replay of the sealed DF004 protocol. No acquisition."""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from kmast.data.store import DataStore, canonical, immutable_write
from kmast.research.ewy import (
    MODELS,
    SPECIAL,
    ForeignBar,
    at,
    bootstrap,
    holm,
    mapping,
    replay,
    require_available,
    us_session,
)

PROTOCOL_COMMIT = "52c0838d5837d3b6116c0165806658b911ef2c64"


def main():
    proof = Path("artifacts/df004")
    protocol_bytes = (proof / "DF004_PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    seal = json.loads((proof / "protocol-seal.json").read_bytes())
    assert hashlib.sha256(protocol_bytes).hexdigest() == seal["protocol_sha256"]
    source = Path("data/data-first-private-df004-ewy")
    budget = json.loads((source / "budget.json").read_bytes())
    us = {}
    for e in budget["events"]:
        if e.get("exchange_code") != "AMS" or e.get("modp") != "0":
            continue
        raw = (source / (e["sha256"] + ".json")).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == e["sha256"]
        for row in json.loads(raw):
            day = datetime.strptime(row["xymd"], "%Y%m%d").date()
            if not date(2025, 10, 17) <= day <= date(2026, 10, 16):
                continue
            bar = ForeignBar(
                session_date=day,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["clos"],
                volume=row["tvol"],
                received_at=e["received_at"],
                source_hash=e["sha256"],
            )
            if day in us:
                assert (us[day].open, us[day].close) == (bar.open, bar.close)
            us[day] = bar
    bars = tuple(us[d] for d in sorted(us))
    expected = []
    day = date(2025, 10, 17)
    while day <= date(2026, 10, 16):
        try:
            us_session(day)
        except ValueError:
            pass
        else:
            expected.append(day)
        day += timedelta(days=1)
    missing_us = sorted(set(expected) - set(us))
    acquired = json.loads(Path("artifacts/data-first/collection.json").read_bytes())
    panels = {}
    store = DataStore(Path(acquired["private_store"]))
    flags = set()
    for dataset in acquired["datasets"]:
        if dataset["operation"] not in {"daily", "index_daily"} or dataset["price_basis"] != "RAW":
            continue
        panel = panels.setdefault(dataset["symbol"], {})
        for row in store.load_dataset(dataset["dataset_id"]):
            assert row.exchange_date not in panel
            panel[row.exchange_date] = row
            flags.update(row.quality_flags)
    dates = tuple(sorted(panels["0001"]))
    assert all(tuple(sorted(p)) == dates for p in panels.values())
    valuation = tuple(d for d in dates if date(2025, 11, 14) <= d <= date(2026, 10, 16))
    mapped = mapping(bars, dates)
    common = {
        d
        for d in valuation
        if d in mapped and d not in SPECIAL and mapped[d].session_date != bars[0].session_date
    }
    # A missing preceding US session must not silently permit an older fresh input.
    for d in list(common):
        bday = mapped[d].session_date
        prior_day = bday - timedelta(days=1)
        while prior_day >= date(2025, 10, 17):
            try:
                us_session(prior_day)
            except ValueError:
                prior_day -= timedelta(days=1)
                continue
            break
        if prior_day not in us:
            common.remove(d)
    code_paths = ["src/kmast/research/ewy.py", "scripts/run_df004.py"]
    contract = dict(
        protocol_commit=PROTOCOL_COMMIT,
        protocol_sha256=seal["protocol_sha256"],
        source_hashes={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in code_paths},
        input_hashes=sorted({b.source_hash for b in bars}),
        missing_us_dates=list(map(str, missing_us)),
    )
    contract_path = proof / "implementation-contract.json"
    if contract_path.exists():
        previous = json.loads(contract_path.read_bytes())
        assert previous["input_hashes"] == contract["input_hashes"]
        assert (
            previous["source_hashes"]["src/kmast/research/ewy.py"]
            == contract["source_hashes"]["src/kmast/research/ewy.py"]
        )
    else:
        immutable_write(contract_path, canonical(contract))
    private = Path("data/data-first-private-df004-results")
    private.mkdir(exist_ok=True)
    summaries, full = [], {}
    for symbol in protocol["korean_symbols"]:
        idx = "0001" if symbol in {"005930", "000660", "035420"} else "1001"
        for scenario in ("BASE", "STRESS"):
            for model in MODELS:
                result = replay(
                    tuple(panels[symbol][d] for d in dates),
                    tuple(panels[idx][d] for d in dates),
                    bars,
                    valuation,
                    common,
                    model,
                    scenario,
                )
                key = (symbol, scenario, model)
                full[key] = result
                immutable_write(private / ("-".join(key) + ".json"), canonical(result))
                summaries.append({k: v for k, v in result.items() if k != "trace"})
    common_dates = sorted(common)

    def mean(values):
        return sum(values, D(0)) / len(values)

    table = {(s["symbol"], s["scenario"], s["model"]): s for s in summaries}
    traces = {key: {r["date"]: r for r in v["trace"]} for key, v in full.items()}
    symbols = protocol["korean_symbols"]
    groups = [mapped[d].body > 0 for d in common_dates]
    body, gap, increments = [], [], [[], []]
    clusters = []
    for d in common_dates:
        ds = str(d)
        body.append(
            float(mean([D(traces[sy, "BASE", "H1_EWY"][ds]["body_return"]) for sy in symbols]))
        )
        gap.append(
            float(mean([D(traces[sy, "BASE", "H1_EWY"][ds]["gap_return"]) for sy in symbols]))
        )
        for k, (a, b) in enumerate(
            (("EWY_AND_DOM_INDEX", "DOM_INDEX"), ("EWY_AND_DOM_STOCK", "DOM_STOCK"))
        ):
            increments[k].append(
                float(
                    mean(
                        [
                            D(traces[sy, "BASE", a][ds]["net"])
                            - D(traces[sy, "BASE", b][ds]["net"])
                            for sy in symbols
                        ]
                    )
                )
            )
        cluster = mean([D(traces[sy, "BASE", "H1_EWY"][ds]["net"]) + 100 for sy in symbols])
        clusters.append(cluster)
    endpoints = holm([bootstrap(body, groups), bootstrap(increments[0]), bootstrap(increments[1])])
    positive = sum((max(D(0), v) for v in clusters), D(0))
    concentration = (
        sum(sorted((max(D(0), v) for v in clusters), reverse=True)[:5], D(0)) / positive
        if positive
        else None
    )
    sufficient = len(common) >= 80 and sum(groups) >= 20 and len(groups) - sum(groups) >= 20
    wins = {
        sc: sum(D(table[sy, sc, "H1_EWY"]["cash_excess"]) > 0 for sy in symbols)
        for sc in ("BASE", "STRESS")
    }
    index_wins = sum(
        D(table[sy, "BASE", "EWY_AND_DOM_INDEX"]["net"]) > D(table[sy, "BASE", "DOM_INDEX"]["net"])
        for sy in symbols
    )
    support = (
        sufficient
        and endpoints[0]["observed"] > 0
        and endpoints[0]["reject"]
        and any(e["observed"] > 0 and e["reject"] for e in endpoints[1:])
        and min(wins.values()) >= 4
        and index_wins >= 4
        and concentration is not None
        and concentration <= D(".5")
    )
    decision = (
        "EWY_EXPLORATORY_SIGNAL_SUPPORTED"
        if support
        else "EWY_EXPLORATORY_SIGNAL_NOT_SUPPORTED"
        if sufficient
        else "EWY_INSUFFICIENT_EVIDENCE"
    )
    comparisons = []
    for sy in symbols:
        for sc in ("BASE", "STRESS"):
            for model, baseline in (
                ("H1_EWY", "ALWAYS_LONG"),
                ("EWY_AND_DOM_INDEX", "DOM_INDEX"),
                ("EWY_AND_DOM_STOCK", "DOM_STOCK"),
            ):
                a, b = table[sy, sc, model], table[sy, sc, baseline]
                ae, be = D(a["average_open_exposure"]), D(b["average_open_exposure"])
                common_exposure = min(ae, be)
                comparisons.append(
                    dict(
                        symbol=sy,
                        scenario=sc,
                        model=model,
                        baseline=baseline,
                        net_increment=str(D(a["net"]) - D(b["net"])),
                        exposure_label="POSTHOC_DIAGNOSTIC",
                        allocation_feedback=False,
                        equal_full_risk=False,
                        exposure_scaled_increment=str(
                            D(a["cash_excess"]) * common_exposure / ae
                            - D(b["cash_excess"]) * common_exposure / be
                        )
                        if ae and be
                        else None,
                    )
                )
    leave_month = {
        m: str(
            sum((v for d, v in zip(common_dates, clusters, strict=True) if str(d)[:7] != m), D(0))
        )
        for m in sorted({str(d)[:7] for d in common_dates})
    }
    leave_stock = {
        sy: str(mean([D(table[o, "BASE", "H1_EWY"]["cash_excess"]) for o in symbols if o != sy]))
        for sy in symbols
    }
    regimes = {}
    for regime in ("BULL", "BEAR", "NEUTRAL", "UNKNOWN"):
        for model in MODELS:
            regimes[regime + ":" + model] = dict(
                reference_day_count=sum(
                    r["regime"] == regime and r["common"]
                    for sy in symbols
                    for r in full[sy, "BASE", model]["trace"]
                ),
                mean_reference_net=str(
                    mean(
                        [
                            sum(
                                (
                                    D(r["net"])
                                    for r in full[sy, "BASE", model]["trace"]
                                    if r["regime"] == regime and r["common"]
                                ),
                                D(0),
                            )
                            for sy in symbols
                        ]
                    )
                ),
            )
    negative_rejected = 0
    for d in common_dates:
        future = next((b for b in bars if b.session_date >= d), None)
        if future:
            try:
                require_available(future, at(d, 8))
            except ValueError:
                negative_rejected += 1
    report = dict(
        protocol_commit=PROTOCOL_COMMIT,
        protocol_sha256=seal["protocol_sha256"],
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        confirmatory_status="NOT_EXECUTED",
        decision=decision,
        independent_references=96,
        us_sessions=len(bars),
        us_interval=[str(bars[0].session_date), str(bars[-1].session_date)],
        missing_us_dates=list(map(str, missing_us)),
        common_dates=len(common),
        positive_dates=sum(groups),
        nonpositive_dates=len(groups) - sum(groups),
        valuation_days=len(valuation),
        strict_publication_dates=len(mapping(bars, dates, True)),
        excluded_dates=[str(d) for d in valuation if d not in common],
        quality_flags=sorted(flags | {f for b in bars for f in b.flags}),
        execution_label=protocol["execution_label"],
        nav_status="NAV_PUBLICATION_UNVERIFIED",
        performance_0905=None,
        nav_performance=None,
        fx_control=None,
        soxx_control=None,
        endpoints=endpoints,
        gap_diagnostic=bootstrap(gap, groups),
        date_cluster_not_joint_account=True,
        h1_positive_cash_excess_count=wins,
        index_combination_improves_count=index_wins,
        top5_positive_date_share=str(concentration),
        leave_one_month_cash_excess_cluster_sum=leave_month,
        leave_one_stock_mean_cash_excess=leave_stock,
        regimes=regimes,
        future_wrong_date_rejections=negative_rejected,
        comparisons=comparisons,
        summaries=summaries,
        network_requests=budget["requests"],
        authentication_calls=budget["auth"],
        order_calls=0,
        cancel_calls=0,
        account_calls=0,
        provenance_limitation=(
            "Initial pages retain sanitized price-field hashes, not wire bytes; "
            "one later wire page preserved. MODP0/1 equality only observed on recent100; "
            "provider session/corporate-action policy not independently certified."
        ),
    )
    immutable_write(proof / "results.json", canonical(report))
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "decision",
                    "common_dates",
                    "positive_dates",
                    "nonpositive_dates",
                    "independent_references",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
