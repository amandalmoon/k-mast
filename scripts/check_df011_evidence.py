"""Independent public gates and optional private source/entitlement verification."""

import argparse
import html
import json
import re
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import urlparse

from kmast.data.store import canonical, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df011")
    result = json.loads((public / "results.json").read_bytes())
    protocol = json.loads((public / "DF011_PROTOCOL.json").read_bytes())
    action = json.loads((public / "corporate-action-lineage.json").read_bytes())
    plan = json.loads((public / "next-price-proposal.json").read_bytes())
    assert digest((public / "DF011_PROTOCOL.json").read_bytes()) == result["protocol_sha256"]
    assert digest(canonical(action)) == result["corporate_action_lineage_sha256"]
    links = json.loads(Path("artifacts/df009r1/event-linkage.json").read_bytes())
    mapped = {r["receipt"] for r in links if r["CORP_STOCK_LINK_VERIFIED"]}
    assert len(mapped) == 8
    used = {
        t["receipt"]
        for t in json.loads(Path("artifacts/df010/DF010_PROTOCOL.json").read_bytes())["targets"]
    }
    assert {t["receipt"] for t in protocol["expansion_targets"]} == mapped - used
    assert [t["target"] for t in plan["targets"]] == protocol["expansion_targets"]
    assert len(plan["targets"]) == 5 and not plan["execution_authorized"]
    assert not plan["unused_df010_budget_carried"]
    assert plan["expected_stock_pages"] == 10 and plan["expected_index_pages"] == 1
    assert len(plan["requests"]) == 11
    assert result["proposed_request_ceiling"] == plan["retry_inclusive_total_ceiling"] == 24
    assert plan["maximum_authentication"] == 2 and plan["maximum_attempts_per_page"] == 2
    assert D(plan["minimum_response_completion_wait_seconds"]) == D("3.10")
    for target in plan["targets"]:
        t = target["target"]
        match = next(r for r in links if r["receipt"] == t["receipt"])
        for key in ("historical_short_code", "standard_code", "then_market", "event_date"):
            assert t[key] == match[key]
        assert target["cached_stock_rows"] == {"RAW": 0, "ADJUSTED": 0}
    assert result["status"] == "DF011_ACTION_PARTIAL_QUALIFICATION"
    assert result["exact_daily_ex_dividend_code_verified"]
    assert action["code_meaning"]["meaning"] == "EX_DIVIDEND"
    assert action["actual_payment_day"] is None and action["investor_dividend_tax"] is None
    assert action["scheduled_payment_day"] == "2023-04-10"
    assert action["issuer_payment_month"] == "2023-04"
    assert result["actual_total_economic_pnl"] is None
    assert result["df010_131290_hold_preserved"] and not result["previous_price_only_pnl_changed"]
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    assert (
        not result["statistical_tests_executed"]
        and result["controls"] == "PREREGISTERED_DESIGN_ONLY"
    )
    boundary_path = public / "control-eligibility-boundary.json"
    assert digest(boundary_path.read_bytes()) == result["control_boundary_sha256"]
    boundary = json.loads(boundary_path.read_bytes())
    assert not boundary["parent_protocol_changed"] and not boundary["selection_thresholds_changed"]
    assert (
        boundary["actual_control_selections_executed"]
        == result["actual_control_selections_executed"]
        == 0
    )
    for key in (
        "new_qualified_strategy_replays",
        "full_research_eligible_events",
        "new_authenticated_requests",
        "new_kis_price_requests",
        "new_authentication",
        "actual_orders",
        "actual_cancels",
        "account_queries",
        "live_authentication",
    ):
        assert result[key] == 0
    for row in result["sidecars"]:
        assert D(row["gross_modeled_entitlement"]) == row["entitled_modeled_shares"] * D(500)
        assert row["verified_spendable_cash_increment"] == "0"
        assert row["actual_total_economic_pnl"] is None and not row["price_path_promoted"]
    if args.private:
        sources = Path("data/data-first-private-df011-sources")

        def raw(name):
            entry = action["sources"][name]
            assert urlparse(entry["url"]).hostname in {
                "apiportal.koreainvestment.com",
                "kind.krx.co.kr",
                "regulation.krx.co.kr",
                "www.hygood.co.kr",
            }
            assert entry["authentication"] is False
            data = (sources / "raw" / (entry["sha256"] + ".bin")).read_bytes()
            assert digest(data) == entry["sha256"]
            return data

        detail = json.loads(raw("kis-daily-official-detail"))
        assert detail["accessUrl"] == protocol["price_plan"]["stock_path"]
        assert detail["realTrId"] == "FHKST03010100"
        properties = json.loads(raw("kis-daily-official-property"))
        field = next(p for p in properties if p["propertyCd"] == "flng_cls_code")
        assert field["bodyType"] == "res_b" and "02 : 배당락" in field["description"]
        decision = html.unescape(re.sub(r"<[^>]+>", " ", raw("kind-dividend-decision").decode()))
        decision = " ".join(decision.split())
        for fact in ("보통주식 500", "2022-12-31", "2023-04-10", "2023-02-22"):
            assert fact in decision
        annual = html.unescape(re.sub(r"<[^>]+>", " ", raw("kind-tse-2024-annual").decode()))
        annual = " ".join(annual.split())
        assert "2023년 3월 24일 주주총회에 의안으로 상정되어 결의 되었습니다" in annual
        assert "배당금은 2023년 4월에 지급되었습니다" in annual
        assert "T+2" in raw("krx-settlement-rule").decode()
        for row in result["sidecars"]:
            p = Path("data/data-first-private-df011-entitlements") / row["private_file"]
            assert digest(p.read_bytes()) == row["private_sha256"]
            sidecar = json.loads(p.read_bytes())
            old = Path("data/data-first-private-df010-replays/references") / (
                "20221226000280-" + row["scenario"] + "-D1.json"
            )
            assert digest(old.read_bytes()) == row["source_price_path_sha256"]
            reference = json.loads(old.read_bytes())
            quantity = sum(
                e[3]
                for e in reference["reference_state"]["executions"]
                if datetime.fromisoformat(e[1]).date() <= date(2022, 12, 27)
            )
            assert quantity == row["entitled_modeled_shares"]
            assert sidecar["price_only_diagnostic_pnl"] == reference["summary"]["net"]
            assert sidecar["before_final_amount_known"]["gross_entitlement"] is None
            assert sidecar["ex_post_pre_payment_receivable"]["gross_entitlement"] == str(
                D(quantity) * 500
            )
            assert sidecar["issuer_payment_month_end"]["net_dividend_cash_verified"] is None
            assert not sidecar["issuer_payment_month_end"]["total_return_verified"]
            assert sidecar["issuer_payment_month_end"]["d1_signal_inputs"] == {}
        assert not Path("data/data-first-private-df011-prices/budget.json").exists()
    print(
        "DF011 independent evidence checks PASS"
        + (" (private issuer/entitlement)" if args.private else " (public aggregates)")
    )


if __name__ == "__main__":
    main()
