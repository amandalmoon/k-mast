"""Synthetic transport checks only; never market or economic evidence."""

from datetime import date
from types import SimpleNamespace

import pytest

from kmast.brokers.kis.requests import MarketRequest
from kmast.data.pilot_acquisition import PilotWire
from tests.test_df005 import config

SYMBOLS = ("131290", "081660", "002840")


def request():
    return MarketRequest(
        operation="daily", symbol="131290", start=date(2022, 10, 27), end=date(2023, 1, 25)
    )


@pytest.mark.parametrize("change", ["disabled", "live", "symbol", "date", "order", "account"])
def test_scope_denied_before_budget_or_io(tmp_path, change):
    wire = PilotWire(tmp_path, SYMBOLS, enabled=change != "disabled")
    r = request()
    params, path = r.params(), r.path
    if change == "symbol":
        params["FID_INPUT_ISCD"] = "005930"
    if change == "date":
        params["FID_INPUT_DATE_2"] = "20230126"
    if change == "order":
        path = "/uapi/domestic-stock/v1/trading/order-cash"
    if change == "account":
        params["CANO"] = "fixture"
    with pytest.raises(PermissionError):
        wire.send(
            config("LIVE" if change == "live" else "PAPER"), "GET", path, {"tr_id": r.tr_id}, params
        )
    assert wire.state["requests"] == 0


def test_failed_response_counted_preserved_and_completion_spacing(tmp_path, monkeypatch):
    import kmast.data.pilot_acquisition as module

    now, starts = [100.0], []
    body = b'{"rt_cd":"1","msg1":"fixture failure"}'

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            # Reservation must survive before any network I/O.
            import json

            state = json.loads((tmp_path / "budget.json").read_bytes())
            assert state["response_pending"]
            assert state["requests"] == len(starts) + 1
            starts.append(now[0])

        def getresponse(self):
            now[0] += 0.75
            return SimpleNamespace(status=500, read=lambda _: body)

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    monkeypatch.setattr(module.time, "perf_counter", lambda: now[0])
    # Simulate early waking; collector must recheck instead of trusting one sleep.
    monkeypatch.setattr(
        module.time, "sleep", lambda s: now.__setitem__(0, now[0] + s * 0.9 + 0.00001)
    )
    wire = PilotWire(tmp_path, SYMBOLS, enabled=True)
    r = request()
    for _ in range(2):
        assert wire.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params()).status == 500
    assert starts[1] - starts[0] - 0.75 >= 3.10
    assert wire.state["requests"] == 2
    assert len(list((tmp_path / "wire").glob("*.bin"))) == 1
    with pytest.raises(PermissionError, match="RETRY"):
        wire.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params())
    resumed = PilotWire(tmp_path, SYMBOLS, enabled=True)
    with pytest.raises(PermissionError, match="RETRY"):
        resumed.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params())


def test_total_budget_and_auth_limit_fail_before_io(tmp_path):
    wire = PilotWire(tmp_path, SYMBOLS, enabled=True)
    r = request()
    wire.state["requests"] = 20
    with pytest.raises(PermissionError, match="BUDGET"):
        wire.send(config(), "GET", r.path, {"tr_id": r.tr_id}, r.params())
    wire.state["requests"] = 0
    wire.state["authentication"] = 2
    with pytest.raises(PermissionError, match="BUDGET"):
        wire.send(
            config(),
            "POST",
            "/oauth2/tokenP",
            {},
            {"grant_type": "client_credentials", "appkey": "fixture", "appsecret": "fixture"},
        )


@pytest.mark.parametrize(
    "field,value",
    [("flng_cls_code", "02"), ("prtt_rate", "1.0"), ("mod_yn", "Y"), ("revl_issu_reas", "UNKNOWN")],
)
def test_unresolved_actions_hold_only_affected_window(field, value):
    from scripts.evaluate_df010 import unresolved_action_flags

    row = {
        "stck_bsop_date": "20221228",
        "flng_cls_code": "00",
        "prtt_rate": "0.00",
        "mod_yn": "N",
        "revl_issu_reas": "",
    }
    row[field] = value
    assert unresolved_action_flags({"output2": [row]}, {"20221228"})
    assert not unresolved_action_flags({"output2": [row]}, {"20250317"})
