"""Authored census/accounting fixtures only; no new economic outcome experiments."""

from decimal import Decimal as D

import pytest

from kmast.data.research_spacing import ResearchGapGuard
from kmast.research.event_census import audit_exposure, classify_title, identity_flags, receipt_ok


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("주요사항보고서(자기주식 취득 결정)", ("D1", "ORIGINAL")),
        ("[기재정정]주요사항보고서(자기주식취득결정)", ("D1", "CORRECTION")),
        ("[철회]주요사항보고서(자기주식취득결정)", ("D1", "CANCEL")),
        ("주요사항보고서(자기주식취득신탁계약체결결정)", ("D2", "ORIGINAL")),
        (
            "[연장결정]주요사항보고서(자기주식취득신탁계약체결결정)",
            ("TRUST_EXTENSION", "EXTENSION"),
        ),
        (
            "[기재정정][연장결정]주요사항보고서(자기주식취득신탁계약체결결정)",
            ("TRUST_EXTENSION", "CORRECTION"),
        ),
        ("주요사항보고서(자기주식처분결정)", ("DISPOSAL", "ORIGINAL")),
        ("자기주식취득결과보고서", ("ACTUAL_ACQUISITION_OR_COMPLETION", "ORIGINAL")),
        ("주요사항보고서(주식소각결정)", ("RETIREMENT", "ORIGINAL")),
    ],
)
def test_frozen_title_families_and_revisions(title, expected):
    assert classify_title(title) == expected


def test_identity_code_change_is_flag_not_backfilled():
    a = dict(
        rcept_no="20240101000001",
        corp_code="00123456",
        stock_code="123450",
        rcept_dt="20240101",
        corp_cls="Y",
    )
    b = a | {"rcept_no": "20240201000001", "stock_code": "987650"}
    c = a | {"rcept_no": "20240201000002", "corp_code": "00987654"}
    d = a | {"rcept_no": "20240201000003", "stock_code": "", "corp_cls": "E"}
    flags = identity_flags([a, b, c, d])
    assert receipt_ok(a) and not receipt_ok(a | {"rcept_no": "bad"})
    assert "CORPORATION_MULTIPLE_SOURCE_CODES" in flags[a["rcept_no"]]
    assert "SOURCE_CODE_MULTIPLE_CORPORATIONS" in flags[a["rcept_no"]]
    assert "MISSING_OR_AMBIGUOUS_STOCK_CODE" in flags[d["rcept_no"]]
    assert all("HISTORICAL_LISTING_STATUS_UNKNOWN" in f for f in flags.values())


def test_observed_spacing_violation_stops_without_threshold_relaxation():
    guard = ResearchGapGuard()
    guard.response_completed(100)
    with pytest.raises(PermissionError, match="OBSERVED_GAP_BELOW"):
        guard.authorize_next_request(103.035479)
    assert guard.stopped and not guard.observations[-1]["compliant"]
    with pytest.raises(PermissionError, match="COLLECTION_STOPPED"):
        guard.authorize_next_request(110)
    with pytest.raises(ValueError, match="CANNOT_BE_RELAXED"):
        ResearchGapGuard(minimum=3)


def test_high_resolution_wait_rechecks_early_wake():
    guard, clock, waits = ResearchGapGuard(), [100.0], []
    guard.response_completed(clock[0])

    def early(seconds):
        waits.append(seconds)
        clock[0] += seconds - 0.02 if len(waits) == 1 else seconds

    guard.wait(lambda: clock[0], early)
    assert len(waits) == 2
    guard.authorize_next_request(clock[0])
    assert guard.observations[-1]["gap"] >= 3.10 - 1e-12
    assert not guard.stopped
    with pytest.raises(PermissionError, match="PREVIOUS_RESPONSE_NOT_OBSERVED"):
        guard.authorize_next_request(clock[0] + 5)


