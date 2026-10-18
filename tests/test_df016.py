"""Synthetic causal oracles only, never observed market prices or broker access."""

import ast
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from kmast.data.bar_orb import (
    BarLedger,
    Baseline,
    Receipt,
    Session,
    breakout,
    later_snapshot,
    opening_range,
    parse_bars,
    parse_quote,
    rvol,
)
from kmast.data.models import KST
from kmast.data.paper_security import require_secure_transport

OPEN = datetime(2026, 10, 20, 9, tzinfo=KST)
SESSION = Session(
    OPEN.date(),
    OPEN,
    OPEN.replace(hour=15, minute=30),
    "KRX",
    "START",
    True,
    True,
    True,
    True,
    OPEN,
    clock_verified=True,
    closed_bar_price_verified=True,
    volume_verified=True,
    evidence_kind="SYNTHETIC_ORACLE",
)


def receipt(minutes=16, tr_id="FHKST03010200", **kw):
    request = OPEN + timedelta(minutes=minutes, seconds=10)
    return replace(
        Receipt(
            "073240",
            tr_id,
            request,
            request + timedelta(seconds=1),
            request + timedelta(seconds=2),
            request.replace(second=0),
        ),
        **kw,
    )


def row(i, **kw):
    stamp = OPEN + timedelta(minutes=i)
    return (
        dict(
            stck_bsop_date=stamp.strftime("%Y%m%d"),
            stck_cntg_hour=stamp.strftime("%H%M%S"),
            stck_oprc="100",
            stck_hgpr="105",
            stck_lwpr="99",
            stck_prpr="102",
            cntg_vol="10",
        )
        | kw
    )


def payload(rows):
    return json.dumps(dict(rt_cd="0", output2=rows)).encode()


def bars(count=15, rec=None, session=SESSION):
    return parse_bars(payload([row(i) for i in range(count)]), rec or receipt(), session)


@pytest.mark.parametrize("minutes", [5, 15])
def test_range_uses_complete_half_open_bars_and_actual_validation_time(minutes):
    rec = receipt()
    rows = bars(minutes, rec)
    assert opening_range(rows, minutes, SESSION, rec.response_at) is None
    result = opening_range(rows, minutes, SESSION, rec.validated_at)
    assert result is not None and result.high == 105 and result.low == 99
    assert result.end == OPEN + timedelta(minutes=minutes)
    assert result.available_at == rec.validated_at and result.volume == minutes * 10


@pytest.mark.parametrize(
    "fault",
    [
        "label",
        "calendar",
        "market",
        "correction",
        "venue",
        "first",
        "clock",
        "close_mapping",
        "volume_mapping",
    ],
)
def test_unknown_context_never_qualifies_range(fault):
    changes = dict(
        label=dict(label_verified=False),
        calendar=dict(calendar_verified=False),
        market=dict(continuous_verified=False),
        correction=dict(corrections_verified=False),
        venue=dict(venue="NXT"),
        first=dict(first_trade_at=None),
        clock=dict(clock_verified=False),
        close_mapping=dict(closed_bar_price_verified=False),
        volume_mapping=dict(volume_verified=False),
    )
    context = replace(SESSION, **changes[fault])
    assert opening_range(bars(session=context), 15, context, receipt().validated_at) is None


@pytest.mark.parametrize(
    "fault",
    [
        "future_query",
        "future_bar",
        "incomplete",
        "zero",
        "date",
        "missing_date",
        "nonminute",
        "revised",
        "fake",
        "pretrade",
    ],
)
def test_bad_bar_is_preserved_flagged_and_not_silently_qualified(fault):
    rec, session, rows = receipt(), SESSION, [row(i) for i in range(5)]
    if fault == "future_query":
        rec = replace(rec, query_at=rec.request_at + timedelta(hours=1))
    elif fault == "future_bar":
        rows[0]["stck_cntg_hour"] = "100000"
    elif fault == "incomplete":
        rec = receipt(4)
    elif fault == "zero":
        rows[0]["cntg_vol"] = "0"
    elif fault == "date":
        rows[0]["stck_bsop_date"] = "20261019"
    elif fault == "missing_date":
        del rows[0]["stck_bsop_date"]
    elif fault == "nonminute":
        rows[0]["stck_cntg_hour"] = "090001"
    elif fault == "revised":
        rows[0]["revised"] = True
    elif fault == "fake":
        rows[0]["synthetic"] = True
    elif fault == "pretrade":
        session = replace(session, first_trade_at=OPEN + timedelta(minutes=2))
    parsed = parse_bars(payload(rows), rec, session)
    assert len(parsed) == 5 and any(b.flags for b in parsed)
    assert opening_range(parsed, 5, session, rec.validated_at) is None


