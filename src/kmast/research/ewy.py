"""DF004 sealed price-only research. No broker, network or OMS capability.

Historical publication and modeled availability are deliberately different fields.
Date clusters describe independent references, never a funded joint account.
"""

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING
from decimal import Decimal as D
from importlib.resources import files
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from kmast.alpha.models import AlphaResult
from kmast.alpha.reference import ReferencePortfolio, SimCosts, Tick
from kmast.core.base import Contract, Positive
from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.data.models import Observation
from kmast.data.normalization import content_hash


def zone(key: str) -> ZoneInfo:
    # Use the pinned tzdata on Linux as well as Windows, not host-dependent rules.
    with files("tzdata.zoneinfo").joinpath(key).open("rb") as stream:
        return ZoneInfo.from_file(stream, key=key)


NY, SEOUL = zone("America/New_York"), zone("Asia/Seoul")
HOLIDAYS = set(
    map(
        date.fromisoformat,
        (
            "2025-01-01",
            "2025-01-09",
            "2025-01-20",
            "2025-02-17",
            "2025-04-18",
            "2025-05-26",
            "2025-06-19",
            "2025-07-04",
            "2025-09-01",
            "2025-11-27",
            "2025-12-25",
            "2026-01-01",
            "2026-01-19",
            "2026-02-16",
            "2026-04-03",
            "2026-05-25",
            "2026-06-19",
            "2026-07-03",
            "2026-09-07",
            "2026-11-26",
            "2026-12-25",
        ),
    )
)
EARLY = set(
    map(
        date.fromisoformat,
        (
            "2025-07-03",
            "2025-11-28",
            "2025-12-24",
            "2026-11-27",
            "2026-12-24",
        ),
    )
)
SPECIAL = {date(2025, 11, 13), date(2026, 1, 2)}
MODELS = (
    "CASH",
    "ALWAYS_LONG",
    "DOM_STOCK",
    "DOM_INDEX",
    "H1_EWY",
    "EWY_AND_DOM_INDEX",
    "EWY_AND_DOM_STOCK",
    "EWY_DELAY_ONE_US_SESSION",
)


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second), SEOUL)


def us_session(day: date) -> tuple[datetime, datetime]:
    if day.year not in {2025, 2026} or day.weekday() >= 5 or day in HOLIDAYS:
        raise ValueError("unsupported or closed US session")
    return (
        datetime.combine(day, time(9, 30), NY).astimezone(UTC),
        datetime.combine(day, time(13 if day in EARLY else 16), NY).astimezone(UTC),
    )


class ForeignBar(Contract):
    """Separate foreign schema: never relabel EWY as a numeric KRX security."""

    symbol: str = "EWY"
    session_date: date
    open: Positive
    high: Positive
    low: Positive
    close: Positive
    volume: D = Field(ge=0, allow_inf_nan=False)
    received_at: AwareDatetime
    historical_publication_at: AwareDatetime | None = None
    source_hash: str
    flags: tuple[str, ...] = (
        "HISTORICAL_PUBLICATION_UNVERIFIED",
        "PROVIDER_SESSION_SCOPE_UNVERIFIED",
        "CORPORATE_ACTION_HISTORY_UNVERIFIED",
        "MODP0_PRICE_BASIS_INFERRED",
    )

    @model_validator(mode="after")
    def coherent(self) -> "ForeignBar":
        _, close_at = us_session(self.session_date)
        if (
            self.symbol != "EWY"
            or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
        ):
            raise ValueError("invalid EWY OHLC")
        if self.received_at < close_at:
            raise ValueError("incomplete US session")
        if self.historical_publication_at is not None and not (
            close_at <= self.historical_publication_at <= self.received_at
        ):
            raise ValueError("invalid publication chronology")
        return self

    def available(self, strict: bool = False) -> datetime:
        if strict:
            if self.historical_publication_at is None:
                raise ValueError("historical publication unverified")
            return self.historical_publication_at
        return us_session(self.session_date)[1] + timedelta(minutes=60)

    @property
    def body(self) -> D:
        return self.close / self.open - 1


def require_available(bar: ForeignBar, decision: datetime, strict: bool = False) -> None:
    if decision.tzinfo is None or bar.available(strict) > decision:
        raise ValueError("future/unavailable US information")


def nav_available(valuation: datetime, publication: datetime | None, decision: datetime) -> bool:
    return publication is not None and valuation <= publication <= decision


