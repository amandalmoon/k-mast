import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kmast.brokers.kis.adapter import AccountRateLimiter, RatePolicy, TokenManager
from kmast.brokers.kis.network import (
    DataError,
    HttpReply,
    KISAuth,
    MarketClient,
    NetworkPermit,
    NetworkPolicy,
    Wire,
)
from kmast.brokers.kis.requests import MarketRequest
from kmast.brokers.kis.stream import KISStream, parse_frame
from kmast.core.clock import ReplayClock
from kmast.data.cli import fixture_run
from kmast.data.dart import parse_disclosure
from kmast.data.models import (
    CorporateAction,
    EconomicSource,
    Provenance,
    SecurityStatus,
    universe_asof,
)
from kmast.data.normalization import content_hash
from kmast.data.parsers import parse_rest
from kmast.data.pipeline import collect_rest
from kmast.data.readiness import coverage, strategy_status
from kmast.data.store import DataStore, canonical, digest, scrub

from .test_broker import config

NOW = datetime(2026, 10, 16, 0, 5, tzinfo=UTC)


def provenance(body, request, **updates):
    return Provenance.model_validate(
        dict(
            source="SYNTHETIC",
            endpoint=request.path,
            tr_id=request.tr_id,
            symbol=request.symbol,
            venue=request.venue,
            session="REGULAR",
            request_time=NOW,
            received_at=NOW,
            acquired_at=NOW,
            source_hash=digest(canonical(scrub(body))),
            ingestion_run_id="test",
            request_fingerprint=content_hash(request.model_dump(mode="json")),
            data_origin="SYNTHETIC_FIXTURE",
        )
        | updates
    )


def daily(fixture):
    case = fixture["rest"][0]
    request = MarketRequest.model_validate(case["request"])
    body = case["response"]
    return request, body, provenance(body, request)


def verified_quote_snapshots(fixture):
    # Explicitly synthetic source-date/clock proof for state-machine tests.
    case = fixture["rest"][3]
    request = MarketRequest.model_validate(case["request"])
    rows = parse_rest(case["response"], request, provenance(case["response"], request))
    return tuple(
        type(r).model_validate(
            r.model_dump()
            | {
                "event_time": NOW - timedelta(seconds=1),
                "quality_flags": (),
                "exchange_date_basis": "SOURCE_BUSINESS_DATE",
                "timestamp_precision": "SECOND",
                "availability_evidence": "SYNTHETIC_VERIFIED_SOURCE_DATE_NOT_REAL_MARKET_EVIDENCE",
            }
        )
        for r in rows
    )


class FakeWire(Wire):
    def __init__(self, replies):
        super().__init__(
            NetworkPermit(NetworkPolicy(allow_network_readonly=True, symbols=("005930",)))
        )
        self.replies = iter(replies)
        self.calls = []

    def send(self, cfg, method, path, headers, payload):
        self.calls.append((method, path, payload))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Auth:
    def approval(self, cfg):
        from pydantic import SecretStr

        return SecretStr("SYNTHETIC_APPROVAL")


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.messages = []
        self.closed = False

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, timeout=None):
        return self.messages.pop(0)

    def close(self):
        self.closed = True

    def pong(self, data):
        self.pong_data = data


def stream():
    socket = FakeSocket()
    clock = ReplayClock(NOW)
    permit = NetworkPermit(NetworkPolicy(allow_network_readonly=True, symbols=("005930", "000660")))
    result = KISStream(config(), permit, Auth(), clock, 4, timedelta(seconds=30), lambda _: socket)
    return result, socket, clock


def ack(socket, tr_id="H0STCNT0", symbol="005930"):
    socket.messages.append(
        json.dumps({"header": {"tr_id": tr_id, "tr_key": symbol}, "body": {"rt_cd": "0"}})
    )


def test_KIS_001_official_request_contract():
    request = MarketRequest(
        operation="daily", symbol="005930", start=date(2026, 10, 14), end=date(2026, 10, 15)
    )
    assert request.tr_id == "FHKST03010100"
    assert request.path.endswith("/inquire-daily-itemchartprice")
    assert request.params() == {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": "005930",
        "FID_INPUT_DATE_1": "20261014",
        "FID_INPUT_DATE_2": "20261015",
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }
    with pytest.raises(ValidationError):
        MarketRequest(operation="daily", symbol="005930")


def test_KIS_002_environment_separation():
    request = MarketRequest(
        operation="minute_history", symbol="005930", end=date(2026, 10, 15), at="09:00:00"
    )
    with pytest.raises(ValueError):
        request.require_environment(config().environment)
    request.require_environment(config("LIVE").environment)


