"""Independent arithmetic and NULL boundaries; private credentials never needed in CI."""

import argparse
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df009")
    result = json.loads((public / "results.json").read_bytes())
    protocol = json.loads((public / "DF009_PROTOCOL.json").read_bytes())
    plan = json.loads((public / "KRX_QUERY_PLAN.json").read_bytes())
    rows = json.loads((public / "event-linkage.json").read_bytes())
    assert (
        result["protocol_sha256"]
        == sha256((public / "DF009_PROTOCOL.json").read_bytes()).hexdigest()
    )
    assert (
        result["query_plan_sha256"]
        == sha256((public / "KRX_QUERY_PLAN.json").read_bytes()).hexdigest()
    )
    assert len(rows) == len(protocol["targets"]) == len({r["corp_code"] for r in rows}) == 12
    assert Counter(r["receipt"][:4] for r in rows) == dict.fromkeys(
        ["2022", "2023", "2024", "2025"], 3
    )
    identities = [{k: r[k] for k in ("receipt", "corp_code")} for r in protocol["targets"]]
    assert sha256(canonical(identities)).hexdigest() == protocol["receipt_corporate_id_sha256"]
    assert sha256(canonical(rows)).hexdigest() == result["event_linkage_sha256"]
    assert len({(q["market"], q["basDd"]) for q in plan["queries"]}) == len(plan["queries"]) == 46
    assert result["maximum_approved_requests"] == plan["maximum_total_requests"] == 92
    assert result["authenticated_requests"] == result["attempted_market_date_queries"] == 1
    assert result["unattempted_queries"] == 45 and result["retries"] == 0
    assert result["response_http_status"] == 401 and result["response_provider_code"] == "401"
    assert result["observed_historical_rows"] is result["historical_date_service_available"] is None
    assert (
        result["cost_requests_per_verified_event"] is result["identity_conflicts_observed"] is None
    )
    assert not result["price_pilot_qualified"] and result["next_price_companies"] == []
    for row in rows:
        assert row["CORPORATE_IDENTITY_VERIFIED"] is True
        assert all(
            row[k] is None
            for k in (
                "HISTORICAL_SECURITY_PRESENT",
                "CORP_STOCK_LINK_VERIFIED",
                "THEN_LISTED_STATUS_VERIFIED",
                "actual_publication_time",
            )
        )
        assert (
            row["DELISTING_AND_HALT_PENDING"]
            and row["CORPORATE_ACTION_PENDING"]
            and row["PRICE_AND_SESSION_PENDING"]
        )
    assert (
        result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
        and result["live_status"] == "LIVE_NOT_APPROVED"
    )
    assert all(
        result[k] == 0
        for k in (
            "new_KIS_requests",
            "new_DART_requests",
            "new_price_requests",
            "new_economic_trials",
            "actual_orders",
            "actual_cancels",
            "account_queries",
        )
    )
    orb = json.loads((public / "orb-supply-plan.json").read_bytes())
    for scenario in orb["storage_scenarios"]:
        daily = 10 * 23400 * 2 * scenario["assumed_messages_per_second_per_channel"] * 1024
        assert scenario["bytes_per_session"] == daily
        assert scenario["bytes_20_sessions_two_copies"] == daily * 40
    assert (
        orb["new_authentication_calls"] == orb["new_subscriptions"] == orb["economic_trials"] == 0
    )
    preservation = json.loads((public / "preservation-audit.json").read_bytes())
    assert preservation["protected_bytes_unchanged"] and preservation["secret_matches"] == 0
    if args.private:
        private = Path("data/data-first-private-df009-krx")
        state = json.loads((private / "budget.json").read_bytes())
        event = state["events"][0]
        assert state["used"] == len(state["events"]) == 1 and state["halted"]
        assert json.loads((private / "events/0001.json").read_bytes()) == event
        raw = (private / "wire" / (event["sha256"] + ".bin")).read_bytes()
        assert sha256(raw).hexdigest() == event["sha256"] == result["response_sha256"]
        assert json.loads(raw)["respCode"] == "401"
        assert event["http_status"] == 401 and event["transmitted"] and not event["success"]
        dossier = json.loads(
            Path("data/data-first-private-df009-identity/corporate-dossier.json").read_bytes()
        )
        assert sha256(canonical(dossier)).hexdigest() == result["corporate_dossier_sha256"]
        assert not list((private / "normalized").glob("*.json"))
        source = Path("data/data-first-private-df009-sources")
        for service in json.loads((public / "source-assessment.json").read_bytes())["services"]:
            assert (
                sha256((source / service["private_spec_name"]).read_bytes()).hexdigest()
                == service["source_doc_sha256"]
            )
    print("DF009 independent frozen scope, actual 401, NULL identity and ORB estimates: PASS")


if __name__ == "__main__":
    main()
