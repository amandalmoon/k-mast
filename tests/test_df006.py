from datetime import date, datetime

import pytest

from kmast.data.models import KST
from kmast.research.event_flow import (
    DecisionReceipt,
    decision_boundary,
    invalidated_at,
    register_receipt,
)


def receipt(**changes: object) -> DecisionReceipt:
    fields = {
        "receipt": "20231006000001",
        "corp_code": "00123456",
        "stock_code": "014790",
        "receipt_date": date(2023, 10, 6),
        "title": "주요사항보고서(자기주식취득결정)",
        "acquired_at": datetime(2026, 10, 17, tzinfo=KST),
        "raw_response_sha256": "a" * 64,
        "original_document_sha256": "b" * 64,
        "historical_identity_verified": True,
        "document_family_verified": True,
    }
    return DecisionReceipt.model_validate(fields | changes)


def test_date_only_after_weekend_and_holiday() -> None:
    event = receipt()
    calendar = (datetime(2023, 10, 6, 8, tzinfo=KST), datetime(2023, 10, 10, 8, tzinfo=KST))
    assert decision_boundary(event, calendar) == calendar[1]
    assert event.published_at is None
    assert event.acquired_at.year == 2026


@pytest.mark.parametrize(
    "title",
    [
        "자기주식처분결정",
        "자기주식취득결과보고서",
        "자기주식취득신탁계약체결결정",
        "[기재정정]자기주식취득결정",
    ],
)
def test_decision_is_not_execution_or_other_family(title: str) -> None:
    assert not receipt(title=title).entry_candidate


def test_document_and_historical_mapping_required() -> None:
    assert receipt().entry_candidate
    assert not receipt(document_family_verified=False).entry_candidate
    assert not receipt(historical_identity_verified=False).entry_candidate


def test_receipt_dedup_and_conflict() -> None:
    event = receipt()
    registry: dict[str, DecisionReceipt] = {}
    register_receipt(registry, event)
    register_receipt(registry, event)
    assert len(registry) == 1
    with pytest.raises(ValueError, match="CONFLICTING_RECEIPT"):
        register_receipt(registry, receipt(stock_code="014440"))


def test_correction_is_prospective_not_backfilled() -> None:
    event = receipt()
    correction = receipt(
        receipt="20231011000001",
        receipt_date=date(2023, 10, 11),
        parent_receipt=event.receipt,
        correction_kind="CANCEL",
    )
    calendar = tuple(datetime(2023, 10, day, 8, tzinfo=KST) for day in (10, 11, 12))
    assert not invalidated_at(event, (correction,), calendar[0], calendar)
    assert invalidated_at(event, (correction,), calendar[2], calendar)
    later = correction.model_copy(update={"receipt_date": date(2023, 10, 30)})
    assert not invalidated_at(event, (later,), calendar[0], calendar)
    assert event.entry_candidate
    assert not correction.entry_candidate


def test_correction_mapping_conflict_rejected() -> None:
    event = receipt()
    with pytest.raises(ValueError, match="UNVERIFIED_CORRECTION_PARENT"):
        register_receipt(
            {event.receipt: event},
            receipt(
                receipt="20231011000001",
                stock_code="014440",
                parent_receipt=event.receipt,
                correction_kind="ADVERSE",
            ),
        )


def test_hash_and_calendar_precision() -> None:
    assert len(receipt().normalized_sha256) == 64
    assert receipt().normalized_sha256 != receipt(title="other").normalized_sha256
    with pytest.raises(ValueError, match="REGULAR_DECISION"):
        decision_boundary(receipt(), (datetime(2023, 10, 10, 9, tzinfo=KST),))
    with pytest.raises(ValueError, match="NO_VERIFIED"):
        decision_boundary(receipt(), ())


def test_dart_scope_and_disabled_network(tmp_path) -> None:
    from scripts.collect_df006 import DartWire, months, validate_request

    assert len(list(months())) == 37
    assert list(months())[0] == ("20221017", "20221031")
    assert list(months())[-1] == ("20251001", "20251008")
    with pytest.raises(ValueError, match="ENDPOINT_BLOCKED"):
        validate_request("/api/anything.json", {})
    with pytest.raises(ValueError, match="DOCUMENT_SCOPE_BLOCKED"):
        validate_request("/api/document.xml", {"rcept_no": "bad"})
    wire = DartWire(tmp_path, "a" * 40)
    with pytest.raises(ValueError, match="EXPLICIT_APPROVAL"):
        wire.get("/api/document.xml", {"rcept_no": "20231006000001"})
    assert wire.budget["used"] == 0


def test_dart_key_loader_no_values_in_exception(tmp_path) -> None:
    from scripts.collect_df006 import load_key

    config = tmp_path / "key.env"
    config.write_bytes(b"OPENDART_API_KEY=private-invalid\n")
    with pytest.raises(ValueError, match="^INVALID_LOCAL_KEY_FORMAT$"):
        load_key(config)
    config.write_bytes(b"OPENDART_API_KEY=" + b"a" * 40 + b"\n")
    assert load_key(config) == "a" * 40


