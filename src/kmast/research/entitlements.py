"""Versioned research sidecar: dividend rights never change a strategy or old ledger."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)


def verify_daily_ex_dividend_definition(
    detail: Mapping[str, object], properties: Sequence[Mapping[str, object]]
) -> bool:
    """Do not transfer a same-named master/other-API code to this daily endpoint."""
    if (
        detail.get("accessUrl")
        != ("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice")
        or detail.get("realTrId") != "FHKST03010100"
    ):
        return False
    fields = [
        p
        for p in properties
        if p.get("propertyCd") == "flng_cls_code" and p.get("bodyType") == "res_b"
    ]
    return (
        len(fields) == 1
        and re.search(r"(?:^|>)\s*02\s*:\s*배당락\s*(?:<|$)", str(fields[0].get("description", "")))
        is not None
    )


@dataclass(frozen=True)
class SettledTrade:
    identity: str
    symbol: str
    trade_day: date
    settlement_day: date
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity == 0 or self.settlement_day <= self.trade_day or not self.identity:
            raise ValueError("INVALID_SETTLED_TRADE")


@dataclass(frozen=True)
class DividendAction:
    identity: str
    symbol: str
    share_class: str
    ex_day: date
    last_purchase_day: date
    record_day: date
    declared_day: date
    resolved_day: date | None
    amount_known_on: date | None
    gross_per_share: Decimal | None
    scheduled_payment_day: date | None
    actual_payment_day: date | None
    payment_evidence_known_on: date | None
    issuer_paid_month: str | None
    identity_verified: bool
    settlement_verified: bool
    amount_verified: bool
    full_action_window_verified: bool
    evidence_hashes: tuple[str, ...]
    issuer_paid_month_known_on: date | None = None

    def __post_init__(self) -> None:
        if not self.last_purchase_day < self.ex_day <= self.record_day:
            raise ValueError("INVALID_RIGHTS_CHRONOLOGY")
        if self.gross_per_share is not None and (
            not self.gross_per_share.is_finite() or self.gross_per_share < ZERO
        ):
            raise ValueError("INVALID_DIVIDEND_AMOUNT")
        if self.actual_payment_day is not None and (
            self.resolved_day is None or self.actual_payment_day < self.resolved_day
        ):
            raise ValueError("PAYMENT_PRECEDES_FINAL_RESOLUTION")
        if self.actual_payment_day is not None and (
            self.payment_evidence_known_on is None
            or self.payment_evidence_known_on < self.actual_payment_day
        ):
            raise ValueError("ACTUAL_PAYMENT_REQUIRES_POST_EVENT_EVIDENCE")
        if self.amount_known_on is not None and (
            self.resolved_day is None or self.amount_known_on < self.resolved_day
        ):
            raise ValueError("FINAL_AMOUNT_KNOWN_BEFORE_RESOLUTION")
        if any(len(value) != 64 for value in self.evidence_hashes):
            raise ValueError("EVIDENCE_SHA256_REQUIRED")


@dataclass(frozen=True)
class CorporateActionEntitlementLedger:
    """DF011_V1 independent RAW-price sidecar, not an account or execution engine.

    Explicit settlement inputs carry evidence from the caller. Gross rights and
    payment timing/tax are independent gates. No rate or actual cash is invented.
    """

    action: DividendAction
    trades: tuple[SettledTrade, ...]
    price_basis: str = "RAW"
    modeled_execution: bool = True
    verified_dividend_tax: Decimal | None = None
    tax_evidence_hash: str | None = None
    tax_known_on: date | None = None
    price_only_pnl: Decimal | None = None
    price_pnl_as_of: date | None = None
    price_path_verified: bool = False

    def __post_init__(self) -> None:
        if self.price_basis != "RAW":
            raise ValueError("ADJUSTED_PLUS_DIVIDEND_DOUBLE_COUNT_FORBIDDEN")
        if len({t.identity for t in self.trades}) != len(self.trades):
            raise ValueError("DUPLICATE_EXECUTION")
        if any(t.symbol != self.action.symbol for t in self.trades):
            raise ValueError("SECURITY_IDENTITY_CONFLICT")
        if self.verified_dividend_tax is not None and (
            not self.verified_dividend_tax.is_finite()
            or self.verified_dividend_tax < ZERO
            or self.tax_known_on is None
            or self.tax_evidence_hash is None
            or len(self.tax_evidence_hash) != 64
        ):
            raise ValueError("VERIFIED_TAX_EVIDENCE_REQUIRED")

    def decision_inputs(self, on: date) -> dict[str, str]:
        """The frozen D1 never consumes ex-post dividend facts, even after acquisition."""
        return {}

    def entitled_quantity(self) -> int | None:
        if not self.action.identity_verified or not self.action.settlement_verified:
            return None
        quantities: dict[date, int] = {}
        for trade in self.trades:
            if trade.settlement_day <= self.action.record_day:
                quantities[trade.settlement_day] = (
                    quantities.get(trade.settlement_day, 0) + trade.quantity
                )
        quantity = 0
        for day in sorted(quantities):
            quantity += quantities[day]
            if quantity < 0:
                raise ValueError("NEGATIVE_SETTLED_ENTITLEMENT_POSITION")
        cutoff_quantity = sum(
            t.quantity for t in self.trades if t.trade_day <= self.action.last_purchase_day
        )
        if quantity != cutoff_quantity:
            raise ValueError("ENTITLEMENT_SETTLEMENT_CUTOFF_CONFLICT")
        return quantity

    def snapshot(self, on: date, knowledge_on: date) -> dict[str, object]:
        action = self.action
        quantity = (
            self.entitled_quantity()
            if on >= action.record_day and knowledge_on >= action.record_day
            else None
        )
        statuses = ["PRICE_ONLY_PNL"]
        amount_known = (
            quantity is not None
            and on >= action.record_day
            and action.amount_verified
            and action.resolved_day is not None
            and on >= action.resolved_day
            and action.amount_known_on is not None
            and action.amount_known_on <= knowledge_on
            and action.gross_per_share is not None
            and bool(action.evidence_hashes)
        )
        gross = None
        if amount_known:
            assert quantity is not None and action.gross_per_share is not None
            gross = Decimal(quantity) * action.gross_per_share
        if gross is None:
            statuses.append("ENTITLEMENT_PENDING")
        else:
            statuses.append("DIVIDEND_RECEIVABLE_VERIFIED")
        paid = (
            gross is not None
            and action.actual_payment_day is not None
            and action.actual_payment_day <= on
            and action.payment_evidence_known_on is not None
            and action.payment_evidence_known_on <= knowledge_on
        )
        tax = (
            self.verified_dividend_tax
            if self.tax_known_on is not None and self.tax_known_on <= knowledge_on
            else None
        )
        if tax is None:
            statuses.append("TAX_TREATMENT_PENDING")
        if gross is not None and tax is not None and tax > gross:
            raise ValueError("TAX_EXCEEDS_GROSS_ENTITLEMENT")
        cash: Decimal | None = None
        if paid:
            statuses.append("CASH_PAYMENT_VERIFIED")
            cash = gross - tax if tax is not None and gross is not None else None
        complete = (
            paid
            and tax is not None
            and action.full_action_window_verified
            and self.price_path_verified
            and self.price_only_pnl is not None
            and self.price_pnl_as_of is not None
            and on >= self.price_pnl_as_of
        )
        total = None
        if complete:
            assert self.price_only_pnl is not None and gross is not None and tax is not None
            total = str(self.price_only_pnl + gross - tax)
        if complete:
            statuses.append("TOTAL_RETURN_VERIFIED")
        # A confirmed payment month cannot establish an exact day or an unpaid balance.
        month_passed = (
            action.issuer_paid_month is not None
            and action.issuer_paid_month_known_on is not None
            and action.issuer_paid_month_known_on <= knowledge_on
            and str(on)[:7] >= action.issuer_paid_month
        )
        receivable = ZERO if paid else None if month_passed else gross
        return {
            "version": "DF011_ENTITLEMENT_V1",
            "economic_on": str(on),
            "knowledge_on": str(knowledge_on),
            "modeled_execution": self.modeled_execution,
            "statuses": statuses,
            "entitled_quantity": quantity,
            "gross_entitlement": str(gross) if gross is not None else None,
            "unpaid_receivable": str(receivable) if receivable is not None else None,
            "net_dividend_cash_verified": str(cash) if cash is not None else None,
            "spendable_cash_increment": str(cash) if cash is not None else "0",
            "actual_dividend_tax": str(tax) if tax is not None else None,
            "actual_after_tax_total_pnl": total if not self.modeled_execution else None,
            "modeled_after_tax_total_pnl": total if self.modeled_execution else None,
            "total_return_verified": bool(complete),
            "d1_signal_inputs": self.decision_inputs(on),
            "actual_payment_day": str(action.actual_payment_day) if paid else None,
            "scheduled_payment_day_is_actual": False,
        }


def settle_t_plus_two(day: date, observed_settlement_days: tuple[date, ...]) -> date:
    """Explicit externally verified calendar only, never generated weekdays."""
    if tuple(sorted(set(observed_settlement_days))) != observed_settlement_days:
        raise ValueError("UNIQUE_SORTED_SETTLEMENT_CALENDAR_REQUIRED")
    if day not in observed_settlement_days:
        raise ValueError("TRADE_NOT_ON_VERIFIED_SESSION")
    offset = observed_settlement_days.index(day) + 2
    if offset >= len(observed_settlement_days):
        raise ValueError("SETTLEMENT_FOLLOWUP_MISSING")
    return observed_settlement_days[offset]
