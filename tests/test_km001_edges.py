import json
from datetime import date, timedelta

import pytest

from kmast.brokers.kis.adapter import TokenManager
from kmast.brokers.kis.network import DataError, NetworkPermit, NetworkPolicy, Wire
from kmast.brokers.kis.requests import MarketRequest
from kmast.brokers.kis.wire_contract import validate_read_payload
from kmast.core.clock import ReplayClock
from kmast.data.dart import DisclosureRegistry, parse_disclosure
from kmast.data.pipeline import collect_rest
from kmast.data.sessions import SessionInterval, classify_session
from kmast.data.store import DataStore

from .test_broker import Provider, config
from .test_km001 import NOW, ack, client, daily, stream, verified_quote_snapshots


def test_real_wire_without_real_network(monkeypatch):
    observed = []

    class Response:
        status = 200

        def read(self, maximum):
            return b'{"rt_cd":"0","output":{}}'

        def getheader(self, key, default):
            return default

    class Connection:
        def __init__(self, host, port, timeout):
            observed.append((host, port, timeout))

        def request(self, method, query, body, headers):
            observed.append((method, query, body))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    permit = NetworkPermit(NetworkPolicy(allow_network_readonly=True, symbols=("005930",)))
    request = MarketRequest(operation="price", symbol="005930")
    assert Wire(permit).send(config(), "GET", request.path, {}, request.params()).status == 200
    assert observed[0][0] == "openapivts.koreainvestment.com"
    assert "FID_INPUT_ISCD=005930" in observed[1][1]
    assert permit.used == 1


@pytest.mark.parametrize(
    "path",
    ["/oauth2/revokeP", "/uapi/domestic-stock/v1/trading/order-rvsecncl", "/oauth2/tokenP?evil=1"],
)
def test_other_posts_rejected(path):
    with pytest.raises(PermissionError):
        Wire(NetworkPermit(NetworkPolicy())).send(config(), "POST", path, {}, {})


def test_wire_scope_cannot_be_bypassed():
    request = MarketRequest(operation="price", symbol="000660")
    permit = NetworkPermit(NetworkPolicy(allow_network_readonly=True, symbols=("005930",)))
    with pytest.raises(PermissionError):
        Wire(permit).send(config(), "GET", request.path, {}, request.params())
    with pytest.raises(PermissionError):
        validate_read_payload(config(), request.path, request.params() | {"ARBITRARY": "x"})


def test_wrong_request_cache_is_rejected(tmp_path, fixture):
    request, body, meta = daily(fixture)
    store = DataStore(tmp_path)
    collect_rest(store, "same", request, lambda: (body, meta))
    new = type(request).model_validate(request.model_dump() | {"start": date(2026, 10, 13)})
    with pytest.raises(ValueError, match="parameters"):
        collect_rest(store, "same", new, lambda: (body, meta))


def test_disclosure_registry_checks_actual_parent(fixture):
    registry = DisclosureRegistry()
    first = parse_disclosure(fixture["dart"][0], NOW, NOW, "SYNTHETIC")
    correction = parse_disclosure(fixture["dart"][1], NOW, NOW, "SYNTHETIC", first.rcept_no)
    with pytest.raises(ValueError):
        registry.add(correction)
    registry.add(first)
    registry.add(correction)
    registry.add(correction)
    assert len(registry.items) == 2


def test_session_calendar_does_not_invent_weekdays():
    row = SessionInterval(
        venue="KRX",
        session="REGULAR",
        start=NOW,
        end=NOW + timedelta(hours=6),
        available_at=NOW,
        calendar_version="SYNTHETIC",
        source_ref="SYNTHETIC",
    )
    assert classify_session((row,), "KRX", NOW, NOW) == "REGULAR"
    assert classify_session((row,), "NXT", NOW, NOW) == "UNKNOWN"
    assert classify_session((row,), "KRX", NOW, NOW - timedelta(seconds=1)) == "UNKNOWN"
    with pytest.raises(ValueError):
        classify_session((row, row), "KRX", NOW, NOW)


def test_unsubscribe_ack_and_ping_are_control_not_data():
    ws, socket, _ = stream()
    ws.connect()
    ws.subscribe("H0STCNT0", "005930")
    ack(socket)
    ws.receive()
    ws.unsubscribe("H0STCNT0", "005930")
    ack(socket)
    assert ws.receive() == ()
    socket.messages.append(json.dumps({"header": {"tr_id": "PINGPONG"}}))
    assert ws.receive() == ()
    assert b"PINGPONG" in socket.pong_data
    assert not ws.healthy()


def test_automatic_reconnect_keeps_gap():
    ws, socket, _ = stream()
    ws.subscribe("H0STCNT0", "005930")
    socket.messages.append("BAD_FRAME")
    ack(socket)
    assert ws.collect(2, reconnect_attempts=1, sleep=lambda _: None) == ()
    assert ws.gaps and ws.state.state == "SYNCING"
    assert not ws.healthy()


def test_auth_response_clock_progress_is_valid():
    clock = ReplayClock(NOW)

    class SlowProvider(Provider):
        def issue(self, cfg):
            clock.advance(NOW + timedelta(seconds=2))
            return super().issue(cfg)

    manager = TokenManager(config(), SlowProvider(clock), clock)
    assert manager.get().issued_at == NOW + timedelta(seconds=2)


def test_daily_pagination_cursor_and_budget(fixture):
    from kmast.brokers.kis.network import HttpReply
    from kmast.brokers.kis.pagination import daily_pages

    request, body, _ = daily(fixture)
    row14 = next(row for row in body["output2"] if row["stck_bsop_date"] == "20261014")
    row15 = next(row for row in body["output2"] if row["stck_bsop_date"] == "20261015")
    market, wire, _ = client(
        [
            HttpReply(status=200, body={"rt_cd": "0", "output2": [row15]}),
            HttpReply(status=200, body={"rt_cd": "0", "output2": [row14]}),
        ]
    )
    pages = daily_pages(market, request, max_pages=2)
    assert len(pages) == 2 and pages[1][0].end == date(2026, 10, 14)
    assert len(wire.calls) == 3


def test_automatic_snapshot_sync(fixture):
    ws, socket, _ = stream()
    ws.snapshot_provider = lambda symbols: verified_quote_snapshots(fixture)
    ws.subscribe("H0STCNT0", "005930")
    ack(socket)
    ws.collect(1)
    assert ws.healthy()


def test_expired_broker_token_not_retried():
    from kmast.brokers.kis.network import HttpReply

    market, wire, _ = client([HttpReply(status=200, body={"rt_cd": "1", "msg_cd": "EGW00123"})])
    with pytest.raises(DataError, match="AUTH_REJECTED"):
        market.read(MarketRequest(operation="price", symbol="005930"))
    assert len(wire.calls) == 2


def test_public_stock_name_is_not_mistaken_for_hts_identity():
    from kmast.data.store import scrub

    assert scrub({"hts_kor_isnm": "SYNTHETIC_STOCK", "hts_id": "PRIVATE"}) == {
        "hts_kor_isnm": "SYNTHETIC_STOCK"
    }
