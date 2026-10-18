"""Synthetic PAPER transports only. Production review registry remains empty."""

import json
import ssl
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import kmast.data.https_bar_gate as gate
from kmast.data.https_bar_collector import Collector, PaperHTTPS, Reply, safe_market_body
from kmast.data.https_bar_quality import diagnose, requery_changes
from kmast.data.https_bar_store import Journal
from kmast.data.store import canonical, digest
from tests.test_df005 import config
from tests.test_df016 import payload, row

RAW = Path("artifacts/df016/PILOT_PROPOSAL.json").read_bytes()
PLAN = json.loads(RAW)


class Clock:
    def __init__(self, now=gate.START):
        self.time, self.nanos = now, 0

    def now(self):
        return self.time

    def mono(self):
        return self.nanos

    def sleep(self, seconds):
        self.time += timedelta(seconds=seconds)
        self.nanos += round(seconds * 1e9)


def proofs(tmp_path, monkeypatch, *, registered=True):
    path = tmp_path / "SYNTHETIC_NOT_REAL_REVIEW.txt"
    path.write_bytes(b"SYNTHETIC_ONLY_NOT_HUMAN_OR_SERVICE_OR_RIGHTS_APPROVAL")
    ref = dict(path=str(path), sha256=digest(path.read_bytes()), reviewed=True)
    approval = dict(
        proposal_sha256=gate.PROPOSAL_HASH,
        scope=PLAN["scope"],
        approved=True,
        environment="PAPER",
        issued_at=(gate.START - timedelta(days=1)).isoformat(),
        expires_at=gate.END.isoformat(),
        statement_path=str(path),
        statement_sha256=ref["sha256"],
    )
    preflight = dict(
        environment="PAPER",
        host=gate.ROOT_URL,
        day="2026-10-20",
        symbols=["073240", "462860"],
        venue="J",
        retention_days=30,
        storage_research_allowed=True,
        hash_retention_allowed=True,
        clock_error_bound_seconds=0.1,
        provider_interval_seconds=3.10,
        **{
            k: ref.copy()
            for k in ("service", "rate", "rights", "calendar", "security_status", "clock", "https")
        },
    )
    if registered:
        monkeypatch.setattr(
            gate,
            "TRUSTED_REVIEWS",
            frozenset({(digest(canonical(approval)), digest(canonical(preflight)))}),
        )
    return approval, preflight


class Wire:
    origin = "SYNTHETIC"

    def __init__(self, statuses=None, auth_status=200, error=None, delay=1, echo=None):
        self.calls, self.statuses, self.auth_status = [], statuses or {}, auth_status
        self.error, self.delay, self.echo = error, delay, echo

    def exchange(self, ordinal, call, config, token, clock):
        request, mono = clock.now(), clock.mono()
        self.calls.append((ordinal, request, mono, call))
        attempt = sum(c[0] == ordinal for c in self.calls)
        status = self.auth_status if ordinal == 0 else self.statuses.get((ordinal, attempt), 200)
        if ordinal == 0:
            raw = json.dumps(dict(access_token="SYNTHETIC-MEMORY-ONLY-TOKEN")).encode()
        elif call["tr_id"] == "FHKST03010200":
            raw = payload([row(i) for i in range(5)])
        elif call["tr_id"] == "FHKST01010200":
            raw = json.dumps(
                dict(
                    rt_cd="0",
                    output1=dict(
                        aspr_acpt_hour=request.strftime("%H%M%S"),
                        bidp1="100",
                        askp1="101",
                        bidp_rsqn1="10",
                        askp_rsqn1="10",
                    ),
                )
            ).encode()
        else:
            raw = json.dumps(
                dict(
                    rt_cd="0",
                    output2=[
                        dict(
                            stck_cntg_hour="090000",
                            stck_prpr="100",
                            cnqn="1",
                            acml_vol="1",
                            askp="101",
                            bidp="100",
                        )
                    ],
                )
            ).encode()
        if self.echo is not None and ordinal > 0:
            raw = json.dumps(dict(rt_cd="1", msg1=self.echo)).encode()
        clock.sleep(self.delay)
        return Reply(
            status,
            raw,
            request,
            mono,
            clock.now(),
            clock.mono(),
            self.error if ordinal else None,
            7 if status == 429 else 0,
            True,
        )