def test_missing_session_bar_and_duplicate_rows_block():
    rec = receipt()
    rows = bars()
    assert opening_range(rows[1:], 15, SESSION, rec.validated_at) is None
    duplicated = parse_bars(payload([row(i) for i in range(5)] + [row(0)]), rec, SESSION)
    assert "DUPLICATE_RESPONSE_ROW" in duplicated[0].flags
    assert opening_range(duplicated, 5, SESSION, rec.validated_at) is None


def test_corrections_are_asof_not_backfilled_and_same_rows_keep_first_availability():
    ledger = BarLedger()
    initial = receipt()
    ledger.append(bars(5, initial))
    later = receipt(18)
    ledger.append(bars(5, later))
    assert (
        opening_range(ledger.view(later.validated_at), 5, SESSION, later.validated_at).available_at
        == initial.validated_at
    )
    revised = parse_bars(payload([row(0, stck_hgpr="200")]), later, SESSION)
    ledger.append(revised)
    assert len(ledger.observations) == 11
    assert (
        opening_range(ledger.view(initial.validated_at), 5, SESSION, initial.validated_at)
        is not None
    )
    assert opening_range(ledger.view(later.validated_at), 5, SESSION, later.validated_at) is None


def test_signal_delayed_to_http_validation_not_exchange_label_or_response():
    rec = receipt()
    window = opening_range(bars(5, rec), 5, SESSION, rec.validated_at)
    post = parse_bars(payload([row(5, stck_prpr="110", stck_hgpr="112")]), rec, SESSION)[0]
    assert breakout(window, post, rec.response_at) is None
    signal = breakout(window, post, rec.validated_at)
    assert signal.available_at == rec.validated_at
    assert signal.breakout_bar_end == OPEN + timedelta(minutes=6)
    assert not signal.execution_verified


@pytest.mark.parametrize(
    "fault",
    [
        "same_request",
        "before_signal",
        "stale",
        "future",
        "missing",
        "symbol",
        "crossed",
        "unknown_market",
    ],
)
def test_quote_snapshot_is_not_simultaneous_price_or_fill(fault):
    rec = receipt()
    window = opening_range(bars(5), 5, SESSION, rec.validated_at)
    post = parse_bars(payload([row(5, stck_prpr="110", stck_hgpr="112")]), rec, SESSION)[0]
    signal = breakout(window, post, rec.validated_at)
    req = rec.validated_at + timedelta(seconds=2)
    qr = Receipt(
        "073240",
        "FHKST01010200",
        req,
        req + timedelta(milliseconds=100),
        req + timedelta(milliseconds=200),
        req,
    )
    data = dict(
        rt_cd="0", output1=dict(askp1="112", bidp1="111", aspr_acpt_hour=req.strftime("%H%M%S"))
    )
    session = SESSION
    if fault == "same_request":
        qr = replace(qr, request_at=rec.request_at)
    elif fault == "before_signal":
        data["output1"]["aspr_acpt_hour"] = rec.request_at.strftime("%H%M%S")
    elif fault == "stale":
        data["output1"]["aspr_acpt_hour"] = "090000"
    elif fault == "future":
        data["output1"]["aspr_acpt_hour"] = "100000"
    elif fault == "missing":
        del data["output1"]["aspr_acpt_hour"]
    elif fault == "symbol":
        qr = replace(qr, symbol="462860")
    elif fault == "crossed":
        data["output1"]["bidp1"] = "113"
    elif fault == "unknown_market":
        session = replace(SESSION, continuous_verified=False)
    if fault == "crossed":
        with pytest.raises(ValueError):
            parse_quote(json.dumps(data).encode(), qr, session)
    else:
        quote = parse_quote(json.dumps(data).encode(), qr, session)
        assert not later_snapshot(signal, quote) and not quote.is_fill


