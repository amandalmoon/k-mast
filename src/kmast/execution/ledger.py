from decimal import ROUND_DOWN, Decimal
from typing import Any, TypeVar

from kmast.core.base import Contract
from kmast.data.models import KST
from kmast.data.normalization import content_hash
from kmast.execution.events import (
    Allocate,
    CashPolicy,
    DecisionRecorded,
    Event,
    Fill,
    Flow,
    Income,
    Mark,
    OrderNotice,
    Plan,
    Reconcile,
    SeedPosition,
    Settle,
    SplitAction,
    Transfer,
)
from kmast.execution.models import (
    TERMINAL,
    TRANSITIONS,
    Book,
    ExecutionState,
    FillReceipt,
    Lot,
    Order,
    Settlement,
    Sleeve,
    Status,
)
from kmast.execution.portfolio import order_allocations
from kmast.execution.risk import evaluate

T = TypeVar("T", bound=Contract)


def change(model: T, **updates: Any) -> T:
    return type(model).model_validate(model.model_dump() | updates)


def patch_book(book: Book, **amounts: Decimal) -> Book:
    return change(book, **{key: getattr(book, key) + value for key, value in amounts.items()})


def sleeve_change(state: ExecutionState, owner: str, book: Book) -> ExecutionState:
    return change(
        state,
        attribution=tuple(
            change(a, book=book) if a.sleeve == owner else a for a in state.attribution
        ),
    )


def post(state: ExecutionState, owner: str, **amounts: Decimal) -> ExecutionState:
    state = change(state, account=patch_book(state.account, **amounts))
    return sleeve_change(state, owner, patch_book(state.book(owner), **amounts))


def transition(order: Order, status: Status) -> Order:
    if status not in TRANSITIONS[order.state]:
        raise ValueError("illegal order state transition")
    return change(order, state=status, history=(*order.history, status))


def replace_order(state: ExecutionState, order: Order) -> ExecutionState:
    return change(
        state,
        orders=tuple(
            order if o.client_order_id == order.client_order_id else o for o in state.orders
        ),
    )


def split_money(total: Decimal, quantities: tuple[int, ...]) -> tuple[Decimal, ...]:
    if not quantities or any(q <= 0 for q in quantities):
        raise ValueError("positive allocation quantities required")
    # Round down pro rata to 0.01 KRW; last allocation receives the exact residual.
    denominator = sum(quantities)
    parts = [
        (total * q / denominator).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        for q in quantities[:-1]
    ]
    return tuple([*parts, total - sum(parts, Decimal(0))])


def consume_lots(
    book: Book, symbol: str, quantity: int, *, settled_only: bool = True
) -> tuple[Book, tuple[Lot, ...]]:
    remaining = quantity
    kept = []
    consumed = []
    for lot in sorted(book.lots, key=lambda lot: (lot.acquired_at, lot.lot_id)):
        if lot.symbol != symbol or remaining == 0 or (settled_only and not lot.settled):
            kept.append(lot)
            continue
        used = min(remaining, lot.quantity)
        consumed.append(change(lot, quantity=used))
        if used < lot.quantity:
            kept.append(change(lot, quantity=lot.quantity - used))
        remaining -= used
    if remaining:
        raise ValueError("sellable inventory insufficient")
    return change(book, lots=tuple(kept)), tuple(consumed)


def synchronize_reserves(state: ExecutionState) -> ExecutionState:
    reserves: dict[str, Decimal] = {a.sleeve: Decimal(0) for a in state.attribution}
    for order in state.orders:
        if order.reserve == 0:
            continue
        done: dict[str, int] = {}
        for fill in state.fills:
            if fill.order_id == order.client_order_id:
                for owner, qty in fill.allocations:
                    done[owner] = done.get(owner, 0) + qty
        outstanding = [
            (owner, qty - done.get(owner, 0))
            for owner, qty in order.allocations
            if qty > done.get(owner, 0)
        ]
        allocated = split_money(order.reserve, tuple(q for _, q in outstanding))
        for (owner, _), amount in zip(outstanding, allocated, strict=True):
            reserves[owner] += amount
    return change(
        state,
        account=change(state.account, reserved_buy_cash=sum(reserves.values(), Decimal(0))),
        attribution=tuple(
            change(a, book=change(a.book, reserved_buy_cash=reserves[a.sleeve]))
            for a in state.attribution
        ),
    )