def collector(tmp_path, monkeypatch, **kwargs):
    approval, preflight = proofs(tmp_path, monkeypatch)
    wire = kwargs.pop("transport", Wire())
    clock = kwargs.pop("clock", Clock())
    return (
        Collector(
            tmp_path / "pilot",
            RAW,
            approval,
            preflight,
            lambda: config("PAPER"),
            enabled=True,
            clock=clock,
            transport=wire,
            **kwargs,
        ),
        wire,
        clock,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "disabled",
        "unregistered",
        "rights",
        "service",
        "rate",
        "clock",
        "https",
        "calendar",
        "security_status",
        "stale",
        "scope",
        "host",
        "LIVE",
        "statement",
    ],
)
def test_unapproved_or_missing_proof_never_loads_keys_or_constructs_http(
    tmp_path, monkeypatch, fault
):
    a, p = proofs(tmp_path, monkeypatch, registered=False)
    enabled = True
    if fault == "disabled":
        enabled = False
    elif fault in {"rights", "service", "rate", "clock", "https", "calendar", "security_status"}:
        p[fault]["reviewed"] = False
    elif fault == "stale":
        a["issued_at"] = (gate.START - timedelta(days=4)).isoformat()
    elif fault == "scope":
        a["scope"] = {}
    elif fault == "host":
        p["host"] = "https://unverified.invalid"
    elif fault == "LIVE":
        a["environment"] = "LIVE"
    elif fault == "statement":
        a["statement_sha256"] = "0" * 64
    if fault != "unregistered":
        monkeypatch.setattr(
            gate, "TRUSTED_REVIEWS", frozenset({(digest(canonical(a)), digest(canonical(p)))})
        )
    called = []
    monkeypatch.setattr(
        "kmast.data.https_bar_collector.http.client.HTTPSConnection",
        lambda *a, **k: called.append("HTTP"),
    )
    c = Collector(
        tmp_path / "never", RAW, a, p, lambda: called.append("KEY"), enabled=enabled, clock=Clock()
    )
    with pytest.raises(PermissionError):
        c.run()
    assert called == [] and not c.root.exists()


def test_22_exact_queries_and_completion_based_cooldown(tmp_path, monkeypatch):
    c, w, clock = collector(tmp_path, monkeypatch)
    result = c.run()
    assert result["attempted"] == 23 and c.token is None and result["origin"] == "SYNTHETIC"
    assert [x[0] for x in w.calls] == list(range(23))
    for previous, current in zip(w.calls, w.calls[1:], strict=False):
        assert (current[2] - previous[2]) / 1e9 >= 4.10 - 1e-6
    for ordinal, stamp, _, call in w.calls[1:]:
        assert call == PLAN["calls"][ordinal - 1] and stamp >= gate.earliest(call)
    outcomes = list((c.root / "outcomes").glob("*.json"))
    assert len(outcomes) == 23
    assert all(
        b"SYNTHETIC-MEMORY-ONLY-TOKEN" not in f.read_bytes()
        for f in c.root.rglob("*")
        if f.is_file()
    )


@pytest.mark.parametrize("status", [401, 429, 500])
def test_auth_errors_consume_single_attempt_no_reissue(tmp_path, monkeypatch, status):
    c, w, _ = collector(tmp_path, monkeypatch, transport=Wire(auth_status=status))
    with pytest.raises(PermissionError):
        c.run()
    assert len(w.calls) == 1 and c.token is None
    j = Journal(c.root, json.loads((c.root / "binding.json").read_bytes()))
    assert len(j.reservations) == 1
    with pytest.raises(PermissionError):
        c.run()
    assert len(w.calls) == 1


@pytest.mark.parametrize("status", [429, 500])
def test_price_retry_and_stricter_retry_after_remain_spent(tmp_path, monkeypatch, status):
    c, w, _ = collector(tmp_path, monkeypatch, transport=Wire(statuses={(1, 1): status}))
    c.run()
    first = [x for x in w.calls if x[0] == 1]
    assert len(w.calls) == 24 and len(first) == 2
    assert (first[1][2] - first[0][2]) / 1e9 >= (8 if status == 429 else 4.10) - 1e-6
    with pytest.raises(PermissionError):
        c.run()
    assert len(w.calls) == 24