def mapping(
    bars: tuple[ForeignBar, ...], korean_dates: tuple[date, ...], strict: bool = False
) -> dict[date, ForeignBar]:
    if len({b.session_date for b in bars}) != len(bars):
        raise ValueError("duplicate US dates")
    result: dict[date, ForeignBar] = {}
    for bar in sorted(bars, key=lambda b: b.session_date):
        try:
            available = bar.available(strict)
        except ValueError:
            continue
        # Each actual US session is consumed once. US holidays create no bar.
        eligible = next(
            (d for d in sorted(korean_dates) if d not in SPECIAL and at(d, 8) >= available), None
        )
        if eligible is not None:
            require_available(bar, at(eligible, 8), strict)
            result[eligible] = bar
    return result


def signal_id(model: str, symbol: str, decision: datetime, evidence: list[str]) -> str:
    # Local evidence only: future append/correction cannot alter prior IDs.
    return content_hash(["DF004_V1", model, symbol, decision.isoformat(), evidence])


def intent(
    model: str,
    symbol: str,
    decision: datetime,
    weight: D,
    expiry: datetime,
    executable: datetime,
    evidence: list[str],
    revision: int,
) -> AlphaResult:
    identity = signal_id(model, symbol, decision, evidence)
    signal = SignalIntent(
        intent_id=identity,
        target_snapshot_id=identity,
        revision=revision,
        strategy_id="A",
        model_version="DF004-" + model,
        config_hash=content_hash(["DF004_V1", model]),
        data_version=content_hash(evidence),
        symbol=symbol,
        venue="KRX",
        session="REGULAR",
        decision_at=decision,
        available_at=decision,
        target_weight=weight,
        horizon=timedelta(days=1),
        valid_until=expiry,
        reason_code="EXPLORATORY_ASSUMPTION",
        evidence_refs=tuple(evidence),
    )
    return AlphaResult(
        snapshot=TargetSnapshot(
            strategy_id="A",
            snapshot_id=identity,
            revision=revision,
            expected_symbols=(symbol,),
            intents=(signal,),
        ),
        exit_deadlines=((symbol, expiry),),
        earliest_execution_at=executable,
        feature_evidence=((symbol, tuple(evidence)),),
        reasons=((symbol, "RESEARCH_ONLY"),),
    )


