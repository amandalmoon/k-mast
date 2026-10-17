"""Pre-registered DF-003 counterfactuals around an unchanged V3 reference kernel.

No original globals are patched. A private function namespace replaces only the
decision callback; sizing, costs, expiry, cash and matching bytecode stay frozen.
These research intents are DATA_BLOCKED and never enter an OMS.
"""

from datetime import timedelta
from decimal import Decimal as D
from types import FunctionType
from typing import Any

from kmast.alpha.models import AlphaConfig, AlphaResult, Context, PositionView
from kmast.alpha.rules import features
from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.data.models import Observation
from kmast.data.normalization import content_hash
from kmast.research.exploratory import SPECIAL_NO_EXECUTION, ExplorationPolicy, candidate_a, replay


class HoldingController:
    def __init__(self, candidate: str):
        if candidate not in {"A0", "A1", "A2", "A3", "T0", "T1", "T2", "T3"}:
            raise ValueError("unregistered research candidate")
        self.candidate = candidate
        self.rule = int(candidate[-1])
        self.trend_entry = candidate.startswith("T")
        self.completed = 0
        self.peak: D | None = None
        self.trace: list[dict[str, Any]] = []

    def __call__(
        self,
        context: Context,
        symbol: str,
        config: AlphaConfig,
        position: PositionView | None,
        revision: int,
    ) -> AlphaResult:
        bars = context.bars
        if config != AlphaConfig(strategy="A") or len(bars) != 21:
            raise ValueError("frozen configuration and 21 completed bars required")
        if any(
            b.end > context.now or b.available_at > context.now for b in bars + context.benchmark
        ):
            raise ValueError("future observations cannot enter holding rules")
        if self.trace and context.now.isoformat() <= self.trace[-1]["decision_at"]:
            raise ValueError("decision clock must advance")
        last = bars[-1]
        eligible = (
            last.end.date() not in SPECIAL_NO_EXECUTION and last.volume > 0 and last.turnover > 0
        )
        if position:
            self.completed += int(eligible)
            self.peak = max(self.peak or position.entry_price, position.entry_price, last.close)
        else:
            self.completed, self.peak = 0, None
        if self.candidate == "A0":
            result = candidate_a(context, symbol, config, position, revision)
        else:
            guarded = position
            if position and self.rule:
                # Suppress only the calendar deadline inside frozen candidate_a.
                # Observed-session limits below govern these research exits instead.
                guarded = PositionView.model_validate(
                    position.model_dump() | {"exit_deadline": context.now + timedelta(days=1)}
                )
            result = candidate_a(context, symbol, config, guarded, revision)
            intent = result.snapshot.intents[0]
            weight, reason = intent.target_weight, result.reasons[0][1]
            trigger, feature_weight, _, evidence = features(context, config, symbol)
            prior_mean = sum((b.close for b in bars[:-1]), D(0)) / config.lookback
            indices = {b.end: b for b in context.benchmark}
            rs = last.close / bars[0].close - indices[last.end].close / indices[bars[0].end].close
            if not position and self.trend_entry:
                trigger = (
                    last.close >= prior_mean
                    and rs >= config.min_relative_strength
                    and min(b.turnover for b in bars) >= config.min_turnover
                )
                weight = feature_weight if trigger else D(0)
                reason = "CONTROL_TREND_ENTRY" if trigger else "CONTROL_ENTRY_FILTERED"
            if position and self.rule:
                basic_stop = last.close <= position.entry_price * (1 - config.stop_fraction)
                limit = 5 if self.rule == 1 else 20
                atr = (
                    sum(
                        (
                            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                            for a, b in zip(bars[:-1], bars[1:], strict=True)
                        ),
                        D(0),
                    )
                    / 20
                )
                if basic_stop:
                    weight, reason = D(0), "BASIC_STOP_EXIT"
                elif self.completed >= limit:
                    weight, reason = D(0), f"OBSERVED_SESSION_{limit}_EXIT"
                elif self.rule == 3 and self.peak is not None and last.close <= self.peak - 3 * atr:
                    weight, reason = D(0), "ATR20_X3_EXIT"
            identity = content_hash(
                [
                    intent.intent_id,
                    self.candidate,
                    self.completed,
                    str(self.peak),
                    "DF003_PROTOCOL_V1",
                ]
            )
            updated = SignalIntent.model_validate(
                intent.model_dump()
                | dict(
                    intent_id=identity,
                    target_snapshot_id=identity,
                    target_weight=weight,
                    model_version="DF003-" + self.candidate,
                    reason_code=reason,
                    config_hash=content_hash(
                        [config.model_dump(mode="json"), self.candidate, "DF003_PROTOCOL_V1"]
                    ),
                    evidence_refs=evidence,
                )
            )
            result = AlphaResult.model_validate(
                result.model_dump()
                | dict(
                    snapshot=TargetSnapshot(
                        strategy_id="A",
                        snapshot_id=identity,
                        revision=revision,
                        expected_symbols=(symbol,),
                        intents=(updated,),
                    ),
                    reasons=((symbol, reason),),
                )
            )
        atr = (
            sum(
                (
                    max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                    for a, b in zip(bars[:-1], bars[1:], strict=True)
                ),
                D(0),
            )
            / 20
        )
        self.trace.append(
            dict(
                decision_at=context.now.isoformat(),
                input_last_date=str(last.end.date()),
                candidate=self.candidate,
                completed_eligible_sessions=self.completed,
                eligible_previous_session=eligible,
                peak_close=str(self.peak) if self.peak else None,
                atr20=str(atr),
                trailing_level=str(self.peak - 3 * atr) if self.peak else None,
                reason=result.reasons[0][1],
            )
        )
        return result


def hypothesis_replay(
    rows: tuple[Observation, ...],
    index: tuple[Observation, ...],
    policy: ExplorationPolicy,
    candidate: str,
) -> dict[str, Any]:
    controller = HoldingController(candidate)
    # Reuse exact kernel bytecode with a per-run callback, not monkeypatches or
    # a second implementation of the ledger/execution model.
    namespace = dict(replay.__globals__) | {"candidate_a": controller}
    kernel = FunctionType(replay.__code__, namespace)
    result: dict[str, Any] = kernel(rows, index, policy, "ALPHA_A")
    if candidate != "A0":
        for signal, trace in zip(result["signal_log"], controller.trace, strict=True):
            signal["original_calendar_deadline_due"] = signal["filters"]["deadline_due"]
            if controller.rule:
                # Attribution must read the registered exit reason, not the
                # template's P5D calendar deadline used by the unchanged kernel.
                signal["filters"]["deadline_due"] = False
            signal["holding_rule_trace"] = trace
    return result


def reduction_status(
    target_zero: bool, quantity: int, pending: int, market_state: str, forced: bool = False
) -> dict[str, Any]:
    if quantity < 0 or pending < 0:
        raise ValueError("negative position or pending quantity")
    if market_state not in {"UNKNOWN", "HALTED", "MODEL_ONLY", "OBSERVED_EXECUTABLE"}:
        raise ValueError("unknown market-state label")
    unresolved = quantity > 0 and (target_zero or forced)
    return dict(
        status="RISK_REDUCTION_HOLD" if unresolved else "NO_UNFULFILLED_REDUCTION",
        remaining_quantity=quantity,
        pending_quantity=pending,
        forced=forced,
        market_state=market_state,
        actual_executable=(
            True
            if market_state == "OBSERVED_EXECUTABLE"
            else False
            if market_state == "HALTED"
            else None
        ),
        automatic_residual_fill=False,
        actual_order_calls=0,
    )
