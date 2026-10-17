import io
import json
import zipfile

import pytest

from kmast.data.document_acquisition import DocumentWire
from kmast.data.document_qualification import qualify_document
from kmast.data.store import canonical, digest

RECEIPT = "20240101000001"


def document(text, receipt=RECEIPT):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(receipt + ".xml", text)
    return stream.getvalue()


def test_corporate_id_does_not_prove_stock_mapping():
    result = qualify_document(
        document('<DOC><COMPANY-NAME AREGCIK="00123456">Name</COMPANY-NAME></DOC>'),
        RECEIPT,
        "00123456",
    )
    assert result["DOCUMENT_VERIFIED"] is True
    assert result["CORPORATE_IDENTITY_VERIFIED"] is True
    assert result["HISTORICAL_SYMBOL_MAPPING_VERIFIED"] is None
    assert result["PRICE_AND_SESSION_QUALIFIED"] is None
    assert result["published_at"] is None


def test_document_receipt_and_company_conflicts():
    assert (
        qualify_document(document("<DOC/>", "20240101000002"), RECEIPT, "00123456")[
            "DOCUMENT_VERIFIED"
        ]
        is None
    )
    result = qualify_document(
        document('<DOC><COMPANY-NAME AREGCIK="00999999"/></DOC>'), RECEIPT, "00123456"
    )
    assert result["CORPORATE_IDENTITY_VERIFIED"] is None


@pytest.mark.parametrize(
    "raw", [b"not zip", document("<bad>"), document('<!DOCTYPE x [<!ENTITY y "z">]><DOC/>')]
)
def test_unsafe_documents_remain_unknown(raw):
    assert qualify_document(raw, RECEIPT, "00123456")["DOCUMENT_VERIFIED"] is None


def test_unknown_identity_cannot_use_explicit_stock_code():
    result = qualify_document(
        document("<DOC><STOCK-CODE>005930</STOCK-CODE></DOC>"), RECEIPT, "00123456"
    )
    assert result["HISTORICAL_SYMBOL_MAPPING_VERIFIED"] is None


def test_network_off_and_exact_allowlist(tmp_path):
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope")
    with pytest.raises(ValueError, match="NETWORK_DISABLED"):
        wire.get(RECEIPT)
    with pytest.raises(ValueError, match="OUTSIDE_APPROVED"):
        wire.get("20240101000002")
    assert wire.state["used"] == 0


def test_persistent_budget_scope_cannot_expand(tmp_path):
    (tmp_path / "budget.json").write_bytes(
        canonical(
            dict(
                scope_sha256="scope",
                maximum=2,
                used=1,
                events=[dict(number=1, receipt=RECEIPT)],
                halted=None,
            )
        )
    )
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope")
    assert wire.state["used"] == 1
    with pytest.raises(ValueError, match="SCOPE_CONFLICT"):
        DocumentWire(tmp_path, (RECEIPT,), "different")


def test_high_resolution_wait_rechecks_early_wakeup(tmp_path, monkeypatch):
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope")
    wire.last_perf = 10.0
    ticks = iter([10.0, 12.0, 13.099, 13.10])
    sleeps = []
    monkeypatch.setattr("kmast.data.document_acquisition.time.perf_counter", lambda: next(ticks))
    monkeypatch.setattr("kmast.data.document_acquisition.time.sleep", sleeps.append)
    wire.wait()
    assert len(sleeps) == 3


def test_fatal_journal_recovery_and_hash_conflict(tmp_path):
    event = dict(
        number=1,
        receipt=RECEIPT,
        fatal="SPACING_FAILURE",
        completed_at="2026-10-17T00:00:00+00:00",
        terminal=True,
        success=False,
        sha256=digest(b"raw"),
        wire_stored=True,
    )
    (tmp_path / "events").mkdir()
    (tmp_path / "events/0001.json").write_bytes(canonical(event))
    (tmp_path / "budget.json").write_bytes(
        canonical(
            dict(
                scope_sha256="scope",
                maximum=2,
                used=1,
                events=[dict(number=1, receipt=RECEIPT)],
                halted=None,
            )
        )
    )
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope")
    assert wire.state["halted"] == "SPACING_FAILURE"
    assert json.loads((tmp_path / "budget.json").read_bytes())["halted"] == "SPACING_FAILURE"


def test_document_normalized_hash_excludes_itself():
    result = qualify_document(document("<DOC/>"), RECEIPT, "00123456")
    value = result.pop("normalized_sha256")
    assert digest(canonical(result)) == value


def test_correction_link_is_only_a_candidate():
    raw = document(
        '<DOC><A HREF="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230101000001"/></DOC>'
    )
    row = qualify_document(raw, RECEIPT, "00123456")
    assert row["correction_parent_candidates"] == ["20230101000001"]
    assert row["correction_parent_receipt"] is None


def test_trust_heading_is_not_direct_acquisition():
    raw = document(
        "<DOC><TITLE>자기주식취득 신탁계약 체결 결정</TITLE>"
        "<P>취득예정주식 취득예정금액 취득예상기간</P></DOC>"
    )
    row = qualify_document(raw, RECEIPT, "00123456")
    assert row["EVENT_FAMILY_VERIFIED"] is None