@pytest.mark.parametrize("mutation", ["url", "venue", "symbol", "tr_id", "hour", "order"])
def test_modified_frozen_queries_cannot_reach_transport(mutation):
    call = json.loads(canonical(PLAN["calls"][0]))
    if mutation == "url":
        call["url"] = "https://unverified.invalid/account"
    elif mutation == "venue":
        call["parameters"]["FID_COND_MRKT_DIV_CODE"] = "UN"
    elif mutation == "symbol":
        call["symbol"] = "005930"
    elif mutation == "tr_id":
        call["tr_id"] = "TTTC8434R"
    elif mutation == "hour":
        call["parameters"]["FID_INPUT_HOUR_1"] = "235959"
    elif mutation == "order":
        call["ordinal"] = 2
    with pytest.raises(PermissionError):
        gate.checked_call(PLAN, 1, call)
    with pytest.raises(PermissionError):
        gate.proposal(canonical(dict(PLAN, calls=[call])))


@pytest.mark.parametrize(
    "stamp", [gate.START - timedelta(seconds=1), gate.END, gate.END + timedelta(days=1)]
)
def test_missed_window_no_alternate_day(tmp_path, monkeypatch, stamp):
    c, w, _ = collector(tmp_path, monkeypatch, clock=Clock(stamp))
    with pytest.raises(PermissionError):
        c.run()
    assert not w.calls


def test_midflight_cutoff_no_later_request(tmp_path, monkeypatch):
    c, w, _ = collector(
        tmp_path, monkeypatch, clock=Clock(gate.END - timedelta(seconds=1)), transport=Wire(delay=2)
    )
    with pytest.raises(PermissionError):
        c.run()
    assert len(w.calls) == 1


def test_real_https_rejects_unregistered_before_http_creation(tmp_path, monkeypatch):
    a, p = proofs(tmp_path, monkeypatch, registered=False)
    calls = []
    monkeypatch.setattr(
        "kmast.data.https_bar_collector.http.client.HTTPSConnection",
        lambda *a, **k: calls.append(a),
    )
    with pytest.raises(PermissionError):
        PaperHTTPS(RAW, a, p, enabled=True).exchange(0, None, config("PAPER"), None, Clock())
    assert calls == []


@pytest.mark.parametrize("status", [200, 302])
def test_tls_hostname_chain_and_secret_send_order(tmp_path, monkeypatch, status):
    a, p = proofs(tmp_path, monkeypatch)
    calls = []

    class Connection:
        def __init__(self, host, port, timeout, context):
            assert host == gate.HOST and port == 29443 and context.check_hostname
            assert (
                context.verify_mode == ssl.CERT_REQUIRED
                and context.minimum_version >= ssl.TLSVersion.TLSv1_2
            )
            self.sock = SimpleNamespace(
                getpeercert=lambda: dict(subject="SYNTHETIC"), version=lambda: "TLSv1.3"
            )

        def connect(self):
            calls.append("TLS")

        def request(self, *args, **kw):
            assert calls == ["TLS"]
            calls.append("SECRET_HTTP")

        def getresponse(self):
            return SimpleNamespace(status=status, getheader=lambda *a: "", read=lambda n: b"{}")

        def close(self):
            pass

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr("kmast.data.https_bar_collector.http.client.HTTPSConnection", Connection)
    reply = PaperHTTPS(RAW, a, p, enabled=True).exchange(0, None, config("PAPER"), None, Clock())
    assert calls == ["TLS", "SECRET_HTTP"] and reply.tls_verified and reply.status == status