def replay(
    stock: tuple[Observation, ...],
    index: tuple[Observation, ...],
    us: tuple[ForeignBar, ...],
    valuation_dates: tuple[date, ...],
    common: set[date],
    model: str,
    scenario: str,
) -> dict[str, Any]:
    if model not in MODELS or scenario not in {"BASE", "STRESS"}:
        raise ValueError("unregistered trial")
    s, ix = {r.exchange_date: r for r in stock}, {r.exchange_date: r for r in index}
    if len(s) != len(stock) or len(ix) != len(index) or not common <= set(valuation_dates):
        raise ValueError("unaligned panel")
    if any(r.data_origin != "KIS_READONLY" or r.price_basis != "RAW" for r in stock + index):
        raise ValueError("real raw observations required")
    dates = sorted(s)
    if dates != sorted(ix) or not set(valuation_dates) <= set(dates):
        raise ValueError("complete stock/index calendar required")
    mapped = mapping(us, tuple(dates))
    ordered_us = sorted(us, key=lambda b: b.session_date)
    us_positions = {b.session_date: n for n, b in enumerate(ordered_us)}
    fee, tax, slip = (D(3), D(20), D(5)) if scenario == "BASE" else (D(10), D(30), D(20))
    ref = ReferencePortfolio(
        "A",
        D(10000000),
        SimCosts(
            version="DF004-" + scenario,
            fee_bps=fee,
            sell_tax_bps=tax,
            slippage_bps=slip,
            max_participation=1,
            cost_scope="REAL_UNVERIFIED",
        ),
    )
    symbol = stock[0].symbol
    trace: list[dict[str, Any]] = []
    blocked_until = -1
    commissions, taxes, slippage = D(0), D(0), D(0)
    gross_total, gap_total = D(0), D(0)
    for n, day in enumerate(valuation_dates):
        pos = dates.index(day)
        if pos < 2:
            raise ValueError("two completed prior sessions required")
        row, prior, before = s[day], s[dates[pos - 1]], s[dates[pos - 2]]
        ip, ib = ix[dates[pos - 1]], ix[dates[pos - 2]]
        if any(
            v is None
            for v in (
                row.open,
                row.close,
                prior.close,
                before.close,
                ip.close,
                ib.close,
                prior.volume,
            )
        ):
            raise ValueError("required OHLC/prior inputs missing")
        assert row.open and row.close and prior.close and before.close and ip.close and ib.close
        assert prior.volume is not None
        decision = at(day, 8)
        ew = mapped.get(day)
        active = False
        evidence = [prior.record_id, before.record_id, ip.record_id, ib.record_id]
        if day in common:
            if ew is None:
                raise ValueError("common date missing fresh EWY")
            require_available(ew, decision)
            up, sp, bp = ew.body > 0, prior.close > before.close, ip.close > ib.close
            k = us_positions[ew.session_date]
            if k == 0:
                raise ValueError("delayed placebo missing prior actual session")
            delayed = ordered_us[k - 1]
            require_available(delayed, decision)
            evidence += [
                content_hash([ew.session_date.isoformat(), str(ew.open), str(ew.close)]),
                content_hash(
                    [delayed.session_date.isoformat(), str(delayed.open), str(delayed.close)]
                ),
            ]
            active = {
                "CASH": False,
                "ALWAYS_LONG": True,
                "DOM_STOCK": sp,
                "DOM_INDEX": bp,
                "H1_EWY": up,
                "EWY_AND_DOM_INDEX": up and bp,
                "EWY_AND_DOM_STOCK": up and sp,
                "EWY_DELAY_ONE_US_SESSION": delayed.body > 0,
            }[model]
        previous_nav = ref.nav
        previous_q = ref.quantity(symbol)
        gap = previous_q * (row.open - prior.close)
        gross = previous_q * (row.close - prior.close)
        ref.mark(symbol, prior.close, at(day, 7, 59))
        capacity = int(prior.volume * D(".001"))
        begin = len(ref.state.executions)
        if active and n >= blocked_until and not previous_q and day not in SPECIAL:
            result = intent(
                model, symbol, decision, D(".25"), at(day, 9, 1), at(day, 9, 0, 1), evidence, n * 2
            )
            ref.submit(result, {symbol: prior.close * D("1.05")})
            ref.match(
                Tick(
                    identity=result.snapshot.snapshot_id + "OPEN",
                    symbol=symbol,
                    at=at(day, 9, 0, 1),
                    available_at=at(day, 9, 0, 1),
                    bid=row.open,
                    ask=row.open,
                    available_quantity=capacity,
                    executable=True,
                    origin="REAL_UNVERIFIED",
                ),
                at(day, 9, 0, 1),
            )
            ref.expire(at(day, 9, 1))
        open_q = ref.quantity(symbol)
        # Sizing mark stays prior-close for target zero; no final close enters the decision.
        if ref.quantity(symbol) and day not in SPECIAL:
            result = intent(
                model,
                symbol,
                at(day, 15, 19),
                D(0),
                at(day, 15, 31),
                at(day, 15, 30, 1),
                evidence + ["EXIT_ZERO"],
                n * 2 + 1,
            )
            ref.submit(result, {symbol: prior.close * D(".70")})
            ref.match(
                Tick(
                    identity=result.snapshot.snapshot_id + "CLOSE",
                    symbol=symbol,
                    at=at(day, 15, 30, 1),
                    available_at=at(day, 15, 30, 1),
                    bid=row.close,
                    ask=row.close,
                    available_quantity=capacity,
                    executable=True,
                    origin="REAL_UNVERIFIED",
                ),
                at(day, 15, 30, 1),
            )
            ref.expire(at(day, 15, 31))
        executions = ref.state.executions[begin:]
        day_fee, day_slip = D(0), D(0)
        for _, _, _, qty, price, total_fee in executions:
            anchor = row.open if qty > 0 else row.close
            gross += qty * (row.close - anchor)
            adverse = D(qty) * (price - anchor)
            day_slip += adverse
            day_fee += total_fee
            commission = (abs(qty) * price * fee / 10000).quantize(D(".01"), rounding=ROUND_CEILING)
            commissions += commission
            taxes += total_fee - commission
            if qty < 0:
                # n and n+1 barred; n+2 first allowed session (T+2).
                blocked_until = n + 2
        ref.mark(symbol, row.close, at(day, 15, 31))
        valued = ref.value(at(day, 16), D(100))
        net = valued.nav - previous_nav
        if abs(net - (gross - day_slip - day_fee - 100)) > D("1e-15"):
            raise ValueError("independent mark-to-market decomposition failed")
        gross_total += gross
        gap_total += gap
        slippage += day_slip
        regime = "UNKNOWN"
        if pos >= 21:
            anchor_close = ix[dates[pos - 21]].close
            if anchor_close:
                change = ip.close / anchor_close - 1
                regime = (
                    "BULL" if change >= D(".05") else "BEAR" if change <= D("-.05") else "NEUTRAL"
                )
        trace.append(
            dict(
                date=str(day),
                common=day in common,
                ewy_positive=ew.body > 0 if ew else None,
                gap_return=str(row.open / prior.close - 1),
                body_return=str(row.close / row.open - 1),
                net=str(net),
                gross=str(gross),
                overnight_gap_pnl=str(gap),
                intraday_body_pnl=str(gross - gap),
                slippage=str(day_slip),
                fee=str(day_fee),
                nav=str(valued.nav),
                cash=str(valued.cash),
                quantity=ref.quantity(symbol),
                open_exposure=str(open_q * row.open / previous_nav),
                signal_id=signal_id(model, symbol, decision, evidence),
                active=active,
                executions=[
                    (i, t.isoformat(), sy, q, str(p), str(f)) for i, t, sy, q, p, f in executions
                ],
                hold=bool(ref.quantity(symbol)),
                regime=regime,
            )
        )
    metrics = ref.metrics(valuation_dates)
    return dict(
        model=model,
        scenario=scenario,
        symbol=symbol,
        capital="10000000",
        days=len(trace),
        common_days=len(common),
        metrics=metrics,
        gross_before_slippage=str(gross_total),
        commission=str(commissions),
        tax=str(taxes),
        slippage=str(slippage),
        overnight_gap_pnl=str(gap_total),
        operating_cost=str(ref.state.operating_costs),
        explicit_cost=str(ref.state.costs),
        net=str(ref.nav - ref.state.capital),
        cash_excess=str(ref.nav - ref.state.capital + ref.state.operating_costs),
        average_open_exposure=str(sum((D(t["open_exposure"]) for t in trace), D(0)) / len(trace)),
        no_trade_days=sum(not t["executions"] for t in trace),
        execution_count=len(ref.state.executions),
        worst_day=str(min(D(t["net"]) for t in trace)),
        residual_quantity=ref.quantity(symbol),
        trace=trace,
    )


