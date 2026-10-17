"""Frozen D1 three-event technical replay; no network or strategy optimization."""

import json
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

from kmast.data.models import Observation
from kmast.data.normalization import content_hash
from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import DataStore, canonical, digest
from kmast.research.domestic_panel import economic_fields
from kmast.research.event_replay import event_replay
from scripts.evaluate_df006 import qualify_window

PUBLIC = Path("artifacts/df010")
SOURCE = Path("data/data-first-private-df010-prices")
PRIVATE = Path("data/data-first-private-df010-replays")


def prices(manifest, symbol, basis):
    found = {}
    store = DataStore(SOURCE)
    for page in manifest["pages"].values():
        query = page["request"]
        if query["symbol"] != symbol or query["price_basis"] != basis:
            continue
        rows = store.load_dataset(page["dataset_id"])
        assert (
            digest(canonical([r.model_dump(mode="json") for r in rows])) == page["normalized_hash"]
        )
        for row in rows:
            if row.exchange_date in found:
                if economic_fields(found[row.exchange_date]) != economic_fields(row):
                    raise ValueError("CONFLICTING_PRICE_REVISION")
            found.setdefault(row.exchange_date, row)
    return tuple(found[d] for d in sorted(found))


def unresolved_action_flags(payload, selected_dates):
    flags = []
    for item in payload["output2"]:
        if item["stck_bsop_date"] in selected_dates and (
            item.get("flng_cls_code") not in {None, "", "00"}
            or D(item.get("prtt_rate") or "0") != 0
            or item.get("mod_yn") not in {None, "", "N"}
            or item.get("revl_issu_reas") not in {None, ""}
        ):
            flags.append(
                {
                    k: item.get(k)
                    for k in (
                        "stck_bsop_date",
                        "flng_cls_code",
                        "prtt_rate",
                        "mod_yn",
                        "revl_issu_reas",
                    )
                }
            )
    return flags


