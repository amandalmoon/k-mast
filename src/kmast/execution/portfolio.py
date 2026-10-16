from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from kmast.core.contracts import CapitalBudget, PortfolioTarget, StrategyTarget, TargetSnapshot
from kmast.core.enums import Policy
from kmast.data.normalization import content_hash
from kmast.execution.models import TERMINAL, ExecutionState, Order, Sleeve, TargetBatch


def aggregate(
    state: ExecutionState,
    budget: CapitalBudget,
    snapshots: tuple[TargetSnapshot, ...],
    now: datetime,
    version: str,
    *,
    holding_deadlines: tuple[tuple[Sleeve, datetime], ...] = (),
) -> TargetBatch:
    if budget.policy_id != Policy.PBASE_FIXED or not budget.approved_by:
        raise ValueError("only explicitly approved synthetic fixed budgets supported")
    if len({s.strategy_id for s in snapshots}) != len(snapshots):
        raise ValueError("duplicate snapshot strategy")
    if {s.strategy_id for s in snapshots} != {s.strategy_id for s in budget.sleeves}:
        raise ValueError("budget/full-snapshot mismatch")
    by_symbol: dict[str, list[StrategyTarget]] = {}
    nav = state.account.nav(state.quotes)
    expiry = []
    for snapshot in snapshots:
        weight = next(s.weight for s in budget.sleeves if s.strategy_id == snapshot.strategy_id)
        for intent in snapshot.intents:
            if intent.decision_at > now or intent.valid_until <= now:
                raise ValueError("future or expired snapshot")
            if intent.venue != "KRX" or intent.session != "REGULAR":
                raise ValueError("only KRX regular targets supported")
            quote = state.quote(intent.symbol)
            if quote.available_at > now:
                raise ValueError("future reference quote")
            qty = int(
                (nav * weight * intent.target_weight / quote.price).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            qty -= qty % quote.lot_size
            by_symbol.setdefault(intent.symbol, []).append(
                StrategyTarget(
                    strategy_id=snapshot.strategy_id,
                    symbol=intent.symbol,
                    target_qty=qty,
                    budget_id=budget.budget_id,
                    revision=snapshot.revision,
                )
            )
            expiry.append(intent.valid_until)
        # Full replacement: previously owned but omitted symbols become zero.
        for lot in state.book(snapshot.strategy_id).lots:
            if lot.symbol not in snapshot.expected_symbols:
                values = by_symbol.setdefault(lot.symbol, [])
                if not any(v.strategy_id == snapshot.strategy_id for v in values):
                    values.append(
                        StrategyTarget(
                            strategy_id=snapshot.strategy_id,
                            symbol=lot.symbol,
                            target_qty=0,
                            budget_id=budget.budget_id,
                            revision=snapshot.revision,
                        )
                    )
    if not expiry:
        raise ValueError("explicit signal lifetime required even for all-cash targets")
    return TargetBatch(
        version=version,
        account_version=state.account_version,
        as_of=now,
        expires_at=min(expiry),
        budget=budget,
        snapshot_refs=tuple((s.strategy_id, s.snapshot_id, s.revision) for s in snapshots),
        holding_deadlines=holding_deadlines,
        targets=tuple(
            PortfolioTarget(
                symbol=symbol,
                aggregate_target_qty=sum(s.target_qty for s in values),
                sleeve_targets=tuple(sorted(values, key=lambda v: v.strategy_id)),
                snapshot_id=content_hash([s.snapshot_id for s in snapshots]),
                target_version=version,
            )
            for symbol, values in sorted(by_symbol.items())
        ),
    )


def order_allocations(
    state: ExecutionState, batch: TargetBatch, fee_buffer: Decimal, decision_id: str
) -> tuple[Order, ...]:
    orders = []
    for target in batch.targets:
        pending = [o for o in state.orders if o.symbol == target.symbol and o.state not in TERMINAL]
        if any(o.state in {"UNKNOWN", "RECONCILING", "CANCEL_PENDING"} for o in pending):
            raise ValueError("uncertain pending order blocks planning")
        if len({o.side for o in pending}) > 1:
            raise ValueError("opposing pending orders require reconciliation")
        deltas: list[tuple[Sleeve, int]] = []
        for sleeve_target in target.sleeve_targets:
            owner = sleeve_target.strategy_id
            if owner not in {"A", "B", "C", "D"}:
                raise ValueError("only managed sleeves may order")
            confirmed_pending = 0
            for order in pending:
                done = sum(
                    q
                    for f in state.fills
                    if f.order_id == order.client_order_id
                    for s, q in f.allocations
                    if s == owner
                )
                remaining = dict(order.allocations).get(owner, 0) - done  # type: ignore[call-overload]
                confirmed_pending += remaining * (1 if order.side == "BUY" else -1)
            delta = (
                sleeve_target.target_qty
                - state.book(owner).quantity(target.symbol)
                - confirmed_pending
            )
            if delta:
                deltas.append((owner, delta))  # type: ignore[arg-type]
        if not deltas:
            continue
        if len({1 if q > 0 else -1 for _, q in deltas}) > 1:
            raise ValueError("explicit internal transfer required before external netting")
        side = "BUY" if deltas[0][1] > 0 else "SELL"
        if pending and any(o.side != side for o in pending):
            raise ValueError("cancel and reconcile opposing order first")
        oid = content_hash([state.account_ref, batch.version, target.symbol, side])
        orders.append(
            Order(
                client_order_id=oid,
                symbol=target.symbol,
                side=side,
                quantity=sum(abs(q) for _, q in deltas),
                limit_price=state.quote(target.symbol).price,
                fee_buffer=fee_buffer,
                allocations=tuple((s, abs(q)) for s, q in deltas),
                target_version=batch.version,
                decision_id=decision_id,
                holding_deadlines=batch.holding_deadlines,
            )
        )
    return tuple(orders)