def assert_integrity(state: ExecutionState) -> None:
    if {a.sleeve for a in state.attribution} != {"A", "B", "C", "D", "EXTERNAL", "CENTRAL"} or len(
        state.attribution
    ) != 6:
        raise ValueError("invalid attribution books")
    for field in (
        "settled_cash",
        "unsettled_receivables",
        "unsettled_payables",
        "reserved_buy_cash",
        "dividend_receivable",
        "fees_payable",
        "taxes_payable",
        "other_liabilities",
        "capital_flows",
        "fees_and_taxes",
        "interest",
        "dividends",
        "account_opex",
    ):
        if getattr(state.account, field) != sum(
            (getattr(a.book, field) for a in state.attribution), Decimal(0)
        ):
            raise ValueError("account/attribution monetary conservation failed")
    symbols = {lot.symbol for lot in state.account.lots} | {
        lot.symbol for a in state.attribution for lot in a.book.lots
    }
    for symbol in symbols:
        if state.account.quantity(symbol) != sum(
            a.book.quantity(symbol) for a in state.attribution
        ):
            raise ValueError("account/attribution quantity conservation failed")
        if state.reserved_sell(symbol) > state.account.sellable(symbol):
            raise ValueError("sell reservation exceeds available inventory")
    if len({o.client_order_id for o in state.orders}) != len(state.orders):
        raise ValueError("duplicate order id")
    broker_ids = [o.broker_order_id for o in state.orders if o.broker_order_id is not None]
    if len(set(broker_ids)) != len(broker_ids):
        raise ValueError("duplicate broker order id")
    if len({f.exec_id for f in state.fills}) != len(state.fills):
        raise ValueError("duplicate execution id")
    if all(any(q.symbol == symbol for q in state.quotes) for symbol in symbols):
        nav = state.account.nav(state.quotes)
        if nav != sum((a.book.nav(state.quotes) for a in state.attribution), Decimal(0)):
            raise ValueError("NAV attribution conservation failed")
        if state.account.gross_pnl(state.quotes) != sum(
            (a.book.gross_pnl(state.quotes) for a in state.attribution), Decimal(0)
        ):
            raise ValueError("PnL attribution conservation failed")
        expected = (
            state.account.gross_pnl(state.quotes)
            + state.account.interest
            + state.account.dividends
            - state.account.fees_and_taxes
            - state.account.account_opex
        )
        if nav - state.account.capital_flows != expected:
            raise ValueError("self-financing NAV/PnL reconciliation failed")


