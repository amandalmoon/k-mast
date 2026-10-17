"""DF005 declared panel eligibility, frozen-candidate replay and descriptive risk.

No broker/network/OMS imports. Special-calendar names live only in new function
namespaces; the original kernel/controller modules remain unchanged.
"""

from datetime import date
from decimal import Decimal as D
from types import FunctionType
from typing import Any

from kmast.data.models import Observation
from kmast.research.exploratory import SPECIAL_NO_EXECUTION, ExplorationPolicy, replay
from kmast.research.holding_analysis import analyze_holding
from kmast.research.hypotheses import HoldingController, hypothesis_replay
from kmast.research.panel_attribution import attribute

SCENARIOS = {"BASE": (3, 20, 5, "1"), "STRESS": (10, 30, 20, "1"), "PARTIAL": (3, 20, 5, ".5")}
MODELS = ("A0", "A1", "T", "CASH", "BUY_HOLD")
WINDOWS = (
    (date(2022, 10, 17), date(2023, 10, 16)),
    (date(2023, 10, 17), date(2024, 10, 16)),
    (date(2024, 10, 17), date(2025, 10, 16)),
)


def economic_fields(row: Observation) -> tuple[Any, ...]:
    return row.open, row.high, row.low, row.close, row.volume, row.turnover, row.price_basis


def window_inputs(
    raw: tuple[Observation, ...],
    adjusted: tuple[Observation, ...],
    index: tuple[Observation, ...],
    start: date,
    end: date,
) -> tuple[tuple[Observation, ...], tuple[Observation, ...], dict[str, Any]]:
    """No price interpolation, gap removal or return-dependent replacement."""
    if not start <= end or start < date(2022, 10, 17) or end > date(2025, 10, 16):
        raise ValueError("window outside protocol")
    stock: dict[date, Observation] = {}
    adj: dict[date, Observation] = {}
    benchmark: dict[date, Observation] = {}
    for rows, target in ((raw, stock), (adjusted, adj), (index, benchmark)):
        for row in rows:
            if row.exchange_date in target:
                raise ValueError("duplicate dates must be resolved with provenance before replay")
            target[row.exchange_date] = row
    dates = sorted(benchmark)
    evaluation = [d for d in dates if start <= d <= end]
    if len(evaluation) < 200:
        raise ValueError("fewer than200 observed index sessions")
    first = dates.index(evaluation[0])
    if first < 21:
        raise ValueError("21 prior warmup sessions unavailable")
    selected = dates[first - 21 : dates.index(evaluation[-1]) + 1]
    if any(d not in stock or d not in adj for d in selected):
        raise ValueError("missing stock/adjusted dates; IPO/halt/history not repaired")
    factors = []
    for d in selected:
        r, a, ix = stock[d], adj[d], benchmark[d]
        if r.price_basis != "RAW" or a.price_basis != "ADJUSTED" or ix.price_basis != "RAW":
            raise ValueError("price-basis mismatch")
        if any(row.data_origin != "KIS_READONLY" or not row.complete for row in (r, a, ix)):
            raise ValueError("actual complete observations required")
        if any(
            v is None or v <= 0 for v in (r.open, r.close, r.volume, r.turnover, a.close, ix.close)
        ):
            raise ValueError("halt/zero or absent required value; explicit lineage needed")
        assert r.close is not None and a.close is not None
        factors.append(a.close / r.close)
    factor_change = max(factors) / min(factors) - 1
    if factor_change > D(0):
        raise ValueError("nonconstant adjustment factor; corporate-action lineage required")
    return (
        tuple(stock[d] for d in selected),
        tuple(benchmark[d] for d in selected),
        dict(
            evaluation_dates=len(evaluation),
            start=str(evaluation[0]),
            end=str(evaluation[-1]),
            warmup=21,
            adjustment_factor_span=str(factor_change),
            eligibility="SURVIVOR_PRICE_ONLY_UNVERIFIED_CORPORATE_ACTION_COMPLETENESS",
        ),
    )


