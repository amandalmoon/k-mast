"""Cached-only D1 stages and deterministic pilot nomination, never economic replay."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import median

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from kmast.research.counterfactual_readiness import ControlEvidence, readiness
from scripts.run_df005 import load_histories


def main():
    public = Path("artifacts/df013")
    private = Path("data/data-first-private-df013-readiness")
    protocol = json.loads((public / "DF013_PROTOCOL.json").read_bytes())
    for name, expected in protocol["source_hashes"].items():
        assert digest(Path(name).read_bytes()) == expected
    panel = json.loads(Path("data/data-first-private-df005-panel/manifest.json").read_bytes())
    panel_protocol = json.loads(Path("artifacts/df005/DF005_PROTOCOL.json").read_bytes())
    markets = {
        code: market
        for key, market in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]
        for code in panel_protocol[key]
    }
    histories = {code: load_histories(panel, code, "RAW") for code in markets}
    indices = {
        market: load_histories(panel, code, "RAW")
        for market, code in [("KOSPI", "0001"), ("KOSDAQ", "1001")]
    }
    snapshots = {}
    source_hashes = {}
    for path in Path("data/data-first-private-df009-krx-access-confirmed/normalized").glob(
        "*.json"
    ):
        record = json.loads(path.read_bytes())
        assert digest(canonical(record["rows"])) == record["normalized_rows_sha256"]
        query = record["query"]
        snapshots[(query["basDd"], query["market"])] = record["rows"]
        source_hashes[path.as_posix()] = digest(path.read_bytes())
    census_path = Path("data/data-first-private-df007-census-v2/all-normalized-disclosures.json")
    census = json.loads(census_path.read_bytes())["records"]
    source_hashes[census_path.as_posix()] = digest(census_path.read_bytes())
    links = json.loads(Path("artifacts/df009r1/event-linkage.json").read_bytes())
    linked = {r["historical_short_code"]: r for r in links if r.get("CORP_STOCK_LINK_VERIFIED")}
    events = []
    for target in protocol["events"]:
        day, market = date.fromisoformat(target["entry_date"]), target["then_market"]
        key = (day.strftime("%Y%m%d"), market)
        exact = snapshots.get(key)
        earlier = sorted(k for k in snapshots if k[1] == market and k[0] < key[0])
        nearest = snapshots[earlier[-1]] if earlier else []
        prior20, aligned20, available20 = [], [], []
        index_dates = [r.exchange_date for r in indices[market] if r.exchange_date < day][-20:]
        for code, rows in histories.items():
            if code == target["symbol"] or markets[code] != market:
                continue
            prior = [r for r in rows if r.exchange_date < day][-20:]
            if len(prior) == 20 and all(
                r.turnover is not None and r.volume is not None and r.volume > 0 for r in prior
            ):
                prior20.append(code)
                if [r.exchange_date for r in prior] == index_dates and len(index_dates) == 20:
                    aligned20.append(code)
                    if all(r.available_at.date() < day for r in prior):
                        available20.append(code)
        price_set = set(prior20)
        exact_codes = {r["ISU_SRT_CD"] for r in exact or [] if r["ISU_SRT_CD"] != target["symbol"]}
        previous_codes = {r["ISU_SRT_CD"] for r in nearest if r["ISU_SRT_CD"] != target["symbol"]}
        ordinary = {
            r["ISU_SRT_CD"]
            for r in exact or []
            if r["ISU_SRT_CD"] != target["symbol"]
            and r["KIND_STKCERT_TP_NM"] == "보통주"
            and r["SECUGRP_NM"] == "주권"
            and r["LIST_DD"] <= key[0]
        }
        # Current census short codes are diagnostic only, never a historical corporate join.
        short_observed = {
            r["row"]["stock_code"]
            for r in census
            if date.fromisoformat(
                r["row"]["rcept_dt"][:4]
                + "-"
                + r["row"]["rcept_dt"][4:6]
                + "-"
                + r["row"]["rcept_dt"][6:]
            )
            < day
        }
        verified_links = {
            code
            for code in price_set
            if code in linked and linked[code]["safe_relevant_correction_lineage_verified"]
        }
        stages = readiness(
            tuple(
                ControlEvidence(
                    standard_code=next(
                        (r["ISU_CD"] for r in exact or [] if r["ISU_SRT_CD"] == code),
                        "UNVERIFIED:" + code,
                    ),
                    pit_at_decision=code in ordinary,
                    prior_sessions=20 if code in aligned20 else 0,
                    historical_feature_availability=code in available20,
                    tradability_liquidity=False,
                    safe_corporate_link=code in verified_links,
                    decision_time_census=code in verified_links,
                    correction_lineage=code in verified_links,
                    future_contamination_coverage=False,
                )
                for code in sorted(price_set)
            )
        )
        assert stages["status"] == "UNMATCHED"
        evidence = dict(
            **target,
            status="UNMATCHED",
            exact_entry_snapshot_available=exact is not None,
            exact_entry_pit_candidates=len(exact_codes),
            exact_entry_ordinary_share_candidates=len(ordinary),
            nearest_previous_snapshot_date=earlier[-1][0] if earlier else None,
            previous_snapshot_securities_diagnostic=len(previous_codes),
            prior20_same_market_cached_candidates=len(price_set),
            index_aligned_prior20_candidates=len(aligned20),
            exact_ordinary_and_aligned_price_overlap=len(ordinary & set(aligned20)),
            previous_snapshot_and_price_overlap_diagnostic=len(previous_codes & price_set),
            exact_pit_and_price_overlap=len(exact_codes & price_set),
            direct_census_short_code_overlap_diagnostic=len(price_set & short_observed),
            safe_historical_corporate_links_among_price_candidates=len(verified_links),
            verified_historical_feature_availability_candidates=len(available20),
            verified_entry_tradability_and_liquidity_candidates=0,
            complete_dart_contamination_auditable_candidates=0,
            preselectable_controls=stages["preselectable_candidates"],
            valid_three_control_set=False,
            matching_executed=False,
            future_returns_read=False,
            missing=[
                *([] if exact is not None else ["Exact entry-date security snapshot"]),
                "PIT short/standard/corporate code histories for control panel",
                "Historical feature availability",
                "Decision-time tradability/halt/action evidence",
                "Complete original/correction and fixed future contamination coverage",
            ],
            additional_exact_request_count=None,
            observed_prior20_cache_fraction_denominator=(
                "25 preselected survivor-panel symbols in same market, not the historical universe"
            ),
            prior20_cache_fraction_of_selected_panel=str(Decimal(len(price_set)) / 25),
            complete_control_cache_coverage_fraction="0",
        )
        detail = dict(
            event=evidence,
            prior20_codes=sorted(price_set),
            exact_pit_codes=sorted(exact_codes),
            direct_census_overlap_codes=sorted(price_set & short_observed),
        )
        payload = canonical(detail)
        detail_file = "versions/" + digest(payload) + ".json"
        immutable_write(private / detail_file, payload)
        evidence["private_detail_sha256"] = digest(payload)
        evidence["private_detail_file"] = detail_file
        events.append(evidence)
    nomination = []
    for market in ["KOSPI", "KOSDAQ"]:
        eligible = []
        for code, rows in histories.items():
            if markets[code] != market:
                continue
            prior = [r for r in rows if r.exchange_date <= date(2025, 10, 16)][-20:]
            if len(prior) == 20 and all(r.turnover is not None for r in prior):
                liquidity = median(r.turnover for r in prior)
                if liquidity >= 1000000000:
                    eligible.append(
                        (digest(f"DF013:{market}:{code}".encode()), code, str(liquidity))
                    )
        rank, code, liquidity = min(eligible)
        nomination.append(
            dict(
                market=market,
                symbol=code,
                rank_sha256=rank,
                historical_median_turnover=liquidity,
                selection_information_end="2025-10-16",
                current_listing_and_tradability_verified=False,
                eligible_cached_candidates=len(eligible),
            )
        )
    atomic_json(
        public / "pilot-proposal.json",
        dict(
            status="PROPOSAL_ONLY_NOT_AUTHORIZED",
            targets=nomination,
            **protocol["track_b"]["pilot_proposal"],
            environment="PAPER",
            channels=protocol["track_b"]["channels"],
            approval_path="POST /oauth2/Approval",
            approval_payload_keys=["grant_type", "appkey", "secretkey"],
            websocket="ws://ops.koreainvestment.com:31000",
            subscriptions=4,
            actual_authentication=0,
            actual_connections=0,
            actual_messages=0,
            subscription_quota_verified=None,
            paper_account_entitlement_verified=None,
            provider_cost=None,
            message_rate=None,
            observed_latency=None,
            observed_store_bytes=None,
            active_window_seconds=2100,
            full_store_budget_basis=(
                "1 GiB raw cap + 2 GiB normalized/journal headroom; "
                "stop before exceeding, not a throughput forecast"
            ),
            heartbeat_control_messages_max=2400,
            total_outgoing_messages_max=2412,
            prerequisites=[
                "Explicit new user approval",
                "Current listing/market verification for nominated symbols",
                "Official session/open confirmation",
                "PAPER entitlement and four-subscription capacity confirmation",
                "No automatic REAL fallback",
            ],
            storage="data/data-first-private-df013-pilot/",
        ),
    )
    immutable_write(private / "input-hashes.json", canonical(source_hashes))
    atomic_json(
        public / "d1-readiness.json",
        dict(
            events=events,
            technical_events=6,
            matched_events=0,
            status="D1_COUNTERFACTUAL_DATA_DEPENDENCY_PENDING",
            economic_experiments=0,
            full_control_sets=0,
            exact_new_api_budget=None,
            complete_event_cache_coverage_fraction="0",
            threshold_contract_unchanged=True,
            population_supply_unavailable_claim=False,
            semantics=dict(
                proposal="MARKET_PURCHASE_D1_V2",
                validated=False,
                frozen_d1_changed=False,
                categories=[
                    "CASH_DIRECT_MARKET_PURCHASE_DECISION",
                    "NONCASH_ACQUISITION",
                    "TRUST_CONTRACT",
                    "PLAN_CHANGE",
                    "CORRECTION_WITHDRAWAL_CANCELLATION",
                    "ACTUAL_ACQUISITION_RESULT",
                    "SHARE_RETIREMENT",
                ],
                rule=(
                    "Original body, funding, method, decision-vs-result "
                    "and official parent lineage "
                    "required; title alone => UNKNOWN; future subtype separately preregistered"
                ),
            ),
        ),
    )
    print(json.dumps(dict(events=6, matched=0, nominations=nomination)))


if __name__ == "__main__":
    main()