def test_valid_later_quote_stays_snapshot_and_preserves_time_basis():
    rec = receipt()
    window = opening_range(bars(5), 5, SESSION, rec.validated_at)
    post = parse_bars(payload([row(5, stck_prpr="110", stck_hgpr="112")]), rec, SESSION)[0]
    signal = breakout(window, post, rec.validated_at)
    qr = receipt(17, "FHKST01010200")
    quote = parse_quote(
        json.dumps(
            dict(
                rt_cd="0",
                output1=dict(
                    bidp1="111", askp1="112", aspr_acpt_hour=qr.request_at.strftime("%H%M%S")
                ),
            )
        ).encode(),
        qr,
        SESSION,
    )
    assert later_snapshot(signal, quote) and not quote.is_fill
    assert quote.date_basis == "INDEPENDENT_SESSION_CONTEXT_NOT_SOURCE_DATE"


@pytest.mark.parametrize("n", [0, 19, 21])
def test_rvol_not_ready_without_twenty_prior_sessions(n):
    prior = baseline(n)
    assert rvol(Decimal(20), prior, OPEN.date(), symbol="073240", minutes=5) is None


def baseline(n=20):
    return tuple(
        Baseline(OPEN.date() - timedelta(days=i + 1), "073240", 5, Decimal(10), True, "0" * 64)
        for i in range(n)
    )


def test_rvol_rejects_current_duplicate_unqualified_sessions():
    prior = baseline()
    assert rvol(Decimal(20), prior, OPEN.date(), symbol="073240", minutes=5) == 2
    for bad in (prior[0], replace(prior[-1], day=OPEN.date()), replace(prior[-1], qualified=False)):
        assert (
            rvol(Decimal(20), prior[:-1] + (bad,), OPEN.date(), symbol="073240", minutes=5) is None
        )


@pytest.mark.parametrize(
    "mutation", [dict(symbol="462860"), dict(minutes=15), dict(source_sha256="")]
)
def test_rvol_never_mixes_symbol_window_or_untraceable_rows(mutation):
    prior = baseline()
    assert (
        rvol(
            Decimal(20),
            prior[:-1] + (replace(prior[-1], **mutation),),
            OPEN.date(),
            symbol="073240",
            minutes=5,
        )
        is None
    )


def test_plaintext_gate_and_no_auth_network_imports_remain():
    with pytest.raises(PermissionError):
        require_secure_transport("ws://ops.koreainvestment.com:31000", "PAPER", OPEN)
    tree = ast.parse(Path("src/kmast/data/bar_orb.py").read_text(encoding="utf-8"))
    modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(
        m and any(k in m for k in ("broker", "network", "http", "urllib", "oms")) for m in modules
    )


def test_synthetic_context_cannot_promote_real_receipts():
    rec = replace(receipt(), origin="OBSERVED")
    observed = bars(5, rec)
    assert all("SYNTHETIC_CONTEXT_CANNOT_QUALIFY_OBSERVED_DATA" in b.flags for b in observed)
    assert opening_range(observed, 5, SESSION, rec.validated_at) is None


@pytest.mark.parametrize("fault", ["naive", "reverse", "tr_id", "secret", "nan", "ohlc"])
def test_invalid_inputs_are_closed_without_echo(fault):
    secret = "SYNTHETIC-DO-NOT-ECHO"
    rec, raw = receipt(), payload([row(0)])
    with pytest.raises((ValueError, PermissionError)) as exc:
        if fault == "naive":
            rec = replace(rec, request_at=rec.request_at.replace(tzinfo=None))
        elif fault == "reverse":
            rec = replace(rec, response_at=rec.request_at - timedelta(seconds=1))
        elif fault == "tr_id":
            rec = replace(rec, tr_id="FHPST01060000")
        elif fault == "secret":
            raw = json.dumps(dict(rt_cd="0", access_token=secret)).encode()
        elif fault == "nan":
            raw = payload([row(0, stck_prpr="NaN")])
        elif fault == "ohlc":
            raw = payload([row(0, stck_hgpr="90")])
        parse_bars(raw, rec, SESSION)
    assert secret not in str(exc.value)
