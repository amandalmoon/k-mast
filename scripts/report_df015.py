"""Hash-verified cached official evidence only. No network imports or key loading."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from kmast.data.panel_acquisition import atomic_json
from kmast.data.paper_security import pilot_disposition
from kmast.data.store import digest


def main():
    public = Path("artifacts/df015")
    old = json.loads(Path("artifacts/df014/preflight.json").read_bytes())
    source = old["source"]
    raw = (
        Path("data/data-first-private-df014-sources/raw") / (source["sha256"] + ".bin")
    ).read_bytes()
    assert digest(raw) == source["sha256"]
    config = yaml.safe_load(raw)
    assert config["vops"] == "ws://ops.koreainvestment.com:31000"
    assert config["vps"] == "https://openapivts.koreainvestment.com:29443"
    sources = [dict(label="kis_devlp.yaml", **source)]
    manifest = json.loads(Path("data/data-first-private-df013-sources/manifest.json").read_bytes())
    texts = {}
    for name, entry in manifest.items():
        raw = (
            Path("data/data-first-private-df013-sources/raw") / (entry["sha256"] + ".bin")
        ).read_bytes()
        assert digest(raw) == entry["sha256"]
        texts[name] = raw.decode("utf-8")
        sources.append(dict(label=name, **entry))
    auth = texts["examples_user/kis_auth.py"]
    assert 'p["secretkey"]' in auth and "/oauth2/Approval" in auth
    assert '_base_headers_ws["approval_key"] = approval_key' in auth
    assert "websockets.connect(url)" in auth
    # Scope is the cached corpus. A failed string search cannot prove absence
    # of provider products, current FAQ answers, private circuits or TLS routes.
    try:
        clock = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, timeout=10)
        clock_result = dict(
            exit_code=clock.returncode,
            stdout_sha256=digest(clock.stdout),
            stderr_sha256=digest(clock.stderr),
        )
    except (OSError, subprocess.TimeoutExpired):
        clock_result = dict(exit_code=None)
    now = datetime.now(UTC)
    stress = json.loads((public / "stress.json").read_bytes())
    assert stress["origin"] == "SYNTHETIC" and len(stress["cases"]) == 10
    alternatives = []
    for name, route, question in [
        (
            "KRX official information distribution / licensed vendor",
            "https://www.krx.co.kr/",
            "Licensed per-event KRX trades/depth, history, capture rights and minimum subscription",
        ),
        (
            "LS Securities OpenAPI",
            "https://openapi.ls-sec.co.kr/",
            "Encrypted quotation service, KRX timestamps, corrections, halt/VI, storage rights",
        ),
        (
            "Kiwoom official API",
            "https://openapi.kiwoom.com/",
            "Official secure transport, venue, timestamps, event completeness and retention rights",
        ),
    ]:
        alternatives.append(
            dict(
                candidate=name,
                reference_locator=route,
                reference_retrieved_in_df015=False,
                assessment="UNVERIFIED_CANDIDATE_NOT_USABLE",
                next_evidence_needed=question,
                krx_trades=None,
                depth=None,
                exchange_event_time=None,
                receipt_measurement_validated=None,
                corrections_gaps_halts=None,
                opening_5_15_coverage=None,
                secure_authentication=None,
                retention_analysis_rights=None,
                historical_coverage=None,
                subscription_cap=None,
                fee=None,
                setup_cost=None,
                operating_cost=None,
                total_cost=None,
                source_switch_authorized=False,
            )
        )
    result = dict(
        milestone="DF015",
        assessed_at=now.isoformat(),
        research_mode="OFFLINE_CACHED_OFFICIAL_ONLY",
        baseline_sha="6780ecfcbd8a4e7e2918846f6262d8206b4f5155",
        baseline_tests=608,
        protocol_remote_sha="7c8d5aa",
        protocol_sha256=digest((public / "DF015_PROTOCOL.json").read_bytes()),
        status="DF015_TRANSPORT_PROTECTION_PENDING",
        supply_status="B_ORB_STREAM_TRANSPORT_BLOCKED",
        alternative_assessment_status="DF015_ALTERNATIVE_SOURCE_ASSESSMENT_READY",
        alternative_assessment_meaning="Comparison and inquiry matrix ready; no provider qualified",
        sources=sources,
        documented_plaintext_endpoint=config["vops"],
        auth_root=config["vps"],
        documented_official_secure_paper_endpoint=None,
        private_encrypted_circuit_support=None,
        official_current_faq_reference_security_notices=None,
        secure_provider_path_nonexistence_proven=False,
        source_freshness="Pinned cache, not a fresh/current provider confirmation",
        static_document_integrity_verified=True,
        provider_security_truth_verified=False,
        runtime_tls_established=False,
        runtime_tls_certificate_verified=False,
        runtime_secure_route_registry_empty=True,
        document_json_cannot_enable_transport=True,
        authentication_attempts=0,
        websocket_connections=0,
        actual_market_frames=0,
        actual_subscriptions=0,
        account_queries=0,
        orders=0,
        cancels=0,
        live_authentication=0,
        network_document_fetches=0,
        tls_test_connections=0,
        scheduled_execution=False,
        human_streaming_approval=False,
        pilot_disposition=pilot_disposition(now),
        pilot_window_end="2026-10-19T09:25:00+09:00",
        automatic_reschedule=False,
        market_context=dict(
            calendar_pilot_day_verified=False,
            continuous_verified=False,
            corrections_verified=False,
            current_halt_vi_resumption=None,
            venue="KRX_CHANNELS_ONLY_NXT_NOT_COMBINED",
            krx_nxt_runtime_disambiguation_verified=False,
            timestamp_resolution_seconds=1,
            timestamp_resolution_means_latency=False,
            quote_business_date_missing=True,
            provider_sequence=None,
            complete_first_opening_trade=None,
            independent_loss_reference=None,
            clock_status=clock_result,
            clock_error_bound_seconds=None,
            clock_sync_verified=False,
            session_special_open_verified=False,
            rvol="RVOL_NOT_READY",
            research_status="HOLD",
        ),
        actual_orb5=None,
        actual_orb15=None,
        actual_vwap=None,
        actual_returns=None,
        alternative_sources=alternatives,
        cheapest_verified_eligible_source=None,
        stress_cases=len(stress["cases"]),
        stress_sha256=digest((public / "stress.json").read_bytes()),
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    atomic_json(public / "results.json", result)
    print("DF015 cached official evidence assessed; transport BLOCKED; auth/socket/frame counts 0")


if __name__ == "__main__":
    main()
