from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime

from kmast.core.base import Contract, Identifier, Nonnegative, Weight
from kmast.core.contracts import PortfolioDecision


class RebalanceInputs(Contract):
    identity: Identifier
    at: AwareDatetime
    account_snapshot: Identifier
    target_version: Identifier
    policy: Literal["PBASE_FIXED", "PBASE_RISK"]
    hold_expected_gross_krw: Decimal
    new_expected_gross_krw: Decimal
    delay_decay_fraction: Weight
    incremental_execution_cost: Nonnegative
    uncertainty_buffer: Nonnegative
    cost_version: Identifier
    hard_risk_passed: bool
    forced_reduction: bool = False
    account_and_quotes_fresh: bool
    execution_feasible: bool
    scope: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"


def assess(inputs: RebalanceInputs) -> PortfolioDecision:
    increment = (inputs.new_expected_gross_krw - inputs.hold_expected_gross_krw) * (
        1 - inputs.delay_decay_fraction
    )
    if not increment.is_finite():
        raise ValueError("nonfinite rebalance expectation")
    executable = (
        inputs.account_and_quotes_fresh and inputs.execution_feasible and inputs.hard_risk_passed
    )
    if inputs.forced_reduction:
        action = "RISK_REDUCTION"
        reason = (
            "FORCED_REDUCTION_REQUEST" if executable else "REDUCTION_REQUIRED_EXECUTION_BLOCKED"
        )
    elif executable and increment > inputs.incremental_execution_cost + inputs.uncertainty_buffer:
        action, reason = "CHANGE_TARGET", "INCREMENT_EXCEEDS_COST_AND_UNCERTAINTY"
    else:
        action = "HOLD_TARGET"
        reason = "STALE_OR_RISK_OR_EXECUTION_BLOCK" if not executable else "NO_ECONOMIC_INCREMENT"
    return PortfolioDecision(
        decision_id=inputs.identity,
        as_of=inputs.at,
        policy_id=inputs.policy,
        target_version=inputs.target_version,
        expected_gross_increment_krw=increment,
        incremental_execution_cost_krw=inputs.incremental_execution_cost,
        uncertainty_buffer_krw=inputs.uncertainty_buffer,
        cost_model_id=inputs.cost_version,
        risk_snapshot_id=inputs.account_snapshot,
        benchmark_id="HOLD_CURRENT_TARGET",
        risk_check="PASS" if executable else "FAIL",
        action=action,
        reason=reason,
    )
