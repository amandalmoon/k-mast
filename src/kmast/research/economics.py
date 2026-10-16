from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from kmast.core.base import Contract, Identifier, Nonnegative, Weight
from kmast.core.contracts import PerformanceBridge
from kmast.portfolio.data_gate import EvaluationScope, compare_scopes


class CostScenario(Contract):
    identity: Identifier
    effective_from: date
    effective_to: date
    provenance: Literal["CONTRACT", "OBSERVED", "RESEARCH_ESTIMATE", "UNVERIFIED"]
    evidence_ref: Identifier | None = None
    buy_fee_bps: Nonnegative | None = None
    sell_fee_bps: Nonnegative | None = None
    sell_tax_bps: Nonnegative | None = None
    embedded_spread_impact_bps: Nonnegative | None = None
    delay_seconds: Nonnegative | None = None
    unfilled_fraction: Weight | None = None
    liquidity_fraction: Weight | None = None
    capital_multiplier: Nonnegative = Decimal(1)
    recurring_account_opex: Nonnegative | None = None
    recurring_external_opex: Nonnegative | None = None

    def verified_for(self, start: date, end: date) -> bool:
        return (
            self.provenance in {"CONTRACT", "OBSERVED"}
            and bool(self.evidence_ref)
            and self.effective_from <= start <= end <= self.effective_to
            and self.capital_multiplier > 0
            and all(
                getattr(self, key) is not None
                for key in (
                    "buy_fee_bps",
                    "sell_fee_bps",
                    "sell_tax_bps",
                    "embedded_spread_impact_bps",
                    "delay_seconds",
                    "unfilled_fraction",
                    "liquidity_fraction",
                    "recurring_account_opex",
                    "recurring_external_opex",
                )
            )
        )


class EconomicResult(Contract):
    metric: Literal["NET_OPERATING_PNL_KRW"] = "NET_OPERATING_PNL_KRW"
    calculation_mode: Literal["SYNTHETIC_FUNCTIONAL", "SIMULATED_REAL_MARKET_DATA"]
    ledger_type: Literal["ACCOUNT"] = "ACCOUNT"
    provenance_refs: tuple[Identifier, ...] = Field(min_length=1)
    account_bridge: PerformanceBridge
    external_operating_cost: Nonnegative

    @property
    def net_operating_pnl_krw(self) -> Decimal:
        return self.account_bridge.net_operating_pnl_krw - self.external_operating_cost


def cash_excess(
    candidate: EconomicResult,
    cash: EconomicResult,
    candidate_scope: EvaluationScope,
    cash_scope: EvaluationScope,
) -> Decimal:
    compare_scopes(candidate_scope, cash_scope)
    if (
        candidate.calculation_mode != cash.calculation_mode
        or candidate.account_bridge.interval_start != cash.account_bridge.interval_start
        or candidate.account_bridge.interval_end != cash.account_bridge.interval_end
        or candidate.account_bridge.starting_capital_krw != cash.account_bridge.starting_capital_krw
        or candidate_scope.capital_krw != candidate.account_bridge.starting_capital_krw
        or candidate_scope.start != candidate.account_bridge.interval_start
        or candidate_scope.end != candidate.account_bridge.interval_end
    ):
        raise ValueError("economic comparison interval/capital/provenance mismatch")
    return candidate.net_operating_pnl_krw - cash.net_operating_pnl_krw


def execution_claim(resolution: str, claim: str) -> None:
    if resolution == "DAILY" and claim != "ASSUMED_SCENARIO":
        raise PermissionError("daily bars cannot establish exact executable fills")


def economic_acceptance(
    data_ready: bool,
    costs_verified: bool,
    confirmatory_completed: bool,
    multiple_strategy_panel: bool,
) -> dict[str, str]:
    return {
        "G2": (
            "NOT_EXECUTED"
            if not data_ready
            else "HOLD_COSTS"
            if not costs_verified
            else "HOLD_CONFIRMATORY"
            if not confirmatory_completed
            else "HOLD_INDEPENDENT_REVIEW"
        ),
        "G3": "HOLD_MULTISTRATEGY_PANEL"
        if not multiple_strategy_panel
        else "HOLD_INCREMENTAL_VALUE",
        "economic_status": "ECON_NOT_EXECUTED" if not data_ready else "ECON_HOLD",
        "live_status": "LIVE_NOT_APPROVED",
    }
