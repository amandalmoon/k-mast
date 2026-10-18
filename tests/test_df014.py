"""Synthetic transports only. Never authorize or contact a real broker."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from kmast.data.paper_collector import PaperCollector, install_control_meter
from kmast.data.paper_pilot import (
    CHANNELS,
    CONTROL_RESERVE,
    ENDPOINT,
    TARGETS,
    BoundedArchive,
    Budget,
    authorize,
    benchmark,
)
from kmast.data.store import canonical, digest
from tests.test_df005 import config
from tests.test_df013 import CONTEXT, OPEN, frame, tick


def records(tmp_path):
    proof = tmp_path / "SYNTHETIC-proof.txt"
    proof.write_bytes(b"SYNTHETIC_ONLY_NOT_HUMAN_AUTHORIZATION_OR_PREFLIGHT")
    ref = dict(verified=True, path=str(proof), sha256=digest(proof.read_bytes()))
    approval = dict(
        symbols=sorted(TARGETS),
        channels=sorted(CHANNELS),
        day="2026-10-19",
        start="08:50:00",
        end="09:25:00",
        timezone="Asia/Seoul",
        environment="PAPER",
        auth_max=1,
        connection_max=2,
        reconnect_max=1,
        subscriptions_max=8,
        unsubscriptions_max=4,
        controls_max=2400,
        outgoing_max=2412,
        raw_bytes_cap=1073741824,
        total_bytes_cap=3221225472,
        orders=False,
        accounts=False,
        live=False,
        protocol_sha256="fixture",
        human_approved=True,
        human_approval_record=ref,
    )
    preflight = {
        key: ref
        for key in [
            "security_status",
            "exchange_calendar",
            "paper_service",
            "four_subscription_entitlement",
            "subscription_hours",
            "usage_terms_fees",
            "official_endpoint",
            "transport_protection",
        ]
    }
    preflight.update(
        protocol_sha256="fixture", transport_mode="VERIFIED_PROTECTED_PATH", endpoint=ENDPOINT
    )
    return approval, preflight


def collector(tmp_path, **kwargs):
    approval, preflight = records(tmp_path)
    return PaperCollector(
        tmp_path / "pilot",
        config("PAPER"),
        approval,
        preflight,
        "fixture",
        now=lambda: OPEN,
        **kwargs,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "disabled",
        "LIVE",
        "old_approval",
        "symbol",
        "channel",
        "time",
        "budget",
        "transport",
        "security",
        "clock_naive",
        "before",
        "after",
        "other_day",
    ],
)
def test_exact_gate_rejects_before_any_io(tmp_path, fault, monkeypatch):
    approval, preflight = records(tmp_path)
    now, enabled, env = OPEN, True, "PAPER"
    if fault == "disabled":
        enabled = False
    elif fault == "LIVE":
        env = "LIVE"
    elif fault == "old_approval":
        approval["human_approved"] = False
    elif fault == "symbol":
        approval["symbols"] = ["005930", "462860"]
    elif fault == "channel":
        approval["channels"] = ["H0STCNT0", "H0STCNI9"]
    elif fault == "time":
        approval["end"] = "10:00:00"
    elif fault == "budget":
        approval["auth_max"] = 2
    elif fault == "transport":
        preflight["transport_mode"] = "ACCEPT_PLAINTEXT_RISK"
    elif fault == "security":
        preflight["security_status"] = dict(verified=False)
    elif fault == "clock_naive":
        now = OPEN.replace(tzinfo=None)
    elif fault == "before":
        now = OPEN.replace(hour=8, minute=49)
    elif fault == "after":
        now = OPEN.replace(minute=25)
    elif fault == "other_day":
        now = OPEN + timedelta(days=1)
    with pytest.raises(PermissionError):
        authorize(approval, preflight, "fixture", now, enabled=enabled, environment=env)


def test_disabled_collector_never_constructs_auth_or_socket(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "kmast.data.paper_collector.http.client.HTTPSConnection", lambda *a, **k: calls.append(a)
    )
    c = collector(tmp_path)
    with pytest.raises(PermissionError):
        c.collect()
    assert calls == [] and c.budget.used["AUTH"] == 0


def test_failed_auth_is_hash_only_and_never_refunded(tmp_path, monkeypatch):
    c = collector(tmp_path, enabled=True)
    secret = c.config.app_key.get_secret_value()
    raw = json.dumps(dict(msg_cd="DENIED", echo=secret)).encode()

    class Failed:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            assert Budget(c.root / "control").used["AUTH"] == 1

        def getresponse(self):
            return SimpleNamespace(status=401, read=lambda _: raw)

        def close(self):
            pass

    monkeypatch.setattr("kmast.data.paper_collector.http.client.HTTPSConnection", Failed)
    with pytest.raises(PermissionError):
        c.issue()
    with pytest.raises(PermissionError):
        c.issue()
    assert Budget(c.root / "control").used["AUTH"] == 1
    assert all(secret.encode() not in p.read_bytes() for p in c.root.rglob("*") if p.is_file())


@pytest.mark.parametrize("kind,cap", [("AUTH", 1), ("CONNECT", 2), ("SUB", 8), ("UNSUB", 4)])
def test_persistent_limits_survive_restart(tmp_path, kind, cap):
    for _ in range(cap):
        Budget(tmp_path).reserve(kind)
    with pytest.raises(PermissionError):
        Budget(tmp_path).reserve(kind)


def test_reservation_journal_detects_tampering(tmp_path):
    Budget(tmp_path).reserve("AUTH")
    path = next((tmp_path / "reservations").glob("*.json"))
    obj = json.loads(path.read_bytes())
    obj["sequence"] = 2
    path.write_bytes(canonical(obj))
    with pytest.raises(ValueError):
        Budget(tmp_path)


def test_library_control_frames_are_counted_before_send(tmp_path, monkeypatch):
    from websockets.frames import OP_PONG, Frame

    import kmast.data.paper_pilot as module

    monkeypatch.setitem(module.CAPS, "CONTROL", 2)
    emitted = []
    protocol = SimpleNamespace(send_frame=lambda frame: emitted.append(frame))
    budget = Budget(tmp_path)
    install_control_meter(protocol, budget, lambda: OPEN)
    protocol.send_frame(Frame(OP_PONG, b"SYNTHETIC"))
    protocol.send_frame(Frame(OP_PONG, b"SYNTHETIC"))
    with pytest.raises(PermissionError):
        protocol.send_frame(Frame(OP_PONG, b"excess"))
    assert len(emitted) == 2 and Budget(tmp_path).used["CONTROL"] == 2


def test_subscription_scope_and_caps_do_not_log_key(tmp_path):
    c = collector(tmp_path, enabled=True)
    c.token = "SYNTHETIC-SECRET-APPROVAL"
    socket = SimpleNamespace(send=lambda value: None)
    with pytest.raises(PermissionError):
        c.send(socket, "SUB", "H0STCNI9", "073240")
    for _ in range(8):
        c.send(socket, "SUB", "H0STCNT0", "073240")
    with pytest.raises(PermissionError):
        c.send(socket, "SUB", "H0STCNT0", "073240")
    assert all(c.token.encode() not in p.read_bytes() for p in c.root.rglob("*") if p.is_file())


def test_two_failed_connections_use_one_auth_and_never_live(tmp_path, monkeypatch):
    import kmast.data.paper_collector as module

    c = collector(tmp_path, enabled=True)

    def issue():
        c.budget.reserve("AUTH")
        c.token = "SYNTHETIC-APPROVAL"

    c.issue = issue
    calls = []

    def connect(*args):
        calls.append(ENDPOINT)
        raise OSError("secret must be suppressed")

    c.connector = connect
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    result = c.collect()
    assert calls == [ENDPOINT, ENDPOINT]
    assert result["budget"]["AUTH"] == 1 and result["budget"]["CONNECT"] == 2
    assert c.token is None


@pytest.mark.parametrize("cap", ["raw", "total"])
def test_caps_stop_before_writing(tmp_path, cap):
    store = BoundedArchive(
        tmp_path,
        raw_cap=1 if cap == "raw" else 1073741824,
        total_cap=CONTROL_RESERVE + (16 if cap == "total" else 1000000),
    )
    with pytest.raises(PermissionError):
        store.append(frame(), tick().receipt, CONTEXT, ())
    assert not list(tmp_path.rglob("*.bin"))


def test_segmented_archive_reopens_checks_raw_and_incomplete_journal(tmp_path):
    store = BoundedArchive(tmp_path)
    store.append(frame(), tick().receipt, CONTEXT, ())
    store.metadata(dict(origin="SYNTHETIC", complete=True))
    reopened = BoundedArchive(tmp_path)
    assert reopened.frames == 1 and reopened.raw_used == len(frame())
    wire = next(tmp_path.rglob("*.bin"))
    wire.write_bytes(b"bad")
    with pytest.raises((AssertionError, ValueError)):
        BoundedArchive(tmp_path)


def test_partial_jsonl_and_orphan_receipt_fail_closed(tmp_path):
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "observations.jsonl").write_bytes(b'{"unfinished":')
    with pytest.raises(ValueError):
        BoundedArchive(tmp_path)


def test_single_process_lock(tmp_path):
    from kmast.data.panel_acquisition import process_lock

    with process_lock(tmp_path / "process.lock"):
        with pytest.raises(PermissionError):
            with process_lock(tmp_path / "process.lock"):
                pass


def test_quotation_filter_keeps_global_and_per_symbol_receipts_separate(tmp_path):
    c = collector(tmp_path)
    c.now = lambda: OPEN + timedelta(seconds=1)
    c.generation = 1
    receipt = replace(tick().receipt, connection="DF014-1", sequence=7)
    c.process(None, frame(MKSC_SHRN_ISCD="073240"), receipt)
    assert c.real_frames == 0  # Synthetic never promoted to observed evidence.
    assert "UNACKNOWLEDGED_DATA" in c.engines["073240"].defects
    rows = [
        json.loads(line) for line in (c.store.data / "observations.jsonl").read_bytes().splitlines()
    ]
    assert rows[0]["sequence"] == 7 and rows[0]["filtered_symbol_frame_sequence"] == 1
    assert rows[0]["origin"] == "SYNTHETIC"
    assert "MARKET_STATE_UNKNOWN" in rows[0]["source_flags"][0]
    assert c.engines["073240"].range_high(5, OPEN + timedelta(minutes=6)) is None


def test_sensitive_ack_and_malformed_frame_are_hash_only(tmp_path):
    c = collector(tmp_path)
    c.token = "SYNTHETIC-APPROVAL-SECRET"
    with pytest.raises(RuntimeError):
        c.process(None, json.dumps(dict(approval_key=c.token)).encode(), tick().receipt)
    c.process(None, b"0|H0STCNT0|1|malformed", replace(tick().receipt, sequence=2))
    assert not list(c.root.rglob("*.bin"))
    assert all(c.token.encode() not in p.read_bytes() for p in c.root.rglob("*") if p.is_file())


def test_synthetic_storage_benchmark_is_not_market_rate(tmp_path):
    result = benchmark(tmp_path, frame(), CONTEXT, count=4)
    assert result["origin"] == "SYNTHETIC" and result["frames"] == 4
    assert result["measured_provider_rate"] is None


def test_successful_approval_is_memory_only(tmp_path, monkeypatch):
    c = collector(tmp_path, enabled=True)
    token = "SYNTHETIC-SUCCESS-APPROVAL-KEY"

    class Success:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return SimpleNamespace(
                status=200, read=lambda _: json.dumps(dict(approval_key=token)).encode()
            )

        def close(self):
            pass

    monkeypatch.setattr("kmast.data.paper_collector.http.client.HTTPSConnection", Success)
    c.issue()
    assert c.token == token and c.state == "APPROVED"
    assert all(token.encode() not in p.read_bytes() for p in c.root.rglob("*") if p.is_file())


def test_ack_is_requested_scoped_and_does_not_retain_crypto_body(tmp_path):
    c = collector(tmp_path)
    c.now = lambda: OPEN + timedelta(seconds=1)
    c.pending[("H0STCNT0", "073240")] = "SUB"
    raw = json.dumps(
        dict(
            header=dict(tr_id="H0STCNT0", tr_key="073240"),
            body=dict(rt_cd="0", output=dict(key="SYNTHETIC-AES-SECRET")),
        )
    ).encode()
    c.process(None, raw, tick().receipt)
    assert ("H0STCNT0", "073240") in c.active
    assert all(
        b"SYNTHETIC-AES-SECRET" not in p.read_bytes() for p in c.root.rglob("*") if p.is_file()
    )
    with pytest.raises(RuntimeError):
        c.process(None, raw, replace(tick().receipt, sequence=2))


def test_outside_window_received_data_cannot_become_an_observation(tmp_path):
    c = collector(tmp_path)
    r = replace(tick().receipt, origin="OBSERVED", received_at=OPEN.replace(minute=25))
    with pytest.raises(PermissionError):
        c.process(None, frame(), r)
    assert not list(c.root.rglob("*.bin"))


def test_cli_never_echoes_unrecognized_secret_input():
    import subprocess
    import sys

    secret = "SYNTHETIC-CLI-SECRET-DO-NOT-ECHO"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.collect_df014", "--unknown", secret], capture_output=True
    )
    assert result.returncode != 0
    assert secret.encode() not in result.stdout + result.stderr