def test_KIS_003_account_and_tr_pacing():
    tick = [0.0]
    limiter = AccountRateLimiter(lambda: tick[0])
    rate = RatePolicy(interval_seconds=1, evidence_ref="SYNTHETIC")
    limiter.acquire(config(), "FHKST03010100", rate)
    with pytest.raises(RuntimeError):
        limiter.acquire(config(), "FHKST03010200", rate)
    limiter.acquire(config(account="OTHER"), "FHKST03010200", rate)
    tick[0] = 1.0
    limiter.acquire(config(), "FHKST03010200", rate)


def client(replies):
    cfg = config()
    # Add only fake credentials through validated input; no host credential access.
    cfg = type(cfg).model_validate(
        dict(
            environment="PAPER",
            credential_environment="PAPER",
            account_environment="PAPER",
            account_ref="SYNTHETIC",
            app_key="SYNTHETIC_KEY",
            app_secret="SYNTHETIC_SECRET",
            endpoint=cfg.endpoint,
        )
    )
    clock = ReplayClock(NOW)
    wire = FakeWire(
        [
            HttpReply(status=200, body={"access_token": "SYNTHETIC_TOKEN", "expires_in": 3600}),
            *replies,
        ]
    )
    tick = [0.0]

    def sleep(seconds):
        tick[0] += seconds

    market = MarketClient(
        cfg,
        wire,
        TokenManager(cfg, KISAuth(wire, clock), clock),
        AccountRateLimiter(lambda: tick[0]),
        RatePolicy(interval_seconds=1, evidence_ref="SYNTHETIC"),
        clock,
        sleep,
    )
    return market, wire, clock


@pytest.mark.parametrize(
    "failure",
    [
        HttpReply(status=503, body={}),
        HttpReply(status=429, body={}),
        DataError("NETWORK_TIMEOUT_OR_IO"),
        HttpReply(status=200, body={"rt_cd": "1", "msg_cd": "EGW00201"}),
    ],
)
def test_KIS_004_retry_policy(failure):
    market, wire, _ = client([failure, HttpReply(status=200, body={"rt_cd": "0", "output": {}})])
    assert market.read(MarketRequest(operation="price", symbol="005930")).status == 200
    assert len(wire.calls) == 3


def test_KIS_005_subscription_and_unsubscribe():
    ws, socket, _ = stream()
    assert ws.plan(("000660",), ("005930",)) == ("000660", "005930")
    ws.connect()
    ws.subscribe("H0STCNT0", "005930")
    assert socket.sent[-1]["header"]["tr_type"] == "1"
    ack(socket)
    ws.receive()
    assert ("H0STCNT0", "005930") in ws.active
    ws.unsubscribe("H0STCNT0", "005930")
    assert socket.sent[-1]["header"]["tr_type"] == "0"
    assert not ws.active and not ws.desired


def test_KIS_006_gap_and_sync(fixture):
    ws, socket, clock = stream()
    ws.subscribe("H0STCNT0", "005930")
    ws.connect()
    ack(socket)
    ws.receive()
    quote_case = fixture["rest"][3]
    request = MarketRequest.model_validate(quote_case["request"])
    snapshots = parse_rest(
        quote_case["response"], request, provenance(quote_case["response"], request)
    )
    with pytest.raises(ValueError):
        ws.mark_synced(ws.state.generation, snapshots)
    snapshots = verified_quote_snapshots(fixture)
    ws.mark_synced(ws.state.generation, snapshots)
    assert ws.healthy()
    clock.advance(NOW + timedelta(seconds=31))
    assert not ws.healthy()
    generation = ws.state.generation
    ws.disconnect()
    ws.connect()
    assert ws.gaps and ws.state.state == "SYNCING" and not ws.healthy()
    with pytest.raises(ValueError):
        ws.mark_synced(generation, snapshots)


def test_KIS_007_closed_capability():
    with pytest.raises(ValidationError):
        MarketRequest(operation="order-cash", symbol="005930")
    permit = NetworkPermit(NetworkPolicy())
    with pytest.raises(PermissionError):
        Wire(permit).send(config(), "POST", "/uapi/domestic-stock/v1/trading/order-cash", {}, {})
    with pytest.raises(PermissionError):
        permit.consume()


def test_DATA_001_raw_provenance_hash(tmp_path, fixture):
    request, body, meta = daily(fixture)
    store = DataStore(tmp_path)
    raw = store.put_raw("identity", body, meta)
    assert raw["metadata"]["source_hash"] == digest(canonical(raw["payload"]))
    assert raw["metadata"]["symbol"] == "005930"
    assert store.cached("identity") == raw


