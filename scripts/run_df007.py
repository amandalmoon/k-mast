"""Offline B001 census and unchanged-ledger exposure audit. No API clients."""

import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from kmast.research.event_census import (
    audit_exposure,
    classify_title,
    identity_flags,
    read_census_page,
    receipt_ok,
    register_source_receipt,
)
from scripts.evaluate_df006 import qualify_window
from scripts.run_df005 import load_histories

SOURCE = Path("data/data-first-private-df006-events")
PRIVATE = Path("data/data-first-private-df007-census-v2")
PUBLIC = Path("artifacts/df007")
PROTOCOL_COMMIT = "697cf97"


def day(value):
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def merge_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1] + timedelta(days=1):
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def main():
    protocol = (PUBLIC / "DF007_PROTOCOL.json").read_bytes()
    frozen = subprocess.check_output(
        ["git", "show", PROTOCOL_COMMIT + ":artifacts/df007/DF007_PROTOCOL.json"]
    )
    assert protocol == frozen
    manifest = json.loads((SOURCE / "manifest.json").read_bytes())
    assert manifest["complete"] and len(manifest["pages"]) == 210
    budget = json.loads((SOURCE / "budget.json").read_bytes())
    assert budget["used"] == 212 and len(budget["events"]) == 212
    unique, lineage, conflicts = {}, defaultdict(list), set()
    occurrences = 0
    for page_name, record in manifest["pages"].items():
        identity = digest(canonical({"path": record["path"], "params": record["params"]}))
        assert identity == record["identity"]
        event = budget["events"][record["request_number"] - 1]
        assert event["identity"] == identity and event["sha256"] == record["sha256"]
        raw = (SOURCE / "wire" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(raw) == record["sha256"]
        body = read_census_page(
            raw,
            record["sha256"],
            record["params"]["bgn_de"],
            record["params"]["end_de"],
            int(record["params"]["page_no"]),
        )
        assert body["status"] == "000"
        assert int(body["page_no"]) == int(record["params"]["page_no"])
        for page in range(1, int(body["total_page"]) + 1):
            assert record["params"]["bgn_de"] + ":" + str(page) in manifest["pages"]
        for row in body["list"]:
            occurrences += 1
            assert record["params"]["bgn_de"] <= row["rcept_dt"] <= record["params"]["end_de"]
            receipt = row["rcept_no"]
            status = register_source_receipt(unique, row)
            if status == "CONFLICT":
                conflicts.add(receipt)
            lineage[receipt].append(
                dict(
                    page=page_name,
                    raw_sha256=record["sha256"],
                    request_identity=identity,
                    acquired_at=record["acquired_at"],
                    normalized_row_sha256=digest(canonical(row)),
                )
            )
    selected = json.loads((SOURCE / "selected-disclosures.json").read_bytes())
    selection = json.loads(Path("artifacts/df005/DF005_PROTOCOL.json").read_bytes())
    old_symbols = set(selection["kospi"] + selection["kosdaq"])
    refilter = {r: row for r, row in unique.items() if row.get("stock_code") in old_symbols}
    assert refilter == {r: v["row"] for r, v in selected["rows"].items()}
    assert len(refilter) == 302
    rows = [r for key, r in unique.items() if key not in conflicts and receipt_ok(r)]
    flags = identity_flags(rows)
    panel = json.loads(Path("data/data-first-private-df005-panel/manifest.json").read_bytes())
    indices = {
        market: load_histories(panel, symbol, "RAW")
        for market, symbol in (("Y", "0001"), ("K", "1001"))
    }
    exclusions = {
        date.fromisoformat(x["date"])
        for x in json.loads(Path("artifacts/df005/session-eligibility-v1.json").read_bytes())[
            "dates"
        ]
    }
    old_results = json.loads(Path("artifacts/df006/results.json").read_bytes())
    old_events = {s["receipt"] for s in old_results["summaries"] if s["model"] == "D1"}
    counts, by_year, by_month = Counter(), defaultdict(Counter), defaultdict(Counter)
    family_rows = defaultdict(list)
    candidates, private_rows = [], []
    for row in rows:
        family, revision = classify_title(row["report_nm"])
        key = family + ":" + revision
        counts[key] += 1
        by_year[row["rcept_dt"][:4]][key] += 1
        by_month[row["rcept_dt"][:6]][key] += 1
        family_rows[family].append(row)
        index = indices.get(row.get("corp_cls"), ())
        receipt_date = day(row["rcept_dt"])
        eligible = [
            r.exchange_date
            for r in index
            if r.exchange_date > receipt_date and r.exchange_date not in exclusions
        ]
        entry = eligible[0] if eligible else None
        prior = [r.close for r in index if entry is not None and r.exchange_date < entry]
        regime = "UNKNOWN"
        if len(prior) >= 21:
            change = prior[-1] / prior[-21] - 1
            regime = "BEAR" if change <= D("-.05") else "BULL" if change >= D(".05") else "SIDEWAYS"
        record = dict(
            row=row,
            normalized_row_sha256=digest(canonical(row)),
            lineage=lineage[row["rcept_no"]],
            family=family,
            revision=revision,
            identity_flags=flags[row["rcept_no"]],
            modeled_entry=str(entry) if entry else None,
            regime=regime,
            published_at=None,
            publication_precision="DATE_ONLY",
            historical_listing_status="UNKNOWN",
            delisted_status="UNKNOWN",
            original_document_verified=row["rcept_no"] in old_events,
        )
        private_rows.append(record)
        if family not in {"D1", "D2"}:
            continue
        if revision != "ORIGINAL":
            continue
        metadata_ok = receipt_ok(row) and not any(
            f in flags[row["rcept_no"]]
            for f in (
                "MISSING_OR_AMBIGUOUS_STOCK_CODE",
                "CORPORATION_MULTIPLE_SOURCE_CODES",
                "SOURCE_CODE_MULTIPLE_CORPORATIONS",
            )
        )
        candidate = dict(
            receipt=row["rcept_no"],
            corp_code=row["corp_code"],
            stock_code=row.get("stock_code", ""),
            source_market=row.get("corp_cls"),
            receipt_date=str(receipt_date),
            family=family,
            entry=str(entry) if entry else None,
            regime=regime,
            tier2_metadata_identified=metadata_ok,
            outside_original50=row.get("stock_code") not in old_symbols,
            old_consumed_event=row["rcept_no"] in old_events,
            tier3_qualified=False,
            price_window_status="NOT_INSPECTED_D2"
            if family == "D2"
            else "NO_MATCHING_HISTORICAL_PRICE_CACHE",
            flags=flags[row["rcept_no"]],
        )
        if family == "D1" and row.get("stock_code") in old_symbols and entry is not None:
            raw = load_histories(panel, row["stock_code"], "RAW")
            adj = load_histories(panel, row["stock_code"], "ADJUSTED")
            try:
                qualify_window(raw, adj, index, entry, frozenset(exclusions))
                candidate["price_window_status"] = "COMPLETE_LIMITED_EXPLORATORY_WINDOW"
                candidate["tier3_qualified"] = row["rcept_no"] in old_events and metadata_ok
            except ValueError as exc:
                candidate["price_window_status"] = str(exc)
        candidates.append(candidate)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    normalized = {"records": private_rows, "conflicts": sorted(conflicts)}
    immutable_write(PRIVATE / "all-normalized-disclosures.json", canonical(normalized))
    immutable_write(PRIVATE / "candidate-register.json", canonical(candidates))
    summaries = {}
    for family in ("D1", "D2"):
        group = [c for c in candidates if c["family"] == family]
        identified = [c for c in group if c["tier2_metadata_identified"]]
        by_company = Counter(c["corp_code"] for c in group)
        collision_groups = Counter((c["corp_code"], c["receipt_date"]) for c in group)
        summaries[family] = dict(
            title_candidates_including_revisions=len(family_rows[family]),
            original_title_candidates=len(group),
            metadata_identified_originals=len(identified),
            source_YK_identified_originals=sum(
                c["source_market"] in {"Y", "K"} for c in identified
            ),
            tier3_qualified=sum(c["tier3_qualified"] for c in group),
            candidate_companies=len(by_company),
            modeled_entry_dates=len({c["entry"] for c in group if c["entry"]}),
            bear_candidates=sum(c["regime"] == "BEAR" for c in group),
            outside_original50_events=sum(c["outside_original50"] for c in group),
            outside_original50_companies=len(
                {c["corp_code"] for c in group if c["outside_original50"]}
            ),
            old_consumed_events=sum(c["old_consumed_event"] for c in group),
            missing_stock_codes=sum("MISSING_OR_AMBIGUOUS_STOCK_CODE" in c["flags"] for c in group),
            unknown_market_candidates=sum(c["regime"] == "UNKNOWN" for c in group),
            historical_delisting_status="UNKNOWN_NOT_INFERRED_FROM_CURRENT_MASTER",
            complete_cached_price_windows=sum(
                c["price_window_status"] == "COMPLETE_LIMITED_EXPLORATORY_WINDOW" for c in group
            ),
            missing_or_unqualified_price_windows=sum(
                c["price_window_status"] != "COMPLETE_LIMITED_EXPLORATORY_WINDOW" for c in group
            )
            if family == "D1"
            else None,
            same_company_date_collision_groups=sum(n > 1 for n in collision_groups.values()),
            confirmed_independent_families=sum(c["tier3_qualified"] for c in group),
            unresolved_original_receipt_families=sum(not c["tier3_qualified"] for c in group),
            largest_company_title_share=max(by_company.values(), default=0) / len(group)
            if group
            else None,
            company_event_counts=[
                {"corp_code": code, "original_title_candidates": number}
                for code, number in sorted(by_company.items())
            ],
            company_counts_not_independent_market_experiments=True,
        )
    d1 = [c for c in candidates if c["family"] == "D1"]
    supply_ok = (
        len(d1) >= 30
        and summaries["D1"]["candidate_companies"] >= 10
        and summaries["D1"]["modeled_entry_dates"] >= 20
        and summaries["D1"]["bear_candidates"] >= 5
    )
    census = dict(
        protocol_commit=subprocess.check_output(
            ["git", "rev-parse", PROTOCOL_COMMIT], text=True
        ).strip(),
        protocol_sha256=digest(protocol),
        source_pages=210,
        source_occurrences=occurrences,
        unique_disclosures=len(unique),
        exact_duplicate_occurrences=occurrences - len(unique),
        conflicting_receipts=len(conflicts),
        valid_nonconflicting_receipts=len(rows),
        invalid_identity_rows=len(unique) - len(rows) - len(conflicts),
        corporate_ids=len({r["corp_code"] for r in rows}),
        old50_refilter_rows=302,
        refilter_exact=True,
        title_counts=dict(counts),
        years={k: dict(v) for k, v in sorted(by_year.items())},
        months={k: dict(v) for k, v in sorted(by_month.items())},
        families=summaries,
        identity_qualification={
            "source_corporations_with_multiple_codes": len(
                {
                    r["corp_code"]
                    for r in rows
                    if "CORPORATION_MULTIPLE_SOURCE_CODES" in flags[r["rcept_no"]]
                }
            ),
            "source_codes_shared_by_multiple_corporations": len(
                {
                    r.get("stock_code")
                    for r in rows
                    if "SOURCE_CODE_MULTIPLE_CORPORATIONS" in flags[r["rcept_no"]]
                }
            ),
            "historical_listing_delisting_code_change_completeness": "UNKNOWN",
            "title_explicit_cancellation_markers": sum(
                classify_title(r["report_nm"])[1] == "CANCEL" for r in rows
            ),
            "content_verified_market_wide_cancellation_count": None,
            "exact_retirement_title_count": len(family_rows["RETIREMENT"]),
        },
        original_receipt_independence_unproven=True,
        normalized_private_sha256=digest(canonical(normalized)),
        candidate_private_sha256=digest(canonical(candidates)),
        source_spacing_compliant=False,
        source_spacing_shortfalls=70,
        source_minimum_gap=3.035479,
        supply_gate_passed=supply_ok,
        event_status="EVENT_DATA_DEPENDENCY_PENDING"
        if supply_ok
        else "EVENT_UNIVERSE_INSUFFICIENT",
        new_authenticated_requests=0,
        new_D1_economic_trials=0,
        D2_economics_executed=False,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
    )
    atomic_json(PUBLIC / "census.json", census)
    # Proposal only: enumerate every missing D1 code, no outcome-based selection.
    intervals, missing_docs = defaultdict(list), []
    pending_identity = []
    for c in d1:
        if not c["tier3_qualified"]:
            missing_docs.append(c["receipt"])
        if not c["tier2_metadata_identified"] or c["source_market"] not in {"Y", "K"}:
            pending_identity.append(c["receipt"])
            continue
        if c["price_window_status"] != "COMPLETE_LIMITED_EXPLORATORY_WINDOW":
            rd = date.fromisoformat(c["receipt_date"])
            intervals[c["stock_code"]].append((rd - timedelta(days=90), rd + timedelta(days=21)))
    plan_rows = []
    for symbol, ranges in sorted(intervals.items()):
        for begin, end in merge_intervals(ranges):
            calendar_days = (end - begin).days + 1
            weekdays = sum((begin + timedelta(days=i)).weekday() < 5 for i in range(calendar_days))
            plan_rows.append(
                dict(
                    symbol=symbol,
                    start=str(begin),
                    end=str(end),
                    price_bases=["RAW", "ADJUSTED"],
                    expected_pages=2 * math.ceil(weekdays / 100),
                    conservative_pages=2 * math.ceil(calendar_days / 100),
                )
            )
    expected = sum(r["expected_pages"] for r in plan_rows)
    conservative = sum(r["conservative_pages"] for r in plan_rows)
    # Late followup and early90-day retrieval envelopes may exceed known index coverage.
    index_plans = []
    if plan_rows:
        lo = min(date.fromisoformat(p["start"]) for p in plan_rows)
        hi = max(date.fromisoformat(p["end"]) for p in plan_rows)
        for market, code in (("Y", "0001"), ("K", "1001")):
            for begin, end in (
                (lo, min(hi, indices[market][0].exchange_date - timedelta(days=1))),
                (max(lo, indices[market][-1].exchange_date + timedelta(days=1)), hi),
            ):
                if begin <= end:
                    index_plans.append(
                        dict(
                            symbol=code,
                            start=str(begin),
                            end=str(end),
                            conservative_pages=math.ceil(((end - begin).days + 1) / 100),
                        )
                    )
    index_pages = sum(p["conservative_pages"] for p in index_plans)
    correction_docs = [
        r["rcept_no"]
        for r in family_rows["D1"]
        if classify_title(r["report_nm"])[1] != "ORIGINAL"
        and r["rcept_no"] not in manifest["documents"]
    ]
    proposal = dict(
        proposal_only=True,
        execution_authorized=False,
        supply_gate_passed=supply_ok,
        recommendation="PREPARE_DOCUMENT_AND_IDENTITY_QUALIFICATION_BEFORE_PRICE_ACQUISITION"
        if supply_ok
        else "STOP_D1_EXPANSION_NO_PRICE_COLLECTION_RECOMMENDED",
        stock_windows=plan_rows if supply_ok else [],
        stock_count=len(intervals) if supply_ok else 0,
        original_document_receipts_pending=missing_docs,
        revision_document_receipts_pending=correction_docs,
        historical_identity_pending_receipts=pending_identity,
        confirmed_delisted_companies=None,
        halt_and_action_completeness="UNVERIFIED",
        stock_endpoints=["/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"],
        index_endpoint="/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
        stock_tr_id="FHKST03010100",
        index_tr_id="FHKUP03500100",
        index_windows=index_plans,
        expected_stock_pages=expected,
        conservative_stock_pages=conservative,
        conservative_index_pages=index_pages,
        proposed_paper_auth_max=2,
        proposed_kis_requests_including_one_retry=2 + 2 * (conservative + index_pages)
        if supply_ok
        else 0,
        proposed_opendart_document_requests_including_one_retry=2
        * (len(missing_docs) + len(correction_docs))
        if supply_ok
        else 0,
        opendart_path="/api/document.xml",
        additional_correction_followup_scope_requires_separate_definition=True,
        cache_qualified_event_reuse=summaries["D1"]["tier3_qualified"],
        total_D1_originals=len(d1),
        qualified_event_cache_reuse_fraction=summaries["D1"]["tier3_qualified"] / len(d1)
        if d1
        else None,
        minimum_warmup_sessions=21,
        holding_calendar_days=5,
        post_deadline_observations=2,
        provider_historical_availability="MUST_BE_PROBED_AFTER_SEPARATE_APPROVAL_NOT_ASSUMED",
        minimum_gap_seconds=3.05,
        proposed_wait_seconds=3.10,
        no_broker_orders=True,
        no_LIVE=True,
    )
    atomic_json(PUBLIC / "expansion-proposal.json", proposal)
    # Independent reconstruction of existing three cost/execution scenarios; no new curve.
    risk = []
    for scenario in ("BASE", "STRESS", "PARTIAL"):
        summary = next(
            s
            for s in old_results["summaries"]
            if s["symbol"] == "263020" and s["model"] == "D1" and s["scenario"] == scenario
        )
        p = Path("data/data-first-private-df006-replays/references") / (
            summary["receipt"] + "-" + scenario + "-D1.json"
        )
        assert digest(p.read_bytes()) == summary["private_sha256"]
        audit = audit_exposure(json.loads(p.read_bytes()))
        immutable_write(PRIVATE / "risk" / (scenario + ".json"), canonical(audit))
        init = audit["initial"]
        risk.append(
            dict(
                scenario=scenario,
                original_replay_sha256=digest(p.read_bytes()),
                private_audit_sha256=digest(canonical(audit)),
                initial_target=init["target"],
                pretrade_nav=init["pretrade_nav"],
                submitted_quantity=init["submitted_quantity"],
                filled_quantity=init["filled_quantity"],
                postfill_weight=init["postfill_weight"],
                max_close_weight=audit["max_close_weight"],
                above_reference_days=audit["above_reference_days"],
                initial_order_target_compliant=audit["initial_order_target_compliant"],
                buy_execution_count=audit["buy_execution_count"],
                no_additional_buy_on_exceedance=audit["above_reference_without_additional_buy"],
                final_quantity=audit["final_quantity"],
                unfulfilled_reduction_days=audit["unfulfilled_reduction_days"],
                original_pnl_unchanged=True,
            )
        )
    atomic_json(
        PUBLIC / "risk-audit.json",
        dict(
            risk_status="RISK_CAP_SEMANTICS_VERIFIED",
            risk_reduction_status="RISK_REDUCTION_UNVERIFIED",
            scenarios=risk,
            continuous_LIVE_cap_approved=False,
            research_reference_weight=".25",
            original_df006_cap_exceedance_preserved=True,
            central_risk_executed_in_reference=False,
            new_risk_reduction_backtest_executed=False,
            new_return_curves=0,
            interpretation="TARGET_CAP_NOT_CONTINUOUS_EXPOSURE_GUARANTEE_NO_APPROVED_LIVE_CAP",
        ),
    )
    atomic_json(
        PUBLIC / "results.json",
        dict(
            event_status=census["event_status"],
            risk_status="RISK_CAP_SEMANTICS_VERIFIED",
            risk_reduction_status="RISK_REDUCTION_UNVERIFIED",
            economic_status="ECONOMIC_EDGE_UNVERIFIED",
            live_status="LIVE_NOT_APPROVED",
            new_authenticated_requests=0,
            new_economic_trials=0,
            D2_price_outcomes_computed=False,
            actual_orders=0,
            actual_cancels=0,
            account_queries=0,
            protocol_sha256=digest(protocol),
        ),
    )
    print(
        json.dumps(
            {
                "unique_disclosures": len(unique),
                "D1_original_titles": summaries["D1"]["original_title_candidates"],
                "D2_original_titles": summaries["D2"]["original_title_candidates"],
                "qualified_D1": summaries["D1"]["tier3_qualified"],
                "event_status": census["event_status"],
                "risk_status": "RISK_CAP_SEMANTICS_VERIFIED",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
