"""Offline accounting attribution; diagnostic exposures never feed strategy decisions."""

from collections import Counter
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any

D = Decimal
ZERO = D(0)


def attribute(replay: dict[str, Any]) -> dict[str, Any]:
    """FIFO fee allocation, exact daily money bridge, and explicitly post-hoc diagnostics."""
    policy = replay["policy"]
    capital = D(replay["capital"])
    daily, trades, lots = [], [], []
    commission = tax = slip = ZERO
    last_nav, last_qty = capital, 0
    overnight = timing = market = residual = ZERO
    cumulative_turnover = ZERO
    exits: dict[str, dict[str, Any]] = {}
    filter_counts: Counter[str] = Counter()
    execution_counts: Counter[str] = Counter()
    price_by_day = {s["day"]: s for s in replay["observed_price_log"]}
    for sig, row in zip(replay["signal_log"], replay["observed_price_log"], strict=True):
        nav = D(row["valuation"]["nav"])
        cash = D(row["valuation"]["cash"])
        close, prior, anchor = D(row["close"]), D(row["prior_close"]), D(row["open"])
        dfee = dtax = dslip = traded = dtime = ZERO
        for key, passed in sig["filters"].items():
            if isinstance(passed, bool):
                filter_counts[key + ("_true" if passed else "_false")] += 1
        constraints = sig["submission_constraints"]
        for key, blocked in constraints.items():
            if blocked:
                execution_counts[key] += 1
        for order in sig["orders"]:
            execution_counts["order_" + order["status"]] += 1
            if order["status"] == "EXPIRED":
                execution_counts["expired_remaining_shares"] += order["quantity"] - order["filled"]
        if sig["submitted"] and not sig["executions"]:
            if sig["prior_volume_capacity"] == 0:
                execution_counts["zero_capacity_submissions"] += 1
            else:
                execution_counts["nonzero_capacity_no_fill"] += 1
        for execution in sig["executions"]:
            qty, price, fee = execution[3], D(execution[4]), D(execution[5])
            count = abs(qty)
            notional = count * price
            comm = (notional * D(policy["fee_bps"]) / 10000).quantize(
                D(".01"), rounding=ROUND_CEILING
            )
            # Combined charge is rounded once by the frozen ledger. Attribute its
            # rounding residual to tax, rather than rounding tax a second time.
            levy = fee - comm
            embedded = count * (price - anchor) * (1 if qty > 0 else -1)
            dfee += comm
            dtax += levy
            dslip += embedded
            traded += notional
            dtime += qty * (close - price)
            if qty > 0:
                lots.append(
                    dict(
                        quantity=qty,
                        price=price,
                        fee_per_share=fee / qty,
                        day=row["day"],
                        at=execution[1],
                        signal=sig["intent"]["intent_id"],
                        decision_at=sig["decision_at"],
                        last_price_date=sig["input_last_date"],
                    )
                )
            else:
                remaining = count
                while remaining:
                    lot = lots[0]
                    take = min(remaining, lot["quantity"])
                    gross = take * (price - lot["price"])
                    allocated = take * (lot["fee_per_share"] + fee / count)
                    reason = (
                        "DEADLINE_AND_STOP"
                        if sig["filters"]["deadline_due"] and sig["filters"]["stop_due"]
                        else "DEADLINE"
                        if sig["filters"]["deadline_due"]
                        else "STOP"
                        if sig["filters"]["stop_due"]
                        else sig["reason"]
                    )
                    # Exit is at the opening anchor: that day's close occurs after
                    # disposal and cannot enter a within-holding excursion proxy.
                    held = [p for d, p in price_by_day.items() if lot["day"] <= d < row["day"]]
                    if replay["mode"] == "TREND_25":
                        reason = (
                            "TREND_RULE_EXIT" if D(sig["target_weight"]) == 0 else "TREND_REBALANCE"
                        )
                    # Observed close excursion proxy, not intraday position MFE/MAE.
                    marks = [D(p["close"]) / lot["price"] - 1 for p in held]
                    marks += [D(0), price / lot["price"] - 1]
                    start_index = D(price_by_day[lot["day"]]["index_prior_close"])
                    trades.append(
                        dict(
                            entry_signal=lot["signal"],
                            decision_at=lot["decision_at"],
                            last_price_date=lot["last_price_date"],
                            entry_at=lot["at"],
                            exit_at=execution[1],
                            entry_price=str(lot["price"]),
                            exit_price=str(price),
                            quantity=take,
                            exit_reason=reason,
                            calendar_holding_seconds=str(
                                D(
                                    str(
                                        (
                                            datetime.fromisoformat(execution[1])
                                            - datetime.fromisoformat(lot["at"])
                                        ).total_seconds()
                                    )
                                )
                            ),
                            observed_holding_days=len(held),
                            gross_pnl_embedded_slippage=str(gross),
                            allocated_explicit_cost=str(allocated),
                            net_pnl=str(gross - allocated),
                            close_mfe_proxy=str(max(marks)),
                            close_mae_proxy=str(min(marks)),
                            true_intraday_mfe=None,
                            true_intraday_mae=None,
                            index_close_return_proxy=str(D(row["index_close"]) / start_index - 1),
                            status="REALIZED_MODEL_NOT_ACTUAL_TRADE",
                        )
                    )
                    bucket = exits.setdefault(
                        reason, dict(fifo_matches=0, quantity=0, gross=ZERO, net=ZERO)
                    )
                    bucket["fifo_matches"] += 1
                    bucket["quantity"] += take
                    bucket["gross"] += gross
                    bucket["net"] += gross - allocated
                    remaining -= take
                    lot["quantity"] -= take
                    if lot["quantity"] == 0:
                        lots.pop(0)
        opex = D(policy["daily_operating_cost"])
        old_exposure = last_qty * prior
        d_overnight = last_qty * (close - prior)
        d_market = old_exposure * (D(row["index_close"]) / D(row["index_prior_close"]) - 1)
        bridge = d_overnight + dtime - dfee - dtax - opex
        assert nav - last_nav == bridge, "daily cash/price/cost bridge"
        overnight += d_overnight
        timing += dtime
        market += d_market
        residual += d_overnight - d_market
        commission += dfee
        tax += dtax
        slip += dslip
        cumulative_turnover += traded
        quantity = row["quantity"]
        pending = sum(
            o["quantity"] - o["filled"] for o in sig["orders"] if o["status"] == "EXPIRED"
        )
        daily.append(
            dict(
                day=row["day"],
                target_weight=sig["target_weight"],
                quantity=quantity,
                actual_close_weight=str(quantity * close / nav),
                cash_weight=str(cash / nav),
                nav=str(nav),
                cash=str(cash),
                occupied_capital=str(quantity * close),
                expired_unfilled_quantity=pending,
                open_unfilled_quantity=0,
                cumulative_commission=str(commission),
                cumulative_tax=str(tax),
                cumulative_embedded_slippage=str(slip),
                turnover=str(traded / capital),
                cumulative_turnover=str(cumulative_turnover / capital),
                prior_close_exposure=str(old_exposure / last_nav),
                close_to_close_inventory_pnl=str(d_overnight),
                fill_to_close_change_pnl=str(dtime),
                market_direction_pnl_proxy=str(d_market),
                stock_relative_pnl_proxy=str(d_overnight - d_market),
                nav_change=str(bridge),
                daily_return=str(nav / last_nav - 1),
            )
        )
        last_nav, last_qty = nav, quantity
    final_close = D(replay["observed_price_log"][-1]["close"])
    unrealized = sum((lot["quantity"] * (final_close - lot["price"]) for lot in lots), ZERO)
    unallocated_entry_fee = sum((lot["quantity"] * lot["fee_per_share"] for lot in lots), ZERO)
    realized_net = sum((D(t["net_pnl"]) for t in trades), ZERO)
    realized_gross = sum((D(t["gross_pnl_embedded_slippage"]) for t in trades), ZERO)
    assert abs(
        realized_net
        + unrealized
        - unallocated_entry_fee
        - D(replay["recurring_operating_cost"])
        - D(replay["scenario_project_net_pnl"])
    ) < D("1e-18")
    weights = [D(r["actual_close_weight"]) for r in daily]
    twr = D(1)
    for row in daily:
        twr *= 1 + D(row["daily_return"])
    realized_days = sum(int(r["quantity"] > 0) for r in daily)
    sector = {
        "005930": "SEMICONDUCTOR_RELATED_UNVERIFIED_HISTORY",
        "000660": "SEMICONDUCTOR_RELATED_UNVERIFIED_HISTORY",
        "035420": "INTERNET_RELATED_UNVERIFIED_HISTORY",
        "247540": "BATTERY_RELATED_UNVERIFIED_HISTORY",
        "086520": "BATTERY_RELATED_UNVERIFIED_HISTORY",
        "028300": "BIO_RELATED_UNVERIFIED_HISTORY",
    }
    summary = dict(
        symbol=replay["symbol"],
        mode=replay["mode"],
        scenario=policy["version"],
        capital=replay["capital"],
        days=replay["days"],
        evaluation_start=replay["evaluation_start"],
        evaluation_end=replay["evaluation_end"],
        project_net=replay["scenario_project_net_pnl"],
        total_return=replay["return_after_scenario_cost"],
        time_weighted_return=str(twr - 1),
        mdd=replay["mdd"],
        average_close_exposure=str(sum(weights, ZERO) / len(weights)),
        maximum_close_exposure=str(max(weights)),
        average_cash_weight=str(1 - sum(weights, ZERO) / len(weights)),
        occupied_capital_days=str(sum((D(r["occupied_capital"]) for r in daily), ZERO)),
        capital_occupancy_fraction=str(
            sum((D(r["occupied_capital"]) for r in daily), ZERO) / (capital * len(daily))
        ),
        actual_holding_days=realized_days,
        positive_target_days=replay["positive_target_days"],
        final_quantity=replay["final_quantity"],
        commission=str(commission),
        tax=str(tax),
        embedded_slippage=str(slip),
        explicit_cost=str(commission + tax),
        operating_cost=replay["recurring_operating_cost"],
        gross_before_modeled_slippage=str(
            D(replay["price_pnl_including_embedded_slippage"]) + slip
        ),
        realized_gross=str(realized_gross),
        realized_net_allocated_cost=str(realized_net),
        unrealized_gross=str(unrealized),
        open_entry_fee=str(unallocated_entry_fee),
        unrealized_net_entry_fee=str(unrealized - unallocated_entry_fee),
        executions=replay["executions"],
        fifo_closed_matches=len(trades),
        turnover=replay["turnover"],
        close_inventory_pnl=str(overnight),
        fill_to_close_change_pnl=str(timing),
        market_direction_pnl_proxy=str(market),
        stock_relative_pnl_proxy=str(residual),
        exit_contributions=exits,
        filters=dict(filter_counts),
        execution_constraints=dict(execution_counts),
        sector_proxy=sector[replay["symbol"]],
        sector_index_return=None,
        opening_execution_confidence="UNVERIFIED_ASSUMPTION",
        mdd_scope="DAILY_CLOSE_NOT_INTRADAY_RISK_LIMIT",
        actual_trade_pnl=None,
        scope="EXPLORATORY_REAL_DATA",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        confirmatory_status="NOT_EXECUTED",
        live_status="LIVE_NOT_APPROVED",
    )
    return dict(
        summary=summary,
        daily=daily,
        fifo_trades=trades,
        open_lots=lots,
        signal_lineage=replay["signal_log"],
    )


def exposure_diagnostic(alpha: dict[str, Any]) -> dict[str, Any]:
    """Ex-post constant-average-exposure stock comparison; no fitted trading strategy."""
    rows = alpha["observed_price_log"]
    weight = sum(
        (D(r["quantity"]) * D(r["close"]) / D(r["valuation"]["nav"]) for r in rows), ZERO
    ) / len(rows)
    # Arithmetic return contribution in initial-capital units, no compounding or costs.
    returns = [D(r["close"]) / D(r["prior_close"]) - 1 for r in rows]
    capital = D(alpha["capital"])
    return dict(
        label="POSTHOC_AVERAGE_EXPOSURE_DIAGNOSTIC_NOT_TRADABLE_OR_CONFIRMATORY",
        weight=str(weight),
        gross_constant_exposure_pnl_proxy=str(capital * weight * sum(returns, ZERO)),
        cost_adjusted_pnl=None,
        risk_equivalence="NOT_PROVEN",
        used_in_signal=False,
        explanation=(
            "Same mean close exposure; different path, gaps and turnover; no causal skill inference"
        ),
    )
