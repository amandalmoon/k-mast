import pytest

from kmast.alpha.readiness import observation_bar
from kmast.brokers.interfaces import MockBroker
from kmast.core.study import StudyContract
from kmast.data.models import universe_asof
from kmast.research.economics import CostScenario
from kmast.research.publication import require_public_file
from kmast.research.qualification import corporate_action_basis, day_status
from kmast.research.rights import PurposeGrant, RightsDocument, rights_decision

from .test_km001 import daily
from .test_km003 import OPEN, change
from .test_km005 import freeze, master, rows


def doc(**updates):
    return RightsDocument.model_validate(
        dict(
            identity="SYNTHETIC_DOC",
            title="SYNTHETIC",
            official_url="https://apiportal.koreainvestment.com/synthetic-fixture",
            checked_at=OPEN,
            content_sha256="a" * 64,
            body_obtained=True,
            applicable_scope="PERSONAL_OWN_INVESTMENT",
        )
        | updates
    )


def grant(purpose="MEMORY_ANALYSIS", **updates):
    return PurposeGrant.model_validate(
        dict(
            purpose=purpose,
            status="ALLOWED",
            basis="DIRECT_TEXT",
            document_ref="SYNTHETIC_DOC",
            clause="SYNTHETIC_NOT_LEGAL_EVIDENCE",
            limitation="OWN_INVESTMENT_LOCAL_ONLY",
        )
        | updates
    )


def decision(g, docs=None):
    return rights_decision(g, docs or (doc(),), own_investment=True, local_only=True)


def test_purpose_specific_memory_right_does_not_imply_storage_right():
    assert decision(grant()) == "ALLOWED_SCOPED_NOT_G1_APPROVAL"
    assert decision(grant("RAW_RETENTION", status="RESTRICTED")).startswith(
        "EXTERNAL_EVIDENCE_PENDING"
    )


def test_private_backtest_interpretation_cannot_be_confirmed_permission():
    assert decision(grant("PRIVATE_BACKTEST", basis="INTERPRETATION")).startswith(
        "EXTERNAL_EVIDENCE_PENDING"
    )


def test_unknown_source_or_title_only_or_wrong_host_rejects_allow_claim():
    for source in (
        doc(identity="DIFFERENT"),
        doc(body_obtained=False),
        doc(official_url="https://example.invalid"),
    ):
        assert decision(grant(), (source,)) == "EXTERNAL_EVIDENCE_PENDING_SOURCE"


def test_grant_scope_and_third_party_restriction():
    assert rights_decision(grant(), (doc(),), own_investment=True, local_only=False).startswith(
        "OUTSIDE"
    )
    assert decision(grant("THIRD_PARTY_DATA", status="PROHIBITED")) == "PROHIBITED"


def test_future_security_master_never_backfills_past_universe():
    from datetime import timedelta

    future = change(master(), available_at=OPEN + timedelta(days=1))
    assert universe_asof((future,), OPEN.date(), OPEN) == ()
    assert universe_asof((master("DELISTED"),), OPEN.date(), OPEN) == ()


def test_raw_action_basis_is_not_adjusted_total_return():
    corporate_action_basis("RAW", True)
    with pytest.raises(ValueError):
        corporate_action_basis("ADJUSTED", True)


def test_calendar_unknown_and_suspension_not_fabricated_missing():
    assert day_status("005930", OPEN.date(), OPEN, None, (master(),), False) == "UNKNOWN_CALENDAR"
    assert (
        day_status("005930", OPEN.date(), OPEN, (OPEN.date(),), (master("SUSPENDED"),), False)
        == "SUSPENDED"
    )


def test_date_only_rows_do_not_gain_fabricated_bar_times(fixture):
    request, _, _ = daily(fixture)
    for row in rows(fixture):
        assert row.bar_start is None and row.bar_end is None
        with pytest.raises(ValueError):
            observation_bar(row, request.symbol)


def test_estimated_cost_not_contract_and_g0_stays_incomplete():
    c = CostScenario(
        identity="ESTIMATE",
        effective_from=OPEN.date(),
        effective_to=OPEN.date(),
        provenance="RESEARCH_ESTIMATE",
        evidence_ref="SYNTHETIC",
    )
    assert not c.verified_for(OPEN.date(), OPEN.date())
    assert StudyContract().missing_economic_fields()
    with pytest.raises(PermissionError):
        freeze().require_oos(freeze().identity, OPEN, True)


def test_actual_order_and_cancel_blocked():
    for operation in (MockBroker().submit_order, MockBroker().cancel_order):
        with pytest.raises(PermissionError):
            operation()


def test_private_raw_data_and_credentials_never_public():
    for path in (".env", "data/km005r1-private/response.json"):
        with pytest.raises(PermissionError):
            require_public_file(path)
    with pytest.raises(PermissionError):
        require_public_file("artifacts/row.json", {"data_origin": "KIS_READONLY", "close": 123})
