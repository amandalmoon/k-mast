from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from kmast.core.base import Contract
from kmast.core.clock import Clock
from kmast.core.contracts import PerformanceBridge, PortfolioDecision
from kmast.execution.events import DecisionRecorded, Event, Plan, Reconcile
from kmast.execution.models import (
    Cash,
    ExecutionState,
    MockRiskDecision,
    MockRiskPolicy,
    Money,
    TargetBatch,
)
from kmast.execution.readers import BrokerAccountReader, BrokerFillReader
from kmast.execution.risk import evaluate
from kmast.execution.store import Journal


class ProjectPerformance(Contract):
    account_bridge: PerformanceBridge
    externally_paid_operating_costs: Cash
    net_operating_pnl_krw: Money
    account_nav_krw: Cash
    valuation_status: str


class ReferenceSleeve(Contract):
    """Independent synthetic comparison NAV; never posted to the account or attribution."""

    sleeve_id: str
    fixed_capital_krw: Cash
    reference_nav_krw: Cash
    ledger_type: Literal["REFERENCE"] = "REFERENCE"


class MockExecution:
    def __init__(self, path: Path, initial: ExecutionState, clock: Clock) -> None:
        self.journal = Journal(path, initial)
        self.clock = clock
        self._runtime_reconciled = False

    @property
    def state(self) -> ExecutionState:
        return self.journal.state

    @property
    def ready(self) -> bool:
        return self._runtime_reconciled and self.state.reconciled

    def apply(self, event: Event) -> ExecutionState:
        if event.at > self.clock.now():
            raise ValueError("future event not available to this clock")
        if isinstance(event, (Plan, DecisionRecorded)) and not self.ready:
            raise PermissionError("startup/reconciliation lock; mock planning disabled")
        state = self.journal.commit(event)
        if isinstance(event, Reconcile):
            self._runtime_reconciled = state.reconciled
        return state

    def reconcile(
        self, event_id: str, account: BrokerAccountReader, fills: BrokerFillReader | None = None
    ) -> ExecutionState:
        return self.apply(
            Reconcile(
                event_id=event_id,
                at=self.clock.now(),
                snapshot=account.snapshot(),
                discovered_fills=fills.fills() if fills else (),
            )
        )

    def decide(
        self,
        event_id: str,
        batch: TargetBatch,
        policy: MockRiskPolicy,
        *,
        fee_buffer: Decimal = Decimal(0),
        expected_gross: Decimal = Decimal(0),
        execution_cost: Decimal = Decimal(0),
        uncertainty: Decimal = Decimal(0),
        reduction: bool = False,
    ) -> MockRiskDecision:
        now = self.clock.now()
        verdict = evaluate(
            self.state, batch, policy, now, fee_buffer=fee_buffer, reduction=reduction
        )
        action = (
            "RISK_REDUCTION"
            if reduction
            else (
                "CHANGE_TARGET"
                if verdict.status == "ALLOW" and expected_gross > execution_cost + uncertainty
                else "HOLD_TARGET"
            )
        )
        portfolio = PortfolioDecision(
            decision_id=verdict.decision_id,
            as_of=now,
            policy_id="PBASE_FIXED",
            target_version=batch.version,
            expected_gross_increment_krw=expected_gross,
            incremental_execution_cost_krw=execution_cost,
            uncertainty_buffer_krw=uncertainty,
            cost_model_id="MOCK_BUFFER:" + str(fee_buffer),
            risk_snapshot_id=verdict.account_version,
            benchmark_id="HOLD_CURRENT_TARGET",
            risk_check="PASS" if verdict.status in {"ALLOW", "REDUCE"} else "FAIL",
            action=action,
            reason=";".join(verdict.reasons),
        )
        self.apply(
            DecisionRecorded(
                event_id=event_id, at=now, batch=batch, decision=verdict, portfolio=portfolio
            )
        )
        return verdict

    def plan(
        self, event_id: str, decision: MockRiskDecision, fee_buffer: Decimal = Decimal(0)
    ) -> ExecutionState:
        return self.apply(
            Plan(
                event_id=event_id,
                at=self.clock.now(),
                decision_id=decision.decision_id,
                fee_buffer_per_order=fee_buffer,
            )
        )

    def performance(
        self, interval_start: datetime, starting_nav: Decimal, opening: ExecutionState | None = None
    ) -> ProjectPerformance:
        state = self.state
        before = opening or self.journal.initial
        nav = state.account.nav(state.quotes)
        status = state.valuation_status(self.clock.now(), timedelta(seconds=30))
        bridge = PerformanceBridge(
            account_snapshot_id=state.account_version,
            interval_start=interval_start,
            interval_end=self.clock.now(),
            starting_capital_krw=starting_nav,
            ending_nav_krw=nav,
            gross_market_pnl=state.account.gross_pnl(state.quotes)
            - before.account.gross_pnl(before.quotes),
            cash_interest=state.account.interest - before.account.interest,
            dividend_income=state.account.dividends - before.account.dividends,
            explicit_fees_and_taxes=state.account.fees_and_taxes - before.account.fees_and_taxes,
            recurring_operating_costs=state.account.account_opex - before.account.account_opex,
            external_net_flow=state.account.capital_flows - before.account.capital_flows,
        )
        costs = state.external_opex - before.external_opex
        return ProjectPerformance(
            account_bridge=bridge,
            externally_paid_operating_costs=costs,
            net_operating_pnl_krw=bridge.net_operating_pnl_krw - costs,
            account_nav_krw=nav,
            valuation_status=status,
        )

    def close(self) -> None:
        self.journal.close()

    def __enter__(self) -> "MockExecution":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
