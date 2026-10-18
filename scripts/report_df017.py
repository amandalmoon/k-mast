"""Aggregate only verified existing private evidence. Never authenticates or schedules."""

import json
from datetime import UTC, datetime
from pathlib import Path

from kmast.data.https_bar_gate import END, PROPOSAL_HASH, STORE, TRUSTED_REVIEWS
from kmast.data.https_bar_quality import audit_store
from kmast.data.https_bar_store import Journal
from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest


def main():
    public = Path("artifacts/df017")
    proposal = Path("artifacts/df016/PILOT_PROPOSAL.json").read_bytes()
    assert digest(proposal) == PROPOSAL_HASH
    now = datetime.now(UTC)
    metrics = None
    audit = None
    auth_count = price_count = 0
    # This version has no registered real review. Do not promote arbitrary files.
    if (STORE / "binding.json").exists():
        binding = json.loads((STORE / "binding.json").read_bytes())
        pair = (binding["approval_sha256"], binding["preflight_sha256"])
        if pair not in TRUSTED_REVIEWS or binding["origin"] != "OBSERVED":
            raise PermissionError("UNREGISTERED_OR_SYNTHETIC_REAL_STORE_NOT_EVIDENCE")
        journal = Journal(STORE, binding)
        auth_count = sum(r["ordinal"] == 0 for r in journal.reservations)
        price_count = len(journal.reservations) - auth_count
        # Future actual qualification requires full source/semantic audit, never implied.
        audit = audit_store(journal)
        audit_path = Path("data/data-first-private-df017-observation-audit/quality.json")
        atomic_json(audit_path, audit)
        metrics = dict(
            attempts=audit["attempts"],
            raw_bytes=audit["raw_bytes"],
            total_bytes=audit["total_bytes"],
            audit_sha256=digest(audit_path.read_bytes()),
            independently_qualified=False,
        )
    elif any(Path("data/data-first-private-df017-retention-audit").glob("*.json")):
        raise PermissionError(
            "PURGED_OR_INTERRUPTED_STORE_REQUIRES_RETENTION_AUDIT_NOT_ZERO_COUNTS"
        )
    result = dict(
        milestone="DF017",
        baseline_sha="892e7565f2000e98e9bb301833b7fbd4b6e5266d",
        baseline_tests=685,
        assessed_at=now.isoformat(),
        protocol_remote_sha="f162c20",
        protocol_sha256=digest((public / "DF017_PROTOCOL.json").read_bytes()),
        proposal_sha256=PROPOSAL_HASH,
        proposal_calls=22,
        status="DF017_MISSED_COLLECTION_WINDOW"
        if now >= END
        else "DF017_COLLECTION_PENDING_APPROVAL",
        default_state="NETWORK_DISABLED",
        registered_approval_count=len(TRUSTED_REVIEWS),
        new_human_approval_verified=False,
        service_permission_verified=False,
        current_provider_rate_verified=False,
        retention_research_hash_rights_verified=False,
        pilot_calendar_security_status_verified=False,
        measured_clock_error_seconds=None,
        tls_runtime_verified=False,
        tls_security_code_only=True,
        auth_attempts=auth_count,
        market_attempts=price_count,
        websocket_approval_attempts=0,
        websocket_connections=0,
        accounts=0,
        orders=0,
        cancels=0,
        live_authentication=0,
        scheduled_execution=False,
        retention_job_scheduled=False,
        actual_retention_purges=0,
        actual_metrics=metrics,
        actual_http_status_counts=None,
        actual_rows=None,
        actual_first_last_data_time=None,
        actual_request_completion_validation_delays=None,
        actual_same_bar_changes=None,
        actual_raw_normalized_hashes=None,
        quality={
            k: None
            for k in (
                "SOURCE_OK",
                "SCHEMA_OK",
                "TEMPORAL_OK",
                "MARKET_OK",
                "CORRECTION_OK",
                "ORB5_OK",
                "ORB15_OK",
                "POST_SIGNAL_QUOTE_OK",
            )
        },
        blocking_reasons=[
            "EXACT_NEW_HUMAN_APPROVAL_ABSENT",
            "INDEPENDENT_PREFLIGHT_NOT_REGISTERED",
            "PAPER_SERVICE_RATE_RIGHTS_CALENDAR_SECURITY_CLOCK_EVIDENCE_MISSING",
            "BAR_LABEL_FIRST_TRADE_MARKET_CORRECTION_UNVERIFIED",
        ],
        actual_orb5=None,
        actual_orb15=None,
        actual_candidates=None,
        actual_post_signal_quote=None,
        execution_verified=False,
        actual_profit=None,
        rvol="RVOL_NOT_READY",
        prior_qualified_sessions=0,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        tick_transport="B_ORB_STREAM_TRANSPORT_BLOCKED",
    )
    if audit is not None:
        quality = {
            k: True if counts["True"] else False if counts["False"] else None
            for k, counts in audit["quality_counts"].items()
        }
        result.update(
            new_human_approval_verified=True,
            service_permission_verified=True,
            current_provider_rate_verified=True,
            retention_research_hash_rights_verified=True,
            pilot_calendar_security_status_verified=True,
            actual_http_status_counts=audit["http_status_counts"],
            actual_rows=audit["rows"],
            actual_first_last_data_time=dict(private_audit_sha256=metrics["audit_sha256"]),
            actual_request_completion_validation_delays=dict(
                count=len(audit["delays"]), private_audit_sha256=metrics["audit_sha256"]
            ),
            actual_same_bar_changes=dict(
                comparisons=len(audit["same_bar_changes"]),
                changed=sum(bool(c["changed_fields"]) for c in audit["same_bar_changes"]),
            ),
            actual_raw_normalized_hashes=dict(private_audit_sha256=metrics["audit_sha256"]),
            quality=quality,
            blocking_reasons=["BAR_LABEL_FIRST_TRADE_MARKET_CORRECTION_UNVERIFIED"],
        )
        if quality["SOURCE_OK"]:
            result["status"] = "DF017_HTTPS_PAPER_SUPPLY_VERIFIED"
            result["tls_runtime_verified"] = True
        elif auth_count or price_count:
            result["status"] = "DF017_PAPER_ACCESS_BLOCKED"
    atomic_json(public / "results.json", result)
    print("DF017 aggregate written; source/ORB/quote remain separate, no economic approval")


if __name__ == "__main__":
    main()
