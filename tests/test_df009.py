"""Authored fixtures test rejection boundaries; they are not historical market evidence."""

import json

import pytest

from kmast.data.historical_security import qualify_link, snapshot_rows
from kmast.data.store import canonical, digest


def security(**changes):
    return dict(
        ISU_CD="KR7005930003",
        ISU_SRT_CD="005930",
        ISU_NM="테스트법인",
        ISU_ABBRV="테스트",
        LIST_DD="20000101",
        MKT_TP_NM="KOSPI",
        SECUGRP_NM="주권",
        KIND_STKCERT_TP_NM="보통주",
        **changes,
    )


def event():
    return dict(
        receipt="20240102000001",
        corp_code="00123456",
        stock_code="005930",
        corporate_identity_verified=True,
        document_legal_names=["테스트법인"],
    )


def link(rows, **options):
    return qualify_link(event(), rows, snapshot_day="20240102", **options)


def test_current_snapshot_or_request_date_alone_never_proves_history():
    row = link([security()], historical_date_evidence_sha256=None)
    assert row["HISTORICAL_SECURITY_PRESENT"] is None
    assert row["CORP_STOCK_LINK_VERIFIED"] is None


def test_presence_listing_and_corporate_link_are_separate():
    row = link([security()], historical_date_evidence_sha256="a" * 64)
    assert row["HISTORICAL_SECURITY_PRESENT"] is True
    assert row["THEN_LISTED_STATUS_VERIFIED"] is True
    assert row["CORP_STOCK_LINK_VERIFIED"] is None
    assert row["DELISTING_AND_HALT_PENDING"] and row["CORPORATE_ACTION_PENDING"]


def test_full_identity_corroboration_still_does_not_qualify_prices():
    row = link(
        [security()],
        historical_date_evidence_sha256="a" * 64,
        issuer_corroboration_sha256="b" * 64,
        security_history_resolved=True,
    )
    assert row["CORP_STOCK_LINK_VERIFIED"] is True
    assert row["PRICE_AND_SESSION_PENDING"] and row["actual_publication_time"] is None


@pytest.mark.parametrize(
    "field,value",
    [("ISU_NM", "다른법인"), ("LIST_DD", "20250101"), ("KIND_STKCERT_TP_NM", "우선주")],
)
def test_rename_future_listing_or_share_class_conflict_is_quarantined(field, value):
    source = security()
    source[field] = value
    row = link(
        [source],
        historical_date_evidence_sha256="a" * 64,
        issuer_corroboration_sha256="b" * 64,
        security_history_resolved=True,
    )
    assert row["CORP_STOCK_LINK_VERIFIED"] is None and row["conflicts"]


def test_names_alone_and_missing_dart_code_remain_null():
    source = event()
    source["stock_code"] = ""
    row = qualify_link(
        source, [security()], snapshot_day="20240102", historical_date_evidence_sha256="a" * 64
    )
    assert row["HISTORICAL_SECURITY_PRESENT"] is None and row["CORP_STOCK_LINK_VERIFIED"] is None


def test_previous_or_future_snapshot_cannot_backfill_event_date():
    for day in ("20240101", "20250102"):
        row = qualify_link(
            event(), [security()], snapshot_day=day, historical_date_evidence_sha256="a" * 64
        )
        assert row["HISTORICAL_SECURITY_PRESENT"] is None


def test_empty_snapshot_is_not_proof_of_delisting():
    row = link([], historical_date_evidence_sha256="a" * 64)
    assert row["THEN_LISTED_STATUS_VERIFIED"] is None
    assert row["DELISTING_AND_HALT_PENDING"]


def test_standard_short_codes_and_response_scope_are_validated():
    raw = canonical(dict(OutBlock_1=[security()]))
    assert len(snapshot_rows(raw, digest(raw), "20240102", "KOSPI")) == 1
    with pytest.raises(ValueError, match="HASH_CONFLICT"):
        snapshot_rows(raw, "0" * 64, "20240102", "KOSPI")
    with pytest.raises(ValueError, match="MARKET_CONFLICT"):
        snapshot_rows(raw, digest(raw), "20240102", "KOSDAQ")
    source = security()
    source["ISU_CD"] = "005930"
    raw = canonical(dict(OutBlock_1=[source]))
    with pytest.raises(ValueError, match="STANDARD_SHORT_CODE"):
        snapshot_rows(raw, digest(raw), "20240102", "KOSPI")


