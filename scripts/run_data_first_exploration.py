"""Run private price/signal/fill replay; publish only bounded aggregate scenario results."""

import json
from pathlib import Path

from kmast.alpha.models import AlphaConfig
from kmast.data.normalization import content_hash
from kmast.data.store import DataStore, canonical, immutable_write
from kmast.research.exploratory import ExplorationPolicy, replay


def main():
    root = Path(__file__).resolve().parents[1]
    proof = root / "artifacts/data-first"
    collected = json.loads((proof / "collection.json").read_bytes())
    folder = root / collected["private_store"]
    store = DataStore(folder)
    panels = {}
    adjusted = {}
    for d in collected["datasets"]:
        if d["operation"] not in {"daily", "index_daily"}:
            continue
        loaded = store.load_dataset(d["dataset_id"])
        target = adjusted if d["price_basis"] == "ADJUSTED" else panels
        panel = target.setdefault(d["symbol"], {})
        for row in loaded:
            if row.exchange_date in panel:
                raise ValueError("duplicate collection session")
            panel[row.exchange_date] = row
    policies = (
        ExplorationPolicy(
            version="BASE_3FEE_20TAX_5SLIP_100OPEX",
            scope_acceptance="SAMPLED_SURVIVOR_PRICE_ONLY_NOT_PIT",
        ),
        ExplorationPolicy(
            version="STRESS_10FEE_30TAX_20SLIP_100OPEX",
            fee_bps=10,
            sell_tax_bps=30,
            slippage_bps=20,
            scope_acceptance="SAMPLED_SURVIVOR_PRICE_ONLY_NOT_PIT",
        ),
        ExplorationPolicy(
            version="PARTIAL_HALF_FILL",
            fill_fraction=".5",
            scope_acceptance="SAMPLED_SURVIVOR_PRICE_ONLY_NOT_PIT",
        ),
    )
    contract = dict(
        scope="EXPLORATORY_REAL_DATA",
        config=AlphaConfig(strategy="A").model_dump(mode="json"),
        policies=[p.model_dump(mode="json") for p in policies],
        source_manifest_hash=content_hash(collected),
        source_ids=sorted(d["dataset_id"] for d in collected["datasets"]),
        time_policy="DERIVED_FULL_DAY_BOUND_THEN_NEXT_OBSERVED_SESSION_OPEN_ASSUMPTION_NOT_OBSERVED_TIMESTAMPS",
        regular_session_basis="https://global.krx.co.kr/contents/GLB/06/0602/0602020204/GLB0602020204T1.jsp",
        selection="USER_APPROVED_CURRENT_SURVIVOR_SAMPLE_NOT_PIT_UNIVERSE",
        actions="RAW_PRICE_ONLY_DIVIDENDS_AND_ACTION_HISTORY_UNVERIFIED",
        scope_limits="REFERENCE_ONLY_NO_OMS_OR_RISK_APPROVAL_NO_CONFIRMATORY_OOS",
        code_hash=content_hash(
            (root / "src/kmast/research/exploratory.py").read_text(encoding="utf-8")
        ),
    )
    contract["revision"] = "V2_BOUNDED_FEATURE_WINDOW_SAME_FROZEN_RULES"
    immutable_write(proof / "exploration-contract-v2.json", canonical(contract))
    private = folder / "exploration-v2"
    private.mkdir(exist_ok=True)
    summaries, errors = [], []
    for symbol in ("005930", "000660", "035420", "247540", "086520", "028300"):
        index_symbol = "0001" if symbol in {"005930", "000660", "035420"} else "1001"
        rows = tuple(sorted(panels[symbol].values(), key=lambda r: r.exchange_date))
        index = tuple(sorted(panels[index_symbol].values(), key=lambda r: r.exchange_date))
        for policy in policies:
            results = {}
            for mode in ("ALPHA_A", "BUY_HOLD", "HOLD_25", "CASH"):
                try:
                    result = replay(rows, index, policy, mode)
                    (private / f"{symbol}-{policy.version}-{mode}.json").write_bytes(
                        canonical(result)
                    )
                    results[mode] = result
                except Exception as error:
                    errors.append(
                        dict(
                            symbol=symbol,
                            scenario=policy.version,
                            mode=mode,
                            category=type(error).__name__,
                        )
                    )
            if len(results) != 4:
                continue
            alpha = results["ALPHA_A"]
            keys = (
                "symbol",
                "evaluation_start",
                "evaluation_end",
                "days",
                "capital",
                "ending_nav",
                "price_pnl_including_embedded_slippage",
                "explicit_fees_taxes",
                "trading_net_pnl",
                "recurring_operating_cost",
                "scenario_project_net_pnl",
                "return_after_scenario_cost",
                "mdd",
                "turnover",
                "executions",
                "positive_target_days",
                "final_quantity",
            )
            summary = {k: alpha[k] for k in keys}
            from decimal import Decimal

            summary.update(
                scenario=policy.version,
                cash_excess=str(
                    Decimal(alpha["scenario_project_net_pnl"])
                    - Decimal(results["CASH"]["scenario_project_net_pnl"])
                ),
                hold_excess=str(
                    Decimal(alpha["scenario_project_net_pnl"])
                    - Decimal(results["BUY_HOLD"]["scenario_project_net_pnl"])
                ),
                hold25_excess=str(
                    Decimal(alpha["scenario_project_net_pnl"])
                    - Decimal(results["HOLD_25"]["scenario_project_net_pnl"])
                ),
                baselines={
                    m: {
                        k: r[k]
                        for k in ("scenario_project_net_pnl", "mdd", "executions", "turnover")
                    }
                    for m, r in results.items()
                    if m != "ALPHA_A"
                },
                round_trip_exit_executions=sum(
                    e[3] < 0 for e in alpha["reference_state"]["executions"]
                ),
            )
            summaries.append(summary)
    pairs = adjusted.get("005930", {})
    comparison = dict(
        paired_dates=len(pairs),
        close_differences=sum(
            row.close != panels["005930"][day].close for day, row in pairs.items()
        ),
        interpretation="EQUALITY_IS_NOT_CORPORATE_ACTION_OR_TOTAL_RETURN_VERIFICATION",
    )
    report = dict(
        scope="EXPLORATORY_REAL_DATA",
        calculation_mode="SIMULATED_REAL_MARKET_DATA",
        scenarios=summaries,
        errors=errors,
        raw_adjusted_check=comparison,
        contract_id=content_hash(contract),
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        confirmatory_status="NOT_EXECUTED",
        live_status="LIVE_NOT_APPROVED",
        actual_orders=0,
        assumptions=(
            "CURRENT_SURVIVOR_SAMPLE",
            "OBSERVED_INDEX_DATE_GRID_NOT_PIT_CALENDAR",
            "DAY_END_BOUNDS_NOT_EXCHANGE_TIMESTAMPS",
            "NEXT_OPEN_ANCHOR_NO_QUEUE_PROOF",
            "PREVIOUS_DAY_VOLUME_CAPACITY_PROXY",
            "RESEARCH_COSTS_NOT_ACCOUNT_CONTRACT",
            "RAW_PRICE_ONLY_NO_VERIFIED_DIVIDENDS",
            "SPECIAL_SESSION_DATES_NO_EXECUTION",
            "SALE_PROCEEDS_NO_REUSE_UNTIL_SECOND_OBSERVED_SESSION",
        ),
        missing_metrics=(
            "TRUE_TOTAL_RETURN",
            "ACTUAL_EXECUTION_PNL",
            "VERIFIED_CAPACITY",
            "CONFIRMATORY_EDGE",
        ),
        private_price_signal_fill_artifacts=private.relative_to(root).as_posix(),
    )
    (proof / "exploration-summary.json").write_bytes(canonical(report))
    print(
        json.dumps(dict(scenarios=len(summaries), errors=errors, primary=summaries[:3]), indent=2)
    )


if __name__ == "__main__":
    main()
