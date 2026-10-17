"""Isolated D1 research replay using the unchanged independent reference ledger.

Open anchors are explicit counterfactual execution scenarios, never broker fills.
Original source observations and their quality flags are retained by the caller.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING
from decimal import Decimal as D
from typing import Any

from kmast.alpha.models import AlphaResult
from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick
from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.data.models import Observation
from kmast.data.store import canonical, digest
from kmast.research.exploratory import boundary


def event_signal(
    symbol: str, now: datetime, target: D, deadline: datetime, identity: str
) -> AlphaResult:
    opening = boundary(now.date(), 9)
    intent = SignalIntent(
        intent_id=identity,
        revision=1,
        target_snapshot_id=identity,
        strategy_id="D",
        model_version="DF006_D1_V1",
        config_hash="DF006_FROZEN_PROTOCOL",
        data_version=identity,
        symbol=symbol,
        venue="KRX",
        session="REGULAR",
        decision_at=now,
        available_at=now,
        target_weight=target,
        horizon=timedelta(days=5),
        valid_until=opening + timedelta(minutes=1),
        reason_code="D1_EXPLORATORY_DECISION",
        evidence_refs=(identity,),
    )
    return AlphaResult(
        snapshot=TargetSnapshot(
            strategy_id="D",
            snapshot_id=identity,
            revision=1,
            expected_symbols=(symbol,),
            intents=(intent,),
        ),
        exit_deadlines=((symbol, deadline),),
        earliest_execution_at=opening,
        feature_evidence=((symbol, (identity,)),),
        reasons=((symbol, "D1_EXPLORATORY_DECISION"),),
    )


def event_replay(
    stock: tuple[Observation, ...],
    index: tuple[Observation, ...],
    entry_day: date,
    scenario: tuple[int, int, int, str],
    model: str,
    excluded_sessions: frozenset[date],
    invalidation_day: date | None = None,
) -> dict[str, Any]:
    """One event-window account, no reentry/top-up and no terminal forced fill.

    Callers must supply 21 warmup sessions followed by the complete common event
    window, RAW prices and a verified constant-factor corporate-action gate.
    Overlapping event accounts are diagnostics, never a pooled feasible portfolio.
    """
    if model not in {"D1", "CASH", "BUY_HOLD", "TREND"}:
        raise ValueError("FROZEN_EVENT_MODEL_REQUIRED")
    rows = {r.exchange_date: r for r in stock}
    ix = {r.exchange_date: r for r in index}
    dates = sorted(ix)
    if len(rows) != len(stock) or set(rows) != set(ix) or len(ix) != len(index):
        raise ValueError("COMPLETE_UNIQUE_COMMON_PANEL_REQUIRED")
    if entry_day not in rows or dates.index(entry_day) < 21:
        raise ValueError("EVENT_WARMUP_REQUIRED")
    if any(r.price_basis != "RAW" or r.data_origin != "KIS_READONLY" for r in stock + index):
        raise ValueError("REAL_RAW_PANEL_REQUIRED")
    if any(
        r.open is None or r.close is None or r.close <= 0 or r.volume is None or r.volume <= 0
        for r in stock
    ):
        raise ValueError("HALT_OR_PRICE_GAP")
    fee, tax, slip, fill = scenario
    costs = SimCosts(
        version="DF006_RESEARCH_COST",
        fee_bps=D(fee),
        sell_tax_bps=D(tax),
        slippage_bps=D(slip),
        max_participation=D(1),
        cost_scope="REAL_UNVERIFIED",
    )
    capital = D(10000000)
    ref = ReferencePortfolio("D", capital, costs)
    symbol = stock[0].symbol
    entry_offset = dates.index(entry_day)
    deadline = boundary(entry_day, 8) + timedelta(days=5)
    prior_nav, peak, mdd = capital, capital, D(0)
    commission = levy = embedded = D(0)
    entry_attempted = False
    daily: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    ref.value(boundary(dates[entry_offset - 1], 23, 59))
    for offset in range(entry_offset, len(dates)):
        day, prior_day = dates[offset], dates[offset - 1]
        current, prior = rows[day], rows[prior_day]
        assert prior.close is not None and current.close is not None and current.open is not None
        assert ix[day].close is not None and ix[prior_day].close is not None
        now, opening = boundary(day, 8), boundary(day, 9)
        ref.mark(symbol, prior.close, now)
        quantity = ref.quantity(symbol)
        entry_price = (
            sum((lot.quantity * lot.unit_cost for lot in ref.state.lots), D(0)) / quantity
            if quantity
            else None
        )
        stop = bool(entry_price is not None and prior.close <= entry_price * D(".95"))
        invalid = invalidation_day is not None and day >= invalidation_day
        exit_due = now >= deadline or invalid or (stop and model != "BUY_HOLD")
        trend = (
            prior.close
            >= sum((rows[d].close or D(0) for d in dates[offset - 21 : offset - 1]), D(0)) / 20
        )
        target = quantity * prior.close / ref.nav if quantity else D(0)
        entry = day == entry_day and not entry_attempted
        if entry:
            entry_attempted = True
            target = (
                D(".25")
                if model != "CASH" and not invalid and (model != "TREND" or trend)
                else D(0)
            )
        if exit_due:
            target = D(0)
        target = min(target, D(".25"))
        identity = digest(canonical([symbol, str(day), model, list(scenario), str(target)]))
        signal = event_signal(symbol, now, target, deadline, identity)
        # Hold is deliberately no rebalance. Only initial entry or full risk reduction.
        submit = day not in excluded_sessions and (
            entry and target > 0 or quantity > 0 and target == 0
        )
        buying = bool(entry and target > 0)
        limit = prior.close * (D("1.05") if buying else D(".95"))
        before, order_before = len(ref.state.executions), len(ref.state.orders)
        capacity = 0
        if submit:
            ref.submit(signal, {symbol: limit})
            remaining = sum(
                o.quantity - o.filled for o in ref.state.orders if o.status in {"OPEN", "PARTIAL"}
            )
            capacity = min(int((prior.volume or D(0)) * D(".001")), int(D(remaining) * D(fill)))
            tick = Tick(
                identity=identity,
                symbol=symbol,
                at=opening + timedelta(seconds=1),
                available_at=opening + timedelta(seconds=1),
                bid=current.open,
                ask=current.open,
                available_quantity=capacity,
                executable=True,
                origin="REAL_UNVERIFIED",
            )
            ref.match(tick, tick.available_at)
            ref.expire(opening + timedelta(minutes=1))
        executions = ref.state.executions[before:]
        for _, _, _, qty, price, charge in executions:
            comm = (abs(qty) * price * D(fee) / 10000).quantize(D(".01"), rounding=ROUND_CEILING)
            commission += comm
            levy += charge - comm
            embedded += abs(qty) * (price - current.open) * (1 if qty > 0 else -1)
        ref.mark(symbol, current.close, boundary(day, 23, 59))
        valuation = ref.value(boundary(day, 23, 59), D(100))
        nav, qty = ref.nav, ref.quantity(symbol)
        peak = max(peak, nav)
        mdd = max(mdd, (peak - nav) / peak)
        daily.append(
            dict(
                day=str(day),
                nav=str(nav),
                cash=str(ref.state.cash),
                quantity=qty,
                occupied=str(qty * current.close),
                exposure=str(qty * current.close / nav),
                net_change=str(nav - prior_nav),
                daily_return=str(nav / prior_nav - 1),
                close=str(current.close),
                open=str(current.open),
                prior_close=str(prior.close),
                index_close=str(ix[day].close),
                index_prior_close=str(ix[prior_day].close),
                valuation=valuation.model_dump(mode="json"),
            )
        )
        prior_nav = nav
        signals.append(
            dict(
                day=str(day),
                decision_at=now.isoformat(),
                target=str(target),
                intent=signal.model_dump(mode="json"),
                prior_record=prior.record_id,
                submitted=submit,
                quantity_before=quantity,
                quantity_after=qty,
                risk_reduction_requested=quantity > 0 and exit_due,
                risk_reduction_filled=quantity - qty if exit_due else 0,
                reduction_unfulfilled=bool(exit_due and qty > 0),
                capacity=capacity,
                executions=[
                    list(e) for e in ref.state.model_dump(mode="json")["executions"][before:]
                ],
                orders=[o.model_dump(mode="json") for o in ref.state.orders[order_before:]],
                execution_model="ASSUMED_OPEN_NOT_OBSERVED_FILL",
            )
        )
    net = ref.nav - capital
    losses = sorted((-D(r["daily_return"]) for r in daily), reverse=True)
    tail = max(1, (len(losses) + 19) // 20)
    summary = dict(
        model=model,
        capital=str(capital),
        days=len(daily),
        net=str(net),
        return_after_cost=str(net / capital),
        gross_before_slippage=str(net + ref.state.costs + ref.state.operating_costs + embedded),
        commission=str(commission),
        tax=str(levy),
        explicit_cost=str(ref.state.costs),
        embedded_slippage=str(embedded),
        operating_cost=str(ref.state.operating_costs),
        cash_excess=str(net + ref.state.operating_costs),
        mdd=str(mdd),
        worst_day=str(min(D(r["daily_return"]) for r in daily)),
        ES5=str(sum(losses[:tail], D(0)) / tail),
        mean_exposure=str(sum((D(r["exposure"]) for r in daily), D(0)) / len(daily)),
        maximum_close_exposure=str(max(D(r["exposure"]) for r in daily)),
        weight_cap_breach_days=sum(D(r["exposure"]) > D(".25") for r in daily),
        capital_occupancy=str(sum((D(r["occupied"]) for r in daily), D(0)) / capital / len(daily)),
        turnover=str(ref.state.turnover / capital),
        executions=len(ref.state.executions),
        final_quantity=ref.quantity(symbol),
        unfulfilled_reduction_days=sum(s["reduction_unfulfilled"] for s in signals),
        expired_unfilled=sum(
            o.quantity - o.filled for o in ref.state.orders if o.status == "EXPIRED"
        ),
        actual_fill_pnl=None,
        scope="EXPLORATORY_REAL_DATA",
        sector_pnl=None,
    )
    assert commission + levy == ref.state.costs
    return dict(
        summary=summary,
        daily=daily,
        signals=signals,
        reference_state=ref.state.model_dump(mode="json"),
    )
