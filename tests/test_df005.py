"""DF005 collection reliability: authored transport fixtures, never economic evidence."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from kmast.brokers.kis.requests import MarketRequest
from kmast.core.config import BrokerConfig
from kmast.data.panel_acquisition import PanelWire, atomic_json, process_lock
from kmast.data.store import digest


def config(environment="PAPER"):
    return BrokerConfig(
        environment=environment,
        credential_environment=environment,
        account_environment=environment,
        account_ref="FIXTURE_ALIAS",
        endpoint="https://openapivts.koreainvestment.com:29443"
        if environment == "PAPER"
        else "https://openapi.koreainvestment.com:9443",
        app_key="fixture-app-key",
        app_secret="fixture-app-secret",
    )


SYMBOLS = tuple(f"{n:06}" for n in range(50))


def request():
    return MarketRequest(
        operation="daily", symbol=SYMBOLS[0], start=date(2022, 9, 1), end=date(2022, 12, 30)
    )


def test_os_lock_release_and_duplicate_collection(tmp_path):
    lock = tmp_path / "process.lock"
    with process_lock(lock):
        with pytest.raises(PermissionError):
            with process_lock(lock):
                pytest.fail("duplicate process acquired lock")
    with process_lock(lock):
        pass


@pytest.mark.parametrize("environment", ["PAPER", "LIVE"])
def test_network_disabled_and_live_fail_closed(tmp_path, environment):
    wire = PanelWire(tmp_path, SYMBOLS, enabled=environment == "LIVE")
    r = request()
    with pytest.raises(PermissionError):
        wire.send(config(environment), "GET", r.path, {"tr_id": r.tr_id}, r.params())
    assert wire.state["requests"] == 0


@pytest.mark.parametrize("change", ["symbol", "date", "route", "tr_id", "extra"])
def test_approved_scope_cannot_expand(tmp_path, change):
    wire = PanelWire(tmp_path, SYMBOLS, enabled=True)
    r = request()
    params, route, headers = r.params(), r.path, {"tr_id": r.tr_id}
    if change == "symbol":
        params["FID_INPUT_ISCD"] = "005930"
    elif change == "date":
        params["FID_INPUT_DATE_2"] = "20261016"
    elif change == "route":
        route = "/uapi/domestic-stock/v1/trading/order-cash"
    elif change == "tr_id":
        headers["tr_id"] = "FORBIDDEN"
    else:
        params["CANO"] = "forbidden"
    with pytest.raises(PermissionError):
        wire.send(config(), "GET", route, headers, params)
    assert wire.state["requests"] == 0


def transport(monkeypatch, body=b'{"rt_cd":"1","msg1":"failed"}', status=500):
    import kmast.data.panel_acquisition as module

    clock, starts = [100.0], []

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("openapivts.koreainvestment.com", 29443)

        def request(self, *args, **kwargs):
            starts.append(clock[0])

        def getresponse(self):
            clock[0] += 0.5
            return SimpleNamespace(status=status, read=lambda _: body)

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    return starts


def test_failed_http_bytes_hash_resume_and_response_complete_wait(tmp_path, monkeypatch):
    raw = b'{"rt_cd":"1","msg1":"provider error"}'
    starts = transport(monkeypatch, raw)
    wire = PanelWire(tmp_path, SYMBOLS, enabled=True)
    r = request()
    for _ in range(2):
        reply = wire.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params())
        assert reply.status == 500
    assert starts[1] - starts[0] == pytest.approx(3.55)
    assert starts[1] - starts[0] > 3
    assert wire.state["requests"] == 2
    event = wire.last_event
    assert (tmp_path / event["wire_path"]).read_bytes() == raw
    assert event["wire_sha256"] == digest(raw)
    resumed = PanelWire(tmp_path, SYMBOLS, enabled=True)
    assert resumed.state["requests"] == 2
    resumed.state["requests"] = 900
    with pytest.raises(PermissionError):
        resumed.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params())
    assert len(starts) == 2


@pytest.mark.parametrize(
    "raw",
    [b'{"appkey":"fixture-app-key"}', b'{"cano":"12345678"}', b'{"msg1":"fixture-app-secret"}'],
)
def test_sensitive_response_bytes_never_retained(tmp_path, monkeypatch, raw):
    transport(monkeypatch, raw)
    wire = PanelWire(tmp_path, SYMBOLS, enabled=True)
    r = request()
    wire.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params())
    assert wire.last_event["body_status"] == "SENSITIVE_HASH_ONLY"
    assert not list((tmp_path / "wire").glob("*"))
    assert not any(
        b"fixture-app-key" in p.read_bytes() or b"fixture-app-secret" in p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    )


def test_interrupted_consumed_call_is_not_forgotten(tmp_path):
    atomic_json(
        tmp_path / "budget.json",
        dict(
            requests=11,
            authentication=2,
            response_pending=True,
            response_completed_epoch=0,
            events=[],
        ),
    )
    wire = PanelWire(tmp_path, SYMBOLS, enabled=True)
    assert wire.state["requests"] == 11 and wire.state["authentication"] == 2
    assert wire.state["events"][0]["body_status"] == "INTERRUPTED_RESPONSE_UNAVAILABLE"
    wire = PanelWire(tmp_path, SYMBOLS, enabled=True)
    assert len(wire.state["events"]) == 1


def test_completed_response_journal_survives_interrupted_budget_commit(tmp_path):
    from kmast.data.store import canonical, immutable_write

    atomic_json(
        tmp_path / "budget.json",
        dict(
            requests=7,
            authentication=1,
            response_pending=True,
            response_completed_epoch=0,
            events=[],
        ),
    )
    event = dict(
        sequence=7,
        kind="DAILY",
        received_at="2026-10-17T00:00:00+00:00",
        body_status="WIRE_BYTES_RETAINED",
        wire_sha256="a" * 64,
    )
    immutable_write(tmp_path / "events/0007.json", canonical(event))
    recovered = PanelWire(tmp_path, SYMBOLS, enabled=True)
    assert recovered.state["requests"] == 7 and recovered.state["authentication"] == 1
    assert recovered.state["events"] == [event] and not recovered.state["response_pending"]
    assert recovered.state["response_completed_epoch"] > 0
    assert PanelWire(tmp_path, SYMBOLS, enabled=True).state["events"] == [event]


def test_atomic_immutable_file_is_never_partially_published(tmp_path, monkeypatch):
    import kmast.data.panel_acquisition as module

    target = tmp_path / "cache.json"
    with monkeypatch.context() as patch:
        patch.setattr(
            module.os, "link", lambda *_: (_ for _ in ()).throw(OSError("authored interrupt"))
        )
        with pytest.raises(OSError):
            module.immutable_write(target, b"complete-bytes")
    assert not target.exists() and not list(tmp_path.glob("*.tmp"))
    module.immutable_write(target, b"complete-bytes")
    module.immutable_write(target, b"complete-bytes")
    with pytest.raises(ValueError):
        module.immutable_write(target, b"conflicting-bytes")
    assert target.read_bytes() == b"complete-bytes"


def test_atomic_store_preserves_frozen_schema_and_dataset_bytes(tmp_path):
    from kmast.data.models import Provenance
    from kmast.data.panel_acquisition import AtomicPanelStore
    from kmast.data.store import DataStore, canonical

    from .test_data_first import panel

    row = panel()[0][0]
    payload = dict(rt_cd="0", output2=[])
    hashed = digest(canonical(payload))
    meta = Provenance(
        source="KIS",
        endpoint="/authored-fixture",
        tr_id="FIXTURE",
        symbol=row.symbol,
        venue="KRX",
        session="UNKNOWN",
        request_time=row.received_at,
        received_at=row.received_at,
        acquired_at=row.acquired_at,
        source_hash=hashed,
        ingestion_run_id="AUTHORED_FIXTURE",
        data_origin="KIS_READONLY",
    )
    row = type(row).model_validate(row.model_dump() | {"source_hash": hashed})
    stores = [DataStore(tmp_path / "old"), AtomicPanelStore(tmp_path / "new")]
    ids = []
    for store in stores:
        store.put_raw("fixture", payload, meta)
        ids.append(store.put_dataset((row,), "fixture"))
    assert ids[0] == ids[1] and stores[0].load_dataset(ids[0]) == stores[1].load_dataset(ids[1])
    for path in (tmp_path / "old").rglob("*"):
        if path.is_file():
            assert (
                path.read_bytes()
                == (tmp_path / "new" / path.relative_to(tmp_path / "old")).read_bytes()
            )


def test_auth_raw_never_persisted_and_auth_budget_not_renewed(tmp_path, monkeypatch):
    raw = b'{"access_token":"fixture-token","expires_in":86400}'
    starts = transport(monkeypatch, raw, 200)
    wire = PanelWire(tmp_path, SYMBOLS, enabled=True)
    for _ in range(2):
        response = wire.send(
            config(),
            "POST",
            "/oauth2/tokenP",
            {},
            dict(
                grant_type="client_credentials",
                appkey="fixture-app-key",
                appsecret="fixture-app-secret",
            ),
        )
        assert response.body["access_token"] == "fixture-token"
    with pytest.raises(PermissionError):
        wire.send(
            config(),
            "POST",
            "/oauth2/tokenP",
            {},
            dict(
                grant_type="client_credentials",
                appkey="fixture-app-key",
                appsecret="fixture-app-secret",
            ),
        )
    assert len(starts) == 2
    assert not any(b"fixture-token" in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


def test_protocol_sealed_fifty_and_no_original_survivors():
    p = Path("artifacts/df005")
    raw = (p / "DF005_PROTOCOL.json").read_bytes()
    protocol, seal = json.loads(raw), json.loads((p / "protocol-seal.json").read_bytes())
    assert digest(raw) == seal["protocol_sha256"]
    symbols = protocol["kospi"] + protocol["kosdaq"]
    assert len(set(symbols)) == 50
    assert not set(symbols) & {"005930", "000660", "035420", "247540", "086520", "028300"}
    assert protocol["trial_budget"]["parameter_combinations"] == 1


@pytest.mark.parametrize("model", ["A0", "A1", "T"])
def test_unchanged_calendar_is_exact_frozen_replay(model):
    from kmast.research.domestic_panel import calendar_replay
    from kmast.research.hypotheses import hypothesis_replay

    from .test_data_first import panel, policy

    stock, index = panel()
    p = policy()
    assert calendar_replay(stock, index, p, model, frozenset()) == hypothesis_replay(
        stock, index, p, "T1" if model == "T" else model
    )


def test_special_calendar_excludes_fill_without_mutating_original_globals():
    from kmast.research.domestic_panel import calendar_replay
    from kmast.research.exploratory import SPECIAL_NO_EXECUTION

    from .test_data_first import panel, policy

    stock, index = panel()
    original = SPECIAL_NO_EXECUTION.copy()
    ordinary = calendar_replay(stock, index, policy(), "A1", frozenset())
    first_fill = next(e[1][:10] for e in ordinary["reference_state"]["executions"])
    special = calendar_replay(
        stock, index, policy(), "A1", frozenset({date.fromisoformat(first_fill)})
    )
    assert all(e[1][:10] != first_fill for e in special["reference_state"]["executions"])
    assert SPECIAL_NO_EXECUTION == original
    assert len(special["observed_price_log"]) == len(ordinary["observed_price_log"])


def test_regimes_are_prior_only_and_sector_is_not_backfilled():
    from decimal import Decimal as D

    from kmast.research.domestic_panel import regime_features

    from .test_data_first import panel

    stock, index = panel()
    before = regime_features(stock, index)
    future = type(index[-1]).model_validate(
        index[-1].model_dump() | dict(close=D(999999), high=D(999999))
    )
    after = regime_features(stock, (*index[:-1], future))
    assert before == after
    assert all(v["sector_leadership"] == "SECTOR_PIT_UNVERIFIED" for v in after.values())


def test_window_missing_history_cannot_be_repaired_or_replaced():
    from datetime import timedelta
    from decimal import Decimal as D

    from kmast.research.domestic_panel import window_inputs

    from .test_data_first import panel

    r, ix = (rows[0] for rows in panel())
    start = date(2022, 9, 1)
    days = [
        start + timedelta(days=n) for n in range(420) if (start + timedelta(days=n)).weekday() < 5
    ]
    stock = tuple(
        type(r).model_validate(r.model_dump() | dict(exchange_date=d, record_id=str(d)))
        for d in days
    )
    index = tuple(
        type(ix).model_validate(ix.model_dump() | dict(exchange_date=d, record_id=str(d)))
        for d in days
    )
    adjusted = tuple(
        type(r).model_validate(
            x.model_dump() | dict(price_basis="ADJUSTED", adjustment_asof=r.received_at)
        )
        for x in stock
    )
    selected, _, report = window_inputs(
        stock, adjusted, index, date(2022, 10, 17), date(2023, 10, 16)
    )
    assert len(selected) > 220 and report["warmup"] == 21
    with pytest.raises(ValueError, match="missing"):
        window_inputs(stock[:-50], adjusted, index, date(2022, 10, 17), date(2023, 10, 16))
    changed = (
        *adjusted[:-1],
        type(r).model_validate(adjusted[-1].model_dump() | dict(close=D(50), low=D(1))),
    )
    assert window_inputs(stock, changed, index, date(2022, 10, 17), date(2023, 10, 16))[2] == report
    changed = (
        *adjusted[:100],
        type(r).model_validate(adjusted[100].model_dump() | dict(close=D(50), low=D(1))),
        *adjusted[101:],
    )
    with pytest.raises(ValueError, match="corporate-action"):
        window_inputs(stock, changed, index, date(2022, 10, 17), date(2023, 10, 16))


def test_generalized_attribution_preserves_all_known_symbol_arithmetic():
    from kmast.research.attribution import attribute as original
    from kmast.research.exploratory import replay
    from kmast.research.panel_attribution import attribute as expanded

    from .test_data_first import panel, policy

    stock, index = panel()
    result = replay(stock, index, policy(), "ALPHA_A")
    assert expanded(result) == original(result)
    # Only nullable report metadata changes for an unseen symbol; no prices/cash are altered.
    changed = result | {"symbol": "014790"}
    new = expanded(changed)
    assert new["summary"]["sector_proxy"] is None
    assert new["summary"]["project_net"] == original(result)["summary"]["project_net"]
    assert new["daily"] == original(result)["daily"]


def test_complete_study_has_es_regimes_and_no_actual_execution_claim():
    from kmast.research.domestic_panel import study_reference

    from .test_data_first import panel

    stock, index = panel()
    result = study_reference(stock, index, "A1", "PARTIAL", frozenset())
    summary = result["analysis"]["summary"]
    assert summary["candidate_status"] == "EXPLORATORY_ONLY"
    assert summary["sector_contribution"] is None
    assert summary["actual_orders"] == summary["actual_cancels"] == 0
    assert all("regime" in r for r in result["analysis"]["daily"])


def test_regime_money_bridge_and_cluster_bootstrap_are_descriptive():
    from decimal import Decimal as D

    from kmast.research.domestic_panel import study_reference
    from scripts.analyze_df005 import bootstrap, regime_metrics

    from .test_data_first import panel

    stock, index = panel()
    result = study_reference(stock, index, "A1", "BASE", frozenset())
    summary = result["analysis"]["summary"] | {"window": 1}
    rows = regime_metrics(result, summary)
    for dimension in ("trend", "volatility", "liquidity"):
        bucket = [r for r in rows if r["dimension"] == dimension]
        assert sum(D(r["net"]) for r in bucket) == D(summary["project_net"])
        assert sum(r["days"] for r in bucket) == summary["days"]
        assert sum(D(r["commission"]) for r in bucket) == D(summary["commission"])
    assert bootstrap([])["p"] is None
    assert bootstrap([1] * 200)["p"] == 1 / 2001
