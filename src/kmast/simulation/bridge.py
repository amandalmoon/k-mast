from datetime import datetime
from decimal import Decimal
from typing import cast

from kmast.alpha.models import AlphaResult
from kmast.core.contracts import CapitalBudget
from kmast.execution.engine import MockExecution
from kmast.execution.models import MockRiskDecision, MockRiskPolicy, Sleeve
from kmast.execution.portfolio import aggregate


def plan_mock(
    engine: MockExecution,
    results: tuple[AlphaResult, ...],
    budget: CapitalBudget,
    policy: MockRiskPolicy,
    identity: str,
    *,
    synthetic_expected_gross: Decimal,
    execution_cost: Decimal,
    uncertainty: Decimal,
    fee_buffer: Decimal,
) -> MockRiskDecision:
    now = engine.clock.now()
    if any(result.earliest_execution_at > now for result in results):
        raise PermissionError("alpha not executable before next eligible session")
    if any(
        result.execution_window_end is not None and now >= result.execution_window_end
        for result in results
    ):
        raise PermissionError("alpha execution session is closed")
    deadlines: list[tuple[Sleeve, datetime]] = []
    for result in results:
        active = {i.symbol for i in result.snapshot.intents if i.target_weight > 0}
        values = [at for symbol, at in result.exit_deadlines if symbol in active]
        if values:
            deadlines.append((cast(Sleeve, result.snapshot.strategy_id), min(values)))
    batch = aggregate(
        engine.state,
        budget,
        tuple(r.snapshot for r in results),
        now,
        identity,
        holding_deadlines=tuple(deadlines),
    )
    verdict = engine.decide(
        identity + "-risk",
        batch,
        policy,
        fee_buffer=fee_buffer,
        expected_gross=synthetic_expected_gross,
        execution_cost=execution_cost,
        uncertainty=uncertainty,
    )
    if (
        verdict.status in {"ALLOW", "REDUCE"}
        and engine.state.portfolio_decisions[-1].action != "HOLD_TARGET"
    ):
        engine.plan(identity + "-plan", verdict, fee_buffer)
    return verdict
