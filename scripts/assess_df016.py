"""Offline official-source assessment and frozen proposal. Never loads credentials."""

import json
from datetime import UTC, datetime
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import digest

ROUTES = {
    "FHKST03010200": "inquire-time-itemchartprice",
    "FHPST01060000": "inquire-time-itemconclusion",
    "FHKST01010200": "inquire-asking-price-exp-ccn",
}
HOST = "https://openapivts.koreainvestment.com:29443"


def main():
    private = Path("data/data-first-private-df016-sources")
    public = Path("artifacts/df016")
    manifest = json.loads((private / "manifest.json").read_bytes())
    texts = {}
    for name, record in manifest.items():
        raw = (private / "raw" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
        texts[name] = raw.decode("utf-8")
    capabilities = []
    for tr, route in ROUTES.items():
        doc = json.loads(texts["portal:" + route])
        sample = texts[
            "sample:examples_llm/domestic_stock/"
            + route.replace("-", "_")
            + "/"
            + route.replace("-", "_")
            + ".py"
        ]
        assert doc["virtualDomain"] == HOST and doc["virtualTrId"] == tr
        assert tr in sample and '"demo"' in sample
        props = doc["apiPropertys"]
        fields = [p["propertyCd"] for p in props if p["bodyType"] == "res_b"]
        params = [p["propertyCd"] for p in props if p["bodyType"] == "req_b"]
        capabilities.append(
            dict(
                tr_id=tr,
                path=doc["accessUrl"],
                paper_https_root=HOST,
                paper_documented=True,
                actual_paper_support=None,
                actual_returned_fields=None,
                documented_response_fields=fields,
                documented_parameters=params,
                venues_documented={"J": "KRX", "NX": "NXT", "UN": "CONSOLIDATED"},
                selected_venue="J",
                tr_cont_pagination_supported=False,
                documented_max_rows=30 if tr == "FHKST03010200" else None,
                documented_depth=10 if tr == "FHKST01010200" else None,
                actual_response_delay=None,
                key_specific_rate_limit=None,
                portal_sha256=manifest["portal:" + route]["sha256"],
            )
        )
    calls = []

    def add(symbol, tr, timing, hour=None):
        params = dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD=symbol)
        if hour:
            params["FID_INPUT_HOUR_1"] = hour
        if tr == "FHKST03010200":
            params.update(FID_PW_DATA_INCU_YN="Y", FID_ETC_CLS_CODE="")
        calls.append(
            dict(
                ordinal=len(calls) + 1,
                symbol=symbol,
                tr_id=tr,
                method="GET",
                url=HOST + "/uapi/domestic-stock/v1/quotations/" + ROUTES[tr],
                parameters=params,
                timing=timing,
            )
        )

    for symbol in ("073240", "462860"):
        for tr in ROUTES:
            add(
                symbol,
                tr,
                "Capability probe after 09:01:20 KST, sequential response+3.10s",
                None if tr == "FHKST01010200" else "090100",
            )
    for hour in ("090500", "090600", "091500", "091600"):
        for symbol in ("073240", "462860"):
            add(
                symbol,
                "FHKST03010200",
                "Not before " + hour[:2] + ":" + hour[2:4] + ":10 KST",
                hour,
            )
            add(
                symbol,
                "FHKST01010200",
                "After preceding bar validation and response+3.10s; "
                "later-signal quote only if qualified signal already exists, otherwise diagnostic",
            )
    protocol = json.loads((public / "DF016_PROTOCOL.json").read_bytes())
    proposal = dict(
        protocol_sha256=digest((public / "DF016_PROTOCOL.json").read_bytes()),
        scope=protocol["pilot_proposal"],
        calls=calls,
        rest_auth_url=HOST + "/oauth2/tokenP",
        rest_auth_attempts_max=1,
        websocket_approval_attempts_max=0,
        executed=False,
        scheduled=False,
        record_clock="Request send, full body receipt, parse/validation completion in aware UTC; "
        "monotonic reservation/cooldown alongside KST session context",
        runtime_requirements=[
            "Fresh exact human approval",
            "PAPER-only trusted TLS server verification",
            "No redirects/proxies/endpoint overrides",
            "Persistent pre-I/O cumulative budget and process lock",
            "Raw/normalized SHA and immutable receipt lineage",
            "Response-completion cooldown 3.10s",
            "Cut off at 09:22 KST; never reschedule",
            "No credentials in logs or raw auth responses",
            "Rights and retention confirmed before raw collection",
            "Unknown semantics stay HOLD",
        ],
        retention_deletion="30-day cap is a proposal, not a deletion job; review retention rights "
        "and derived/hash policy before future execution",
        executor_implemented=False,
    )
    assert len(calls) == 22 and 1 + 2 * len(calls) == 45
    atomic_json(public / "PILOT_PROPOSAL.json", proposal)
    result = dict(
        milestone="DF016",
        assessed_at=datetime.now(UTC).isoformat(),
        baseline_sha=protocol["baseline_sha"],
        baseline_tests=637,
        protocol_sha256=proposal["protocol_sha256"],
        protocol_remote_sha="db8d07f",
        contract="B_BAR_ORB_V1_SEPARATE_FROM_B_TICK_ORB",
        status="BAR_ORB_COLLECTION_PENDING_APPROVAL",
        source_status="BAR_ORB_HTTPS_SOURCE_DOCUMENTED",
        qualification="NO_ACTUAL_DATA; DOCUMENTED_SCHEMA_ONLY",
        capabilities=capabilities,
        sources=manifest,
        public_document_count=len(manifest),
        authenticated_market_requests=0,
        rest_authentication_attempts=0,
        websocket_approval_attempts=0,
        websocket_connections=0,
        account_queries=0,
        orders=0,
        cancels=0,
        live_authentication=0,
        scheduled_execution=False,
        actual_raw_prices=None,
        actual_orb5=None,
        actual_orb15=None,
        actual_signal_available_at=None,
        actual_later_quote=None,
        actual_fill=None,
        actual_profit=None,
        exact_bar_label_semantics=None,
        exact_bar_end_publication_delay=None,
        closed_bar_price_mapping_verified=False,
        bar_volume_mapping_verified=False,
        calendar_for_pilot_verified=False,
        market_state_verified=False,
        correction_coverage_verified=False,
        clock_error_bound_seconds=None,
        first_trade_independently_verified=False,
        rvol="RVOL_NOT_READY",
        prior_qualified_sessions=0,
        history_route="FHKST03010230",
        history_paper_support="NOT_DOCUMENTED_BLOCKED",
        history_sample_max_rows=120,
        history_sample_max_years=1,
        rvol_acquisition="20 separately approved prospective same-symbol same-window KRX sessions, "
        "or separately approved/documented eligible history; no assumed PAPER history",
        pilot_proposal_sha256=digest((public / "PILOT_PROPOSAL.json").read_bytes()),
        prior_tick_transport_status="B_ORB_STREAM_TRANSPORT_BLOCKED",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    atomic_json(public / "results.json", result)
    print(
        "DF016 official HTTPS schemas documented; actual auth/market requests 0; approval pending"
    )


if __name__ == "__main__":
    main()