def apply_fill(state: ExecutionState, event: Fill) -> ExecutionState:
    fingerprint = content_hash(event.model_dump(mode="json", exclude={"event_id"}))
    existing = next((f for f in state.fills if f.exec_id == event.exec_id), None)
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValueError("conflicting execution id")
        return state
    order = next(o for o in state.orders if o.client_order_id == event.order_id)
    approval = next(d for d in state.decisions if d.decision_id == order.decision_id)
    if event.at < approval.at:
        raise ValueError("execution predates order approval")
    if order.state in TERMINAL or event.quantity > order.remaining:
        raise ValueError("fill exceeds outstanding order or contradicts terminal state")
    if event.at.astimezone(KST).date() != event.trade_date:
        raise ValueError("trade date differs from execution date")
    if (order.side == "BUY" and event.price > order.limit_price) or (
        order.side == "SELL" and event.price < order.limit_price
    ):
        raise ValueError("fill violates limit price")
    fees = order.fees_incurred + event.fee + event.tax
    if fees > order.fee_buffer:
        raise ValueError("execution costs exceed reserved buffer")
    if any(
        f.at > event.at
        for f in state.fills
        if next(o for o in state.orders if o.client_order_id == f.order_id).symbol == order.symbol
    ):
        raise ValueError("late economic fill requires explicit chronological reconciliation")
    done: dict[str, int] = {}
    for fill in state.fills:
        if fill.order_id == order.client_order_id:
            for owner, qty in fill.allocations:
                done[owner] = done.get(owner, 0) + qty
    remaining = event.quantity
    allocations: list[tuple[Sleeve, int]] = []
    for owner, qty in order.allocations:
        portion = min(qty - done.get(owner, 0), remaining)
        if portion:
            allocations.append((owner, portion))
            remaining -= portion
    if remaining:
        raise ValueError("fill attribution exceeds target allocation")
    fee_parts = split_money(event.fee, tuple(q for _, q in allocations))
    tax_parts = split_money(event.tax, tuple(q for _, q in allocations))
    settlement_parts = []
    for (owner, qty), fee, tax in zip(allocations, fee_parts, tax_parts, strict=True):
        notional = event.price * qty
        state = post(
            state,
            owner,
            fees_payable=fee,
            taxes_payable=tax,
            fees_and_taxes=fee + tax,
            **{"unsettled_payables" if order.side == "BUY" else "unsettled_receivables": notional},
        )
        if order.side == "BUY":
            lot = Lot(
                lot_id=event.exec_id + ":" + owner,
                fill_id=event.exec_id,
                symbol=order.symbol,
                quantity=qty,
                unit_cost=event.price,
                origin_unit_cost=event.price,
                acquired_at=event.at,
                origin_sleeve=owner,
                lineage=(event.exec_id,),
                holding_deadline=dict(order.holding_deadlines).get(owner),
            )
            state = change(state, account=change(state.account, lots=(*state.account.lots, lot)))
            state = sleeve_change(
                state, owner, change(state.book(owner), lots=(*state.book(owner).lots, lot))
            )
        else:
            book, pieces = consume_lots(state.book(owner), order.symbol, qty)
            cost = sum((p.quantity * p.unit_cost for p in pieces), Decimal(0))
            state = sleeve_change(state, owner, patch_book(book, realized_pnl=notional - cost))
            account, actual_pieces = consume_lots(state.account, order.symbol, qty)
            actual_cost = sum((p.quantity * p.unit_cost for p in actual_pieces), Decimal(0))
            state = change(state, account=patch_book(account, realized_pnl=notional - actual_cost))
        settlement_parts.append((owner, notional, fee, tax))
    # Reject unsafe sell charges rather than allowing negative settlement proceeds.
    if order.side == "SELL" and event.fee + event.tax > event.price * event.quantity:
        raise ValueError("sell settlement proceeds negative")
    new_filled = order.filled + event.quantity
    order = change(order, filled=new_filled, fees_incurred=fees)
    if new_filled == order.quantity:
        order = transition(order, "FILLED")
    elif order.state in {"UNKNOWN", "CANCEL_PENDING"}:
        order = change(order, history=(*order.history, "PARTIAL_FILL_WHILE_" + order.state))
    else:
        order = transition(order, "PARTIALLY_FILLED")
    state = replace_order(state, order)
    return change(
        state,
        fills=(
            *state.fills,
            FillReceipt(
                exec_id=event.exec_id,
                fingerprint=fingerprint,
                order_id=order.client_order_id,
                allocations=tuple(allocations),
                at=event.at,
            ),
        ),
        settlements=(
            *state.settlements,
            Settlement(
                exec_id=event.exec_id,
                side=order.side,
                notional=event.price * event.quantity,
                fee=event.fee,
                tax=event.tax,
                sleeve_amounts=tuple(settlement_parts),
                due=state.calendar.due(event.trade_date),
            ),
        ),
    )


