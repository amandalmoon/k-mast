"""Independent access-resumed totals, interval gates and optional raw response audit."""

import argparse
import io
import json
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from kmast.data.store import canonical, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df009r1")
    result = json.loads((public / "results.json").read_bytes())
    rows = json.loads((public / "event-linkage.json").read_bytes())
    lineage = json.loads((public / "snapshot-lineage.json").read_bytes())
    plan = json.loads(Path("artifacts/df009/KRX_QUERY_PLAN.json").read_bytes())
    assert len(rows) == 12 and len(lineage) == 46
    assert digest(canonical(rows)) == result["event_linkage_sha256"]
    assert digest(canonical(lineage)) == result["snapshot_lineage_sha256"]
    assert len({(r["query"]["basDd"], r["query"]["market"]) for r in lineage}) == 46
    assert sum(r["rows"] for r in lineage) == result["observed_security_rows"] == 60886
    assert (
        sum(r["CORP_STOCK_LINK_VERIFIED"] is True for r in rows)
        == result["corp_stock_links_verified"]
        == 8
    )
    assert sum(r["HISTORICAL_SECURITY_PRESENT"] is True for r in rows) == 8
    assert (
        result["cumulative_authenticated_requests"]
        == 47
        <= result["maximum_approved_requests"]
        == 92
    )
    assert (
        result["post_approval_successful_requests"] == 46 and result["original_401_requests"] == 1
    )
    assert result["spacing_violations"] == 0 and result["minimum_observed_utc_gap_seconds"] >= 3.05
    proposal = json.loads((public / "next-price-proposal.json").read_bytes())
    assert (
        proposal["proposal_only"]
        and not proposal["execution_authorized"]
        and len(proposal["targets"]) == 3
    )
    eligible = {r["receipt"] for r in rows if r["price_pilot_eligible"]}
    original = json.loads(Path("artifacts/df009/DF009_PROTOCOL.json").read_bytes())["targets"]
    selected = sorted(
        (t for t in original if t["receipt"] in eligible), key=lambda t: t["rank_sha256"]
    )[:3]
    assert [r["receipt"] for r in proposal["targets"]] == [r["receipt"] for r in selected]
    assert len(eligible) >= 5
    assert all(
        result[k] == 0
        for k in (
            "new_price_requests",
            "new_KIS_requests",
            "new_DART_requests",
            "new_economic_trials",
            "actual_orders",
            "actual_cancels",
            "account_queries",
        )
    )
    assert (
        result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and result["live_status"] == "LIVE_NOT_APPROVED"
    )
    audit = json.loads((public / "preservation-audit.json").read_bytes())
    assert audit["prior_bytes_unchanged"] and audit["secret_matches"] == 0
    if args.private:
        folder = Path("data/data-first-private-df009-krx-access-confirmed")
        state = json.loads((folder / "budget.json").read_bytes())
        events = state["events"]
        assert len(events) == state["used"] == 47 and not state["halted"]
        assert max(Counter(e["request_identity"] for e in events).values()) == 2
        allowed = {digest(canonical(q)) for q in plan["queries"]}
        for event in events:
            assert event["request_identity"] in allowed
            assert (
                json.loads((folder / "events" / f"{event['number']:04}.json").read_bytes()) == event
            )
            assert (
                digest((folder / "wire" / (event["sha256"] + ".bin")).read_bytes())
                == event["sha256"]
            )
        for a, b in zip(events, events[1:], strict=False):
            assert (
                datetime.fromisoformat(b["started_at"]) - datetime.fromisoformat(a["completed_at"])
            ).total_seconds() >= 3.05
            if a["run_id"] == b["run_id"]:
                assert b["start_perf"] - a["response_completed_perf"] >= 3.05
        for proof in lineage:
            raw = (folder / "wire" / (proof["raw_sha256"] + ".bin")).read_bytes()
            data = json.loads(raw)["OutBlock_1"]
            assert (
                digest(canonical(data)) == proof["normalized_rows_sha256"]
                and len(data) == proof["rows"]
            )
        by_date = {}
        for proof in lineage:
            data = json.loads((folder / "wire" / (proof["raw_sha256"] + ".bin")).read_bytes())[
                "OutBlock_1"
            ]
            by_date.setdefault(proof["query"]["basDd"], []).extend(data)
        document_store = Path("data/data-first-private-df008-documents/wire")
        for row in rows:
            if row["CORP_STOCK_LINK_VERIFIED"] is not True:
                continue
            matched = [
                r
                for r in by_date[row["event_date"].replace("-", "")]
                if r["ISU_SRT_CD"] == row["historical_short_code"]
            ]
            assert len(matched) == 1
            actual = matched[0]
            assert (
                actual["ISU_CD"] == row["standard_code"]
                and actual["MKT_TP_NM"] == row["then_market"]
            )
            assert actual["LIST_DD"] <= row["event_date"].replace("-", "")
            raw = (document_store / (row["document_raw_sha256"] + ".bin")).read_bytes()
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                root = ET.fromstring(archive.read(row["receipt"] + ".xml"))
            company = [e for e in root.iter() if e.tag == "COMPANY-NAME"]
            assert {e.attrib.get("AREGCIK") for e in company} == {row["corp_code"]}
            aliases = set()
            for element in company:
                value = "".join("".join(element.itertext()).split())
                for marker in ("주식회사", "(주)", "㈜"):
                    value = value.removeprefix(marker).removesuffix(marker)
                aliases.add(value)
            assert "".join(actual["ISU_ABBRV"].split()) in aliases
            assert actual["KIND_STKCERT_TP_NM"] in {"보통주", "보통주권"}
        assert digest((folder / "query-plan.json").read_bytes()) == result["query_plan_sha256"]
    print(
        "DF009R1 independent 46 dated responses, 8 issuer links, cumulati"
        "ve budget and proposal gates: PASS"
    )


if __name__ == "__main__":
    main()
