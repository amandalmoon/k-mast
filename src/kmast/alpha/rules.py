"""Frozen candidate rules, pure inputs -> absolute target snapshots. No execution imports."""

from datetime import timedelta
from decimal import Decimal

from kmast.alpha.models import AlphaConfig, AlphaResult, Bar, Context
from kmast.core.contracts import SignalIntent, TargetSnapshot
from kmast.data.normalization import content_hash


def visible(bars: tuple[Bar, ...], ctx: Context, symbol: str, resolution: str) -> list[Bar]:
    return sorted(
        (
            b
            for b in bars
            if b.symbol == symbol
            and b.resolution == resolution
            and b.end <= ctx.now
            and b.available_at <= ctx.now
        ),
        key=lambda b: b.end,
    )


def features(
    ctx: Context, config: AlphaConfig, symbol: str
) -> tuple[bool, Decimal, str, tuple[str, ...]]:
    if config.strategy == "A":
        if symbol in ctx.corporate_action_discontinuities:
            return False, Decimal(0), "CORPORATE_ACTION_CONTINUITY_REQUIRED", ()
        rows = visible(ctx.bars, ctx, symbol, "DAILY")
        if len(rows) < config.lookback + 1:
            return False, Decimal(0), "WARMUP_OR_GAP", ()
        window = rows[-config.lookback - 1 :]
        grid = tuple(t for t in ctx.expected_daily_ends if t <= ctx.now)[-len(window) :]
        if tuple(b.end for b in window) != grid:
            return False, Decimal(0), "DAILY_GRID_UNVERIFIED", ()
        benchmark = [b for b in ctx.benchmark if b.available_at <= ctx.now and b.end <= ctx.now]
        by_end = {b.end: b for b in benchmark}
        if any(b.end not in by_end for b in window):
            return False, Decimal(0), "BENCHMARK_GAP", ()
        previous, current = window[:-1], window[-1]
        rs = (
            current.close / window[0].close
            - by_end[current.end].close / by_end[window[0].end].close
        )
        tr = (
            sum(
                (
                    max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                    for a, b in zip(window[:-1], window[1:], strict=True)
                ),
                Decimal(0),
            )
            / config.lookback
        )
        weight = min(
            config.max_weight, config.volatility_budget / max(tr / current.close, Decimal(".0001"))
        )
        trigger = (
            current.close > max(b.high for b in previous)
            and rs >= config.min_relative_strength
            and min(b.turnover for b in window) >= config.min_turnover
        )
        trend_intact = current.close >= sum((b.close for b in previous), Decimal(0)) / len(previous)
        return (
            trigger,
            weight,
            "TREND_INTACT" if trend_intact else "TREND_EXIT",
            tuple(b.identity for b in window) + tuple(by_end[b.end].identity for b in window),
        )
    rows = visible(ctx.bars, ctx, symbol, "MINUTE")
    rows = [b for b in rows if ctx.session_open <= b.start < ctx.session_close]
    if config.strategy in {"B", "C"}:
        elapsed = int((ctx.now - ctx.session_open).total_seconds() // 60)
        if not rows or elapsed < 1:
            return False, Decimal(0), "INTRADAY_WARMUP", ()
        expected = [ctx.session_open + timedelta(minutes=i + 1) for i in range(elapsed)]
        if [b.end for b in rows] != expected or any(
            b.end - b.start != timedelta(minutes=1) for b in rows
        ):
            return False, Decimal(0), "INTRADAY_GAP", ()
        qty = sum((b.volume for b in rows), Decimal(0))
        if not qty:
            return False, Decimal(0), "NO_TRADE_VOLUME", ()
        vwap = sum((b.turnover for b in rows), Decimal(0)) / qty
        evidence = tuple(b.identity for b in rows)
        if config.strategy == "B":
            if elapsed <= config.range_minutes:
                return False, Decimal(0), "ORB_NOT_CONFIRMED", evidence
            baselines = [
                v
                for v in ctx.volume_baselines
                if v.symbol == symbol
                and v.session_date < ctx.session_open.date()
                and v.known_at <= ctx.now
                and v.elapsed_minutes == elapsed
            ]
            if not baselines:
                return False, Decimal(0), "RVOL_UNVERIFIED", evidence
            if len({v.session_date for v in baselines}) != len(baselines):
                return False, Decimal(0), "RVOL_DUPLICATE_SESSION", evidence
            historical = sum((b.cumulative_volume for b in baselines), Decimal(0)) / len(baselines)
            upper = max(b.high for b in rows[: config.range_minutes])
            trigger = (
                rows[-1].close > upper
                and rows[-1].close >= vwap
                and qty / historical >= config.min_rvol
            )
            return trigger, config.max_weight, "ORB_BREAKOUT" if trigger else "ORB_EXIT", evidence
        quote = next((q for q in ctx.quotes if q.symbol == symbol), None)
        if (
            quote is None
            or quote.available_at > ctx.now
            or quote.at > ctx.now
            or ctx.now - quote.at > config.quote_age
        ):
            return False, Decimal(0), "QUOTE_UNVERIFIED", evidence
        spread = (quote.ask - quote.bid) / quote.mid
        trigger = (
            quote.mid <= vwap * (1 - config.reversion_gap)
            and spread <= config.max_spread
            and quote.recovering_liquidity
            and not quote.information_shock
        )
        return (
            trigger,
            config.max_weight,
            "REVERT_ENTRY" if trigger else "REVERT_EXIT",
            evidence + (quote.source_ref,),
        )
    candidates = [
        e
        for e in ctx.events
        if e.symbol == symbol
        and e.available_at <= ctx.now
        and e.mechanism == config.event_mechanism
    ]
    # Validate correction chains before using a family's newest point-in-time version.
    chosen = []
    for family in {e.family for e in candidates}:
        chain = sorted((e for e in candidates if e.family == family), key=lambda e: e.revision)
        if chain[0].supersedes_id is not None or len({e.revision for e in chain}) != len(chain):
            return False, Decimal(0), "EVENT_LINEAGE_BLOCKED", ()
        if any(b.supersedes_id != a.event_id for a, b in zip(chain[:-1], chain[1:], strict=True)):
            return False, Decimal(0), "EVENT_LINEAGE_BLOCKED", ()
        chosen.append(chain[-1])
    if not chosen:
        return False, Decimal(0), "EVENT_DATA_BLOCKED", ()
    latest = max(chosen, key=lambda e: (e.available_at, e.event_id))
    trigger = (
        latest.observed > latest.prior_baseline
        and ctx.now < latest.available_at + config.max_holding
        and (
            latest.family not in ctx.consumed_event_families
            or any(p.symbol == symbol for p in ctx.positions)
        )
    )
    return (
        trigger,
        config.max_weight,
        "EVENT_POSITIVE" if trigger else "EVENT_EXIT",
        (latest.event_id,),
    )


def decide(ctx: Context, config: AlphaConfig, revision: int = 1) -> AlphaResult:
    identity = content_hash([ctx.model_dump(mode="json"), config.model_dump(mode="json"), revision])
    cfg_hash = content_hash(config.model_dump(mode="json"))
    execution = (
        (ctx.now if ctx.session_open <= ctx.now < ctx.session_close else ctx.next_session_open)
        if config.strategy in {"A", "D"}
        else max(ctx.now, ctx.session_open)
    )
    universe = {u.symbol: u for u in ctx.universe}
    positions = {p.symbol: p for p in ctx.positions}
    symbols = sorted(set(universe) | set(positions))
    values = {}
    evidence = []
    reasons = []
    deadlines = []
    for symbol in symbols:
        old = positions.get(symbol)
        eligible = symbol in universe and universe[symbol].eligible(ctx.now)
        active, weight, reason, refs = (
            features(ctx, config, symbol)
            if eligible
            else (
                False,
                Decimal(0),
                "PIT_UNIVERSE_EXIT",
                (),
            )
        )
        deadline = (
            old.exit_deadline
            if old
            else (
                ctx.session_close if config.strategy in {"B", "C"} else ctx.now + config.max_holding
            )
        )
        if old:
            bars = visible(ctx.bars, ctx, symbol, "DAILY" if config.strategy == "A" else "MINUTE")
            price = bars[-1].close if bars else old.entry_price
            if deadline <= ctx.now or price <= old.entry_price * (1 - config.stop_fraction):
                active, reason = False, "DEADLINE_OR_STOP_EXIT"
            elif config.strategy == "A" and reason == "TREND_INTACT":
                active, weight = True, old.weight
            if active:
                weight = min(weight, old.weight)  # no averaging up/down through repeated signal
        if config.strategy in {"B", "C"} and not ctx.session_open <= ctx.now < ctx.session_close:
            active, reason = False, "SESSION_EXIT"
        values[symbol] = weight if active else Decimal(0)
        evidence.append((symbol, refs))
        reasons.append((symbol, reason))
        deadlines.append((symbol, deadline))
    total = sum(values.values(), Decimal(0))
    if total > 1:
        values = {s: w / total for s, w in values.items()}
        # Decimal division can leave a tiny excess: preserve sum <= 1 exactly.
        last = symbols[-1]
        values[last] = max(
            Decimal(0), 1 - sum((w for s, w in values.items() if s != last), Decimal(0))
        )
    intents = tuple(
        SignalIntent(
            intent_id=identity + symbol,
            revision=revision,
            target_snapshot_id=identity,
            strategy_id=config.strategy,
            model_version=config.version,
            config_hash=cfg_hash,
            data_version=ctx.source_version,
            symbol=symbol,
            venue="KRX",
            session="REGULAR",
            decision_at=ctx.now,
            available_at=ctx.now,
            target_weight=values[symbol],
            horizon=config.max_holding
            if config.strategy in {"A", "D"}
            else max(
                ctx.session_close - ctx.now,
                timedelta(seconds=1),
            ),
            valid_until=execution + config.order_lifetime,
            reason_code=dict(reasons)[symbol],
            evidence_refs=dict(evidence)[symbol],
        )
        for symbol in symbols
    )
    return AlphaResult(
        snapshot=TargetSnapshot(
            strategy_id=config.strategy,
            snapshot_id=identity,
            revision=revision,
            expected_symbols=tuple(symbols),
            intents=intents,
        ),
        exit_deadlines=tuple(deadlines),
        earliest_execution_at=execution,
        execution_window_end=ctx.session_close
        if execution < ctx.session_close
        else (ctx.session_close if config.strategy in {"B", "C"} else None),
        feature_evidence=tuple(evidence),
        reasons=tuple(reasons),
    )