def test_DATA_002_recollection_deduplicates(tmp_path, fixture):
    request, body, meta = daily(fixture)
    calls = []

    def acquire():
        calls.append(1)
        return body, meta

    store = DataStore(tmp_path)
    a = collect_rest(store, "daily", request, acquire)
    b = collect_rest(store, "daily", request, acquire)
    assert a == b and len(calls) == 1


def test_DATA_003_conflict_quarantine(tmp_path, fixture):
    request, body, meta = daily(fixture)
    store = DataStore(tmp_path)
    store.put_raw("same", body, meta)
    other = body | {"output1": {"changed": "1"}}
    with pytest.raises(ValueError, match="quarantined"):
        store.put_raw("same", other, provenance(other, request))
    assert len(list((tmp_path / "quarantine").glob("*.json"))) == 1
    assert store.cached("same")["payload"] == body


def test_DATA_004_time_semantics(fixture):
    request, body, meta = daily(fixture)
    records = parse_rest(body, request, meta)
    assert records[0].event_time is None
    assert all(r.available_at == NOW and r.acquired_at == NOW for r in records)
    assert {r.exchange_date for r in records} == {date(2026, 10, 14), date(2026, 10, 15)}


def test_DATA_005_future_input_blocked(fixture):
    request, body, meta = daily(fixture)
    record = parse_rest(body, request, meta)[0]
    with pytest.raises(ValueError):
        record.require_strategy_input(NOW - timedelta(seconds=1))


def test_DATA_006_incomplete_bar(fixture):
    case = fixture["rest"][1]
    request = MarketRequest.model_validate(case["request"])
    record = parse_rest(case["response"], request, provenance(case["response"], request))[0]
    assert not record.complete and "INCOMPLETE_BAR" in record.quality_flags
    with pytest.raises(ValueError):
        record.require_strategy_input(NOW + timedelta(minutes=2))


def test_DATA_007_venue_session(fixture):
    request, body, meta = daily(fixture)
    nxt = type(request).model_validate(request.model_dump() | {"venue": "NXT"})
    nxt_meta = provenance(body, nxt, session="UNKNOWN")
    record = parse_rest(body, nxt, nxt_meta)[0]
    assert record.venue == "NXT" and record.session == "UNKNOWN"
    assert "SESSION_UNVERIFIED" in record.quality_flags
    with pytest.raises(ValueError):
        parse_rest(body, nxt, meta)


def test_DATA_008_corporate_action_single_cost(fixture):
    action = CorporateAction(
        action_id="s",
        symbol="005930",
        kind="SPLIT",
        announced_at=NOW,
        effective_date=date(2026, 10, 17),
        quantity_multiplier=2,
        source_ref="SYNTHETIC",
    )
    action.require_single_recognition("RAW", True)
    with pytest.raises(ValueError):
        action.require_single_recognition("ADJUSTED", True)
    request, body, _ = daily(fixture)
    adjusted = type(request).model_validate(request.model_dump() | {"price_basis": "ADJUSTED"})
    record = parse_rest(body, adjusted, provenance(body, adjusted))[0]
    with pytest.raises(ValueError):
        record.require_strategy_input(NOW, executable_price=True)


def test_DATA_009_historical_security_status():
    fields = dict(
        symbol="005930",
        name="SYNTHETIC",
        listing_market="KOSPI",
        available_at=NOW,
        managed=False,
        classification_version="v1",
        source_ref="SYNTHETIC",
    )
    rows = (
        SecurityStatus(
            **fields, valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 15), state="LISTED"
        ),
        SecurityStatus(
            **fields, valid_from=date(2026, 10, 15), valid_to=date(2026, 10, 16), state="SUSPENDED"
        ),
        SecurityStatus(**fields, valid_from=date(2026, 10, 16), state="DELISTED"),
    )
    assert universe_asof(rows, date(2026, 10, 14), NOW) == ("005930",)
    assert universe_asof(rows, date(2026, 10, 15), NOW) == ()
    assert universe_asof(rows, date(2026, 10, 16), NOW) == ()
    assert universe_asof(rows, date(2026, 10, 14), NOW - timedelta(seconds=1)) == ()


def test_DATA_010_missing_volume_is_not_zero(fixture):
    request, body, meta = daily(fixture)
    assert any(r.volume == 0 for r in parse_rest(body, request, meta))
    row = body["output2"][0].copy()
    del row["acml_vol"]
    with pytest.raises(ValueError):
        parse_rest(body | {"output2": [row]}, request, meta)