def test_failed_certificate_never_sends_secret_http(tmp_path, monkeypatch):
    a, p = proofs(tmp_path, monkeypatch)
    sent = []
    clock = Clock()

    class Failed:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            raise ssl.SSLCertVerificationError("SYNTHETIC-SECRET")

        def request(self, *a, **k):
            sent.append(a)

        def close(self):
            clock.sleep(0.5)

    monkeypatch.setattr("kmast.data.https_bar_collector.http.client.HTTPSConnection", Failed)
    reply = PaperHTTPS(RAW, a, p, enabled=True).exchange(0, None, config("PAPER"), None, clock)
    assert not sent and not reply.tls_verified and not reply.request_started
    assert reply.response_mono == clock.mono() == 500000000


def test_unknown_bar_semantics_and_source_are_separate(tmp_path, monkeypatch):
    clock = Clock(gate.START.replace(hour=9, minute=6, second=10))
    wire = Wire()
    reply = wire.exchange(1, PLAN["calls"][0], config("PAPER"), "synthetic", clock)
    parsed = diagnose(reply, PLAN["calls"][0], "OBSERVED", clock)
    assert parsed["schema_ok"] and parsed["quality"]["SOURCE_OK"]
    assert not parsed["quality"]["ORB5_OK"] and "BAR_LABEL_SEMANTICS_UNKNOWN" in parsed["flags"]
    synthetic = diagnose(reply, PLAN["calls"][0], "SYNTHETIC", clock)
    assert synthetic["quality"]["SOURCE_OK"] is None and synthetic["profit"] is None


def test_requery_changes_never_certify_correction_finality():
    base = dict(
        tr_id="FHKST03010200",
        symbol="073240",
        rows=[
            dict(
                label_at="SYNTHETIC-LABEL",
                open="1",
                high="2",
                low="1",
                close="2",
                volume="1",
                source_sha256="a" * 64,
            )
        ],
    )
    second = json.loads(canonical(base))
    second["rows"][0]["high"] = "3"
    changes = requery_changes([base, second])
    assert (
        changes[0]["changed_fields"] == ["high"] and not changes[0]["correction_finality_verified"]
    )


def test_sensitive_market_echo_withheld(tmp_path, monkeypatch):
    c, w, _ = collector(tmp_path, monkeypatch, transport=Wire(echo="SYNTHETIC-MEMORY-ONLY-TOKEN"))
    c.run()
    assert not list((c.root / "raw").glob("*.bin"))
    assert not safe_market_body(b'{"cano":"12345678"}', ())
    assert not safe_market_body(b'{"msg1":"\\u0041\\u0042\\u0043"}', (b"ABC",))
    assert not safe_market_body(b'{"\\u0061ppkey":"hidden"}', ())


def test_journal_integrity_cap_and_orphan_hold(tmp_path, monkeypatch):
    c, _, _ = collector(tmp_path, monkeypatch)
    c.run()
    binding = json.loads((c.root / "binding.json").read_bytes())
    j = Journal(c.root, binding)
    with pytest.raises(PermissionError):
        j.reserve(0, gate.START)
    file = next((c.root / "raw").glob("*.bin"))
    file.write_bytes(b"changed")
    with pytest.raises(ValueError):
        Journal(c.root, binding)


def test_pending_reservation_survives_restart_without_refund(tmp_path):
    binding = dict(origin="SYNTHETIC", hash_retention_allowed=True)
    j = Journal(tmp_path, binding)
    j.reserve(0, gate.START)
    j = Journal(tmp_path, binding)
    assert len(j.reservations) == 1
    with pytest.raises(PermissionError):
        j.reserve(0, gate.START)


def test_store_pre_reservation_and_response_caps(tmp_path, monkeypatch):
    j = Journal(tmp_path, dict(origin="SYNTHETIC", hash_retention_allowed=True))
    monkeypatch.setattr("kmast.data.https_bar_store.TOTAL_CAP", 1024)
    with pytest.raises(PermissionError):
        j.reserve(0, gate.START)
    assert not j.reservations


def test_expiry_purge_only_exact_manifest_and_never_sibling_data(tmp_path, monkeypatch):
    c, _, _ = collector(tmp_path, monkeypatch)
    c.run()
    sibling = tmp_path / "prior-data"
    sibling.write_bytes(b"PRESERVE")
    j = Journal(c.root, json.loads((c.root / "binding.json").read_bytes()))
    with pytest.raises(PermissionError):
        j.purge_expired(gate.END, j.retention_plan(gate.END))
    now = gate.END + timedelta(days=31)
    plan = j.retention_plan(now)
    j.purge_expired(now, plan)
    assert sibling.read_bytes() == b"PRESERVE"
    assert not list((c.root / "raw").glob("*.bin"))