def calendar_replay(
    stock: tuple[Observation, ...],
    index: tuple[Observation, ...],
    policy: ExplorationPolicy,
    model: str,
    exclusions: frozenset[date],
) -> dict[str, Any]:
    if model not in MODELS:
        raise ValueError("unregistered candidate")
    eligible = SPECIAL_NO_EXECUTION | set(exclusions)
    kernel = FunctionType(
        replay.__code__, dict(replay.__globals__) | {"SPECIAL_NO_EXECUTION": eligible}
    )
    if model in {"CASH", "BUY_HOLD"}:
        result: dict[str, Any] = kernel(stock, index, policy, model)
        return result
    call = FunctionType(
        HoldingController.__call__.__code__,
        dict(HoldingController.__call__.__globals__) | {"SPECIAL_NO_EXECUTION": eligible},
    )
    controller = type("DF005CalendarController", (HoldingController,), {"__call__": call})
    registered = FunctionType(
        hypothesis_replay.__code__,
        dict(hypothesis_replay.__globals__) | {"replay": kernel, "HoldingController": controller},
    )
    result = registered(stock, index, policy, "T1" if model == "T" else model)
    return result


def regime_features(
    stock: tuple[Observation, ...], index: tuple[Observation, ...]
) -> dict[str, dict[str, str]]:
    if [r.exchange_date for r in stock] != [r.exchange_date for r in index]:
        raise ValueError("regime calendars must align")
    result = {}
    for n in range(21, len(stock)):
        closes = [r.close for r in index[n - 21 : n]]
        turns = [r.turnover for r in stock[n - 20 : n]]
        if any(v is None or v <= 0 for v in closes + turns):
            raise ValueError("regime input absent")
        cp = [v for v in closes if v is not None]
        tv = [v for v in turns if v is not None]
        returns = [b / a - 1 for a, b in zip(cp[:-1], cp[1:], strict=True)]
        mean = sum(returns, D(0)) / len(returns)
        vol = (sum(((r - mean) ** 2 for r in returns), D(0)) / len(returns)).sqrt() * D(252).sqrt()
        trend = cp[-1] / cp[0] - 1
        deteriorating = sum(tv[-5:], D(0)) / 5 < sum(tv, D(0)) / 20 * D(".5")
        result[str(stock[n].exchange_date)] = dict(
            trend="BULL" if trend >= D(".05") else "BEAR" if trend <= D("-.05") else "SIDEWAYS",
            volatility="HIGH" if vol >= D(".25") else "LOW" if vol <= D(".15") else "MIDDLE",
            liquidity="DETERIORATING" if deteriorating else "NORMAL",
            sector_leadership="SECTOR_PIT_UNVERIFIED",
        )
    return result


def study_reference(
    stock: tuple[Observation, ...],
    index: tuple[Observation, ...],
    model: str,
    scenario: str,
    exclusions: frozenset[date],
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError("unregistered costs")
    fee, tax, slip, fraction = SCENARIOS[scenario]
    policy = ExplorationPolicy(
        version="DF005-" + scenario,
        fee_bps=fee,
        sell_tax_bps=tax,
        slippage_bps=slip,
        fill_fraction=fraction,
        scope_acceptance="SAMPLED_SURVIVOR_PRICE_ONLY_NOT_PIT",
    )
    result = calendar_replay(stock, index, policy, model, exclusions)
    analyzer = FunctionType(
        analyze_holding.__code__, dict(analyze_holding.__globals__) | {"attribute": attribute}
    )
    analysis = analyzer(result, model)
    summary = analysis["summary"]
    returns = sorted(D(d["daily_return"]) for d in analysis["daily"])
    tail = returns[: max(1, (len(returns) + 19) // 20)]
    summary.update(
        ES5_daily_loss=str(max(D(0), -sum(tail, D(0)) / len(tail))),
        ES_scope="WORST_CEIL_5PCT_OBSERVED_DAILY_NAV_RETURNS",
        sector_contribution=None,
        model=model,
        scenario=scenario,
        candidate_status="EXPLORATORY_ONLY",
        calendar_model="DF005_SESSION_ELIGIBILITY_V1",
        actual_orders=0,
        actual_cancels=0,
    )
    regimes = regime_features(stock, index)
    for row in analysis["daily"]:
        row["regime"] = regimes[row["day"]]
    return dict(replay=result, analysis=analysis)