def test_row_date_conflict_and_duplicate_code_collision():
    source = security()
    source["BAS_DD"] = "20250102"
    raw = canonical(dict(OutBlock_1=[source]))
    with pytest.raises(ValueError, match="DATE_CONFLICT"):
        snapshot_rows(raw, digest(raw), "20240102", "KOSPI")
    other = security()
    other["ISU_NM"] = "코드충돌"
    raw = canonical(dict(OutBlock_1=[security(), other]))
    with pytest.raises(ValueError, match="CODE_COLLISION"):
        snapshot_rows(raw, digest(raw), "20240102", "KOSPI")


def test_protocol_targets_and_pair_hash_frozen():
    from collections import Counter
    from pathlib import Path

    protocol = json.loads(Path("artifacts/df009/DF009_PROTOCOL.json").read_bytes())
    targets = protocol["targets"]
    assert len(targets) == len({r["corp_code"] for r in targets}) == 12
    assert Counter(r["receipt"][:4] for r in targets) == dict.fromkeys(
        ["2022", "2023", "2024", "2025"], 3
    )
    assert (
        digest(canonical([{k: r[k] for k in ("receipt", "corp_code")} for r in targets]))
        == protocol["receipt_corporate_id_sha256"]
    )
    assert protocol["maximum_unique_requests"] == 48 and protocol["maximum_total_requests"] == 96
    assert not protocol["authentication_authorized"] and protocol["service_paths"] is None


def test_krx_transport_default_off_and_dated_allowlist(tmp_path):
    from kmast.data.krx_acquisition import KRXBasicsWire

    query = dict(market="KOSPI", basDd="20240102")
    wire = KRXBasicsWire(tmp_path, (query,), "scope")
    with pytest.raises(ValueError, match="NETWORK_DISABLED"):
        wire.get(digest(canonical(query)))
    with pytest.raises(ValueError, match="OUTSIDE_APPROVED"):
        wire.get("0" * 64)
    assert wire.state["used"] == 0
    with pytest.raises(ValueError, match="OUTSIDE_SCOPE"):
        KRXBasicsWire(tmp_path, (dict(market="ACCOUNT", basDd="20240102"),), "scope")


def test_krx_cache_resume_hash_and_durable_budget(tmp_path):
    from kmast.data.krx_acquisition import KRXBasicsWire
    from kmast.data.panel_acquisition import atomic_json, immutable_write

    query = dict(market="KOSPI", basDd="20240102")
    identity = digest(canonical(query))
    raw = canonical(dict(OutBlock_1=[]))
    wire = KRXBasicsWire(tmp_path, (query,), "scope")
    final = dict(
        number=1,
        request_identity=identity,
        success=True,
        terminal=True,
        sha256=digest(raw),
        wire_stored=True,
        completed_at="2026-10-17T00:00:00+00:00",
    )
    immutable_write(tmp_path / "wire" / (digest(raw) + ".bin"), raw)
    immutable_write(tmp_path / "events/0001.json", canonical(final))
    wire.state.update(used=1, events=[dict(number=1, request_identity=identity)])
    atomic_json(tmp_path / "budget.json", wire.state)
    resumed = KRXBasicsWire(tmp_path, (query,), "scope")
    assert resumed.get(identity)["success"] and resumed.state["used"] == 1
    (tmp_path / "wire" / (digest(raw) + ".bin")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="RAW_HASH_CONFLICT"):
        resumed.get(identity)


def test_krx_only_official_basic_endpoint_and_auth_failure_stops(tmp_path, monkeypatch):
    from kmast.data.krx_acquisition import KRXBasicsWire

    calls = []

    class Response:
        status = 403

        def read(self, maximum):
            return b'{"error":"permission denied"}'

    class Connection:
        def __init__(self, host, timeout):
            assert host == "data-dbg.krx.co.kr"

        def request(self, method, path, headers):
            assert method == "GET"
            assert path == "/svc/apis/sto/stk_isu_base_info?basDd=20240102"
            assert headers["AUTH_KEY"] == "x" * 40 and "x" * 40 not in path
            calls.append(path)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("kmast.data.krx_acquisition.http.client.HTTPSConnection", Connection)
    queries = (dict(market="KOSPI", basDd="20240102"), dict(market="KOSDAQ", basDd="20240102"))
    wire = KRXBasicsWire(tmp_path, queries, "scope", "x" * 40, enabled=True)
    with pytest.raises(ValueError, match="AUTH_PERMISSION_OR_QUOTA"):
        wire.get(digest(canonical(queries[0])))
    assert wire.state["used"] == 1 and len(calls) == 1
    assert wire.state["events"][0]["wire_stored"]
    with pytest.raises(ValueError, match="PERSISTENT_COLLECTION_HALT"):
        KRXBasicsWire(tmp_path, queries, "scope", "x" * 40, enabled=True).get(
            digest(canonical(queries[1]))
        )
