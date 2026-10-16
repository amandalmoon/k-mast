from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field

from kmast.core.base import Contract, Identifier, Positive, Weight
from kmast.core.contracts import CapitalBudget, ReturnUnits, SleeveBudget
from kmast.data.normalization import content_hash


class ReturnSeries(Contract):
    strategy: Literal["A", "B", "C", "D"]
    units: ReturnUnits
    at: tuple[AwareDatetime, ...]
    known_at: tuple[AwareDatetime, ...]
    returns: tuple[Decimal, ...]
    origin: Literal["SYNTHETIC", "REAL_VERIFIED"]
    evidence_ref: Identifier


class RiskSettings(Contract):
    version: Identifier
    min_samples: int = Field(default=30, ge=3)
    volatility_floor: Positive = Decimal(".01")
    reserve_weight: Weight = Decimal(".1")
    caps: tuple[tuple[Identifier, Weight], ...]
    risk_budgets: tuple[tuple[Identifier, Weight], ...]
    scope: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"


class AllocationProposal(Contract):
    identity: Identifier
    policy: Literal["PBASE_FIXED", "PBASE_RISK"]
    status: Literal["PROPOSAL_ONLY", "HOLD"]
    reasons: tuple[Identifier, ...]
    weights: tuple[tuple[Identifier, Weight], ...] = ()
    cash_weight: Weight = Decimal(1)
    covariance: tuple[tuple[Decimal, ...], ...] = ()
    variance: Decimal | None = None
    volatility: Decimal | None = None
    risk_contributions: tuple[tuple[Identifier, Decimal], ...] = ()
    input_hash: Identifier
    scope: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"
    live_approved: Literal[False] = False


def psd(matrix: tuple[tuple[Decimal, ...], ...]) -> None:
    count = len(matrix)
    if not count or any(len(row) != count for row in matrix):
        raise ValueError("covariance matrix incomplete")
    if any(not value.is_finite() for row in matrix for value in row):
        raise ValueError("nonfinite covariance")
    if any(matrix[i][j] != matrix[j][i] for i in range(count) for j in range(count)):
        raise ValueError("asymmetric covariance")
    if any(matrix[i][i] < 0 for i in range(count)):
        raise ValueError("negative covariance diagonal")
    lower = [[Decimal(0) for _ in matrix] for _ in matrix]
    diagonal: list[Decimal] = []
    tolerance = Decimal("1e-24")
    for i in range(count):
        lower[i][i] = Decimal(1)
        pivot = matrix[i][i] - sum((lower[i][k] ** 2 * diagonal[k] for k in range(i)), Decimal(0))
        if pivot < -tolerance:
            raise ValueError("covariance not positive semidefinite")
        diagonal.append(max(pivot, Decimal(0)))
        for j in range(i + 1, count):
            residual = matrix[j][i] - sum(
                (lower[j][k] * lower[i][k] * diagonal[k] for k in range(i)), Decimal(0)
            )
            if diagonal[i] == 0:
                if abs(residual) > tolerance:
                    raise ValueError("singular covariance inconsistent")
            else:
                lower[j][i] = residual / diagonal[i]


def variance_and_rc(
    weights: tuple[Decimal, ...], matrix: tuple[tuple[Decimal, ...], ...]
) -> tuple[Decimal, Decimal, tuple[Decimal, ...]]:
    psd(matrix)
    if (
        len(weights) != len(matrix)
        or any(not w.is_finite() or w < 0 for w in weights)
        or sum(weights) > 1
    ):
        raise ValueError("risk weights invalid")
    marginal = tuple(
        sum((cov * weight for cov, weight in zip(row, weights, strict=True)), Decimal(0))
        for row in matrix
    )
    variance = sum((w * m for w, m in zip(weights, marginal, strict=True)), Decimal(0))
    if variance < -Decimal("1e-24"):
        raise ValueError("negative portfolio variance")
    variance = max(variance, Decimal(0))
    vol = variance.sqrt()
    rc = tuple(w * m / vol if vol else Decimal(0) for w, m in zip(weights, marginal, strict=True))
    return variance, vol, rc


