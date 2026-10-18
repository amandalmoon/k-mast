"""DF015 production interlock and offline fault tests. No network access."""

from datetime import UTC, timedelta

import pytest

from kmast.data.paper_collector import connect_paper
from kmast.data.paper_pilot import ENDPOINT, authorize
from kmast.data.paper_security import pilot_disposition, require_secure_transport
from scripts.stress_df015 import run
from tests.test_df013 import OPEN
from tests.test_df014 import collector, records


@pytest.mark.parametrize(
    "endpoint",
    [
        ENDPOINT,
        "wss://ops.koreainvestment.com:31000",
        "wss://unverified.invalid",
        "ws://localhost:31000",
        "https://unverified.invalid",
        "SYNTHETIC-SECRET",
    ],
)
def test_no_json_or_url_can_register_a_secure_route(endpoint):
    with pytest.raises(PermissionError) as exc:
        require_secure_transport(endpoint, "PAPER", OPEN)
    assert endpoint not in str(exc.value)


@pytest.mark.parametrize(
    "mutation", ["forged", "stale", "endpoint", "vpn", "proxy", "last_hop", "certificate", "mode"]
)
def test_forged_paperwork_cannot_issue_key_or_send(tmp_path, monkeypatch, mutation):
    c = collector(tmp_path, enabled=True)
    # Legacy verified/hash paperwork passes even though its contents explicitly
    # say SYNTHETIC. DF015 must add an independent production boundary.
    authorize(c.approval, c.preflight, "fixture", OPEN, enabled=True, environment="PAPER")
    c.preflight.update({mutation: True, "verified": True, "tls_verified": True})
    if mutation == "endpoint":
        c.preflight["endpoint"] = "wss://unverified.invalid"
    if mutation == "stale":
        c.approval["approved_at"] = "2025-01-01T00:00:00+09:00"
    called = []
    monkeypatch.setattr(
        "kmast.data.paper_collector.http.client.HTTPSConnection",
        lambda *a, **k: called.append("HTTP"),
    )
    c.connector = lambda *a: called.append("WS")
    c.token = "SYNTHETIC-TOKEN"
    for operation in (c.issue, c.collect, lambda: c.send(None, "SUB", "H0STCNT0", "073240")):
        with pytest.raises(PermissionError):
            operation()
    assert called == [] and c.budget.used["AUTH"] == c.budget.used["CONNECT"] == 0
    assert not (c.root / "control/authorization.json").exists()


def test_direct_socket_entry_denied_before_library_connect(tmp_path, monkeypatch):
    import websockets.sync.client

    calls = []
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *a, **k: calls.append(a))
    c = collector(tmp_path)
    with pytest.raises(PermissionError):
        connect_paper(c.budget, lambda: OPEN)
    assert calls == []


def test_cli_denies_before_records_keys_and_collector(tmp_path, monkeypatch, capsys):
    import scripts.collect_df014 as cli

    secret = "SYNTHETIC-SECRET-PATH"
    calls = []
    monkeypatch.setattr(
        "sys.argv",
        [
            "collect",
            "--execute-approved-paper",
            "--approval-record",
            secret,
            "--preflight-record",
            secret,
        ],
    )
    monkeypatch.setattr(cli, "load_env", lambda *a: calls.append("KEY"))
    monkeypatch.setattr(cli, "PaperCollector", lambda *a, **k: calls.append("COLLECT"))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert calls == [] and secret not in str(exc.value)
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize(
    "delta,status",
    [
        (timedelta(minutes=-11), "DF014_FROZEN_WINDOW_NOT_OPEN"),
        (timedelta(minutes=-10), "DF014_PILOT_PENDING_APPROVAL"),
        (timedelta(minutes=24, seconds=59), "DF014_PILOT_PENDING_APPROVAL"),
        (timedelta(minutes=25), "DF014_MISSED_OBSERVATION_WINDOW"),
        (timedelta(days=1), "DF014_MISSED_OBSERVATION_WINDOW"),
    ],
)
def test_frozen_window_expiry_never_reschedules(delta, status):
    now = OPEN + delta
    assert pilot_disposition(now) == pilot_disposition(now.astimezone(UTC)) == status
    with pytest.raises(PermissionError):
        require_secure_transport(ENDPOINT, "PAPER", now)


def test_naive_clock_cannot_authorize():
    with pytest.raises(PermissionError):
        require_secure_transport(ENDPOINT, "PAPER", OPEN.replace(tzinfo=None))


@pytest.mark.parametrize("environment", ["LIVE", "PROD", "paper", "SYNTHETIC-SECRET"])
def test_no_environment_fallback(environment):
    with pytest.raises(PermissionError) as exc:
        require_secure_transport(ENDPOINT, environment, OPEN)
    assert str(exc.value) == "PAPER_ONLY_NO_LIVE_FALLBACK"


def test_actual_endpoint_cannot_change_after_document_validation(tmp_path, monkeypatch):
    c = collector(tmp_path, enabled=True)
    approval, preflight = records(tmp_path)
    c.approval, c.preflight = approval, preflight
    monkeypatch.setattr("kmast.data.paper_collector.ENDPOINT", "wss://unverified.invalid")
    with pytest.raises(PermissionError):
        c.issue()
    assert c.budget.used["AUTH"] == 0


def test_unknown_market_context_is_still_not_research_ready(tmp_path):
    c = collector(tmp_path)
    assert all(
        not e.context.continuous_verified and not e.context.corrections_verified
        for e in c.engines.values()
    )
    assert all(e.range_high(5, OPEN + timedelta(minutes=6)) is None for e in c.engines.values())


def test_synthetic_fault_matrix_retains_caps_and_failures(tmp_path):
    report = run(tmp_path)
    assert len(report["cases"]) == 10
    assert report["origin"] == "SYNTHETIC" and report["actual_market_frames"] == 0
    assert report["raw_cap"] == 1073741824 and report["total_cap"] == 3221225472
    assert report["real_provider_rate"] is None