def test_raw_page_hash_scope_and_date_precision():
    from kmast.data.store import canonical, digest
    from kmast.research.event_census import read_census_page

    row = dict(rcept_no="20240101000001", corp_code="00123456", stock_code="", rcept_dt="20240101")
    raw = canonical(dict(status="000", page_no=1, list=[row]))
    body = read_census_page(raw, digest(raw), "20240101", "20240131", 1)
    assert body["list"][0]["rcept_dt"] == "20240101"
    assert "published_at" not in body["list"][0]
    with pytest.raises(ValueError, match="RAW_PAGE_HASH_CONFLICT"):
        read_census_page(raw + b" ", digest(raw), "20240101", "20240131", 1)
    with pytest.raises(ValueError, match="RECEIPT_OUTSIDE_SCOPE"):
        read_census_page(raw, digest(raw), "20240201", "20240229", 1)


def test_missing_price_events_remain_in_candidate_denominator():
    from kmast.data.store import canonical, digest
    from kmast.research.event_census import read_census_page

    rows = [
        dict(
            rcept_no="20240101000001",
            corp_code="00123456",
            stock_code="123450",
            rcept_dt="20240101",
            report_nm="자기주식취득결정",
        ),
        dict(
            rcept_no="20240101000002",
            corp_code="00987654",
            stock_code="",
            rcept_dt="20240101",
            report_nm="자기주식취득결정",
        ),
    ]
    raw = canonical(dict(status="000", page_no=1, list=rows))
    body = read_census_page(raw, digest(raw), "20240101", "20240131", 1)
    assert len(body["list"]) == 2
    assert all(classify_title(r["report_nm"])[0] == "D1" for r in body["list"])


def test_receipt_duplicates_revisions_and_conflicts_are_not_new_events():
    from kmast.research.event_census import register_source_receipt

    original = dict(
        rcept_no="20240101000001",
        corp_code="00123456",
        rcept_dt="20240101",
        report_nm="자기주식취득결정",
    )
    registry = {}
    assert register_source_receipt(registry, original) == "NEW"
    assert register_source_receipt(registry, original) == "DUPLICATE"
    assert register_source_receipt(registry, original | {"corp_code": "00987654"}) == "CONFLICT"
    correction = original | {
        "rcept_no": "20240201000001",
        "rcept_dt": "20240201",
        "report_nm": "[기재정정]자기주식취득결정",
    }
    assert register_source_receipt(registry, correction) == "NEW"
    assert sum(classify_title(r["report_nm"])[1] == "ORIGINAL" for r in registry.values()) == 1


def test_exposure_is_marked_inventory_not_target_and_partial_is_hold():
    from kmast.research.event_replay import event_replay
    from tests.test_df006 import event_test_panel

    rows = event_test_panel()
    result = event_replay(rows, rows, rows[21].exchange_date, (3, 20, 5, ".5"), "D1", frozenset())
    audit = audit_exposure(result)
    assert D(audit["initial"]["target"]) == D(".25")
    assert D(audit["initial"]["postfill_weight"]) < D(".25")
    assert audit["final_quantity"] > 0 and audit["unfulfilled_reduction_days"] > 0
    assert audit["pnl_unchanged"]
    assert any(p["reduction_requested"] and p["residual_hold"] for p in audit["daily_path"])


def test_price_appreciation_can_raise_weight_without_new_buy():
    from kmast.research.event_replay import event_replay
    from tests.test_df006 import event_test_panel

    rows = list(event_test_panel())
    for i in range(22, 25):
        rows[i] = rows[i].model_copy(
            update={"open": D(15000), "close": D(15000), "high": D(15000), "low": D(15000)}
        )
    replay = event_replay(
        tuple(rows), tuple(rows), rows[21].exchange_date, (3, 20, 5, "1"), "D1", frozenset()
    )
    audit = audit_exposure(replay)
    assert audit["initial_order_target_compliant"]
    assert audit["above_reference_days"] > 0
    assert audit["above_reference_without_additional_buy"]
    assert audit["buy_execution_count"] == 1
