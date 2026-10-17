import json

import pytest

from kmast.data.store import canonical, digest
from scripts.resume_df009 import ConfirmedAccessWire


def prepared(tmp_path):
    query = dict(market="KOSPI", basDd="20221226")
    identity = digest(canonical(query))
    raw = b'{"respCode":"401"}'
    event = dict(
        number=1,
        request_identity=identity,
        http_status=401,
        sha256=digest(raw),
        fatal="KRX_AUTH_PERMISSION_OR_QUOTA_FAILURE",
        terminal=True,
        success=False,
        completed_at="2026-10-17T00:00:00+00:00",
        wire_stored=True,
    )
    (tmp_path / "events").mkdir()
    (tmp_path / "events/0001.json").write_bytes(canonical(event))
    (tmp_path / "budget.json").write_bytes(
        canonical(
            dict(scope_sha256="scope", maximum=2, used=1, events=[event], halted=event["fatal"])
        )
    )
    (tmp_path / "access-confirmation.json").write_bytes(
        canonical(
            dict(
                scope_sha256="scope", waived_through_request=1, original_response_sha256=digest(raw)
            )
        )
    )
    return query, identity


def test_confirmed_access_does_not_refund_failure_or_enable_network(tmp_path):
    query, identity = prepared(tmp_path)
    wire = ConfirmedAccessWire(tmp_path, (query,), "scope")
    assert wire.state["used"] == 1 and wire.state["maximum"] == 2
    with pytest.raises(ValueError, match="NETWORK_DISABLED"):
        wire.get(identity)
    assert wire.state["used"] == 1


def test_later_auth_failure_cannot_be_waived_again(tmp_path):
    query, identity = prepared(tmp_path)
    path = tmp_path / "budget.json"
    state = json.loads(path.read_bytes())
    second = state["events"][0] | dict(number=2)
    (tmp_path / "events/0002.json").write_bytes(canonical(second))
    state.update(used=2, events=state["events"] + [second])
    path.write_bytes(canonical(state))
    wire = ConfirmedAccessWire(tmp_path, (query,), "scope")
    assert wire.state["halted"] and wire.state["used"] == 2


def test_observed_alphanumeric_security_is_retained_without_coercion():
    from kmast.data.historical_security_v2 import snapshot_rows
    from tests.test_df009 import security

    row = security()
    row.update(ISU_CD="KR700104K010", ISU_SRT_CD="00104K")
    raw = canonical(dict(OutBlock_1=[row]))
    parsed = snapshot_rows(raw, digest(raw), "20221226", "KOSPI")
    assert len(parsed) == 1 and parsed[0]["ISU_SRT_CD"] == "00104K"
    row.update(ISU_CD="KYG5307W1015", ISU_SRT_CD="900140")
    raw = canonical(dict(OutBlock_1=[row]))
    assert snapshot_rows(raw, digest(raw), "20221226", "KOSPI")[0]["ISU_CD"] == "KYG5307W1015"


def test_access_confirmation_cannot_clear_hash_or_clock_halt(tmp_path):
    query, _ = prepared(tmp_path)
    path = tmp_path / "budget.json"
    state = json.loads(path.read_bytes())
    state["halted"] = "CACHE_RAW_HASH_CONFLICT"
    path.write_bytes(canonical(state))
    wire = ConfirmedAccessWire(tmp_path, (query,), "scope")
    assert wire.state["halted"] == "CACHE_RAW_HASH_CONFLICT"


def test_dated_multisource_identity_and_official_filing_date():
    from kmast.data.cross_source_identity import corroborate
    from tests.test_df009 import security

    event = dict(
        receipt="20230101000001",
        event_date="2023-01-02",
        corp_code="00123456",
        corporate_verified=True,
        stock_code_candidate="005930",
        document_legal_names=["(주)테스트법인"],
        document_raw_sha256="a" * 64,
        dart_row_sha256="b" * 64,
    )
    row = security()
    row["ISU_ABBRV"] = "테스트법인"
    result = corroborate(event, [row], [row])
    assert result["CORP_STOCK_LINK_VERIFIED"] is True
    assert result["event_date"] == "2023-01-02" and result["CORPORATE_ACTION_PENDING"]
    event["stock_code_candidate"] = ""
    assert corroborate(event, [row], [row])["CORP_STOCK_LINK_VERIFIED"] is None


def test_name_or_code_history_conflicts_remain_quarantined():
    from kmast.data.cross_source_identity import corroborate
    from tests.test_df009 import security

    event = dict(
        receipt="20240102000001",
        event_date="2024-01-02",
        corp_code="00123456",
        corporate_verified=True,
        stock_code_candidate="005930",
        document_legal_names=["다른법인"],
        document_raw_sha256="a" * 64,
        dart_row_sha256="b" * 64,
    )
    row = security()
    assert corroborate(event, [row], [row])["CORP_STOCK_LINK_VERIFIED"] is None
    event["document_legal_names"] = ["테스트법인"]
    changed = row | dict(ISU_CD="KR7005930011")
    assert corroborate(event, [row], [changed])["CORP_STOCK_LINK_VERIFIED"] is None