def bootstrap(values: list[float], groups: list[bool] | None = None) -> dict[str, Any]:
    if not values or (groups is not None and (len(groups) != len(values) or len(set(groups)) < 2)):
        return {"observed": None, "ci95": None, "p": None}

    def statistic(indices: list[int]) -> float | None:
        if groups is None:
            return sum(values[i] for i in indices) / len(indices)
        a, b = (
            [values[i] for i in indices if groups[i]],
            [values[i] for i in indices if not groups[i]],
        )
        return sum(a) / len(a) - sum(b) / len(b) if a and b else None

    n = len(values)
    observed = statistic(list(range(n)))
    assert observed is not None
    rng = random.Random(404)
    samples = []
    for _ in range(1000):
        indices: list[int] = []
        while len(indices) < n:
            start = rng.randrange(n)
            indices.extend((start + k) % n for k in range(5))
        value = statistic(indices[:n])
        if value is not None:
            samples.append(value)
    if len(samples) != 1000:
        return {"observed": observed, "ci95": None, "p": None}
    samples.sort()
    return {
        "observed": observed,
        "ci95": [samples[24], samples[974]],
        "p": (1 + sum(abs(b - observed) >= abs(observed) for b in samples)) / 1001,
    }


def holm(endpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        range(len(endpoints)),
        key=lambda k: endpoints[k]["p"] if endpoints[k]["p"] is not None else 1,
    )
    maximum = 0.0
    result = [dict(e) for e in endpoints]
    for rank, k in enumerate(ordered):
        p = endpoints[k]["p"]
        if p is None:
            result[k].update(adjusted_p=None, reject=False)
        else:
            maximum = max(maximum, min(1.0, (len(endpoints) - rank) * p))
            result[k].update(adjusted_p=maximum, reject=maximum <= 0.05)
    return result