def test_cli_disabled_never_loads_env_or_echoes_inputs(monkeypatch, capsys):
    import scripts.collect_df017 as cli

    seen = []
    monkeypatch.setattr("sys.argv", ["collect_df017"])
    monkeypatch.setattr(cli, "load_env", lambda *a: seen.append("KEY"))
    with pytest.raises(SystemExit):
        cli.main()
    assert not seen and capsys.readouterr().out == ""


def test_worst_case_all_logical_retries_exactly_45_attempts(tmp_path, monkeypatch):
    statuses = {(i, 1): 500 for i in range(1, 23)}
    c, w, _ = collector(tmp_path, monkeypatch, transport=Wire(statuses=statuses))
    result = c.run()
    assert result["attempted"] == len(w.calls) == 45
    j = Journal(c.root, json.loads((c.root / "binding.json").read_bytes()))
    assert sum(r["ordinal"] == 0 for r in j.reservations) == 1
    with pytest.raises(PermissionError):
        j.reserve(22, gate.START)


def test_partial_bodies_hold_and_budget_retry_once(tmp_path, monkeypatch):
    c, w, _ = collector(tmp_path, monkeypatch, transport=Wire(error="PARTIAL_BODY_CAPTURED"))
    c.run()
    assert len(w.calls) == 45
    entries = [json.loads(p.read_bytes()) for p in (c.root / "outcomes").glob("*.json")]
    assert all(r["response_at"] is None for r in entries if r["id"] > 1)
    assert all(not r["successful_response"] for r in entries if r["id"] > 1)


def test_unexpected_transport_failure_does_not_invent_request_time(tmp_path, monkeypatch):
    class Broken(Wire):
        def exchange(self, *a):
            raise OSError("SYNTHETIC-SECRET")

    c, _, _ = collector(tmp_path, monkeypatch, transport=Broken())
    with pytest.raises(RuntimeError) as exc:
        c.run()
    assert "SYNTHETIC-SECRET" not in str(exc.value)
    entry = json.loads(next((c.root / "outcomes").glob("*.json")).read_bytes())
    assert entry["request_at"] is None and entry["response_at"] is None
    assert len(list((c.root / "reservations").glob("*.json"))) == 1


def test_custom_ca_environment_is_rejected(tmp_path, monkeypatch):
    a, p = proofs(tmp_path, monkeypatch)
    monkeypatch.setenv("SSL_CERT_FILE", "SYNTHETIC-SECRET-PATH")
    with pytest.raises(PermissionError):
        PaperHTTPS(RAW, a, p, enabled=True).exchange(0, None, config("PAPER"), None, Clock())


def test_clock_or_proof_change_during_wait_blocks_keys(tmp_path, monkeypatch):
    c, w, _ = collector(tmp_path, monkeypatch)
    c.preflight["rights"]["sha256"] = "0" * 64
    with pytest.raises(PermissionError):
        c.run()
    assert not w.calls


def test_orphan_response_and_incomplete_metadata_stop_reopen(tmp_path):
    j = Journal(tmp_path, dict(origin="SYNTHETIC", hash_retention_allowed=True))
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / (digest(b"orphan") + ".bin")).write_bytes(b"orphan")
    with pytest.raises(ValueError):
        Journal(tmp_path, j.binding)


def test_process_lock_disallows_duplicate_collector(tmp_path, monkeypatch):
    from kmast.data.panel_acquisition import process_lock

    c, w, _ = collector(tmp_path, monkeypatch)
    with process_lock(c.root / "process.lock"):
        with pytest.raises(PermissionError):
            c.run()
    assert not w.calls


def test_cli_unknown_argument_never_echoes_secret(monkeypatch):
    import scripts.collect_df017 as cli

    monkeypatch.setattr("sys.argv", ["collect", "--unknown", "SYNTHETIC-SECRET"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert "SYNTHETIC-SECRET" not in str(exc.value)
