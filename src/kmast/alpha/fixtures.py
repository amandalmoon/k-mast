"""Small authored fixtures for correctness checks, not an economic dataset."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from kmast.alpha.models import Bar, BookQuote, Context, EventFeature, UniverseRecord, VolumeBaseline

OPEN = datetime(2026, 10, 16, tzinfo=UTC)


def trend() -> Context:
    close = OPEN - timedelta(days=1) + timedelta(hours=6, minutes=30)
    dates: list[datetime] = []
    candidate = close
    while len(dates) < 21:
        if candidate.weekday() < 5:
            dates.append(candidate)
        candidate -= timedelta(days=1)
    dates.reverse()
    rows: list[Bar] = []
    benchmark: list[Bar] = []
    for index, end in enumerate(dates):
        price = Decimal(100 + index if index < 20 else 130)
        for symbol, p, collection in (
            ("005930", price, rows),
            ("KOSPI", Decimal(200 + index), benchmark),
        ):
            collection.append(
                Bar(
                    identity="FIXTURE-" + symbol + str(index),
                    symbol=symbol,
                    start=end - timedelta(hours=6, minutes=30),
                    end=end,
                    available_at=end + timedelta(seconds=1),
                    resolution="DAILY",
                    open=p,
                    high=p + 1,
                    low=p - 1,
                    close=p,
                    volume=1000,
                    turnover=p * 1000,
                    source_ref="AUTHORED_SYNTHETIC",
                )
            )
    return Context(
        now=close + timedelta(seconds=1),
        session_open=close - timedelta(hours=6, minutes=30),
        session_close=close,
        next_session_open=OPEN,
        universe=(
            UniverseRecord(
                symbol="005930",
                listed_at=dates[0] - timedelta(days=1),
                known_at=dates[0] - timedelta(days=1),
                sector="MOCK",
                source_ref="MOCK_PIT",
            ),
        ),
        bars=tuple(rows),
        benchmark=tuple(benchmark),
        expected_daily_ends=tuple(dates),
        source_version="SYNTHETIC_TREND_V1",
    )


def intraday(strategy: str = "B") -> Context:
    now = OPEN + timedelta(minutes=6)
    rows = []
    for index in range(6):
        price = Decimal(115 if strategy == "B" and index == 5 else 100)
        end = OPEN + timedelta(minutes=index + 1)
        rows.append(
            Bar(
                identity="MINUTE-" + str(index),
                symbol="005930",
                start=end - timedelta(minutes=1),
                end=end,
                available_at=end,
                resolution="MINUTE",
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000,
                turnover=price * 1000,
                source_ref="MOCK_TRADES",
            )
        )
    return Context(
        now=now,
        session_open=OPEN,
        session_close=OPEN + timedelta(hours=6, minutes=30),
        next_session_open=OPEN + timedelta(days=3),
        bars=tuple(rows),
        universe=(
            UniverseRecord(
                symbol="005930",
                listed_at=OPEN - timedelta(days=100),
                known_at=OPEN - timedelta(days=1),
                sector="MOCK",
                source_ref="MOCK_PIT",
            ),
        ),
        volume_baselines=(
            VolumeBaseline(
                symbol="005930",
                session_date=(OPEN - timedelta(days=1)).date(),
                elapsed_minutes=6,
                cumulative_volume=3000,
                known_at=OPEN,
            ),
        ),
        quotes=(
            BookQuote(
                symbol="005930",
                at=now,
                available_at=now,
                bid="94.9",
                ask="95.1",
                last_trade=90,
                recovering_liquidity=True,
                information_shock=False,
                source_ref="MOCK_QUOTE",
            ),
        ),
        events=(
            EventFeature(
                event_id="original",
                family="earnings-1",
                symbol="005930",
                mechanism="EARNINGS_SEASONAL",
                receipt_date=(OPEN - timedelta(days=1)).date(),
                conservative_next_session=OPEN,
                available_at=OPEN,
                baseline_known_at=OPEN - timedelta(days=2),
                observed=120,
                prior_baseline=100,
                revision=0,
                source_ref="MOCK_EVENT",
            ),
        ),
        source_version="SYNTHETIC_INTRADAY_V1",
    )
