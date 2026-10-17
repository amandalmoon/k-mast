"""Explicit sampled-universe, next-session scenarios; preserves all source observations.

Uses the frozen A feature function and existing reference ledger. No G1/OOS/OMS approval.
Derived day boundaries are conservative scenario bounds, never observed exchange timestamps.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from kmast.alpha.models import AlphaConfig, AlphaResult, Bar, Context, PositionView
from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick
from kmast.alpha.rules import features
from kmast.core.base import Contract, Identifier, Nonnegative, Positive, Weight
from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.data.models import KST, Observation
from kmast.data.normalization import content_hash

D = Decimal
SPECIAL_NO_EXECUTION = {date(2025, 11, 13), date(2026, 1, 2)}


class ExplorationPolicy(Contract):
    scope: Literal["EXPLORATORY_REAL_DATA"] = "EXPLORATORY_REAL_DATA"
    version: Identifier
    capital: Positive = D(10_000_000)
    fee_bps: Nonnegative = D(3)
    sell_tax_bps: Nonnegative = D(20)
    slippage_bps: Nonnegative = D(5)
    previous_volume_fraction: Weight = D(".001")
    fill_fraction: Weight = D(1)
    limit_buffer: Weight = D(".05")
    daily_operating_cost: Nonnegative = D(100)
    scope_acceptance: Literal["SAMPLED_SURVIVOR_PRICE_ONLY_NOT_PIT"]
    minimum_samples: int = Field(default=22, ge=22)
    cost_provenance: Literal["RESEARCH_ESTIMATE"] = "RESEARCH_ESTIMATE"
    economic_status: Literal["ECONOMIC_EDGE_UNVERIFIED"] = "ECONOMIC_EDGE_UNVERIFIED"
    live_approved: Literal[False] = False


def boundary(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), KST)


def daily_bar(row: Observation, available: datetime) -> Bar:
    if row.price_basis != "RAW" or row.venue != "KRX" or row.kind not in {"DAILY", "INDEX"}:
        raise ValueError("exploratory daily RAW KRX rows required")
    if any(v is None for v in (row.open, row.high, row.low, row.close)):
        raise ValueError("OHLC missing")
    # Conservative full-date bounds. This is a new derived object, not a flag-cleared Observation.
    return Bar.model_validate(
        dict(
            identity=row.record_id,
            symbol=row.symbol,
            start=boundary(row.exchange_date, 0),
            end=boundary(row.exchange_date, 23, 59),
            available_at=available,
            resolution="DAILY",
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume if row.volume is not None else 0,
            turnover=row.turnover if row.turnover is not None else 0,
            source_ref=row.source_hash,
            origin="REAL",
        )
    )


def candidate_a(
    context: Context, symbol: str, config: AlphaConfig, position: PositionView | None, revision: int
) -> AlphaResult:
    """Frozen A rules; declared sample eligibility does not claim a PIT security master."""
    active, weight, reason, evidence = features(context, config, symbol)
    deadline = position.exit_deadline if position else context.now + config.max_holding
    if position:
        close = context.bars[-1].close
        if deadline <= context.now or close <= position.entry_price * (1 - config.stop_fraction):
            active, reason = False, "DEADLINE_OR_STOP_EXIT"
        elif reason == "TREND_INTACT":
            active, weight = True, position.weight
        if active:
            weight = min(weight, position.weight)
    identity = content_hash(
        [
            context.model_dump(mode="json"),
            config.model_dump(mode="json"),
            position.model_dump(mode="json") if position else None,
            revision,
            "EXPLORATORY_SAMPLED_ELIGIBILITY",
        ]
    )
    intent = SignalIntent(
        intent_id=identity,
        revision=revision,
        target_snapshot_id=identity,
        strategy_id="A",
        model_version=config.version,
        config_hash=content_hash(config.model_dump(mode="json")),
        data_version=context.source_version,
        symbol=symbol,
        venue="KRX",
        session="REGULAR",
        decision_at=context.now,
        available_at=context.now,
        target_weight=weight if active else D(0),
        horizon=config.max_holding,
        valid_until=context.next_session_open + config.order_lifetime,
        reason_code=reason,
        evidence_refs=evidence,
    )
    return AlphaResult(
        snapshot=TargetSnapshot(
            strategy_id="A",
            snapshot_id=identity,
            revision=revision,
            expected_symbols=(symbol,),
            intents=(intent,),
        ),
        exit_deadlines=((symbol, deadline),),
        earliest_execution_at=context.next_session_open,
        feature_evidence=((symbol, evidence),),
        reasons=((symbol, reason),),
    )


def replay(
    rows: tuple[Observation, ...],
    index: tuple[Observation, ...],
    policy: ExplorationPolicy,
    mode: Literal["ALPHA_A", "BUY_HOLD", "HOLD_25", "CASH", "TREND_25"],
) -> dict[str, Any]:
    stock = {row.exchange_date: row for row in rows}
    benchmark = {row.exchange_date: row for row in index}
    if len(stock) != len(rows) or len(benchmark) != len(index):
        raise ValueError("duplicate daily observations")
    dates = sorted(stock)
    if len(dates) < policy.minimum_samples or any(day not in benchmark for day in dates):
        raise ValueError("insufficient or unaligned daily benchmark")
    if dates != sorted(benchmark):
        raise ValueError("missing stock or index sessions require explicit gap analysis")
    if any(row.data_origin != "KIS_READONLY" for row in rows + index):
        raise ValueError("real exploratory path requires real source lineage")
    symbol = rows[0].symbol
    if any(row.symbol != symbol or row.kind != "DAILY" for row in rows):
        raise ValueError("single-symbol daily panel required")
    config = AlphaConfig(strategy="A")
    costs = SimCosts(
        version=policy.version,
        fee_bps=policy.fee_bps,
        sell_tax_bps=policy.sell_tax_bps,
        slippage_bps=policy.slippage_bps,
        max_participation=1,
        cost_scope="REAL_UNVERIFIED",
    )
    ref = ReferencePortfolio("A", policy.capital, costs)
    observations: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    deadline = boundary(dates[0], 23, 59)
    block_until = -1
    started = False
    positive = 0
    first_evaluation = config.lookback + 1
    opening_nav = policy.capital
    ref.value(boundary(dates[first_evaluation - 1], 23, 59))
    for offset in range(first_evaluation, len(dates)):
        day, prior_day = dates[offset], dates[offset - 1]
        current, prior = stock[day], stock[prior_day]
        assert current.open is not None and current.close is not None and prior.close is not None
        decision_at, opening = boundary(day, 8), boundary(day, 9)
        window_start = offset - config.lookback - 1
        bars = tuple(
            daily_bar(stock[d], boundary(dates[i + 1], 8))
            for i, d in enumerate(dates[window_start:offset], start=window_start)
        )
        indices = tuple(
            daily_bar(benchmark[d], boundary(dates[i + 1], 8))
            for i, d in enumerate(dates[window_start:offset], start=window_start)
        )
        # Separate full acquisition manifest from the actually visible decision inputs.
        source_version = content_hash(
            [[b.model_dump(mode="json") for b in panel] for panel in (bars, indices)]
        )
        ref.mark(symbol, prior.close, decision_at)
        quantity = ref.quantity(symbol)
        position = None
        if quantity:
            cost = sum((lot.quantity * lot.unit_cost for lot in ref.state.lots), D(0)) / quantity
            position = PositionView(
                symbol=symbol,
                weight=min(D(1), quantity * prior.close / ref.nav),
                entry_price=cost,
                exit_deadline=deadline,
            )
        context = Context(
            now=decision_at,
            session_open=boundary(prior_day, 0),
            session_close=boundary(prior_day, 23, 59),
            next_session_open=opening,
            universe=(),
            bars=bars,
            benchmark=indices,
            expected_daily_ends=tuple(b.end for b in bars),
            source_version=source_version,
            scope="REAL_UNVERIFIED",
        )
        signal = candidate_a(context, symbol, config, position, offset)
        if mode not in {"ALPHA_A", "TREND_25"}:
            target = (
                (D(1) / (1 + policy.fee_bps / 10000) if mode == "BUY_HOLD" else D(".25"))
                if mode != "CASH"
                else D(0)
            )
            # One entry only; no daily rebalancing for the passive baselines.
            if started:
                target = quantity * prior.close / ref.nav
            raw = signal.snapshot.intents[0].model_dump() | {"target_weight": target}
            intent = SignalIntent.model_validate(raw)
            signal = AlphaResult.model_validate(
                signal.model_dump()
                | {"snapshot": signal.snapshot.model_dump() | {"intents": (intent,)}}
            )
        if mode == "TREND_25":
            # Pre-registered comparator: previous close >= preceding 20-close mean;
            # constant 25% target, no breakout/RS/turnover/deadline/stop optimization.
            trend = bars[-1].close >= sum((b.close for b in bars[:-1]), D(0)) / config.lookback
            intent = SignalIntent.model_validate(
                signal.snapshot.intents[0].model_dump()
                | {"target_weight": D(".25") if trend else D(0)}
            )
            signal = AlphaResult.model_validate(
                signal.model_dump()
                | {"snapshot": signal.snapshot.model_dump() | {"intents": (intent,)}}
            )
        target = signal.snapshot.intents[0].target_weight
        if target > 0:
            positive += 1
        buying = target * ref.nav / prior.close > quantity
        limit = prior.close * (1 + policy.limit_buffer if buying else 1 - policy.limit_buffer)
        can_submit = day not in SPECIAL_NO_EXECUTION and not (buying and offset < block_until)
        if abs(target * ref.nav / prior.close - quantity) < 1:
            can_submit = False
        if mode not in {"ALPHA_A", "TREND_25"} and started:
            can_submit = False
        before = len(ref.state.executions)
        order_before = len(ref.state.orders)
        pre_cash, pre_nav = ref.state.cash, ref.nav
        feature_active, feature_weight, _, _ = features(context, config, symbol)
        rs = bars[-1].close / bars[0].close - indices[-1].close / indices[0].close
        diagnostic_filters = dict(
            breakout=bars[-1].close > max(b.high for b in bars[:-1]),
            relative_strength=rs >= config.min_relative_strength,
            turnover=min(b.turnover for b in bars) >= config.min_turnover,
            feature_active=feature_active,
            uncapped_volatility_weight=str(
                config.volatility_budget
                / max(
                    sum(
                        (
                            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                            for a, b in zip(bars[:-1], bars[1:], strict=True)
                        ),
                        D(0),
                    )
                    / config.lookback
                    / bars[-1].close,
                    D(".0001"),
                )
            ),
            capped_feature_weight=str(feature_weight),
            deadline_due=bool(position and position.exit_deadline <= decision_at),
            stop_due=bool(
                position and prior.close <= position.entry_price * (1 - config.stop_fraction)
            ),
        )
        capacity = 0
        if can_submit:
            ref.submit(signal, {symbol: limit})
            remaining = sum(
                o.quantity - o.filled for o in ref.state.orders if o.status in {"OPEN", "PARTIAL"}
            )
            capacity = min(
                int((prior.volume or D(0)) * policy.previous_volume_fraction),
                int(remaining * policy.fill_fraction),
            )
            # Open is an assumed next-session fill anchor, never known to the decision function.
            event = Tick(
                identity=f"{mode}:{day}",
                symbol=symbol,
                at=opening + timedelta(seconds=1),
                available_at=opening + timedelta(seconds=1),
                bid=current.open,
                ask=current.open,
                available_quantity=capacity,
                # Final day volume is unavailable at 09:00:01. This is an assumed
                # opening-price anchor, not an observed executable market Tick.
                executable=True,
                origin="REAL_UNVERIFIED",
            )
            ref.match(event, event.at)
        trades = ref.state.executions[before:]
        if trades:
            if any(e[3] < 0 for e in trades):
                block_until = offset + 2  # no purchase using T/T+1 sale proceeds
            if any(e[3] > 0 for e in trades) and not quantity:
                deadline = dict(signal.exit_deadlines)[symbol]
            started = True
        ref.expire(opening + config.order_lifetime)
        end = boundary(day, 23, 59)
        ref.mark(symbol, current.close, end)
        valuation = ref.value(end, policy.daily_operating_cost)
        signals.append(
            dict(
                day=str(day),
                decision_at=decision_at.isoformat(),
                input_last_date=str(prior_day),
                target_weight=str(target),
                reason=signal.reasons[0][1],
                intent=signal.snapshot.intents[0].model_dump(mode="json"),
                lineage=dict(
                    input_hash=source_version,
                    stock_record_ids=[b.identity for b in bars],
                    index_record_ids=[b.identity for b in indices],
                    last_available_at=bars[-1].available_at.isoformat(),
                    scenario_availability="DERIVED_NOT_OBSERVED_HISTORICAL_TIMESTAMP",
                ),
                filters=diagnostic_filters,
                opening_model="ASSUMED_OPEN_ANCHOR_NO_QUOTE_TRADE_OR_HALT_PROOF",
                opening_confidence="UNVERIFIED",
                prior_volume_capacity=capacity,
                pre_quantity=quantity,
                post_quantity=ref.quantity(symbol),
                pre_nav=str(pre_nav),
                pre_cash=str(pre_cash),
                orders=[o.model_dump(mode="json") for o in ref.state.orders[order_before:]],
                executions=[
                    list(e) for e in ref.state.model_dump(mode="json")["executions"][before:]
                ],
                submitted=can_submit,
                blocked_reason="SPECIAL_SESSION_OR_UNSETTLED_CASH" if not can_submit else None,
                submission_constraints=dict(
                    special_session=day in SPECIAL_NO_EXECUTION,
                    unsettled_cash=buying and offset < block_until,
                    below_one_share=abs(target * pre_nav / prior.close - quantity) < 1,
                    passive_started=mode not in {"ALPHA_A", "TREND_25"} and started,
                ),
            )
        )
        observations.append(
            dict(
                day=str(day),
                open=str(current.open),
                close=str(current.close),
                prior_close=str(prior.close),
                index_close=str(benchmark[day].close),
                index_prior_close=str(benchmark[prior_day].close),
                quantity=ref.quantity(symbol),
                cumulative_costs=str(ref.state.costs),
                cumulative_turnover=str(ref.state.turnover),
                realized_gross=str(ref.state.realized),
                valuation=valuation.model_dump(mode="json"),
            )
        )
    navs = [opening_nav] + [D(row["valuation"]["nav"]) for row in observations]
    peak, maximum_drawdown = navs[0], D(0)
    for nav in navs:
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, (peak - nav) / peak)
    net = ref.nav - policy.capital
    net_before_opex = net + ref.state.operating_costs
    gross_price = net_before_opex + ref.state.costs
    return dict(
        mode=mode,
        symbol=symbol,
        evaluation_start=str(dates[first_evaluation - 1]),
        evaluation_end=str(dates[-1]),
        days=len(observations),
        capital=str(policy.capital),
        ending_nav=str(ref.nav),
        price_pnl_including_embedded_slippage=str(gross_price),
        explicit_fees_taxes=str(ref.state.costs),
        trading_net_pnl=str(net_before_opex),
        recurring_operating_cost=str(ref.state.operating_costs),
        scenario_project_net_pnl=str(net),
        return_after_scenario_cost=str(net / policy.capital),
        mdd=str(maximum_drawdown),
        turnover=str(ref.state.turnover / policy.capital),
        executions=len(ref.state.executions),
        positive_target_days=positive,
        final_quantity=ref.quantity(symbol),
        signal_log=signals,
        observed_price_log=observations,
        reference_state=ref.state.model_dump(mode="json"),
        policy=policy.model_dump(mode="json"),
        scope="EXPLORATORY_REAL_DATA",
        source_quality_flags=sorted({f for row in rows + index for f in row.quality_flags}),
        corporate_action_total_return_pnl=None,
        oos_status="NOT_EXECUTED",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        engine_revision="V3_CAUSAL_INPUT_LINEAGE_OPEN_ANCHOR",
    )
