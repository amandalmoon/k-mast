"""Independent public count/budget assertions and private source/weight arithmetic."""

import argparse
import json
import re
from collections import Counter
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    folder = Path("artifacts/df007")
    census = json.loads((folder / "census.json").read_bytes())
    result = json.loads((folder / "results.json").read_bytes())
    risk = json.loads((folder / "risk-audit.json").read_bytes())
    plan = json.loads((folder / "expansion-proposal.json").read_bytes())
    audit = json.loads((folder / "preservation-audit.json").read_bytes())
    assert (
        census["protocol_sha256"]
        == sha256((folder / "DF007_PROTOCOL.json").read_bytes()).hexdigest()
    )
    assert (
        census["source_pages"] == 210
        and census["old50_refilter_rows"] == 302
        and census["refilter_exact"]
    )
    assert sum(census["title_counts"].values()) == census["valid_nonconflicting_receipts"] == 19319
    assert sum(sum(d.values()) for d in census["years"].values()) == 19319
    assert sum(sum(d.values()) for d in census["months"].values()) == 19319
    assert census["corporate_ids"] == 2451
    d1, d2 = census["families"]["D1"], census["families"]["D2"]
    assert d1["original_title_candidates"] == 620 and d1["candidate_companies"] == 301
    assert (
        d1["metadata_identified_originals"] == 578 and d1["source_YK_identified_originals"] == 532
    )
    assert d1["missing_stock_codes"] == 42
    assert (
        d1["outside_original50_events"] == 618
        and d1["tier3_qualified"] == d1["old_consumed_events"] == 2
    )
    assert d1["missing_or_unqualified_price_windows"] == 618
    assert d2["original_title_candidates"] == 872 and d2["tier3_qualified"] == 0
    assert result["event_status"] == "EVENT_DATA_DEPENDENCY_PENDING"
    assert result["risk_status"] == "RISK_CAP_SEMANTICS_VERIFIED"
    assert result["risk_reduction_status"] == "RISK_REDUCTION_UNVERIFIED"
    assert (
        result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and result["live_status"] == "LIVE_NOT_APPROVED"
    )
    assert all(
        result[k] == 0
        for k in (
            "new_authenticated_requests",
            "new_economic_trials",
            "actual_orders",
            "actual_cancels",
            "account_queries",
        )
    )
    assert not result["D2_price_outcomes_computed"]
    assert plan["proposal_only"] and not plan["execution_authorized"]
    assert plan["stock_count"] == len({r["symbol"] for r in plan["stock_windows"]}) == 249
    assert plan["proposed_kis_requests_including_one_retry"] == 2 + 2 * (
        sum(r["conservative_pages"] for r in plan["stock_windows"])
        + sum(r["conservative_pages"] for r in plan["index_windows"])
    )
    assert (
        plan["proposed_opendart_document_requests_including_one_retry"]
        == 2
        * (
            len(plan["original_document_receipts_pending"])
            + len(plan["revision_document_receipts_pending"])
        )
        == 1496
    )
    assert (
        audit["protected_bytes_unchanged"]
        and audit["secret_matches"] == audit["new_authenticated_requests"] == 0
    )
    assert (
        not risk["continuous_LIVE_cap_approved"] and not risk["central_risk_executed_in_reference"]
    )
    for scenario in risk["scenarios"]:
        assert scenario["initial_target"] == "0.25" and scenario["initial_order_target_compliant"]
        assert D(scenario["postfill_weight"]) <= D(".25")
        assert scenario["original_pnl_unchanged"] and scenario["buy_execution_count"] == 1
        if scenario["scenario"] != "PARTIAL":
            assert (
                D(scenario["max_close_weight"]) > D(".25") and scenario["above_reference_days"] == 2
            )
            assert scenario["no_additional_buy_on_exceedance"]
        else:
            assert scenario["final_quantity"] == 41 and scenario["unfulfilled_reduction_days"] == 3
    if args.private:
        source = Path("data/data-first-private-df006-events")
        manifest = json.loads((source / "manifest.json").read_bytes())
        unique = {}
        for page in manifest["pages"].values():
            raw = (source / "wire" / (page["sha256"] + ".bin")).read_bytes()
            assert sha256(raw).hexdigest() == page["sha256"]
            for row in json.loads(raw)["list"]:
                assert row["rcept_no"] not in unique or unique[row["rcept_no"]] == row
                unique[row["rcept_no"]] = row
        assert len(unique) == census["unique_disclosures"]
        original = [
            r
            for r in unique.values()
            if "".join(r["report_nm"].split())
            in {"자기주식취득결정", "주요사항보고서(자기주식취득결정)"}
        ]
        assert len(original) == 620 and len({r["corp_code"] for r in original}) == 301
        assert sum(not re.fullmatch(r"[0-9]{6}", r.get("stock_code", "")) for r in original) == 42
        private = Path("data/data-first-private-df007-census-v2")
        assert (
            sha256((private / "all-normalized-disclosures.json").read_bytes()).hexdigest()
            == census["normalized_private_sha256"]
        )
        assert (
            sha256((private / "candidate-register.json").read_bytes()).hexdigest()
            == census["candidate_private_sha256"]
        )
        normalized = json.loads((private / "all-normalized-disclosures.json").read_bytes())[
            "records"
        ]
        assert all(
            r["published_at"] is None and r["publication_precision"] == "DATE_ONLY"
            for r in normalized
        )
        candidates = json.loads((private / "candidate-register.json").read_bytes())
        assert Counter(c["family"] for c in candidates) == {"D1": 620, "D2": 872}
        assert all(
            c["price_window_status"] == "NOT_INSPECTED_D2"
            for c in candidates
            if c["family"] == "D2"
        )
        for row in risk["scenarios"]:
            payload = (private / "risk" / (row["scenario"] + ".json")).read_bytes()
            assert sha256(payload).hexdigest() == row["private_audit_sha256"]
            proof = json.loads(payload)
            initial = proof["initial"]
            assert (
                int(D(initial["target"]) * D(initial["pretrade_nav"]) / D(initial["limit"]))
                == initial["submitted_quantity"]
            )
            assert D(initial["postfill_cash"]) + initial["filled_quantity"] * D(
                initial["opening_mark"]
            ) == D(initial["postfill_nav"])
            assert initial["filled_quantity"] * D(initial["opening_mark"]) / D(
                initial["postfill_nav"]
            ) == D(initial["postfill_weight"])
            for p in proof["daily_path"]:
                assert D(p["cash"]) + p["quantity"] * D(p["close"]) == D(p["nav"])
                assert p["quantity"] * D(p["close"]) / D(p["nav"]) == D(p["weight"])
    print("DF007 independent whole-page census, proposal bounds and exposure semantics: PASS")


if __name__ == "__main__":
    main()