def apply_notice(state: ExecutionState, event: OrderNotice) -> ExecutionState:
    order = next(o for o in state.orders if o.client_order_id == event.order_id)
    if event.action == "ACK":
        if not event.broker_order_id or not event.broker_order_id.startswith("MOCK_"):
            raise ValueError("mock broker identity required")
        if order.broker_order_id not in {None, event.broker_order_id}:
            raise ValueError("conflicting broker order id")
        if any(
            o.broker_order_id == event.broker_order_id
            and o.client_order_id != order.client_order_id
            for o in state.orders
        ):
            raise ValueError("broker id already belongs to another order")
        order = change(order, broker_order_id=event.broker_order_id)
        if order.state == "SUBMITTING":
            order = transition(order, "ACKNOWLEDGED")
        # Late ACK records identity, never rolls FILLED/PARTIAL/CANCEL state backwards.
    elif event.action == "TIMEOUT":
        order = transition(order, "UNKNOWN")
        state = change(state, reconciled=False)
    elif event.action == "CANCEL_REQUEST":
        order = transition(order, "CANCEL_PENDING")
    elif event.action == "CANCEL_CONFIRMED":
        if event.confirmed_filled != order.filled:
            raise ValueError("cancel final cumulative quantity requires reconciliation")
        order = transition(order, "CANCELLED")
    else:
        if order.filled or event.confirmed_filled != 0:
            raise ValueError("cannot reject an executed order")
        order = transition(order, "REJECTED")
    return replace_order(state, order)


def reconcile(state: ExecutionState, event: Reconcile) -> ExecutionState:
    snapshot = event.snapshot
    if snapshot.observed_at > event.at:
        raise ValueError("future broker snapshot")
    if state.last_event_at is not None and snapshot.observed_at < state.last_event_at:
        raise ValueError("broker snapshot predates latest local activity")
    for fill in event.discovered_fills:
        if fill.at > snapshot.observed_at:
            raise ValueError("fill newer than reconciliation snapshot")
        state = synchronize_reserves(apply_fill(state, fill))
    before_terminal_proof = state
    remote = {o.client_order_id: o for o in snapshot.orders}
    if len(remote) != len(snapshot.orders) or set(remote) != {
        o.client_order_id for o in state.orders
    }:
        return change(
            state, reconciled=False, warnings=(*state.warnings, "BROKER_ORDER_SET_MISMATCH")
        )
    for order in state.orders:
        observed = remote[order.client_order_id]
        if observed.quantity != order.quantity or observed.filled != order.filled:
            return change(
                before_terminal_proof,
                reconciled=False,
                warnings=(*state.warnings, "BROKER_FILL_QUANTITY_MISMATCH"),
            )
        if order.broker_order_id not in {
            None,
            observed.broker_order_id,
        } or not observed.broker_order_id.startswith("MOCK_"):
            raise ValueError("broker identity changed or is not synthetic")
        if order.state == "UNKNOWN":
            order = transition(order, "RECONCILING")
        if order.state == "RECONCILING":
            order = transition(order, observed.state)
        elif order.state == "SUBMITTING" and observed.state == "ACKNOWLEDGED":
            order = transition(order, "ACKNOWLEDGED")
        elif order.state == "CANCEL_PENDING" and observed.state == "CANCELLED":
            order = transition(order, "CANCELLED")
        elif order.state != observed.state:
            return change(
                before_terminal_proof,
                reconciled=False,
                warnings=(*state.warnings, "ORDER_STATE_MISMATCH"),
            )
        state = replace_order(state, change(order, broker_order_id=observed.broker_order_id))
    state = synchronize_reserves(state)
    quantities = tuple(
        sorted(
            (symbol, state.account.quantity(symbol))
            for symbol in {lot.symbol for lot in state.account.lots}
        )
    )
    reserved = tuple(
        sorted(
            (symbol, state.reserved_sell(symbol))
            for symbol in {o.symbol for o in state.orders}
            if state.reserved_sell(symbol)
        )
    )
    remote = {o.client_order_id: o for o in snapshot.orders}
    mismatch = (
        quantities != tuple(sorted(snapshot.quantities))
        or len(remote) != len(snapshot.orders)
        or set(remote) != {o.client_order_id for o in state.orders}
        or state.account.settled_cash != snapshot.settled_cash
        or state.account.unsettled_receivables != snapshot.receivables
        or state.account.unsettled_payables != snapshot.payables
        or state.account.fees_payable != snapshot.fees_payable
        or state.account.taxes_payable != snapshot.taxes_payable
        or state.account.reserved_buy_cash != snapshot.reserved_buy_cash
        or reserved != tuple(sorted(snapshot.reserved_sells))
    )
    if mismatch:
        return change(
            before_terminal_proof,
            reconciled=False,
            warnings=(*state.warnings, "BROKER_SNAPSHOT_MISMATCH"),
        )
    return change(
        state,
        reconciled=True,
        broker_buying_power=snapshot.buying_power,
        withdrawal_available=snapshot.withdrawal_available,
        broker_snapshot_at=snapshot.observed_at,
    )


