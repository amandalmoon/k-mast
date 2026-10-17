"""Authored entitlement/control fixtures; not real economic evidence."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from kmast.research.entitlements import (
    CorporateActionEntitlementLedger,
    DividendAction,
    SettledTrade,
    settle_t_plus_two,
    verify_daily_ex_dividend_definition,
)
from kmast.research.event_controls import (
    MatchingObservation,
    audit_fixed_controls,
    match_non_events,
    statistical_sample_admissible,
)
from scripts.prepare_df011 import guard_unapproved_expansion


def action(**changes):
    base = DividendAction(
        identity="FIXTURE_DIVIDEND",
        symbol="131290",
        share_class="COMMON",
        ex_day=date(2022, 12, 28),
        last_purchase_day=date(2022, 12, 27),
        record_day=date(2022, 12, 31),
        declared_day=date(2023, 2, 22),
        resolved_day=date(2023, 3, 24),
        amount_known_on=date(2023, 3, 25),
        gross_per_share=D(500),
        scheduled_payment_day=date(2023, 4, 10),
        actual_payment_day=None,
        payment_evidence_known_on=None,
        issuer_paid_month=None,
        identity_verified=True,
        settlement_verified=True,
        amount_verified=True,
        full_action_window_verified=False,
        evidence_hashes=("a" * 64,),
    )
    return replace(base, **changes)


def trades():
    return (
        SettledTrade("buy", "131290", date(2022, 12, 27), date(2022, 12, 29), 10),
        SettledTrade("sell", "131290", date(2023, 1, 3), date(2023, 1, 5), -10),
    )


@pytest.mark.parametrize("change", ["endpoint", "tr", "field", "body"])
def test_code_definition_cannot_transfer_from_other_endpoint(change):
    detail = {
        "accessUrl": "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        "realTrId": "FHKST03010100",
    }
    field = {
        "propertyCd": "flng_cls_code",
        "bodyType": "res_b",
        "description": "01 : 권리락<br/>02 : 배당락<br/>03 : 분배락",
    }
    assert verify_daily_ex_dividend_definition(detail, [field])
    if change == "endpoint":
        detail["accessUrl"] = "/master"
    if change == "tr":
        detail["realTrId"] = "OTHER"
    if change == "field":
        field["propertyCd"] = "another_field"
    if change == "body":
        field["bodyType"] = "req_b"
    assert not verify_daily_ex_dividend_definition(detail, [field])


def test_rights_survive_sale_after_ex_date_and_do_not_follow_final_position():
    ledger = CorporateActionEntitlementLedger(action(), trades())
    assert sum(t.quantity for t in trades()) == 0
    assert ledger.entitled_quantity() == 10
    s = ledger.snapshot(date(2023, 3, 25), date(2023, 3, 25))
    assert s["gross_entitlement"] == "5000"
    assert s["unpaid_receivable"] == "5000"
    assert s["spendable_cash_increment"] == "0"
    assert s["actual_after_tax_total_pnl"] is None


def test_buy_on_ex_date_settles_after_record_and_has_no_rights():
    late = (SettledTrade("late", "131290", date(2022, 12, 28), date(2023, 1, 2), 10),)
    assert CorporateActionEntitlementLedger(action(), late).entitled_quantity() == 0
    wrong = (replace(late[0], settlement_day=date(2022, 12, 29)),)
    with pytest.raises(ValueError, match="CUTOFF"):
        CorporateActionEntitlementLedger(action(), wrong).entitled_quantity()


def test_future_amount_never_enters_frozen_signal_or_earlier_nav():
    a = CorporateActionEntitlementLedger(action(), trades())
    b = CorporateActionEntitlementLedger(action(gross_per_share=D(100000)), trades())
    assert a.decision_inputs(date(2022, 12, 27)) == b.decision_inputs(date(2022, 12, 27)) == {}
    for ledger in (a, b):
        earlier = ledger.snapshot(date(2022, 12, 27), date(2022, 12, 27))
        assert earlier["entitled_quantity"] is None
        assert earlier["gross_entitlement"] is None
        retrospective = ledger.snapshot(date(2023, 3, 25), date(2022, 12, 27))
        assert retrospective["gross_entitlement"] is None


def test_scheduled_payment_and_known_month_cannot_become_actual_cash():
    ledger = CorporateActionEntitlementLedger(
        action(issuer_paid_month="2023-04", issuer_paid_month_known_on=date(2024, 3, 20)), trades()
    )
    old_knowledge = ledger.snapshot(date(2023, 4, 30), date(2023, 4, 30))
    assert old_knowledge["unpaid_receivable"] == "5000"
    newer = ledger.snapshot(date(2023, 4, 30), date(2024, 3, 20))
    assert newer["unpaid_receivable"] is None
    assert newer["net_dividend_cash_verified"] is None
    assert newer["spendable_cash_increment"] == "0"
    assert "CASH_PAYMENT_VERIFIED" not in newer["statuses"]


def test_actual_payment_tax_and_total_price_path_are_independent_gates():
    a = action(
        actual_payment_day=date(2023, 4, 10),
        payment_evidence_known_on=date(2023, 4, 11),
        full_action_window_verified=True,
    )
    ledger = CorporateActionEntitlementLedger(
        a,
        trades(),
        verified_dividend_tax=D(100),
        tax_evidence_hash="b" * 64,
        tax_known_on=date(2023, 4, 12),
        price_only_pnl=D(-1000),
        price_pnl_as_of=date(2023, 1, 5),
        price_path_verified=True,
    )
    assert ledger.snapshot(date(2023, 4, 9), date(2023, 4, 12))["spendable_cash_increment"] == "0"
    no_tax_yet = ledger.snapshot(date(2023, 4, 10), date(2023, 4, 11))
    assert not no_tax_yet["total_return_verified"]
    assert "TAX_TREATMENT_PENDING" in no_tax_yet["statuses"]
    final = ledger.snapshot(date(2023, 4, 10), date(2023, 4, 12))
    assert final["net_dividend_cash_verified"] == "4900"
    assert final["modeled_after_tax_total_pnl"] == "3900"
    assert final["actual_after_tax_total_pnl"] is None
    rejected = replace(ledger, price_path_verified=False).snapshot(
        date(2023, 4, 10), date(2023, 4, 12)
    )
    assert not rejected["total_return_verified"]
    assert rejected["modeled_after_tax_total_pnl"] is None


def test_no_adjusted_plus_cash_or_duplicate_execution():
    with pytest.raises(ValueError, match="DOUBLE_COUNT"):
        CorporateActionEntitlementLedger(action(), trades(), price_basis="ADJUSTED")
    with pytest.raises(ValueError, match="DUPLICATE"):
        CorporateActionEntitlementLedger(action(), (trades()[0], trades()[0]))


def test_missing_settlement_action_evidence_cannot_promote_diagnostic():
    ledger = CorporateActionEntitlementLedger(
        action(settlement_verified=False), trades(), price_only_pnl=D(999999)
    )
    s = ledger.snapshot(date(2024, 1, 1), date(2024, 1, 1))
    assert s["entitled_quantity"] is None and s["gross_entitlement"] is None
    assert not s["total_return_verified"] and s["modeled_after_tax_total_pnl"] is None


def test_settlement_calendar_never_invents_year_end_holiday():
    sessions = tuple(date(2022, 12, d) for d in (27, 28, 29)) + (date(2023, 1, 2),)
    assert settle_t_plus_two(date(2022, 12, 27), sessions) == date(2022, 12, 29)
    assert settle_t_plus_two(date(2022, 12, 28), sessions) == date(2023, 1, 2)
    with pytest.raises(ValueError, match="VERIFIED_SESSION"):
        settle_t_plus_two(date(2022, 12, 30), sessions)


def obs(code, **changes):
    base = MatchingObservation(
        code,
        "KOSPI",
        date(2023, 1, 10),
        date(2023, 1, 9),
        date(2023, 1, 9),
        (1.0, 0.1, 0.2),
        True,
        True,
        True,
        date(2023, 1, 9),
    )
    return replace(base, **changes)


def test_matching_rejects_future_unknown_pit_and_event_contaminated_controls():
    target = obs("T")
    valid = tuple(obs(str(i)) for i in range(3))
    wrong = (
        obs("future", feature_available_on=date(2023, 1, 10)),
        obs("future_census", non_event_available_on=date(2023, 1, 15)),
        obs("unknown", non_event_verified=None),
        obs("event", non_event_verified=False),
        obs("survivor", pit_identity_verified=False),
        obs("market", market="KOSDAQ"),
    )
    assert set(match_non_events("receipt", target, valid + wrong)) == {"0", "1", "2"}
    assert match_non_events("receipt", target, valid[:2] + wrong) == ()
    assert match_non_events("receipt", target, valid) == match_non_events(
        "receipt", target, valid[::-1]
    )


def test_post_event_contamination_never_rematches_fixed_controls():
    selected = match_non_events("receipt", obs("T"), tuple(obs(str(i)) for i in range(5)))
    clean = dict.fromkeys(selected, True)
    assert audit_fixed_controls(selected, clean)
    contaminated = clean | {selected[0]: False, "extra_unselected": True}
    assert not audit_fixed_controls(selected, contaminated)
    assert not audit_fixed_controls(selected, {selected[0]: None})
    assert set(selected) == set(clean)


def test_insufficient_sample_never_runs_significance():
    assert not statistical_sample_admissible(8, 8, 8, 1, 1.0)
    assert not statistical_sample_admissible(30, 10, 20, 5, 0.79)
    assert statistical_sample_admissible(30, 10, 20, 5, 0.8)


def test_five_remaining_mapped_events_are_exact_and_unapproved():
    rows = json.loads(Path("artifacts/df009r1/event-linkage.json").read_bytes())
    used = {
        r["receipt"]
        for r in json.loads(Path("artifacts/df010/DF010_PROTOCOL.json").read_bytes())["targets"]
    }
    expected = {r["receipt"] for r in rows if r["CORP_STOCK_LINK_VERIFIED"]} - used
    protocol = json.loads(Path("artifacts/df011/DF011_PROTOCOL.json").read_bytes())
    assert {r["receipt"] for r in protocol["expansion_targets"]} == expected
    assert len(expected) == 5
    plan = json.loads(Path("artifacts/df011/next-price-proposal.json").read_bytes())
    assert not plan["execution_authorized"] and not plan["unused_df010_budget_carried"]
    with pytest.raises(PermissionError, match="SEPARATE_APPROVAL"):
        guard_unapproved_expansion(plan)
