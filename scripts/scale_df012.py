"""Evidence inventory and conditional scaling bounds, never a new collection approval."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from scripts.evaluate_df011 import SourceText


def main():
    public = Path("artifacts/df012")
    result = json.loads((public / "results.json").read_bytes())
    action_store = Path("data/data-first-private-df012-actions")
    sources = json.loads((action_store / "manifest.json").read_bytes())
    for record in sources.values():
        raw = (action_store / "raw" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
    prospectus = sources["352770-prospectus"]
    parser = SourceText()
    parser.feed(
        (action_store / "raw" / (prospectus["sha256"] + ".bin")).read_text(encoding="utf-8")
    )
    text = " ".join(" ".join(parser.parts).split())
    assert "클리노믹스" in text and "무상증자" in text and "0.5" in text
    assert "2023년 08월 11일" in text
    field_source = json.loads(Path("artifacts/df011/corporate-action-lineage.json").read_bytes())[
        "sources"
    ]["kis-daily-official-property"]
    raw = (
        Path("data/data-first-private-df011-sources/raw") / (field_source["sha256"] + ".bin")
    ).read_bytes()
    assert digest(raw) == field_source["sha256"]
    field = next(p for p in json.loads(raw) if p["propertyCd"] == "flng_cls_code")
    assert "01 : 권리락" in field["description"]
    action = dict(
        symbol="352770",
        provider_day="2023-08-10",
        field="flng_cls_code",
        value="01",
        exact_daily_meaning="EX_RIGHTS",
        provider_prtt_rate="-33.02",
        official_sources={k: v for k, v in sources.items() if k.startswith("352770-")},
        official_field_source=field_source,
        issuer_plan=dict(record_day="2023-08-11", bonus_new_shares_per_existing="0.5"),
        reconciliation_complete=False,
        qualification="HOLD",
        reasons=[
            "NONCONSTANT_FACTOR_WITHOUT_ACTION_LINEAGE",
            "WARMUP_CROSSES_RIGHTS_ACTION",
        ],
        original_method="NONCASH_RECEIPT",
        event_interpretation="Not evidence of issuer-funded market purchases",
        frozen_d1_rule_changed=False,
        no_price_rewrite=True,
        no_dividend_or_share_adjustment_added=True,
        complete_action_halt_history=None,
    )
    atomic_json(public / "corporate-action-review.json", action)
    # A requested-history dividend flag occurs after 012330's frozen replay.
    # Corroborate it without importing later dividend decisions into entry data.
    source = sources["012330-annual-2023"]
    parser = SourceText()
    parser.feed((action_store / "raw" / (source["sha256"] + ".bin")).read_text(encoding="utf-8"))
    text = " ".join(" ".join(parser.parts).split())
    assert "현대모비스" in text and "2022년 사업연도" in text
    assert "주당 3,000원" in text and "2023년 3월 22일 주주총회" in text
    assert "02 : 배당락" in field["description"]
    atomic_json(
        public / "outside-replay-action-review.json",
        dict(
            symbol="012330",
            provider_day="2022-12-28",
            provider_code="02",
            exact_daily_meaning="EX_DIVIDEND",
            official_field_source=field_source,
            retrospective_issuer_source=source,
            fiscal_year=2022,
            gross_common_final_dividend_per_share="3000",
            selected_replay_end="2022-12-16",
            selected_replay_end_quantity=0,
            outside_selected_warmup_and_replay=True,
            used_in_entry_signal=False,
            entitlement_added_to_pnl=False,
            complete_action_history=None,
            actual_net_cash=None,
            actual_payment_day=None,
        ),
    )
    candidates = [
        r
        for r in json.loads(
            Path("data/data-first-private-df007-census-v2/candidate-register.json").read_bytes()
        )
        if r["family"] == "D1"
    ]
    census = json.loads(
        Path("data/data-first-private-df007-census-v2/all-normalized-disclosures.json").read_bytes()
    )["records"]
    corrections = [r for r in census if r["family"] == "D1" and r["revision"] == "CORRECTION"]
    original_receipts = {r["receipt"] for r in candidates}
    revision_receipts = {r["row"]["rcept_no"] for r in corrections}
    folder = Path("data/data-first-private-df008-documents/qualified")
    metadata = {p.stem: json.loads(p.read_bytes()) for p in folder.glob("*.json")}
    old = json.loads(Path("data/data-first-private-df006-events/manifest.json").read_bytes())
    cached_originals = (set(metadata) | set(old["documents"])) & original_receipts
    cached_revisions = set(metadata) & revision_receipts
    parsed_originals = {
        r
        for r in set(metadata) & original_receipts
        if metadata[r]["DOCUMENT_VERIFIED"] and metadata[r]["EVENT_FAMILY_VERIFIED"]
    }
    parsed_revisions = {r for r in cached_revisions if metadata[r]["DOCUMENT_VERIFIED"]}
    pairs = set()
    for event in candidates:
        day = date.fromisoformat(event["receipt_date"])
        for d in (day, day - timedelta(days=1)):
            for market in ("KOSPI", "KOSDAQ"):
                pairs.add((d.strftime("%Y%m%d"), market))
    lineage = json.loads(Path("artifacts/df009r1/snapshot-lineage.json").read_bytes())
    existing = {(r["query"]["basDd"], r["query"]["market"]) for r in lineage}
    missing = sorted(pairs - existing)
    grid = dict(
        scope="ALL_620_TITLE_CANDIDATES_INVENTORY_NOT_A_30_EVENT_SELECTION_OR_APPROVAL",
        date_type="Event and adjacent calendar dates, not asserted trading sessions",
        execution_authorized=False,
        queries=[dict(basDd=d, market=m) for d, m in missing],
    )
    atomic_json(public / "scaling-krx-date-inventory.json", grid)
    cache = json.loads((public / "cache-audit.json").read_bytes())
    cached_index_slots = sum(t["cached_index_rows"] for t in cache["targets"])
    index_slots = sum(e["index_rows"] for e in result["events"])
    budget = json.loads(Path("data/data-first-private-df012-prices/budget.json").read_bytes())
    elapsed = (
        datetime.fromisoformat(budget["events"][-1]["received_at"])
        - datetime.fromisoformat(budget["events"][0]["request_time"])
    ).total_seconds()
    feasibility = dict(
        title_candidates=len(candidates),
        title_candidate_corporations=len({r["corp_code"] for r in candidates}),
        title_candidate_receipt_dates=len({r["receipt_date"] for r in candidates}),
        potential_d1_corrections=len(corrections),
        cached_original_documents=len(cached_originals),
        df008_parsed_family_original_documents=len(parsed_originals),
        original_documents_not_cached=len(original_receipts - cached_originals),
        cached_revision_documents=len(cached_revisions),
        parsed_revision_documents=len(parsed_revisions),
        revision_documents_not_cached=len(revision_receipts - cached_revisions),
        related_revision_lineage_complete_for_population=False,
        identity_mapped_events=8,
        new_price_events=5,
        new_technical_events=result["technical_replay_events"],
        cumulative_selected_technical_events=2 + result["technical_replay_events"],
        selected_new_hold_count=5 - result["technical_replay_events"],
        selected_new_hold_denominator=5,
        full_research_eligible_events=0,
        actual_preselected_non_event_controls=0,
        full_complete_units_still_needed=30,
        minimum_additional_event_identities_if_all_eight_recover=22,
        conditional_additional_paid_market_events_if_seven_recover=23,
        minimum_additional_distinct_corporations_if_all_eight_recover=2,
        conditional_additional_paid_market_corporations_if_seven_recover=3,
        paid_subtype_requires_future_preregistration_not_a_current_d1_change=True,
        known_noncash_originals_in_mapped_eight=1,
        maximum_mapped_market_purchase_candidates=7,
        actual_additional_corporations_to_investigate=None,
        population_conversion_rate=None,
        additional_candidates_outside_mapped_corporations=len({r["corp_code"] for r in candidates})
        - 8,
        all_candidate_krx_date_market_pairs=len(pairs),
        cached_relevant_krx_pairs=len(pairs & existing),
        all_candidate_missing_krx_queries=len(missing),
        thirty_event_subset_krx_queries=None,
        thirty_event_subset_dart_originals_and_corrections=None,
        nominal_30_treatment_plus_90_control_windows=120,
        nominal_uncached_raw_adjusted_pages_after_controls_are_fixed=240,
        minimum_valid_control_triplets_at_80_percent=24,
        minimum_valid_control_slots=72,
        required_preselection_feature_panel=(
            "PIT universe x prior20 observed sessions x event dates; not only the 90 winners"
        ),
        actual_control_feature_panel_pages=None,
        actual_pit_industry_coverage=None,
        actual_extra_authentication_budget=None,
        actual_complete_event_request_cost=None,
        actual_complete_event_monetary_cost=None,
        vendor_unit_price=None,
        labor_cost=None,
        measured_new_requests=budget["requests"],
        measured_new_authentication=budget["authentication"],
        measured_response_window_seconds=elapsed,
        cached_index_observation_slots=cached_index_slots,
        total_index_observation_slots=index_slots,
        index_cache_slot_reuse_fraction=str(cached_index_slots / index_slots),
        index_reuse_denominator=(
            "Event-window observation slots, not unique independent market observations"
        ),
        sampled_hold_rate_is_population_estimate=False,
        stop_rules=[
            (
                "No inferential/OOS test below 30 full units,10 firms,20 dates,5 ex-ante "
                "bearish contexts,80% matched controls"
            ),
            (
                "Unknown PIT/feature availability or incomplete contamination census => "
                "unmatched; no rematch after future audit"
            ),
            "Original title is not proof of a market-funded repurchase; verify acquisition method",
            (
                "Missing action/settlement/payment/tax evidence => corresponding HOLD/NULL, "
                "never favorable synthetic values"
            ),
            "New symbol/date/service or request-budget expansion needs separate approval",
        ],
        collection_authorized_by_this_inventory=False,
    )
    immutable_write(
        Path("data/data-first-private-df012-scaling/census-input-hashes.json"),
        canonical(
            {
                "candidate_register": digest(
                    Path(
                        "data/data-first-private-df007-census-v2/candidate-register.json"
                    ).read_bytes()
                ),
                "census": digest(
                    Path(
                        "data/data-first-private-df007-census-v2/all-normalized-disclosures.json"
                    ).read_bytes()
                ),
            }
        ),
    )
    atomic_json(public / "scaling-feasibility.json", feasibility)
    print(
        json.dumps(
            {
                k: feasibility[k]
                for k in (
                    "title_candidates",
                    "title_candidate_corporations",
                    "cached_original_documents",
                    "original_documents_not_cached",
                    "all_candidate_missing_krx_queries",
                    "full_complete_units_still_needed",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