def reduce_event(state: ExecutionState, event: Event) -> ExecutionState:
    if isinstance(event, Flow):
        if event.amount < 0 and -event.amount > min(
            state.account.conservative_cash, state.book(event.sleeve).conservative_cash
        ):
            raise ValueError("withdrawal exceeds unencumbered cash")
        state = post(state, event.sleeve, settled_cash=event.amount, capital_flows=event.amount)
    elif isinstance(event, Allocate):
        if (
            event.from_sleeve == event.to_sleeve
            or state.book(event.from_sleeve).conservative_cash < event.cash
        ):
            raise ValueError("invalid capital allocation")
        state = sleeve_change(
            state,
            event.from_sleeve,
            patch_book(
                state.book(event.from_sleeve), settled_cash=-event.cash, capital_flows=-event.cash
            ),
        )
        state = sleeve_change(
            state,
            event.to_sleeve,
            patch_book(
                state.book(event.to_sleeve), settled_cash=event.cash, capital_flows=event.cash
            ),
        )
    elif isinstance(event, SeedPosition):
        mark = state.quote(event.symbol)
        if mark.available_at > event.at:
            raise ValueError("opening inventory mark unavailable")
        value = mark.price * event.quantity
        state = post(state, "EXTERNAL", capital_flows=value)
        lot = Lot(
            lot_id=event.event_id,
            fill_id=event.event_id,
            symbol=event.symbol,
            quantity=event.quantity,
            unit_cost=mark.price,
            origin_unit_cost=event.cost,
            acquired_at=event.at,
            origin_sleeve="EXTERNAL",
            lineage=(event.event_id,),
            settled=True,
        )
        state = change(state, account=change(state.account, lots=(*state.account.lots, lot)))
        state = sleeve_change(
            state,
            "EXTERNAL",
            change(state.book("EXTERNAL"), lots=(*state.book("EXTERNAL").lots, lot)),
        )
    elif isinstance(event, Mark):
        if event.quote.available_at > event.at:
            raise ValueError("future quote")
        old = next((q for q in state.quotes if q.symbol == event.quote.symbol), None)
        if old and event.quote.at < old.at:
            raise ValueError("late quote requires historical replay, not mark overwrite")
        state = change(
            state,
            quotes=tuple(
                sorted(
                    (*[q for q in state.quotes if q.symbol != event.quote.symbol], event.quote),
                    key=lambda q: q.symbol,
                )
            ),
        )
    elif isinstance(event, SplitAction):
        if event.effective_date > event.at.astimezone(KST).date() or (
            state.last_event_at is not None and event.at < state.last_event_at
        ):
            raise ValueError("split effect unavailable or late event requires replay")
        affected_orders = {o.client_order_id for o in state.orders if o.symbol == event.symbol}
        if any(o.symbol == event.symbol and o.state not in TERMINAL for o in state.orders) or any(
            not item.settled
            and any(
                f.exec_id == item.exec_id and f.order_id in affected_orders for f in state.fills
            )
            for item in state.settlements
        ):
            raise ValueError("split requires settled inventory and resolved orders")
        if any(
            f.order_id in affected_orders and f.at.astimezone(KST).date() >= event.effective_date
            for f in state.fills
        ):
            raise ValueError("post-effective execution requires explicit corporate-action replay")
        if not state.account.quantity(event.symbol):
            raise ValueError("split action requires owned inventory")

        def split_book(book: Book) -> Book:
            lots = []
            for lot in book.lots:
                if lot.symbol != event.symbol:
                    lots.append(lot)
                    continue
                quantity = lot.quantity * event.multiplier
                if quantity != int(quantity):
                    raise ValueError("fractional split requires explicit cash-in-lieu")
                lots.append(
                    change(
                        lot,
                        quantity=int(quantity),
                        unit_cost=lot.unit_cost / event.multiplier,
                        origin_unit_cost=lot.origin_unit_cost / event.multiplier,
                        lineage=(*lot.lineage, event.action_id),
                    )
                )
            return change(book, lots=tuple(lots))

        state = change(
            state,
            account=split_book(state.account),
            attribution=tuple(change(a, book=split_book(a.book)) for a in state.attribution),
            quotes=tuple(
                change(
                    q,
                    price=q.price / event.multiplier,
                    session="UNKNOWN",
                    halted=True,
                    source_ref="MECHANICAL_SPLIT_NOT_EXECUTABLE",
                )
                if q.symbol == event.symbol
                else q
                for q in state.quotes
            ),
            reconciled=False,
        )
    elif isinstance(event, CashPolicy):
        state = change(state, cash_policy=event.policy)
    elif isinstance(event, DecisionRecorded):
        fee_buffer = Decimal(event.portfolio.cost_model_id.removeprefix("MOCK_BUFFER:"))
        expected = evaluate(
            state,
            event.batch,
            event.decision.policy,
            event.at,
            fee_buffer=fee_buffer,
            reduction=event.portfolio.action == "RISK_REDUCTION",
        )
        if expected != event.decision or event.portfolio.as_of != event.at:
            raise ValueError("risk decision is not reproducible from current state")
        if any(b.version == event.batch.version and b != event.batch for b in state.batches):
            raise ValueError("target version reused with different content")
        for previous in state.batches:
            prior = {
                owner: (identity, revision) for owner, identity, revision in previous.snapshot_refs
            }
            for owner, identity, revision in event.batch.snapshot_refs:
                if owner in prior:
                    old_identity, old_revision = prior[owner]
                    if (
                        revision < old_revision
                        or (identity != old_identity and revision == old_revision)
                        or (identity == old_identity and revision != old_revision)
                    ):
                        raise ValueError("stale or conflicting strategy snapshot revision")
        state = change(
            state,
            decisions=(*state.decisions, event.decision),
            batches=(*state.batches, event.batch),
            portfolio_decisions=(*state.portfolio_decisions, event.portfolio),
        )
    elif isinstance(event, Plan):
        decision = next(d for d in state.decisions if d.decision_id == event.decision_id)
        batch = next(b for b in state.batches if b.version == decision.target_version)
        existing = tuple(o for o in state.orders if o.target_version == batch.version)
        if not existing:
            portfolio = next(
                p for p in state.portfolio_decisions if p.decision_id == decision.decision_id
            )
            if decision.status not in {"ALLOW", "REDUCE"} or portfolio.action == "HOLD_TARGET":
                raise PermissionError("target not approved for mock planning")
            if decision.expires_at <= event.at or decision.account_version != state.account_version:
                raise PermissionError("expired approval or changed account")
            if portfolio.cost_model_id != "MOCK_BUFFER:" + str(event.fee_buffer_per_order):
                raise ValueError("fee buffer differs from approved risk preview")
            refreshed = evaluate(
                state,
                batch,
                decision.policy,
                event.at,
                fee_buffer=event.fee_buffer_per_order,
                reduction=portfolio.action == "RISK_REDUCTION",
            )
            if refreshed.status not in {"ALLOW", "REDUCE"}:
                raise PermissionError("risk conditions changed before mock planning")
            orders = order_allocations(state, batch, event.fee_buffer_per_order, event.decision_id)
            state = change(state, orders=(*state.orders, *orders))
    elif isinstance(event, OrderNotice):
        state = apply_notice(state, event)
    elif isinstance(event, Fill):
        state = apply_fill(state, event)
    elif isinstance(event, Settle):
        item = next(s for s in state.settlements if s.exec_id == event.exec_id)
        if item.settled:
            return change(state, sequence=state.sequence + 1)
        if event.settlement_date != item.due or event.at.astimezone(KST).date() < item.due:
            raise ValueError("settlement before eligible due date")
        for owner, notional, fee, tax in item.sleeve_amounts:
            if item.side == "BUY":
                state = post(
                    state,
                    owner,
                    settled_cash=-(notional + fee + tax),
                    unsettled_payables=-notional,
                    fees_payable=-fee,
                    taxes_payable=-tax,
                )
            else:
                state = post(
                    state,
                    owner,
                    settled_cash=notional - fee - tax,
                    unsettled_receivables=-notional,
                    fees_payable=-fee,
                    taxes_payable=-tax,
                )
        if item.side == "BUY":
            state = change(
                state,
                account=change(
                    state.account,
                    lots=tuple(
                        change(lot, settled=True) if lot.fill_id == item.exec_id else lot
                        for lot in state.account.lots
                    ),
                ),
                attribution=tuple(
                    change(
                        a,
                        book=change(
                            a.book,
                            lots=tuple(
                                change(lot, settled=True) if lot.fill_id == item.exec_id else lot
                                for lot in a.book.lots
                            ),
                        ),
                    )
                    for a in state.attribution
                ),
            )
        state = change(
            state,
            settlements=tuple(
                change(s, settled=True) if s.exec_id == item.exec_id else s
                for s in state.settlements
            ),
        )
    elif isinstance(event, Transfer):
        if event.from_sleeve == event.to_sleeve or state.reserved_sell(
            event.symbol, event.from_sleeve
        ):
            raise ValueError("transfer conflicts with ownership or reservations")
        quote = state.quote(event.symbol)
        if (
            quote.at != event.reference_at
            or quote.price != event.reference_price
            or quote.available_at > event.at
        ):
            raise ValueError("transfer reference is not an observed current mark")
        cash = event.reference_price * event.quantity
        if state.book(event.to_sleeve).conservative_cash < cash:
            raise ValueError("receiver virtual cash insufficient")
        sender, lots = consume_lots(state.book(event.from_sleeve), event.symbol, event.quantity)
        cost = sum((lot.quantity * lot.unit_cost for lot in lots), Decimal(0))
        sender = patch_book(sender, settled_cash=cash, realized_pnl=cash - cost)
        receiver = patch_book(state.book(event.to_sleeve), settled_cash=-cash)
        moved = tuple(
            change(
                lot,
                lot_id=lot.lot_id + ":" + event.event_id,
                unit_cost=event.reference_price,
                lineage=(*lot.lineage, event.event_id),
            )
            for lot in lots
        )
        state = sleeve_change(
            sleeve_change(state, event.from_sleeve, sender),
            event.to_sleeve,
            change(receiver, lots=(*receiver.lots, *moved)),
        )
    elif isinstance(event, Income):
        amount = event.amount
        if event.category == "EXTERNAL_OPEX":
            state = change(state, external_opex=state.external_opex + amount)
        elif event.category == "INTEREST":
            state = post(state, event.sleeve, settled_cash=amount, interest=amount)
        elif event.category == "ACCOUNT_OPEX":
            if amount > state.book(event.sleeve).conservative_cash:
                raise ValueError("account operating cost exceeds free cash")
            state = post(state, event.sleeve, settled_cash=-amount, account_opex=amount)
        elif event.category == "DIVIDEND_ACCRUAL":
            if not event.entitlement_id or any(
                k == event.entitlement_id for k, _, _ in state.dividends_known
            ):
                raise ValueError("duplicate or missing dividend entitlement")
            state = post(state, event.sleeve, dividend_receivable=amount, dividends=amount)
            state = change(
                state,
                dividends_known=(
                    *state.dividends_known,
                    (event.entitlement_id, amount, event.sleeve),
                ),
            )
        else:
            if (
                event.entitlement_id,
                amount,
                event.sleeve,
            ) not in state.dividends_known or event.entitlement_id in state.dividends_paid:
                raise ValueError("dividend payment does not match unpaid entitlement")
            state = post(state, event.sleeve, settled_cash=amount, dividend_receivable=-amount)
            assert event.entitlement_id is not None
            state = change(state, dividends_paid=(*state.dividends_paid, event.entitlement_id))
    elif isinstance(event, Reconcile):
        state = reconcile(state, event)
    state = synchronize_reserves(
        change(
            state,
            sequence=state.sequence + 1,
            last_event_at=max(event.at, state.last_event_at) if state.last_event_at else event.at,
        )
    )
    assert_integrity(state)
    return state
