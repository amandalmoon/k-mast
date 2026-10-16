from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from kmast.core.base import (
    Amount,
    Contract,
    Identifier,
    Nonnegative,
    Positive,
    Weight,
)
from kmast.core.enums import CostBasis, LedgerType, Policy

Horizon = Annotated[timedelta, Field(gt=timedelta(0))]
Revision = Annotated[int, Field(ge=0, strict=True)]
Quantity = Annotated[int, Field(ge=0, strict=True)]


class ReturnUnits(Contract):
    horizon: Horizon
    capital_basis: Literal["REFERENCE_NAV", "SLEEVE_NAV", "ACCOUNT_NAV"]
    capital_policy_id: Identifier
    valuation_calendar: Identifier
    currency: Literal["KRW"] = "KRW"
    cost_basis: CostBasis = CostBasis.GROSS
    cost_model_version: Identifier
    risk_basis: Literal["REFERENCE_NAV", "SLEEVE_NAV", "ACCOUNT_NAV"]
    ledger_type: LedgerType


class Forecast(Contract):
    units: ReturnUnits
    expected_return: Amount
    uncertainty: Nonnegative


def validate_optimizer_inputs(forecasts: tuple[Forecast, ...], risk_units: ReturnUnits) -> None:
    if not forecasts or risk_units.cost_basis != CostBasis.GROSS:
        raise ValueError("optimizer requires gross forecasts and risk estimates")
    for forecast in forecasts:
        if forecast.units != risk_units:
            raise ValueError("incompatible horizon/capital/cost/risk units")


class SignalIntent(Contract):
    intent_id: Identifier
    revision: Revision
    target_snapshot_id: Identifier
    strategy_id: Identifier
    model_version: Identifier
    config_hash: Identifier
    data_version: Identifier
    symbol: Identifier
    venue: Identifier
    session: Identifier
    decision_at: AwareDatetime
    available_at: AwareDatetime
    target_weight: Weight
    target_basis: Literal["SLEEVE_NAV_WEIGHT"] = "SLEEVE_NAV_WEIGHT"
    horizon: Horizon
    valid_until: AwareDatetime
    reason_code: Identifier
    forecast: Forecast | None = None
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def causal(self) -> Self:
        if self.available_at > self.decision_at or self.valid_until <= self.decision_at:
            raise ValueError("unavailable or expired intent")
        return self


class TargetSnapshot(Contract):
    """Full replacement; omitted symbols become zero, never patch the old snapshot."""

    strategy_id: Identifier
    snapshot_id: Identifier
    revision: Revision
    expected_symbols: tuple[Identifier, ...]
    intents: tuple[SignalIntent, ...]
    replacement: Literal["FULL_REPLACE"] = "FULL_REPLACE"

    @model_validator(mode="after")
    def atomic(self) -> Self:
        symbols = tuple(x.symbol for x in self.intents)
        if len(set(self.expected_symbols)) != len(self.expected_symbols):
            raise ValueError("duplicate manifest symbol")
        if len(set(symbols)) != len(symbols) or set(symbols) != set(self.expected_symbols):
            raise ValueError("incomplete or duplicate snapshot")
        if len({x.intent_id for x in self.intents}) != len(self.intents):
            raise ValueError("duplicate intent id")
        for intent in self.intents:
            if (intent.strategy_id, intent.target_snapshot_id, intent.revision) != (
                self.strategy_id,
                self.snapshot_id,
                self.revision,
            ):
                raise ValueError("mixed snapshot/revision/strategy")
        if sum((x.target_weight for x in self.intents), Decimal(0)) > 1:
            raise ValueError("sleeve weights exceed one")
        return self


