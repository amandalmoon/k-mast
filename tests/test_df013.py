"""Synthetic protocol/time/accounting tests, never market evidence."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from kmast.data.models import KST
from kmast.data.orb_observation import (
    COLUMNS,
    Context,
    FrameArchive,
    OpeningResearch,
    Receipt,
    parse,
    require_pilot_permission,
)
from kmast.research.counterfactual_readiness import ControlEvidence, readiness

OPEN = datetime(2026, 10, 19, 9, tzinfo=KST)
CONTEXT = Context(OPEN.date(), "KOSPI", OPEN, True, True, True, "SYNTHETIC_ONLY")


def frame(second=0, *, channel="H0STCNT0", **changes):
    row = dict.fromkeys(COLUMNS[channel], "0")
    row.update(MKSC_SHRN_ISCD="005930", HOUR_CLS_CODE="0", MARKET_CLS_CODE="2")
    stamp = OPEN + timedelta(seconds=second)
    if channel == "H0STCNT0":
        row.update(
            BSOP_DATE=stamp.strftime("%Y%m%d"),
            STCK_CNTG_HOUR=stamp.strftime("%H%M%S"),
            STCK_PRPR="100",
            CNTG_VOL="1",
            ACML_VOL=str(second + 1),
            ACML_TR_PBMN=str(100 * (second + 1)),
            TRHT_YN="N",
        )
    else:
        row.update(BSOP_HOUR=stamp.strftime("%H%M%S"))
        for level in range(1, 11):
            row.update(
                {
                    f"ASKP{level}": str(101 + level),
                    f"BIDP{level}": str(100 - level),
                    f"ASKP_RSQN{level}": "100",
                    f"BIDP_RSQN{level}": "200",
                }
            )
    row.update(changes)
    return ("0|" + channel + "|001|" + "^".join(row[c] for c in COLUMNS[channel])).encode()


def tick(second=0, *, sequence=None, channel="H0STCNT0", context=CONTEXT, **changes):
    receipt = Receipt(
        OPEN + timedelta(seconds=second, milliseconds=100),
        (second + 1) * 10**9,
        "fixture-1",
        sequence or second + 1,
    )
    return parse(frame(second, channel=channel, **changes), receipt, context)[0]


def engine():
    result = OpeningResearch(CONTEXT, "005930")
    for channel in COLUMNS:
        result.acknowledge(channel, OPEN - timedelta(seconds=1))
    return result


@pytest.mark.parametrize("minutes", [5, 15])
def test_opening_range_requires_completion_and_receipt_boundary(minutes):
    state = engine()
    end = minutes * 60
    for second in range(end + 1):
        state.ingest(tick(second, STCK_PRPR="999" if second == end else "100"))
    assert state.range_high(minutes, OPEN + timedelta(seconds=end - 1)) is None
    assert state.range_high(minutes, OPEN + timedelta(seconds=end + 1)) is None
    assert state.range_high(minutes, OPEN + timedelta(seconds=end + 2)) == Decimal(100)
    assert state.rvol_status() == "RVOL_NOT_READY"


def test_vwap_uses_eligible_trade_value_not_auction_cumulative_value():
    state = engine()
    state.ingest(tick(0, ACML_VOL="1001", ACML_TR_PBMN="999999"))
    state.ingest(tick(1, STCK_PRPR="200", ACML_VOL="1002", ACML_TR_PBMN="1000199"))
    assert state.vwap(OPEN + timedelta(seconds=1)) == 100
    assert state.vwap(OPEN + timedelta(seconds=2)) == 150


def test_preopen_exclusion_and_synthetic_context_cannot_promote_observed_data():
    state = engine()
    r = Receipt(OPEN - timedelta(seconds=60), 1, "fixture-1", 1)
    preopen = parse(frame(-60, ACML_VOL="50", ACML_TR_PBMN="5000"), r, CONTEXT)[0]
    state.ingest(preopen)
    state.ingest(tick(0, sequence=2, ACML_VOL="51", ACML_TR_PBMN="5100"))
    assert not state.defects and len(state.trades) == 1
    assert state.vwap(OPEN + timedelta(seconds=1)) == 100
    with pytest.raises(ValueError):
        parse(frame(), replace(tick().receipt, origin="OBSERVED"), CONTEXT)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "reverse",
        "missing",
        "cumulative",
        "late",
        "halt",
        "unknown",
        "quote_date",
        "inactivity",
        "sequence_reused",
        "correction_unknown",
        "turnover_regression",
    ],
)
def test_observed_defects_fail_closed(fault):
    state = engine()
    state.ingest(tick(0))
    candidate = tick(1)
    if fault == "duplicate":
        candidate = replace(tick(0), receipt=candidate.receipt)
    elif fault == "reverse":
        state.ingest(tick(2, sequence=2))
        candidate = tick(1, sequence=3)
    elif fault == "missing":
        candidate = tick(2, sequence=3)
    elif fault == "inactivity":
        candidate = tick(6, sequence=2, ACML_VOL="2")
    elif fault == "sequence_reused":
        candidate = tick(1, sequence=1)
    elif fault == "turnover_regression":
        candidate = tick(1, ACML_TR_PBMN="0")
    elif fault == "cumulative":
        candidate = tick(1, ACML_VOL="0")
    elif fault == "late":
        candidate = replace(
            candidate, receipt=replace(candidate.receipt, received_at=OPEN + timedelta(seconds=10))
        )
    elif fault == "halt":
        candidate = tick(1, TRHT_YN="Y")
    elif fault == "unknown":
        unknown = replace(CONTEXT, continuous_verified=False)
        state = OpeningResearch(unknown, "005930")
        candidate = tick(1, context=unknown)
    elif fault == "quote_date":
        unknown = replace(CONTEXT, calendar_verified=False)
        state = OpeningResearch(unknown, "005930")
        candidate = tick(1, channel="H0STASP0", context=unknown)
        assert candidate.exchange_time is None
    elif fault == "correction_unknown":
        unknown = replace(CONTEXT, corrections_verified=False)
        state = OpeningResearch(unknown, "005930")
        candidate = tick(1, context=unknown)
    state.ingest(candidate)
    assert state.defects
    assert state.range_high(5, OPEN + timedelta(minutes=6)) is None
    assert state.vwap(OPEN + timedelta(minutes=6)) is None


def test_disconnect_reconnect_never_restores_missing_opening_history():
    state = engine()
    state.ingest(tick(0))
    state.disconnect()
    next_tick = tick(1)
    state.ingest(
        replace(next_tick, receipt=replace(next_tick.receipt, connection="fixture-2", sequence=1))
    )
    for channel in COLUMNS:
        state.acknowledge(channel, OPEN + timedelta(seconds=2))
    assert "RECONNECTED_WINDOW_INCOMPLETE" in state.defects
    assert state.range_high(5, OPEN + timedelta(minutes=6)) is None


def test_signal_quote_alignment_is_later_and_stale_safe():
    state = engine()
    quote = tick(1, sequence=1, channel="H0STASP0")
    state.ingest(quote)
    assert state.later_quote(OPEN, OPEN + timedelta(seconds=1, milliseconds=200)) == quote
    assert state.later_quote(quote.receipt.received_at, quote.receipt.received_at) is None
    assert state.later_quote(OPEN, OPEN + timedelta(seconds=3)) is None


def test_subscription_acknowledgement_cannot_travel_back_in_time():
    state = OpeningResearch(CONTEXT, "005930")
    for channel in COLUMNS:
        state.acknowledge(channel, OPEN + timedelta(hours=1))
    for second in range(301):
        state.ingest(tick(second))
    assert state.range_high(5, OPEN + timedelta(minutes=5, seconds=2)) is None
    assert state.vwap(OPEN + timedelta(minutes=5, seconds=2)) is None


def test_validation_delay_is_information_unavailable_before_completion():
    state = engine()
    for second in range(301):
        observation = tick(second)
        state.ingest(
            observation, validated_at=observation.receipt.received_at + timedelta(seconds=60)
        )
    assert state.range_high(5, OPEN + timedelta(minutes=5, seconds=2)) is None
    assert state.range_high(5, OPEN + timedelta(minutes=6, seconds=2)) == 100
    with pytest.raises(ValueError):
        state.ingest(tick(302), validated_at=OPEN)


def test_crossed_quote_and_unacknowledged_channel_block_use():
    state = engine()
    state.ingest(tick(0, channel="H0STASP0", ASKP1="98", BIDP1="99"))
    assert state.later_quote(OPEN, OPEN + timedelta(seconds=1)) is None
    state = OpeningResearch(CONTEXT, "005930")
    for second in range(301):
        state.ingest(tick(second))
    assert state.range_high(5, OPEN + timedelta(minutes=6)) is None


def test_archive_duplicate_retention_restart_and_integrity(tmp_path):
    store = FrameArchive(tmp_path)
    original = frame()
    r = tick().receipt
    store.append(original, r, CONTEXT)
    store.append(original, replace(r, sequence=2, monotonic_ns=r.monotonic_ns + 1), CONTEXT)
    reopened = FrameArchive(tmp_path)
    assert len(reopened.records) == 2
    reopened.verify()
    with pytest.raises(ValueError):
        reopened.append(original, r, CONTEXT)
    wire = next((tmp_path / "wire").iterdir())
    wire.write_bytes(b"corrupted")
    with pytest.raises(AssertionError):
        reopened.verify()


@pytest.mark.parametrize(
    "raw", [b'{"approval_key":"fixture"}', b"1|H0STCNI9|001|account", b"0|H0STCNT0|1|bad"]
)
def test_auth_account_and_invalid_frame_not_archived(tmp_path, raw):
    with pytest.raises(ValueError):
        FrameArchive(tmp_path).append(raw, tick().receipt, CONTEXT)
    assert not list(tmp_path.rglob("*.bin"))


def test_storage_and_secret_boundaries(tmp_path):
    with pytest.raises(PermissionError):
        FrameArchive(tmp_path, cap=1).append(frame(), tick().receipt, CONTEXT)
    with pytest.raises(PermissionError):
        FrameArchive(tmp_path).append(frame(), tick().receipt, CONTEXT, secrets=(b"005930",))
    assert not list(tmp_path.rglob("*.bin"))


@pytest.mark.parametrize(
    "approved,environment,entitlement",
    [(False, "PAPER", True), (True, "LIVE", True), (True, "PAPER", False)],
)
def test_new_pilot_authentication_boundary(approved, environment, entitlement):
    with pytest.raises(PermissionError):
        require_pilot_permission(
            approved=approved, environment=environment, entitlement_verified=entitlement
        )


@pytest.mark.parametrize(
    "missing",
    [
        "pit_at_decision",
        "historical_feature_availability",
        "tradability_liquidity",
        "safe_corporate_link",
        "decision_time_census",
        "correction_lineage",
    ],
)
def test_counterfactual_missing_input_never_matches(missing):
    rows = tuple(
        ControlEvidence(str(i), True, 20, True, True, True, True, True, True) for i in range(3)
    )
    rows = (replace(rows[0], **{missing: False}), *rows[1:])
    assert readiness(rows)["status"] == "UNMATCHED"


def test_future_contamination_never_used_for_preselection():
    rows = tuple(
        ControlEvidence(str(i), True, 20, True, True, True, True, True, False) for i in range(3)
    )
    assert readiness(rows)["preselectable_candidates"] == 3
    assert readiness(rows)["future_auditable_candidates"] == 0
    with pytest.raises(ValueError):
        readiness((rows[0], rows[0]))
