"""Independent DF006 public arithmetic and private raw-lineage verification."""

import argparse
import json
from datetime import datetime
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    folder = Path("artifacts/df006")
    result = json.loads((folder / "results.json").read_bytes())
    audit = json.loads((folder / "collection-and-preservation-audit.json").read_bytes())
    assert (
        result["protocol_sha256"]
        == sha256((folder / "DF006_PROTOCOL.json").read_bytes()).hexdigest()
    )
    assert result["protocol_commit"] == "60900915a3e65dd5f03e9b4f21a792d2fa0ace76"
    assert result["parameter_combinations"] == 1
    assert result["authenticated_requests"] == audit["request_count"] <= 600
    assert audit["complete_months"] == 37 and audit["all_list_pages_complete"]
    assert audit["approved_minimum_gap_seconds"] == 3.05
    assert audit["spacing_deviation_preserved_not_waived"]
    if not audit["strict_spacing_compliant"]:
        assert audit["spacing_shortfall_count"] > 0
        assert "ACQUISITION_SPACING_NONCOMPLIANT" in result["limitations"]
    assert audit["protected_bytes_unchanged"] and audit["secret_matches"] == 0
    assert audit["all_selected_rows_lineage_verified"]
    assert all(
        result[k] == 0
        for k in ("actual_orders", "actual_cancels", "account_queries", "kis_requests")
    )
    assert result["decision"] == "D_EVENT_INSUFFICIENT_EVIDENCE"
    assert result["eligible_events"] < 30
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    assert result["confirmatory_status"] == "NOT_EXECUTED"
    assert not result["statistical_tests"]["executed"]
    for row in result["summaries"]:
        assert abs(
            D(row["gross_before_slippage"])
            - D(row["embedded_slippage"])
            - D(row["explicit_cost"])
            - D(row["operating_cost"])
            - D(row["net"])
        ) < D("1e-14")
        assert D(row["commission"]) + D(row["tax"]) == D(row["explicit_cost"])
        assert D(row["operating_cost"]) == 100 * row["days"]
        assert row["actual_fill_pnl"] is None
    if result["eligible_events"] == 0:
        assert not result["summaries"] and not result["economics_executed"]
        assert result["net_operating_pnl"] is None
        assert result["economic_metrics_missing_reason"] == "NO_ELIGIBLE_REAL_DISCLOSURE_EVENTS"
    if args.private:
        store = Path("data/data-first-private-df006-events")
        manifest = json.loads((store / "manifest.json").read_bytes())
        assert manifest["complete"]
        assert len(manifest["pages"]) == result["list_pages"]
        assert len(manifest["documents"]) == result["documents"]
        for record in list(manifest["pages"].values()) + list(manifest["documents"].values()):
            raw = (store / "wire" / (record["sha256"] + ".bin")).read_bytes()
            assert sha256(raw).hexdigest() == record["sha256"]
        budget = json.loads((store / "budget.json").read_bytes())
        gaps = [
            (
                datetime.fromisoformat(b["started_at"]) - datetime.fromisoformat(a["completed_at"])
            ).total_seconds()
            for a, b in zip(budget["events"][:-1], budget["events"][1:], strict=True)
        ]
        assert min(gaps) == audit["minimum_response_completion_gap_seconds"]
        assert sum(g < 3.05 for g in gaps) == audit["spacing_shortfall_count"]
        target = Path("data/data-first-private-df006-replays/references")
        for summary in result["summaries"]:
            stem = summary["receipt"] + "-" + summary["scenario"]
            path = target / (stem + "-" + summary["model"] + ".json")
            assert sha256(path.read_bytes()).hexdigest() == summary["private_sha256"]
            replay = json.loads(path.read_bytes())
            state = replay["reference_state"]
            final = replay["daily"][-1]
            assert D(final["cash"]) + final["quantity"] * D(final["close"]) - D(
                summary["capital"]
            ) == D(summary["net"])
            assert sum((D(e[5]) for e in state["executions"]), D(0)) == D(summary["explicit_cost"])
            assert sum((abs(e[3]) * D(e[4]) for e in state["executions"]), D(0)) / D(
                summary["capital"]
            ) == D(summary["turnover"])
            if summary["model"] == "D1":
                trend = json.loads((target / (stem + "-TREND.json")).read_bytes())["summary"]
                assert D(summary["net"]) - D(trend["net"]) == D(summary["D1_minus_TREND"])
                a0 = json.loads((target / (stem + "-A0.json")).read_bytes())["analysis"]["summary"]
                assert D(summary["net"]) - D(a0["project_net"]) == D(summary["D1_minus_A0"])
                if summary["placebo_net"] is not None:
                    placebo = json.loads((target / (stem + "-PLACEBO.json")).read_bytes())[
                        "summary"
                    ]
                    assert D(placebo["net"]) == D(summary["placebo_net"])
                    assert D(summary["net"]) - D(placebo["net"]) == D(summary["D1_minus_PLACEBO"])
    print("DF006 independent event scope, accounting and no-economic-claim evidence: PASS")


if __name__ == "__main__":
    main()
