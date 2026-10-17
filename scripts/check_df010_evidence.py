"""Independent arithmetic/causality checks; private wire and ledger audit is local only."""

import argparse
import json
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

from kmast.data.store import DataStore, canonical, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    public = Path("artifacts/df010")
    protocol = json.loads((public / "DF010_PROTOCOL.json").read_bytes())
    result = json.loads((public / "results.json").read_bytes())
    proposal = json.loads(Path("artifacts/df009r1/next-price-proposal.json").read_bytes())
    assert protocol["targets"] == proposal["targets"]
    assert result["protocol_sha256"] == digest((public / "DF010_PROTOCOL.json").read_bytes())
    assert result["actual_requests"] <= 20 and result["authentication"] <= 2
    assert result["new_index_requests"] == 0 and result["spacing_violations"] == 0
    assert result["minimum_response_completion_gap_seconds"] >= 3.10
    assert result["economic_status"] == "ECONOMIC_EDGE_UNVERIFIED"
    assert result["live_status"] == "LIVE_NOT_APPROVED"
    assert not result["statistical_tests_executed"] and not result["confirmatory_oos"]
    assert all(
        result[k] == 0
        for k in (
            "actual_orders",
            "actual_cancels",
            "account_queries",
            "live_authentication",
            "full_research_eligible_events",
        )
    )
    qualified = {e["receipt"] for e in result["events"] if e["technical_qualified"]}
    assert len(qualified) == result["technical_replay_events"]
    assert len(result["summaries"]) == len(qualified) * 12
    for event in result["events"]:
        assert event["actual_publication_time"] is None
        assert event["full_action_history"] is None and event["full_halt_history"] is None
        assert not event["full_research_eligible"]
        if event["technical_qualified"]:
            assert event["warmup_sessions"] >= 21
            assert event["entry_date"] > event["event_date"]
            assert not event["selected_window_provider_action_flags"]
        else:
            assert not any(s["receipt"] == event["receipt"] for s in result["summaries"])
    for row in result["summaries"]:
        assert row["receipt"] in qualified
        assert abs(
            D(row["gross_before_slippage"])
            - D(row["embedded_slippage"])
            - D(row["explicit_cost"])
            - D(row["operating_cost"])
            - D(row["net"])
        ) < D("1e-14")
        assert D(row["commission"]) + D(row["tax"]) == D(row["explicit_cost"])
        assert D(row["realized_price_pnl"]) + D(row["unrealized_price_pnl"]) - D(
            row["explicit_cost"]
        ) - D(row["operating_cost"]) == D(row["net"])
        assert row["actual_fill_pnl"] is None and not row["central_risk_policy_executed"]
        assert row["execution_model"] == "ASSUMED_OPEN_NOT_OBSERVED_FILL"
        if row["model"] == "D1":
            for control in ("CASH", "BUY_HOLD", "TREND"):
                other = next(
                    s
                    for s in result["summaries"]
                    if s["receipt"] == row["receipt"]
                    and s["scenario"] == row["scenario"]
                    and s["model"] == control
                )
                assert D(row["net"]) - D(other["net"]) == D(row["D1_minus_" + control])
    if args.private:
        source = Path("data/data-first-private-df010-prices")
        manifest = json.loads((source / "manifest.json").read_bytes())
        budget = json.loads((source / "budget.json").read_bytes())
        assert budget["requests"] == len(budget["events"]) == result["actual_requests"]
        assert budget["authentication"] == sum(e["kind"] == "AUTH" for e in budget["events"])
        for a, b in zip(budget["events"][:-1], budget["events"][1:], strict=True):
            assert (
                datetime.fromisoformat(b["request_time"]) - datetime.fromisoformat(a["received_at"])
            ).total_seconds() >= 3.10
        for event in budget["events"]:
            if event["kind"] == "AUTH":
                assert "wire_path" not in event
                continue
            raw = (source / event["wire_path"]).read_bytes()
            assert digest(raw) == event["wire_sha256"]
            payload = json.loads(raw)
            assert event["operation"] == "daily"
            target = next(t for t in protocol["targets"] if t["symbol"] == event["symbol"])
            assert target["start"].replace("-", "") <= event["start"] <= event["end"]
            assert event["end"] <= target["end"].replace("-", "")
            assert payload["rt_cd"] == "0"
        for page in manifest["pages"].values():
            rows = DataStore(source).load_dataset(page["dataset_id"])
            assert (
                digest(canonical([r.model_dump(mode="json") for r in rows]))
                == page["normalized_hash"]
            )
            event = next(
                e for e in budget["events"] if e.get("canonical_sha256") == page["source_hash"]
            )
            raw = json.loads((source / event["wire_path"]).read_bytes())
            mapping = {r["stck_bsop_date"]: r for r in raw["output2"]}
            assert len(rows) == len(mapping)
            for row in rows:
                item = mapping[row.exchange_date.strftime("%Y%m%d")]
                for field, key in [
                    ("open", "stck_oprc"),
                    ("high", "stck_hgpr"),
                    ("low", "stck_lwpr"),
                    ("close", "stck_clpr"),
                    ("volume", "acml_vol"),
                    ("turnover", "acml_tr_pbmn"),
                ]:
                    assert getattr(row, field) == D(item[key])
        private = Path("data/data-first-private-df010-replays")
        for summary in result["summaries"]:
            path = private / "references" / summary["private_file"]
            assert digest(path.read_bytes()) == summary["private_sha256"]
            replay = json.loads(path.read_bytes())
            state, final = replay["reference_state"], replay["daily"][-1]
            assert D(final["cash"]) + final["quantity"] * D(final["close"]) - D(
                summary["capital"]
            ) == D(summary["net"])
            assert sum((D(e[5]) for e in state["executions"]), D(0)) == D(summary["explicit_cost"])
            buys = sum(e[3] for e in state["executions"] if e[3] > 0)
            sells = -sum(e[3] for e in state["executions"] if e[3] < 0)
            assert buys - sells == summary["final_quantity"]
            assert (
                sum(s["reduction_unfulfilled"] for s in replay["signals"])
                == summary["unfulfilled_reduction_days"]
            )
            event = next(e for e in result["events"] if e["receipt"] == summary["receipt"])
            assert all(
                date.fromisoformat(s["day"]) > date.fromisoformat(event["event_date"])
                for s in replay["signals"]
            )
            assert all(
                D(s["target"]) <= D(".25")
                for s in replay["signals"]
                if s["submitted"] and not s["risk_reduction_requested"]
            )
        snapshot = json.loads(
            Path("data/data-first-private-df010-audit/preexisting-files.json").read_bytes()
        )
        assert all(
            Path(p).exists() and digest(Path(p).read_bytes()) == h for p, h in snapshot.items()
        )
    print(
        "DF010 independent evidence checks PASS"
        + (" (private wire/ledger/preservation)" if args.private else " (public aggregates)")
    )


if __name__ == "__main__":
    main()
