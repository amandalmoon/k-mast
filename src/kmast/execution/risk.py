from datetime import datetime
from decimal import Decimal

from kmast.data.normalization import content_hash
from kmast.execution.models import (
    TERMINAL,
    ExecutionState,
    MockRiskDecision,
    MockRiskPolicy,
    TargetBatch,
)
from kmast.execution.portfolio import order_allocations


def evaluate(
    state: ExecutionState,
    batch: TargetBatch,
    policy: MockRiskPolicy,
    now: datetime,
    *,
    fee_buffer: Decimal = Decimal(0),
    reduction: bool = False,
) -> MockRiskDecision:
    reasons: list[str] = []
    status = "ALLOW"

    def result(status: str, reasons: list[str]) -> MockRiskDecision:
        return MockRiskDecision(
            decision_id=content_hash(
                [
                    batch.model_dump(mode="json"),
                    policy.model_dump(mode="json"),
                    now.isoformat(),
                    str(fee_buffer),
                    reduction,
                ]
            ),
            at=now,
            expires_at=min(batch.expires_at, now + policy.decision_lifetime),
            status=status,
            reasons=tuple(reasons or ["SYNTHETIC_LIMITS_PASSED"]),
            account_version=state.account_version,
            target_version=batch.version,
            target_hash=content_hash(batch.model_dump(mode="json")),
            policy=policy,
        )

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware risk clock required")
    if (
        batch.account_version != state.account_version
        or batch.as_of > now
        or batch.expires_at <= now
    ):
        return result("HOLD", ["STALE_ACCOUNT_OR_TARGET"])
    if not policy.complete() or not batch.budget.approved_by:
        return result("HOLD", ["RISK_POLICY_UNVERIFIED"])
    if batch.budget.policy_id != "PBASE_FIXED":
        return result("REJECT", ["DYNAMIC_POLICY_DISABLED"])
    if not state.reconciled or any(
        o.state in {"UNKNOWN", "CANCEL_PENDING", "RECONCILING"} for o in state.orders
    ):
        return result("HOLD", ["OPERATIONAL_RECONCILIATION_REQUIRED"])
    if state.cash_policy != "SYNTHETIC_NO_UNSETTLED_REUSE":
        return result("HOLD", ["CASH_POLICY_UNVERIFIED"])
    if (
        state.broker_buying_power is None
        or state.broker_snapshot_at is None
        or now - state.broker_snapshot_at > policy.quote_max_age
    ):
        return result("HOLD", ["BUYING_POWER_UNVERIFIED"])
    if state.valuation_status(now, policy.quote_max_age) == "VALUATION_UNVERIFIED":
        return result("HOLD", ["VALUATION_UNVERIFIED"])
    try:
        plans = order_allocations(state, batch, fee_buffer, "RISK_PREVIEW")
    except ValueError:
        return result("HOLD", ["PENDING_OR_ATTRIBUTION_CONFLICT"])
    nav = state.account.nav(state.quotes)
    if nav <= 0:
        return result("REJECT", ["NONPOSITIVE_NAV"])
    increasing = any(o.side == "BUY" for o in plans)
    if reduction and increasing:
        return result("REJECT", ["REDUCTION_MAY_NOT_INCREASE_EXPOSURE"])
    if not plans:
        return result("HOLD", ["NO_DELTA"])
    budgets = {s.strategy_id: s.weight for s in batch.budget.sleeves}
    exposure_by_sleeve: dict[str, Decimal] = {}
    for target in batch.targets:
        for sleeve in target.sleeve_targets:
            if sleeve.budget_id != batch.budget.budget_id or sleeve.strategy_id not in budgets:
                reasons.append("BUDGET_IDENTITY_MISMATCH")
            exposure_by_sleeve[sleeve.strategy_id] = (
                exposure_by_sleeve.get(sleeve.strategy_id, Decimal(0))
                + sleeve.target_qty * state.quote(target.symbol).price
            )
    for owner, exposure in exposure_by_sleeve.items():
        if increasing and (
            exposure > nav * budgets.get(owner, Decimal(0))
            or exposure > nav * (policy.max_sleeve_weight or Decimal(0))
        ):
            reasons.append("STRATEGY_BUDGET_EXCEEDED")
    for order in plans:
        quote = state.quote(order.symbol)
        if order.side == "BUY":
            deadlines = dict(batch.holding_deadlines)
            if any(
                owner not in deadlines or deadlines[owner] <= now for owner, _ in order.allocations
            ):
                reasons.append("HOLDING_DEADLINE_UNVERIFIED")
            elif not policy.allow_overnight and (
                quote.session_ends_at is None
                or any(deadlines[owner] > quote.session_ends_at for owner, _ in order.allocations)
            ):
                reasons.append("OVERNIGHT_NOT_APPROVED")
        if (
            quote.available_at > now
            or now - quote.at > policy.quote_max_age
            or quote.session != "REGULAR"
        ):
            reasons.append("INVALID_SESSION_OR_STALE_QUOTE")
        if (
            quote.halted
            or quote.vi
            or not quote.lower_limit <= order.limit_price <= quote.upper_limit
        ):
            reasons.append("MARKET_NOT_EXECUTABLE")
        if order.quantity % quote.lot_size or order.limit_price % quote.tick_size:
            reasons.append("INVALID_ORDER_UNIT")
        if order.quantity > quote.liquidity_quantity * (policy.max_participation or Decimal(0)):
            reasons.append("LIQUIDITY_LIMIT")
        if not policy.allow_overnight and order.side == "BUY" and quote.at.date() != now.date():
            reasons.append("OVERNIGHT_NOT_APPROVED")
        if order.side == "SELL":
            for owner, qty in order.allocations:
                if qty > state.book(owner).sellable(order.symbol) - state.reserved_sell(
                    order.symbol, owner
                ):
                    reasons.append("SELLABLE_QUANTITY_EXCEEDED")
        elif any(
            lot.symbol == order.symbol and quote.price < lot.origin_unit_cost
            for lot in state.account.lots
        ):
            reasons.append("AVERAGING_DOWN_FORBIDDEN")
    buy_reserve = sum((o.reserve for o in plans), Decimal(0))
    if buy_reserve > min(state.account.conservative_cash, state.broker_buying_power or Decimal(0)):
        reasons.append("INSUFFICIENT_ACCOUNT_CASH")
    for owner in budgets:
        needed = sum(
            (
                o.limit_price * qty + (o.fee_buffer if o.side == "BUY" else Decimal(0))
                for o in plans
                for s, qty in o.allocations
                if s == owner and o.side == "BUY"
            ),
            Decimal(0),
        )
        if needed > state.book(owner).conservative_cash:
            reasons.append("INSUFFICIENT_SLEEVE_CASH")
    symbols = {lot.symbol for lot in state.account.lots} | {t.symbol for t in batch.targets}
    target_qty = {
        t.symbol: t.aggregate_target_qty + state.book("EXTERNAL").quantity(t.symbol)
        for t in batch.targets
    }
    sectors: dict[str, Decimal] = {}
    gross = Decimal(0)
    for symbol in symbols:
        quote = state.quote(symbol)
        actual = state.account.quantity(symbol)
        pending_buys = sum(
            o.remaining
            for o in state.orders
            if o.symbol == symbol and o.side == "BUY" and o.state not in TERMINAL
        )
        # Pending sells do not offset worst-case buy exposure.
        worst = max(
            actual
            + pending_buys
            + sum(o.quantity for o in plans if o.symbol == symbol and o.side == "BUY"),
            target_qty.get(symbol, actual),
        )
        value = worst * quote.price
        gross += value
        sectors[quote.sector] = sectors.get(quote.sector, Decimal(0)) + value
        if value > nav * (policy.max_symbol_weight or Decimal(0)) and increasing:
            reasons.append("SYMBOL_CONCENTRATION")
    if increasing and any(
        v > nav * (policy.max_sector_weight or Decimal(0)) for v in sectors.values()
    ):
        reasons.append("SECTOR_CONCENTRATION")
    if increasing and gross > nav * (policy.max_gross_weight or Decimal(0)):
        reasons.append("GROSS_EXPOSURE")
    if (
        increasing
        and policy.allow_overnight
        and gross > nav * (policy.max_overnight_weight or Decimal(0))
    ):
        reasons.append("OVERNIGHT_EXPOSURE")
    if increasing and gross * (policy.stress_shock or Decimal(0)) > (
        policy.stress_loss_limit_krw or Decimal(0)
    ):
        reasons.append("COMMON_STRESS_LIMIT")
    account_loss = state.account.nav(state.quotes) - state.account.capital_flows
    loss_breach = account_loss < -(policy.loss_limit_krw or Decimal(0))
    sleeve_breach = any(
        state.book(s).nav(state.quotes) - state.book(s).capital_flows
        < -(policy.sleeve_loss_limit_krw or Decimal(0))
        for s in budgets
    )
    if increasing and (loss_breach or sleeve_breach):
        return result("RISK_REDUCTION_REQUIRED", ["LOSS_LIMIT_BREACH", *sorted(set(reasons))])
    if increasing and any(
        lot.holding_deadline is not None and lot.holding_deadline <= now
        for lot in state.account.lots
    ):
        return result("RISK_REDUCTION_REQUIRED", ["HOLDING_DEADLINE_BREACH", *sorted(set(reasons))])
    if reasons:
        status = "REJECT"
    elif reduction:
        status = "REDUCE"
    return result(status, sorted(set(reasons)))