def test_DATA_011_e2e_deterministic_storage(tmp_path):
    a = fixture_run(tmp_path / "a")
    b = fixture_run(tmp_path / "a")
    c = fixture_run(tmp_path / "b")
    assert a == b == c
    paths = sorted(
        p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*") if p.is_file()
    )
    assert any(p.suffix == ".parquet" for p in paths)
    assert all(
        (tmp_path / "a" / p).read_bytes() == (tmp_path / "b" / p).read_bytes() for p in paths
    )


def test_DATA_012_coverage_denominator(fixture):
    request, body, meta = daily(fixture)
    rows = parse_rest(body, request, meta)
    assert coverage(rows)["missing_rate"] is None
    grid = frozenset(("005930", date(2026, 10, day)) for day in (13, 14, 15))
    result = coverage(rows + rows, grid)
    assert result["observed"] == 2 and result["missing_rate"] == Decimal(1) - Decimal(2) / 3


def test_DART_001_date_is_not_publication_time(fixture):
    event = parse_disclosure(fixture["dart"][0], NOW, NOW, "SYNTHETIC_CALENDAR")
    assert event.public_event.published_at is None
    assert event.public_event.first_seen_at == NOW
    assert event.public_event.published_lower < event.public_event.published_upper <= NOW
    with pytest.raises(ValueError):
        event.public_event.require_available(NOW - timedelta(seconds=1))


def test_DART_002_correction_lineage(fixture):
    row = fixture["dart"][1]
    event = parse_disclosure(row, NOW, NOW, "SYNTHETIC_CALENDAR", row["supersedes_receipt"])
    assert event.correction and event.lineage_status == "LINKED"
    assert event.supersedes_receipt == fixture["dart"][0]["rcept_no"]
    assert row["rcept_no"] in event.original_ref
    assert parse_disclosure(row, NOW, NOW, "SYNTHETIC_CALENDAR").lineage_status == "UNRESOLVED"


def test_ECON_001_unverified_cost_sources():
    for category in ("COMMISSION", "TAX", "SERVER_COST", "DATA_COST", "SETTLED_CASH"):
        item = EconomicSource(category=category, unit="UNVERIFIED", version="v1")
        assert item.value is None and item.status == "UNVERIFIED"
    with pytest.raises(ValidationError):
        EconomicSource(category="TAX", status="VERIFIED", value="0.1", unit="RATE", version="v1")


def test_ECON_002_fixture_cannot_approve_strategy(tmp_path):
    result = fixture_run(tmp_path)
    assert result["actual_market_rows"] == 0
    assert all(
        s["status"] == "DATA_BLOCKED" and not s["economic_approval"] for s in result["strategies"]
    )
    assert strategy_status("A", ())["status"] == "DATA_BLOCKED"


def test_SEC_002_collection_redaction(tmp_path, fixture, caplog):
    request, body, _ = daily(fixture)
    secret = "SYNTHETIC_CREDENTIAL_NEVER_STORE"
    payload = body | {
        "appkey": secret,
        "output1": {"authorization": secret, "note": secret},
        "msg1": secret,
    }
    safe = scrub(payload, (secret,))
    store = DataStore(tmp_path)
    store.put_raw("safe", payload, provenance(safe, request), (secret,))
    assert secret not in store.raw_path("safe").read_text() + caplog.text


def test_SAFE_001_no_trading_after_km001():
    market, _, _ = client([])
    ws, _, _ = stream()
    for obj in (market, ws):
        for method in (obj.submit_order, obj.cancel_order):
            with pytest.raises(PermissionError):
                method()


@pytest.mark.parametrize("status", [400, 401, 403, 302])
def test_permanent_http_is_not_retried(status):
    market, wire, _ = client([HttpReply(status=status, body={})])
    with pytest.raises(DataError):
        market.read(MarketRequest(operation="price", symbol="005930"))
    assert len(wire.calls) == 2


def test_retry_budget_exhaustion():
    market, _, _ = client([HttpReply(status=503, body={})] * 3)
    with pytest.raises(DataError, match="READ_RETRY_EXHAUSTED"):
        market.read(MarketRequest(operation="price", symbol="005930"))


def test_malformed_stream_fails_closed(fixture):
    with pytest.raises(DataError):
        parse_frame("0|H0STCNT0|001|bad", NOW)
    ws, socket, _ = stream()
    ws.connect()
    socket.messages.append("NOT_A_VALID_FRAME")
    with pytest.raises(DataError):
        ws.receive()
    assert ws.state.state == "GAP" and not ws.healthy()


def test_storage_corruption_detected(tmp_path, fixture):
    request, body, meta = daily(fixture)
    store = DataStore(tmp_path)
    dataset, _ = collect_rest(store, "d", request, lambda: (body, meta))
    path = tmp_path / "normalized" / dataset / "observations.parquet"
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="corruption"):
        store.load_dataset(dataset)
