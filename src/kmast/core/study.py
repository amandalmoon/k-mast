from decimal import Decimal
from typing import Literal

from kmast.core.base import Contract, Identifier, Nonnegative, Positive, Weight
from kmast.core.contracts import Horizon
from kmast.core.enums import CostBasis, Policy


class StudyContract(Contract):
    objective_id: Literal["PROFIT_FIRST_RISK_CONSTRAINED_V12"] = "PROFIT_FIRST_RISK_CONSTRAINED_V12"
    primary_metric: Literal["NET_OPERATING_PNL_KRW"] = "NET_OPERATING_PNL_KRW"
    baseline_policy_id: Policy | None = None
    capital_scenarios: tuple[Positive, ...] | None = None
    valuation_calendar: Identifier | None = None
    common_horizon: Horizon | None = None
    cost_basis: CostBasis = CostBasis.GROSS
    fixed_cost_schedule_id: Identifier | None = None
    fold_manifest_id: Identifier | None = None
    label_maturity_policy_id: Identifier | None = None
    trial_registry_id: Identifier | None = None
    dependence_test_method: Identifier | None = None
    confidence_level: Weight | None = None
    minimum_economic_improvement: Nonnegative | None = None
    stress_loss_limit: Nonnegative | None = None
    expected_shortfall_limit: Nonnegative | None = None
    capacity_acceptance_policy: Identifier | None = None
    net_operating_profit_definition: Literal["V12_ACCOUNT_LEDGER_SINGLE_COST"] = (
        "V12_ACCOUNT_LEDGER_SINGLE_COST"
    )
    freeze_approved_by: Identifier | None = None
    optimizer_approved: Literal[False] = False
    live_approved: Literal[False] = False

    def missing_economic_fields(self) -> tuple[str, ...]:
        fields = (
            "baseline_policy_id",
            "capital_scenarios",
            "valuation_calendar",
            "common_horizon",
            "fixed_cost_schedule_id",
            "fold_manifest_id",
            "label_maturity_policy_id",
            "trial_registry_id",
            "dependence_test_method",
            "confidence_level",
            "minimum_economic_improvement",
            "stress_loss_limit",
            "expected_shortfall_limit",
            "capacity_acceptance_policy",
            "freeze_approved_by",
        )
        return tuple(
            name for name in fields if getattr(self, name) is None or getattr(self, name) == ()
        )

    def g3_status(self) -> Literal["HOLD", "NOT_IMPLEMENTED"]:
        if (
            self.missing_economic_fields()
            or self.cost_basis != CostBasis.GROSS
            or self.confidence_level in (Decimal(0), Decimal(1))
        ):
            return "HOLD"
        # Complete settings are not empirical OOS evidence. No PASS path in KM-000.
        return "NOT_IMPLEMENTED"