def test_dart_completion_spacing_failure_budget_and_resume(tmp_path, monkeypatch) -> None:
    import json
    from types import SimpleNamespace

    from scripts import collect_df006 as module

    clock, starts = [100.0], []

    class Connection:
        def __init__(self, host, timeout):
            assert host == "opendart.fss.or.kr"

        def request(self, *args, **kwargs):
            starts.append(clock[0])

        def getresponse(self):
            clock[0] += 0.5
            return SimpleNamespace(status=500, read=lambda _: b"safe failure bytes")

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(module.time, "monotonic", lambda: int(clock[0] * 64) / 64)
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    waits = []

    def early_waking_sleep(seconds):
        waits.append(seconds)
        clock[0] += max(0, seconds - 0.02) if len(waits) == 1 else seconds

    monkeypatch.setattr(module.time, "sleep", early_waking_sleep)
    wire = module.DartWire(tmp_path, "a" * 40, enabled=True)
    with pytest.raises(ValueError, match="TRANSPORT_RETRY_EXHAUSTED"):
        wire.get("/api/document.xml", {"rcept_no": "20231006000001"})
    assert starts[1] - starts[0] == pytest.approx(3.60)
    assert len(waits) == 2  # Early wake is rechecked; coarse monotonic is unused.
    assert len(list((tmp_path / "wire").glob("*.bin"))) == 1
    assert json.loads((tmp_path / "budget.json").read_bytes())["used"] == 2
    resumed = module.DartWire(tmp_path, "a" * 40, enabled=True)
    assert resumed.budget["used"] == 2
    with pytest.raises(ValueError, match="REQUEST_RETRY_BUDGET_EXHAUSTED"):
        resumed.get("/api/document.xml", {"rcept_no": "20231006000001"})
    resumed.budget["used"] = 600
    with pytest.raises(ValueError, match="REQUEST_BUDGET_EXHAUSTED"):
        resumed.get("/api/document.xml", {"rcept_no": "20231006000002"})
    assert len(starts) == 2


def test_secret_echo_is_hash_only_not_persisted(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from scripts import collect_df006 as module

    key = "z" * 40

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda _: key.encode())

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, "HTTPSConnection", Connection)
    wire = module.DartWire(tmp_path, key, enabled=True)
    with pytest.raises(ValueError, match="^SENSITIVE_RESPONSE_WITHHELD$"):
        wire.get("/api/document.xml", {"rcept_no": "20231006000001"})
    assert wire.budget["used"] == 1
    assert not (tmp_path / "wire").exists()
    assert key.encode() not in (tmp_path / "budget.json").read_bytes()


def test_response_before_cache_crash_recovery_without_new_request(tmp_path, monkeypatch) -> None:
    import json

    from kmast.data.store import canonical, digest
    from scripts import collect_df006 as module

    params = {
        "bgn_de": "20221017",
        "end_de": "20221031",
        "pblntf_detail_ty": "B001",
        "last_reprt_at": "N",
        "page_count": "100",
        "page_no": "1",
        "sort": "date",
        "sort_mth": "asc",
    }
    path = "/api/list.json"
    identity = digest(canonical({"path": path, "params": params}))
    raw = b'{"status":"000","list":[],"total_page":0}'
    event = dict(
        number=1,
        identity=identity,
        path=path,
        attempt=0,
        http_status=200,
        sha256=digest(raw),
        completed_at="2026-10-17T00:00:00+00:00",
    )
    (tmp_path / "wire").mkdir()
    (tmp_path / "wire" / (digest(raw) + ".bin")).write_bytes(raw)
    (tmp_path / "budget.json").write_bytes(
        canonical({"used": 1, "maximum": 600, "events": [event]})
    )

    def forbidden(*args, **kwargs):
        pytest.fail("recovery must not issue a second request")

    monkeypatch.setattr(module.http.client, "HTTPSConnection", forbidden)
    wire = module.DartWire(tmp_path, "a" * 40, enabled=True)
    observed, record = wire.get(path, params)
    assert observed == raw and wire.budget["used"] == 1
    assert wire.get(path, params)[0] == raw
    cache = tmp_path / "cache" / (identity + ".json")
    broken = json.loads(cache.read_bytes()) | {"params": {}}
    cache.write_bytes(canonical(broken))
    with pytest.raises(ValueError, match="CACHE_IDENTITY_CONFLICT"):
        wire.get(path, params)
    assert record["sha256"] == digest(raw)