def risk_candidate(
    series: tuple[ReturnSeries, ...],
    settings: RiskSettings,
    as_of: datetime,
    covariance: tuple[tuple[Decimal, ...], ...] | None = None,
) -> AllocationProposal:
    fingerprint = content_hash(
        [s.model_dump(mode="json") for s in series]
        + [
            settings.model_dump(mode="json"),
            as_of.isoformat(),
            [[str(v) for v in row] for row in covariance] if covariance is not None else None,
        ]
    )

    def hold(reason: str) -> AllocationProposal:
        return AllocationProposal(
            identity=fingerprint,
            policy="PBASE_RISK",
            status="HOLD",
            reasons=(reason,),
            input_hash=fingerprint,
        )

    if not series or len({s.strategy for s in series}) != len(series):
        return hold("NO_UNAMBIGUOUS_RETURN_PANEL")
    count = len(series[0].returns)
    if count < settings.min_samples:
        return hold("INSUFFICIENT_SAMPLES")
    for item in series:
        if (
            item.units != series[0].units
            or item.units.ledger_type != "REFERENCE"
            or item.units.capital_basis != "REFERENCE_NAV"
            or item.units.risk_basis != "REFERENCE_NAV"
        ):
            return hold("H_NAV_COST_CALENDAR_UNITS_MISMATCH")
        if (
            len(item.returns) != count
            or len(item.at) != count
            or len(item.known_at) != count
            or item.at != series[0].at
            or tuple(sorted(set(item.at))) != item.at
            or any(
                t > as_of or k > as_of or k < t for t, k in zip(item.at, item.known_at, strict=True)
            )
            or any(not r.is_finite() or r < -1 for r in item.returns)
        ):
            return hold("PANEL_ALIGNMENT_AVAILABILITY_OR_RETURN_INVALID")
    if len({s.origin for s in series}) != 1:
        return hold("MIXED_REAL_SYNTHETIC_PANEL")
    ids = {s.strategy for s in series}
    caps, budgets = dict(settings.caps), dict(settings.risk_budgets)
    if (
        len(caps) != len(settings.caps)
        or len(budgets) != len(settings.risk_budgets)
        or set(caps) != ids
        or set(budgets) != ids
    ):
        return hold("CAP_OR_RISK_BUDGET_IDENTITY_MISMATCH")
    if sum(budgets.values()) <= 0 or sum(budgets.values()) > 1:
        return hold("RISK_BUDGET_SUM_INVALID")
    if covariance is None:
        means = [sum(s.returns, Decimal(0)) / count for s in series]
        covariance = tuple(
            tuple(
                sum(
                    (
                        (x - means[i]) * (y - means[j])
                        for x, y in zip(a.returns, b.returns, strict=True)
                    ),
                    Decimal(0),
                )
                / (count - 1)
                for j, b in enumerate(series)
            )
            for i, a in enumerate(series)
        )
    try:
        psd(covariance)
    except ValueError:
        return hold("COVARIANCE_INVALID")
    if len(covariance) != len(series):
        return hold("COVARIANCE_DIMENSION_MISMATCH")
    if all(covariance[i][i] <= 0 for i in range(len(series))):
        return hold("ZERO_VARIANCE_NO_RISK_INFORMATION")
    inverse = [
        budgets[s.strategy] / max(covariance[i][i].sqrt(), settings.volatility_floor)
        for i, s in enumerate(series)
    ]
    total = sum(inverse)
    weights = tuple(
        min(caps[s.strategy], (1 - settings.reserve_weight) * raw / total)
        for s, raw in zip(series, inverse, strict=True)
    )
    # No redistribution of capped remainder: retain it as cash.
    variance, vol, rc = variance_and_rc(weights, covariance)
    return AllocationProposal(
        identity=fingerprint,
        policy="PBASE_RISK",
        status="PROPOSAL_ONLY",
        reasons=("FLOORED_CAPPED_INVERSE_VOL_NOT_OPTIMIZED_RISK_PARITY",),
        weights=tuple((s.strategy, w) for s, w in zip(series, weights, strict=True)),
        cash_weight=1 - sum(weights),
        covariance=covariance,
        variance=variance,
        volatility=vol,
        risk_contributions=tuple((s.strategy, c) for s, c in zip(series, rc, strict=True)),
        input_hash=fingerprint,
    )


def freeze_mock_fixed(proposal: AllocationProposal, approved_by: str) -> CapitalBudget:
    if proposal.status != "PROPOSAL_ONLY" or not approved_by.startswith("SYNTHETIC_"):
        raise PermissionError("explicit synthetic-only freeze required")
    return CapitalBudget(
        budget_id="RISK_CANDIDATE_FIXED_" + proposal.identity,
        approved_by=approved_by,
        sleeves=tuple(SleeveBudget(strategy_id=s, weight=w) for s, w in proposal.weights),
    )