class SnapshotStore:
    """Single-process contract prototype; persistent transactional store is KM-002."""

    def __init__(self) -> None:
        self._snapshots: dict[str, TargetSnapshot] = {}

    def current(self, strategy_id: str) -> TargetSnapshot | None:
        return self._snapshots.get(strategy_id)

    def replace(self, snapshot: TargetSnapshot, now: AwareDatetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware clock required")
        if any(x.decision_at > now or x.valid_until <= now for x in snapshot.intents):
            raise ValueError("snapshot not current")
        old = self.current(snapshot.strategy_id)
        if old == snapshot:
            return
        if old and (snapshot.revision <= old.revision or snapshot.snapshot_id == old.snapshot_id):
            raise ValueError("stale or conflicting replacement")
        self._snapshots[snapshot.strategy_id] = snapshot


class SleeveBudget(Contract):
    strategy_id: Identifier
    weight: Weight
    risk_budget: Weight | None = None
    capital_cap: Weight | None = None

    @model_validator(mode="after")
    def cap(self) -> Self:
        if self.capital_cap is not None and self.weight > self.capital_cap:
            raise ValueError("capital cap exceeded")
        return self


class CapitalBudget(Contract):
    budget_id: Identifier
    policy_id: Policy = Policy.PBASE_FIXED
    sleeves: tuple[SleeveBudget, ...] = ()
    approved_by: Identifier | None = None

    @model_validator(mode="after")
    def conserve(self) -> Self:
        if len({x.strategy_id for x in self.sleeves}) != len(self.sleeves):
            raise ValueError("duplicate sleeve budget")
        if sum((x.weight for x in self.sleeves), Decimal(0)) > 1:
            raise ValueError("capital budget exceeds NAV")
        if self.policy_id == Policy.PBASE_RISK and any(
            x.risk_budget is None or x.capital_cap is None for x in self.sleeves
        ):
            raise ValueError("risk baseline requires risk budgets and capital caps")
        if sum((x.risk_budget or Decimal(0) for x in self.sleeves), Decimal(0)) > 1:
            raise ValueError("risk budgets exceed one")
        return self

    @property
    def cash_residual(self) -> Decimal:
        return Decimal(1) - sum((x.weight for x in self.sleeves), Decimal(0))


class CashResidual(Contract):
    central_reserve: Weight
    sleeve_uninvested: tuple[tuple[Identifier, Weight], ...]

    @classmethod
    def from_targets(cls, budget: CapitalBudget, targets: tuple[TargetSnapshot, ...]) -> Self:
        by_strategy = {x.strategy_id: x for x in targets}
        if len(by_strategy) != len(targets) or set(by_strategy) != {
            x.strategy_id for x in budget.sleeves
        }:
            raise ValueError("budget/target sleeve mismatch")
        return cls(
            central_reserve=budget.cash_residual,
            sleeve_uninvested=tuple(
                (
                    s.strategy_id,
                    s.weight
                    * (
                        1
                        - sum(
                            (i.target_weight for i in by_strategy[s.strategy_id].intents),
                            Decimal(0),
                        )
                    ),
                )
                for s in budget.sleeves
            ),
        )


class StrategyTarget(Contract):
    strategy_id: Identifier
    symbol: Identifier
    target_qty: Quantity
    budget_id: Identifier
    revision: Revision


class PortfolioTarget(Contract):
    symbol: Identifier
    aggregate_target_qty: Quantity
    sleeve_targets: tuple[StrategyTarget, ...]
    snapshot_id: Identifier
    target_version: Identifier

    @model_validator(mode="after")
    def aggregate(self) -> Self:
        if any(x.symbol != self.symbol for x in self.sleeve_targets):
            raise ValueError("mixed symbol")
        if len({x.strategy_id for x in self.sleeve_targets}) != len(self.sleeve_targets):
            raise ValueError("duplicate sleeve target")
        if sum(x.target_qty for x in self.sleeve_targets) != self.aggregate_target_qty:
            raise ValueError("aggregate target mismatch")
        return self

    def explanatory_delta(self, current_qty: int) -> int:
        if current_qty < 0:
            raise ValueError("long-only quantity required")
        return self.aggregate_target_qty - current_qty


class RiskLimitSnapshot(Contract):
    snapshot_id: Identifier
    account_version: Identifier
    approved_by: Identifier | None = None
    expires_at: AwareDatetime
    stress_loss_limit: Nonnegative | None = None
    expected_shortfall_limit: Nonnegative | None = None


class RiskDecision(Contract):
    decision_id: Identifier
    target_version: Identifier
    max_qty: Quantity
    expires_at: AwareDatetime
    reasons: tuple[Identifier, ...]
    account_version: Identifier
    risk_snapshot: RiskLimitSnapshot
    hard_limits_passed: bool = False

    def require_contract_approval(
        self, now: AwareDatetime, account_version: str, target_version: str
    ) -> None:
        limits = self.risk_snapshot
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware clock required")
        if (
            not limits.approved_by
            or limits.stress_loss_limit is None
            or limits.expected_shortfall_limit is None
            or not self.hard_limits_passed
            or now >= min(self.expires_at, limits.expires_at)
            or account_version != self.account_version
            or account_version != limits.account_version
            or target_version != self.target_version
        ):
            raise PermissionError("risk contract approval denied")


class PortfolioDecision(Contract):
    decision_id: Identifier
    as_of: AwareDatetime
    objective_id: Literal["PROFIT_FIRST_RISK_CONSTRAINED_V12"] = "PROFIT_FIRST_RISK_CONSTRAINED_V12"
    policy_id: Policy
    target_version: Identifier
    expected_gross_increment_krw: Amount
    incremental_execution_cost_krw: Nonnegative
    uncertainty_buffer_krw: Nonnegative
    cost_model_id: Identifier
    risk_snapshot_id: Identifier
    benchmark_id: Identifier
    risk_check: Literal["PASS", "FAIL", "UNKNOWN"]
    action: Literal["HOLD_TARGET", "CHANGE_TARGET", "RISK_REDUCTION"]
    reason: Identifier

    @property
    def expected_net_increment(self) -> Decimal:
        return self.expected_gross_increment_krw - self.incremental_execution_cost_krw

    @model_validator(mode="after")
    def economic_filter(self) -> Self:
        if self.action == "CHANGE_TARGET" and (
            self.risk_check != "PASS" or self.expected_net_increment <= self.uncertainty_buffer_krw
        ):
            raise ValueError("hold target: insufficient improvement or hard risk failure")
        # RISK_REDUCTION expresses a separate request, never an order permission.
        return self


class PerformanceBridge(Contract):
    account_snapshot_id: Identifier
    ledger_type: Literal[LedgerType.ACCOUNT] = LedgerType.ACCOUNT
    interval_start: AwareDatetime
    interval_end: AwareDatetime
    starting_capital_krw: Positive
    ending_nav_krw: Nonnegative
    gross_market_pnl: Amount
    cash_interest: Amount = Decimal(0)
    dividend_income: Amount = Decimal(0)
    explicit_fees_and_taxes: Nonnegative = Decimal(0)
    recurring_operating_costs: Nonnegative = Decimal(0)
    external_net_flow: Amount = Decimal(0)
    internal_net_transfer: Literal[0] = 0
    actual_exec_effect_diagnostic: Amount = Decimal(0)
    unfilled_opportunity_cost_diagnostic: Amount = Decimal(0)
    execution_effect_basis: Literal["ALREADY_IN_ACTUAL_FILL_PRICES"] = (
        "ALREADY_IN_ACTUAL_FILL_PRICES"
    )
    currency: Literal["KRW"] = "KRW"

    @property
    def net_operating_pnl_krw(self) -> Decimal:
        return (
            self.gross_market_pnl
            + self.cash_interest
            + self.dividend_income
            - self.explicit_fees_and_taxes
            - self.recurring_operating_costs
        )

    @model_validator(mode="after")
    def reconciliation(self) -> Self:
        if self.interval_end <= self.interval_start:
            raise ValueError("invalid valuation interval")
        if (
            self.ending_nav_krw - self.starting_capital_krw - self.external_net_flow
            != self.net_operating_pnl_krw
        ):
            raise ValueError("NAV/PnL reconciliation failed")
        return self