def event_test_panel():
    """Authored transport-shaped test data only; never project economic evidence."""
    from datetime import timedelta

    from kmast.data.models import Observation

    days = [date(2023, 1, 3) + timedelta(days=i) for i in range(48)]
    days = [d for d in days if d.weekday() < 5]
    rows = []
    for i, day in enumerate(days):
        rows.append(
            Observation.model_validate(
                dict(
                    record_id=f"test-{i}",
                    kind="DAILY",
                    symbol="014790",
                    venue="KRX",
                    session="REGULAR",
                    exchange_date=day,
                    received_at=datetime(2026, 10, 17, tzinfo=KST),
                    acquired_at=datetime(2026, 10, 17, tzinfo=KST),
                    available_at=datetime(2026, 10, 17, tzinfo=KST),
                    availability_method="CONSERVATIVE_BOUND",
                    availability_evidence="TEST_ONLY",
                    open="10000",
                    high="11000",
                    low="9000",
                    close="10000",
                    volume="1000000",
                    turnover="10000000000",
                    price_basis="RAW",
                    complete=True,
                    timestamp_precision="DATE_ONLY",
                    source_hash="a" * 64,
                    parser_version="TEST_ONLY",
                    data_origin="KIS_READONLY",
                    quality_flags=("TEST_ONLY_NOT_ECONOMIC_EVIDENCE",),
                )
            )
        )
    return tuple(rows)


def test_event_ledger_cost_once_deadline_and_no_reentry() -> None:
    from decimal import Decimal as D

    from kmast.research.event_replay import event_replay

    rows = event_test_panel()
    result = event_replay(rows, rows, rows[21].exchange_date, (3, 20, 5, "1"), "D1", frozenset())
    s = result["summary"]
    assert s["executions"] == 2 and s["final_quantity"] == 0
    assert D(s["net"]) < 0
    assert D(s["gross_before_slippage"]) == 0
    assert D(s["net"]) == -D(s["explicit_cost"]) - D(s["operating_cost"]) - D(
        s["embedded_slippage"]
    )
    assert D(s["commission"]) + D(s["tax"]) == D(s["explicit_cost"])
    assert all(D(r["target"]) <= D(".25") for r in result["signals"])
    assert all(r["execution_model"] == "ASSUMED_OPEN_NOT_OBSERVED_FILL" for r in result["signals"])
    assert s["actual_fill_pnl"] is None
    assert rows[0].quality_flags == ("TEST_ONLY_NOT_ECONOMIC_EVIDENCE",)


def test_partial_residual_and_invalidated_entry_not_success() -> None:
    from kmast.research.event_replay import event_replay

    rows = event_test_panel()
    partial = event_replay(rows, rows, rows[21].exchange_date, (3, 20, 5, ".5"), "D1", frozenset())
    assert partial["summary"]["final_quantity"] > 0
    assert partial["summary"]["unfulfilled_reduction_days"] > 0
    cancelled = event_replay(
        rows,
        rows,
        rows[21].exchange_date,
        (3, 20, 5, "1"),
        "D1",
        frozenset(),
        rows[21].exchange_date,
    )
    assert cancelled["summary"]["executions"] == 0


def test_document_identity_requires_original_evidence() -> None:
    import io
    import zipfile

    from scripts.evaluate_df006 import document_evidence

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "test.xml",
            '<ROOT><COMPANY-NAME AREGCIK="00123456">TEST</COMPANY-NAME>'
            "<P>자기주식 취득 결정 취득예정금액</P></ROOT>",
        )
    row = {"corp_name": "TEST", "corp_code": "00123456", "stock_code": "014790"}
    evidence = document_evidence(buffer.getvalue(), row)
    assert evidence["historical_identity_verified"] and evidence["family_verified"]
    wrong = document_evidence(buffer.getvalue(), row | {"corp_code": "00999999"})
    assert not wrong["historical_identity_verified"]
    assert document_evidence(buffer.getvalue(), row | {"corp_name": "TES"})[
        "historical_identity_verified"
    ]  # Legal-name suffixes do not erase the original document's exact corporate ID.


def test_nonconstant_action_factor_quarantines_whole_event() -> None:
    from decimal import Decimal as D

    from scripts.evaluate_df006 import qualify_window

    raw = event_test_panel()
    adjusted = tuple(
        r.model_copy(update={"price_basis": "ADJUSTED", "close": D(5000)}) for r in raw
    )
    first, _ = qualify_window(raw, adjusted, raw, raw[21].exchange_date, frozenset())
    assert first[21].open == 10000  # Adjusted close is never an executable price.
    changed = list(adjusted)
    changed[22] = changed[22].model_copy(update={"close": D(5100)})
    with pytest.raises(ValueError, match="NONCONSTANT_FACTOR"):
        qualify_window(raw, tuple(changed), raw, raw[21].exchange_date, frozenset())


def test_unknown_open_does_not_change_decision_or_force_limit_fill() -> None:
    from decimal import Decimal as D

    from kmast.research.event_replay import event_replay

    rows = event_test_panel()
    normal = event_replay(rows, rows, rows[21].exchange_date, (3, 20, 5, "1"), "D1", frozenset())
    changed = list(rows)
    changed[21] = rows[21].model_copy(update={"open": D(12000), "high": D(13000)})
    gap = event_replay(
        tuple(changed), rows, rows[21].exchange_date, (3, 20, 5, "1"), "D1", frozenset()
    )
    assert normal["signals"][0]["intent"] == gap["signals"][0]["intent"]
    assert gap["summary"]["executions"] == 0
    assert gap["summary"]["expired_unfilled"] > 0
    assert gap["summary"]["final_quantity"] == 0