def main():
    protocol = json.loads((PUBLIC / "DF010_PROTOCOL.json").read_bytes())
    cache = json.loads((PUBLIC / "cache-audit.json").read_bytes())
    identities = {
        r["receipt"]: r
        for r in json.loads(Path("artifacts/df009r1/event-linkage.json").read_bytes())
    }
    calendar = json.loads(Path("artifacts/df005/session-eligibility-v1.json").read_bytes())
    exclusions = frozenset(date.fromisoformat(r["date"]) for r in calendar["dates"])
    manifest = json.loads((SOURCE / "manifest.json").read_bytes())
    assert manifest["protocol_sha256"] == digest((PUBLIC / "DF010_PROTOCOL.json").read_bytes())
    events, summaries = [], []
    for target, cached in zip(protocol["targets"], cache["histories"], strict=True):
        receipt, symbol = target["receipt"], target["symbol"]
        identity = identities[receipt]
        assert identity["CORP_STOCK_LINK_VERIFIED"] and identity["historical_short_code"] == symbol
        assert identity["then_market"] == target["then_market"]
        assert identity["safe_relevant_correction_lineage_verified"]
        raw, adjusted = (prices(manifest, symbol, basis) for basis in ("RAW", "ADJUSTED"))
        meta = cached["histories"][2]
        payload = (Path("data/data-first-private-df010-cache") / meta["private_file"]).read_bytes()
        assert digest(payload) == meta["normalized_sha256"]
        index = tuple(Observation.model_validate(r) for r in json.loads(payload))
        receipt_day = date.fromisoformat(identity["event_date"])
        eligible = [
            r.exchange_date
            for r in index
            if r.exchange_date > receipt_day and r.exchange_date not in exclusions
        ]
        event = dict(
            receipt=receipt,
            symbol=symbol,
            event_date=str(receipt_day),
            historical_identity_verified=True,
            then_market=target["then_market"],
            actual_publication_time=None,
            full_action_history=None,
            full_halt_history=None,
            full_listing_lifecycle=None,
            historical_price_revision_lineage=None,
            full_research_eligible=False,
            technical_qualified=False,
            raw_rows=len(raw),
            adjusted_rows=len(adjusted),
            index_rows=len(index),
            raw_first=str(raw[0].exchange_date) if raw else None,
            raw_last=str(raw[-1].exchange_date) if raw else None,
            quality_flags=sorted({f for r in raw + adjusted + index for f in r.quality_flags}),
        )
        try:
            if not eligible:
                raise ValueError("NO_OBSERVED_POST_RECEIPT_SESSION")
            entry = eligible[0]
            selected, ix = qualify_window(raw, adjusted, index, entry, exclusions)
            selected_dates = {r.exchange_date.strftime("%Y%m%d") for r in selected}
            action_flags = []
            for page in manifest["pages"].values():
                if page["request"]["symbol"] != symbol:
                    continue
                saved = DataStore(SOURCE).cached("DF010_V1:" + content_hash(page["request"]))
                assert saved is not None
                action_flags.extend(unresolved_action_flags(saved["payload"], selected_dates))
            event["selected_window_provider_action_flags"] = action_flags
            if action_flags:
                raise ValueError("PROVIDER_ACTION_FLAG_WITHOUT_RESOLVED_ACTION_LINEAGE")
            # Complete OHLC diagnostics; retain original source flags.
            if any(r.open is None or r.high is None or r.low is None for r in selected):
                raise ValueError("MISSING_OHLC")
            inp = dict(
                stock=[r.model_dump(mode="json") for r in selected],
                index=[r.model_dump(mode="json") for r in ix],
                entry=str(entry),
                exclusions=sorted(str(d) for d in exclusions),
                receipt=receipt,
                identity=identity,
            )
            input_bytes = canonical(inp)
            immutable_write(PRIVATE / "inputs" / (receipt + ".json"), input_bytes)
            prior = [r for r in selected if r.exchange_date < entry]
            entry_row = next(r for r in selected if r.exchange_date == entry)
            assert prior[-1].close and prior[0].close and entry_row.open
            event.update(
                technical_qualified=True,
                entry_date=str(entry),
                warmup_sessions=len(prior),
                modeled_deadline_calendar_days=5,
                input_sha256=digest(input_bytes),
                raw_adjusted_factor=str(adjusted[0].close / raw[0].close),
                factor_scope="Constant on selected warmup/replay window only",
                prior_21_session_return=str(prior[-1].close / prior[0].close - 1),
                entry_gap=str(entry_row.open / prior[-1].close - 1),
                market_direction_return=str(ix[-1].close / ix[len(prior) - 1].close - 1),
                reason="BOUNDED_OBSERVED_SESSION_TECHNICAL_REPLAY_ONLY",
            )
            replays = {}
            for scenario, values in protocol["replay"]["scenarios"].items():
                fee, tax, slip, fill = values
                for model in protocol["replay"]["models"]:
                    replay = event_replay(
                        selected,
                        ix,
                        entry,
                        (int(fee), int(tax), int(slip), fill),
                        model,
                        exclusions,
                    )
                    replay = json.loads(json.dumps(replay, default=str))
                    replay["input_sha256"] = digest(input_bytes)
                    encoded = canonical(replay)
                    filename = f"{receipt}-{scenario}-{model}.json"
                    immutable_write(PRIVATE / "references" / filename, encoded)
                    summary = dict(
                        replay["summary"],
                        receipt=receipt,
                        symbol=symbol,
                        scenario=scenario,
                        private_file=filename,
                        private_sha256=digest(encoded),
                    )
                    state, final = replay["reference_state"], replay["daily"][-1]
                    realized = D(state["realized"])
                    unrealized = sum(
                        (
                            D(lot["quantity"]) * (D(final["close"]) - D(lot["unit_cost"]))
                            for lot in state["lots"]
                        ),
                        D(0),
                    )
                    summary.update(
                        bought_quantity=sum(e[3] for e in state["executions"] if e[3] > 0),
                        sold_quantity=-sum(e[3] for e in state["executions"] if e[3] < 0),
                        risk_reduction_requested_days=sum(
                            signal["risk_reduction_requested"] for signal in replay["signals"]
                        ),
                        realized_price_pnl=str(realized),
                        unrealized_price_pnl=str(unrealized),
                        central_risk_policy_executed=False,
                        execution_model="ASSUMED_OPEN_NOT_OBSERVED_FILL",
                    )
                    replays[scenario, model] = (summary, replay)
                    summaries.append(summary)
            for scenario in protocol["replay"]["scenarios"]:
                d1, replay = replays[scenario, "D1"]
                for model in ("CASH", "BUY_HOLD", "TREND"):
                    control, other = replays[scenario, model]
                    d1["D1_minus_" + model] = str(D(d1["net"]) - D(control["net"]))
                    if model == "TREND":
                        equal = (
                            replay["reference_state"]["executions"]
                            == other["reference_state"]["executions"]
                            and d1["net"] == control["net"]
                        )
                        d1["identical_trend_trades_and_pnl"] = equal
                        d1["event_specific_incremental_value"] = (
                            "NONE_OBSERVED" if equal else "UNIDENTIFIED_CASE_DIFFERENCE"
                        )
        except ValueError as error:
            event["reason"] = str(error)
        events.append(event)
    budget = json.loads((SOURCE / "budget.json").read_bytes())
    gaps = [
        (
            datetime.fromisoformat(b["request_time"]) - datetime.fromisoformat(a["received_at"])
        ).total_seconds()
        for a, b in zip(budget["events"][:-1], budget["events"][1:], strict=True)
    ]
    count = sum(e["technical_qualified"] for e in events)
    result = dict(
        status="DF010_PRICE_AND_SESSION_PILOT_VERIFIED"
        if count == 3
        else "DF010_PRICE_PARTIAL_QUALIFICATION"
        if count
        else "DF010_DATA_BLOCKED",
        protocol_sha256=digest((PUBLIC / "DF010_PROTOCOL.json").read_bytes()),
        protocol_commit="f2c6691",
        events=events,
        summaries=summaries,
        technical_replay_events=count,
        full_research_eligible_events=0,
        actual_requests=budget["requests"],
        authentication=budget["authentication"],
        new_index_requests=0,
        minimum_response_completion_gap_seconds=min(gaps),
        spacing_violations=sum(g < 3.10 for g in gaps),
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        live_authentication=0,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        actual_fill_pnl=None,
        statistical_tests_executed=False,
        confirmatory_oos=False,
        limitations=[
            "THREE_SELECTED_CASES_ONLY",
            "OBSERVED_SESSION_CALENDAR_NOT_FULL_PIT",
            "FULL_ACTION_HALT_LISTING_HISTORY_UNKNOWN",
            "PUBLICATION_SECONDS_UNKNOWN",
            "MODELED_OPEN_EXECUTION",
            "RESEARCH_COSTS_NOT_VERIFIED_TARIFFS",
            "CENTRAL_RISK_POLICY_NOT_EXECUTED",
            "NO_MARKET_CAUSAL_ATTRIBUTION",
        ],
    )
    atomic_json(PUBLIC / "results.json", result)
    print(
        json.dumps({k: result[k] for k in ("status", "technical_replay_events", "actual_requests")})
    )


if __name__ == "__main__":
    main()