def test_frozen_target_scope_and_sample_strata():
    from collections import Counter
    from pathlib import Path

    targets = json.loads(Path("artifacts/df008/document-targets.json").read_bytes())
    assert len(targets["originals"]) == 60 and len(targets["revisions"]) == 29
    assert Counter(r["receipt_date"][:4] for r in targets["originals"]) == dict.fromkeys(
        ["2022", "2023", "2024", "2025"], 15
    )
    assert sum(r["regime"] == "BEAR" for r in targets["originals"]) == 7
    assert len({r["receipt"] for r in targets["originals"] + targets["revisions"]}) == 89


def test_unknown_consumed_attempts_cannot_be_refunded(tmp_path):
    state = dict(
        scope_sha256="scope",
        maximum=2,
        used=2,
        events=[dict(number=i, receipt=RECEIPT) for i in (1, 2)],
        halted=None,
    )
    (tmp_path / "budget.json").write_bytes(canonical(state))
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope", "x" * 40, enabled=True)
    with pytest.raises(ValueError, match="ATTEMPTS_EXHAUSTED"):
        wire.get(RECEIPT)
    assert wire.state["used"] == 2


def test_backwards_clock_halts_persistently(tmp_path, monkeypatch):
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope", "x" * 40, enabled=True)
    wire.last_perf = 10.0
    monkeypatch.setattr("kmast.data.document_acquisition.time.perf_counter", lambda: 9.0)
    with pytest.raises(ValueError, match="CLOCK_REVERSED"):
        wire.wait()
    assert json.loads((tmp_path / "budget.json").read_bytes())["halted"]
    with pytest.raises(ValueError, match="PERSISTENT_COLLECTION_HALT"):
        DocumentWire(tmp_path, (RECEIPT,), "scope", "x" * 40, enabled=True).get(RECEIPT)


def test_actual_boundary_short_gap_blocks_before_send(tmp_path, monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pytest.fail("short-gap request must never be sent")

        def close(self):
            pass

    monkeypatch.setattr("kmast.data.document_acquisition.http.client.HTTPSConnection", Connection)
    monkeypatch.setattr(DocumentWire, "wait", lambda self: None)
    monkeypatch.setattr("kmast.data.document_acquisition.time.perf_counter", lambda: 10.0)
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope", "x" * 40, enabled=True)
    wire.last_perf = 9.0
    with pytest.raises(ValueError, match="SPACING_VIOLATION"):
        wire.get(RECEIPT)
    assert wire.state["used"] == 1 and wire.state["halted"]
    assert not wire.state["events"][0].get("transmitted", False)


def test_process_lock_prevents_duplicate_collector(tmp_path):
    from kmast.data.panel_acquisition import process_lock

    with process_lock(tmp_path / "collector.lock"):
        with pytest.raises(PermissionError, match="ALREADY_LOCKED"):
            with process_lock(tmp_path / "collector.lock"):
                pytest.fail("duplicate collector entered")


def test_official_correction_date_unique_parent_without_backfill():
    from kmast.data.document_relations import correction_relation

    originals = [dict(receipt="20230101000001", corp_code="00123456")]
    text = "정정대상 공시서류: 자기주식취득결정 정정대상 공시서류의 최초제출일:2023년 1월 1일"
    row = correction_relation(text, RECEIPT, "00123456", originals)
    assert row["relation_verified"] is True and row["parent_receipt"] == "20230101000001"
    assert row["effective_publication_time"] is None
    assert not row["earlier_original_information_changed"]
    originals.append(dict(receipt="20230101000002", corp_code="00123456"))
    assert correction_relation(text, RECEIPT, "00123456", originals)["relation_verified"] is None
    assert correction_relation(text, RECEIPT, "00999999", originals)["relation_verified"] is None


def test_generic_date_proximity_is_not_correction_evidence():
    from kmast.data.document_relations import correction_relation

    row = correction_relation("자기주식취득결정 2023년 1월 1일", RECEIPT, "00123456", [])
    assert row["parent_receipt"] is None


def test_transport_retry_resume_and_cache_integrity(tmp_path, monkeypatch):
    calls = []
    raw = document("<DOC/>")

    class Response:
        status = 200

        def read(self, limit):
            return raw

    class Connection:
        def __init__(self, host, timeout):
            assert host == "opendart.fss.or.kr"

        def request(self, method, path, headers):
            calls.append(method)
            assert path.startswith("/api/document.xml?")
            if len(calls) == 1:
                raise OSError("unlogged transport error")

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("kmast.data.document_acquisition.http.client.HTTPSConnection", Connection)
    # Independent spacing tests exercise waiting; avoid actual sleep in this retry test.
    monkeypatch.setattr(DocumentWire, "wait", lambda self: setattr(self, "last_perf", None))
    wire = DocumentWire(tmp_path, (RECEIPT,), "scope", "x" * 40, enabled=True)
    # Remove only UTC comparison in this mock by advancing mocked completion timestamps.
    from datetime import UTC, datetime, timedelta

    class Clock(datetime):
        count = 0

        @classmethod
        def now(cls, zone):
            cls.count += 1
            return datetime(2026, 10, 17, tzinfo=UTC) + timedelta(seconds=cls.count * 4)

    monkeypatch.setattr("kmast.data.document_acquisition.datetime", Clock)
    saved = wire.get(RECEIPT)
    assert saved["success"] and wire.state["used"] == 2 and len(calls) == 2
    offline = DocumentWire(tmp_path, (RECEIPT,), "scope")
    assert offline.get(RECEIPT) == saved and len(calls) == 2
    (tmp_path / "wire" / (saved["sha256"] + ".bin")).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="RAW_HASH_CONFLICT"):
        offline.get(RECEIPT)
