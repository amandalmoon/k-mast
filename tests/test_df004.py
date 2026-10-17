"""Independent causality, partial evidence and execution boundary regression."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from kmast.research.ewy import (
    ForeignBar,
    at,
    bootstrap,
    holm,
    mapping,
    nav_available,
    replay,
    require_available,
    us_session,
)
from scripts.collect_df004_ewy import ROUTE, validate

from .test_data_first import panel


def bar(day="2026-03-06", **changes):
    return ForeignBar.model_validate(
        dict(
            session_date=day,
            open="100",
            high="110",
            low="90",
            close="101",
            volume="1000",
            source_hash="a" * 64,
            received_at="2026-10-17T00:00:00Z",
        )
        | changes
    )


@pytest.mark.parametrize(
    ("day", "hour"),
    [
        ("2026-03-06", 21),
        ("2026-03-09", 20),
        ("2026-10-16", 20),
        ("2025-11-28", 18),
        ("2025-12-24", 18),
    ],
)
def test_actual_calendar_dst_early_close(day, hour):
    assert us_session(date.fromisoformat(day))[1].hour == hour


@pytest.mark.parametrize(
    "day", ["2025-11-27", "2026-01-19", "2026-07-03", "2026-03-08", "2027-01-04"]
)
def test_closed_or_unknown_us_session_rejected(day):
    with pytest.raises(ValueError):
        us_session(date.fromisoformat(day))


def test_no_repeated_signal_after_us_holiday():
    b = bar("2026-01-16")
    result = mapping((b,), (date(2026, 1, 19), date(2026, 1, 20)))
    assert list(result) == [date(2026, 1, 19)]


def test_korean_holiday_collapses_to_latest_actual_us_session():
    result = mapping(
        (bar("2026-02-12"), bar("2026-02-13"), bar("2026-02-17")), (date(2026, 2, 19),)
    )
    assert result[date(2026, 2, 19)].session_date == date(2026, 2, 17)


def test_no_same_date_future_us_close():
    with pytest.raises(ValueError):
        require_available(bar(), at(date(2026, 3, 6), 8))
    require_available(bar(), at(date(2026, 3, 9), 8))


def test_strict_and_exploratory_independent_no_receipt_backdating():
    b = bar()
    assert mapping((b,), (date(2026, 3, 9),))
    assert not mapping((b,), (date(2026, 3, 9),), True)
    assert b.received_at == datetime(2026, 10, 17, tzinfo=UTC)
    assert "HISTORICAL_PUBLICATION_UNVERIFIED" in b.flags


def test_publication_boundary_and_nav_reference_not_publication():
    decision = at(date(2026, 3, 9), 8)
    b = bar(historical_publication_at=decision)
    require_available(b, decision, True)
    with pytest.raises(ValueError):
        require_available(b, decision - timedelta(microseconds=1), True)
    assert not nav_available(decision - timedelta(days=1), None, decision)
    assert not nav_available(decision, decision + timedelta(seconds=1), decision)
    assert nav_available(decision, decision, decision)


def test_correction_is_local_to_evidence_identity():
    stock, index, bars, dates = replay_fixture()
    before = replay(stock, index, bars, dates, set(dates), "H1_EWY", "BASE")
    # Append then correct a future US bar: neither IDs nor past fills/NAV may change.
    for close in ("110", "90"):
        later = (*bars, bar("2026-09-04", close=close))
        assert replay(stock, index, later, dates, set(dates), "H1_EWY", "BASE") == before
    # Correct the actual input used by the first decision: identity must change.
    changed = (bars[0], bar("2026-09-02", close="99"), bars[2])
    revised = replay(stock, index, changed, dates, set(dates), "H1_EWY", "BASE")
    assert revised["trace"][0]["signal_id"] != before["trace"][0]["signal_id"]


def test_price_only_body_does_not_use_nav():
    assert bar().body == D(".01")
    with pytest.raises(ValueError):
        bar(open="0")


def test_cluster_bootstrap_and_holm_no_sixfold_sample_inflation():
    result = bootstrap([0.1] * 80)
    assert result["ci95"][0] == pytest.approx(0.1)
    assert result["p"] == 1 / 1001
    corrected = holm([dict(p=0.01), dict(p=0.03), dict(p=0.9)])
    assert [r["reject"] for r in corrected] == [True, False, False]
    assert bootstrap([], None)["p"] is None
    assert bootstrap([1, 2], [True, True])["p"] is None


def params():
    return dict(AUTH="", EXCD="AMS", SYMB="EWY", GUBN="0", BYMD="20261016", MODP="0")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SYMB", "AAPL"),
        ("EXCD", "NAS"),
        ("MODP", "2"),
        ("BYMD", "20251016"),
        ("BYMD", "20261017"),
        ("GUBN", "1"),
    ],
)
def test_scope_cannot_expand(key, value):
    with pytest.raises((PermissionError, ValueError)):
        validate("GET", ROUTE, params() | {key: value})


@pytest.mark.parametrize(
    "path",
    [
        "/uapi/overseas-stock/v1/trading/order",
        "/oauth2/Approval",
        "/uapi/domestic-stock/v1/trading/inquire-balance",
    ],
)
def test_orders_cancels_account_and_websocket_denied(path):
    with pytest.raises(PermissionError):
        validate("POST", path, {})


def test_only_approved_daily_endpoint():
    validate("GET", ROUTE, params())
    with pytest.raises(PermissionError):
        validate("GET", ROUTE, params() | {"CANO": "forbidden"})


def replay_fixture(close="104"):
    stock, index = panel()
    stock = tuple(
        type(r).model_validate(
            r.model_dump()
            | dict(
                open=D(104) if n >= 2 else D(100),
                close=D(close) if n >= 2 else D(100),
                high=D(110),
                low=D(50),
                volume=D(1000000),
            )
        )
        for n, r in enumerate(stock[:4])
    )
    bars = tuple(bar(d) for d in ("2026-09-01", "2026-09-02", "2026-09-03"))
    dates = tuple(r.exchange_date for r in stock[2:])
    return stock, index[:4], bars, dates


def test_new_open_position_earns_no_prior_close_gap_and_costs_once():
    stock, index, bars, dates = replay_fixture()
    original = [r.model_dump_json() for r in stock]
    result = replay(stock, index, bars, dates, set(dates), "H1_EWY", "BASE")
    assert D(result["gross_before_slippage"]) == 0
    assert D(result["overnight_gap_pnl"]) == 0
    assert result["execution_count"] == 2  # T+1 sale proceeds never reused
    assert D(result["net"]) == -D(result["explicit_cost"]) - D(result["slippage"]) - 200
    assert [r.model_dump_json() for r in stock] == original
    assert result["trace"][0]["gap_return"] == ".04" or D(result["trace"][0]["gap_return"]) == D(
        ".04"
    )
    cash = replay(stock, index, bars, dates, set(dates), "CASH", "BASE")
    assert cash["days"] == result["days"] and D(cash["net"]) == -200


def test_unresolved_exit_is_hold_and_no_terminal_forced_fill():
    stock, index, bars, dates = replay_fixture("60")
    stock = (
        *stock[:-1],
        type(stock[-1]).model_validate(stock[-1].model_dump() | dict(close=D(30), low=D(20))),
    )
    result = replay(stock, index, bars, dates, set(dates), "H1_EWY", "BASE")
    assert result["residual_quantity"] > 0 and result["trace"][-1]["hold"]
    assert result["execution_count"] == 1
    with pytest.raises(ValueError):
        replay(stock, index, bars, dates, {date(2026, 9, 7)}, "H1_EWY", "BASE")


def test_paper_transport_budget_resume_and_response_based_spacing(tmp_path, monkeypatch):
    from pydantic import SecretStr

    import scripts.collect_df004_ewy as collector

    clock = [100.0]
    starts = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "openapivts.koreainvestment.com" and port == 29443

        def request(self, method, path, body, headers):
            self.auth = method == "POST"
            starts.append(clock[0])
            clock[0] += 0.2

        def getresponse(self):
            return SimpleNamespace(
                status=200,
                read=lambda _: json.dumps(
                    {"access_token": "fixture-only-token"} if self.auth else {"output2": []}
                ).encode(),
            )

        def close(self):
            pass

    monkeypatch.setattr(collector, "ROOT", tmp_path / "private")
    monkeypatch.setattr(collector.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(collector.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        collector.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(
        collector,
        "load_env",
        lambda _: SimpleNamespace(
            environment=SimpleNamespace(value="PAPER"),
            app_key=SecretStr("fixture-app-key"),
            app_secret=SecretStr("fixture-app-secret"),
        ),
    )
    monkeypatch.setattr("sys.argv", ["collector", "--allow-approved-paper-readonly"])
    for _ in range(3):
        collector.main()
    budget = json.loads((collector.ROOT / "budget.json").read_bytes())
    # First run5 calls; second auth only, because four empty responses are cached.
    assert budget["auth"] == 2 and budget["requests"] == 6
    assert all(b - a >= 3 for a, b in zip(starts, starts[1:], strict=False))
    assert not (collector.ROOT / "collection.lock").exists()


def test_live_configuration_rejected_before_transport(tmp_path, monkeypatch):
    import scripts.collect_df004_ewy as collector

    monkeypatch.setattr(collector, "ROOT", tmp_path)
    monkeypatch.setattr(
        collector, "load_env", lambda _: SimpleNamespace(environment=SimpleNamespace(value="LIVE"))
    )
    monkeypatch.setattr("sys.argv", ["collector", "--allow-approved-paper-readonly"])
    with pytest.raises(PermissionError, match="PAPER_REQUIRED"):
        collector.main()
