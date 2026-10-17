"""Frozen D1 discovery, independent cache qualification, and private event accounts."""

import io
import json
import zipfile
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from xml.etree import ElementTree as ET

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from kmast.research.domestic_panel import SCENARIOS, study_reference
from kmast.research.event_flow import DecisionReceipt, decision_boundary
from kmast.research.event_replay import event_replay
from kmast.research.exploratory import boundary
from scripts.run_df005 import load_histories

SOURCE = Path("data/data-first-private-df006-events")
TARGET = Path("data/data-first-private-df006-replays")
PUBLIC = Path("artifacts/df006")


def document_evidence(raw, row):
    """No current master backfill. Require historical document's company/code evidence.

    XML can be non-well-formed legacy DART markup; fallback text is diagnostic,
    never enough to verify identity or family automatically.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
            raise ValueError("DOCUMENT_EXPANSION_LIMIT")
        members = [(n, archive.read(n)) for n in archive.namelist() if n.lower().endswith(".xml")]
    evidence = {"members": [], "family_verified": False, "historical_identity_verified": False}
    for name, content in members:
        member = {"name": name, "sha256": digest(content), "xml_parseable": False}
        try:
            tree = ET.fromstring(content)
        except ET.ParseError:
            evidence["members"].append(member)
            continue
        member["xml_parseable"] = True
        text = "".join("".join(tree.itertext()).split())
        company_nodes = [n for n in tree.iter() if n.tag.upper() == "COMPANY-NAME"]
        company_matches = [
            n
            for n in company_nodes
            if "".join("".join(n.itertext()).split()) == "".join(row["corp_name"].split())
        ]
        code_match = any(row["corp_code"] in n.attrib.values() for n in company_nodes)
        legal_name_corroborated = any(
            "".join(row["corp_name"].split()) in "".join("".join(n.itertext()).split())
            for n in company_nodes
        )
        stock_nodes = [n for n in tree.iter() if n.tag.upper() in {"STOCK-CODE", "STOCK_CODE"}]
        stock_match = any("".join(n.itertext()).strip() == row["stock_code"] for n in stock_nodes)
        family = "자기주식취득결정" in text and any(
            marker in text for marker in ("취득예정금액", "취득예정주식", "취득예정기간")
        )
        member.update(
            company_name_match=bool(company_matches),
            legal_name_corroborated=legal_name_corroborated,
            corp_code_attribute_match=code_match,
            stock_code_element_match=stock_match,
            decision_fields_present=family,
        )
        # Corp code on the original company node, corroborated by historical list
        # stock_code, is stronger than a present-day corpCode master lookup.
        evidence["historical_identity_verified"] |= (legal_name_corroborated and code_match) or (
            bool(company_matches) and stock_match
        )
        evidence["family_verified"] |= family
        evidence["members"].append(member)
    return evidence


def qualify_window(raw, adjusted, index, entry, exclusions):
    r, a, ix = ({v.exchange_date: v for v in panel} for panel in (raw, adjusted, index))
    dates = sorted(ix)
    if entry not in dates or dates.index(entry) < 21:
        raise ValueError("WARMUP_OR_ENTRY_MISSING")
    start = dates.index(entry)
    exits = [
        i
        for i, day in enumerate(dates)
        if day >= entry + timedelta(days=5) and day not in exclusions
    ]
    if not exits:
        raise ValueError("NO_DEADLINE_SESSION")
    # Two further observed sessions expose partial residuals without forced liquidation.
    end = exits[0] + 2
    if end >= len(dates):
        raise ValueError("INCOMPLETE_EXIT_FOLLOWUP")
    if dates[end] > date(2025, 10, 8):
        raise ValueError("DISCLOSURE_FOLLOWUP_OUTSIDE_APPROVED_INTERVAL")
    selected = dates[start - 21 : end + 1]
    if any(day not in r or day not in a for day in selected):
        raise ValueError("MISSING_STOCK_OR_ADJUSTED_SESSION")
    factors = []
    for day in selected:
        for row in (r[day], a[day], ix[day]):
            if (
                not row.complete
                or row.data_origin != "KIS_READONLY"
                or row.close is None
                or row.close <= 0
            ):
                raise ValueError("INCOMPLETE_REAL_PRICE")
        if (
            r[day].volume is None
            or r[day].volume <= 0
            or r[day].turnover is None
            or r[day].turnover <= 0
        ):
            raise ValueError("HALT_OR_LIQUIDITY_LINEAGE_MISSING")
        if r[day].price_basis != "RAW" or a[day].price_basis != "ADJUSTED":
            raise ValueError("PRICE_BASIS_CONFLICT")
        factors.append(a[day].close / r[day].close)
    if len(set(factors)) != 1:
        raise ValueError("NONCONSTANT_FACTOR_WITHOUT_ACTION_LINEAGE")
    return tuple(r[d] for d in selected), tuple(ix[d] for d in selected)


def main():
    manifest = json.loads((SOURCE / "manifest.json").read_bytes())
    if not manifest["complete"]:
        raise ValueError("COLLECTION_INCOMPLETE")
    protocol = (PUBLIC / "DF006_PROTOCOL.json").read_bytes()
    assert digest(protocol) == manifest["protocol_sha256"]
    selected_bytes = (SOURCE / "selected-disclosures.json").read_bytes()
    selected = json.loads(selected_bytes)
    assert digest(canonical(selected["rows"])) == selected["normalized_sha256"]
    rows = selected["rows"]
    budget = json.loads((SOURCE / "budget.json").read_bytes())
    price_manifest = json.loads(
        Path("data/data-first-private-df005-panel/manifest.json").read_bytes()
    )
    selection = json.loads(Path("artifacts/df005/DF005_PROTOCOL.json").read_bytes())
    exclusions = frozenset(
        date.fromisoformat(r["date"])
        for r in json.loads(Path("artifacts/df005/session-eligibility-v1.json").read_bytes())[
            "dates"
        ]
    )
    coverage, candidates, rejected, replay_summaries = Counter(), [], [], []
    histories = {}
    TARGET.mkdir(parents=True, exist_ok=True)
    for receipt, value in sorted(rows.items()):
        row = value["row"]
        title = "".join(row["report_nm"].split())
        if "자기주식" in title:
            coverage["self_stock_related_reports"] += 1
        if "신탁" in title:
            coverage["trust_contract_reports_not_D1"] += 1
        if "자기주식처분" in title:
            coverage["disposal_reports_not_D1"] += 1
        if "소각" in title:
            coverage["retirement_reports_not_D1"] += 1
        if "자기주식취득決定" in title:
            coverage["unrecognized_hanja_title"] += 1
        if "자기주식취득결정" not in title:
            coverage["other_major_report"] += 1
            continue
        correction = any(s in title for s in ("정정", "첨부추가", "철회"))
        if correction:
            coverage["correction_not_new_entry"] += 1
        original_title = title in {"주요사항보고서(자기주식취득결정)", "자기주식취득결정"}
        coverage["decision_title_matches"] += 1
        doc = manifest["documents"].get(receipt)
        if doc is None:
            rejected.append(
                dict(receipt=receipt, symbol=row["stock_code"], reason="ORIGINAL_DOCUMENT_MISSING")
            )
            continue
        rawdoc = (SOURCE / "wire" / (doc["sha256"] + ".bin")).read_bytes()
        assert digest(rawdoc) == doc["sha256"]
        evidence = document_evidence(rawdoc, row)
        atomic_json(TARGET / "document-evidence" / (receipt + ".json"), evidence)
        if correction or not original_title:
            continue
        coverage["original_exact_title"] += 1
        event = DecisionReceipt(
            receipt=receipt,
            corp_code=row["corp_code"],
            stock_code=row["stock_code"],
            receipt_date=date.fromisoformat(
                row["rcept_dt"][:4] + "-" + row["rcept_dt"][4:6] + "-" + row["rcept_dt"][6:]
            ),
            title=row["report_nm"],
            acquired_at=value["acquired_at"],
            original_document_sha256=doc["sha256"],
            raw_response_sha256=value["raw_response_sha256"],
            document_family_verified=evidence["family_verified"],
            historical_identity_verified=evidence["historical_identity_verified"],
        )
        atomic_json(
            TARGET / "events" / (receipt + ".json"),
            {
                "event": event.model_dump(mode="json"),
                "normalized_sha256": event.normalized_sha256,
                "list_row_sha256": digest(canonical(row)),
            },
        )
        symbol = event.stock_code
        if symbol not in histories:
            index_symbol = "0001" if symbol in selection["kospi"] else "1001"
            histories[symbol] = tuple(
                load_histories(price_manifest, code, basis)
                for code, basis in ((symbol, "RAW"), (symbol, "ADJUSTED"), (index_symbol, "RAW"))
            )
        raw, adjusted, index = histories[symbol]
        reason = None
        if not raw:
            reason = "NO_CACHED_PRICE_HISTORY"
            coverage["missing_price_events"] += 1
        elif not event.entry_candidate:
            reason = "DOCUMENT_OR_HISTORICAL_IDENTITY_UNVERIFIED"
        if reason:
            rejected.append(dict(receipt=receipt, symbol=symbol, reason=reason))
            continue
        calendar = tuple(
            boundary(r.exchange_date, 8) for r in index if r.exchange_date not in exclusions
        )
        entry = decision_boundary(event, calendar).date()
        try:
            stock, ix = qualify_window(raw, adjusted, index, entry, exclusions)
        except ValueError as exc:
            rejected.append(dict(receipt=receipt, symbol=symbol, reason=str(exc)))
            continue
        input_payload = {
            "event_sha256": event.normalized_sha256,
            "stock": [r.model_dump(mode="json") for r in stock],
            "index": [r.model_dump(mode="json") for r in ix],
            "adjusted": [
                r.model_dump(mode="json")
                for r in adjusted
                if r.exchange_date in {s.exchange_date for s in stock}
            ],
            "derived_availability": "DATE_ONLY_EXPLORATORY_BOUND_NOT_OBSERVED_PUBLICATION",
            "source_quality_flags": sorted({f for r in stock + ix for f in r.quality_flags}),
        }
        immutable_write(TARGET / "inputs" / (receipt + ".json"), canonical(input_payload))
        # Unknown correction linkage is quarantined prospectively. Never infer parent
        # using similar title alone; conservatively treat a same-company correction
        # as unresolved family risk from its own date boundary.
        correction_days = []
        for val in rows.values():
            rr = val["row"]
            tt = "".join(rr["report_nm"].split())
            if (
                rr["corp_code"] == event.corp_code
                and "자기주식취득결정" in tt
                and any(s in tt for s in ("정정", "첨부추가", "철회"))
            ):
                rd = date(
                    int(rr["rcept_dt"][:4]), int(rr["rcept_dt"][4:6]), int(rr["rcept_dt"][6:])
                )
                if rd >= event.receipt_date:
                    future = [t.date() for t in calendar if t.date() > rd]
                    if future:
                        correction_days.append(future[0])
        invalidation = min(correction_days) if correction_days else None
        candidates.append(
            dict(
                receipt=receipt,
                symbol=symbol,
                entry=str(entry),
                event_sha256=event.normalized_sha256,
            )
        )
        prior = [r for r in index if r.exchange_date < entry]
        bear = len(prior) >= 21 and prior[-1].close / prior[-21].close - 1 <= D("-.05")
        all_dates = sorted(r.exchange_date for r in index)
        placebo = None
        placebo_reason = "INSUFFICIENT_PRIOR_SESSIONS"
        at = all_dates.index(entry)
        if at >= 41:
            placebo_day = all_dates[at - 20]
            regular = [d for d in all_dates[at - 20 :] if d not in exclusions]
            if regular:
                placebo_day = regular[0]
            known_dates = [
                date(
                    int(v["row"]["rcept_dt"][:4]),
                    int(v["row"]["rcept_dt"][4:6]),
                    int(v["row"]["rcept_dt"][6:]),
                )
                for v in rows.values()
                if v["row"]["corp_code"] == event.corp_code
                and "자기주식취득결정" in "".join(v["row"]["report_nm"].split())
            ]
            prior5 = all_dates[max(0, all_dates.index(placebo_day) - 5)]
            if any(prior5 <= d <= placebo_day + timedelta(days=9) for d in known_dates):
                placebo_reason = "PREDEFINED_PLACEBO_OVERLAPS_EVENT"
            else:
                try:
                    ps, pi = qualify_window(raw, adjusted, index, placebo_day, exclusions)
                    placebo = (ps, pi, placebo_day)
                    placebo_reason = None
                except ValueError as exc:
                    placebo_reason = str(exc)
        # Fixed single-company reference for each event; never a joint account.
        for scenario, costs in SCENARIOS.items():
            models = {}
            event_result = None
            for model in ("D1", "CASH", "BUY_HOLD", "TREND"):
                result = event_replay(
                    stock,
                    ix,
                    entry,
                    costs,
                    model,
                    exclusions,
                    invalidation if model in {"D1", "TREND"} else None,
                )
                path = TARGET / "references" / f"{receipt}-{scenario}-{model}.json"
                immutable_write(path, canonical(result))
                models[model] = result["summary"]
                if model == "D1":
                    event_result = result
                summary = result["summary"] | dict(
                    receipt=receipt,
                    symbol=symbol,
                    scenario=scenario,
                    entry=str(entry),
                    bear=bool(bear),
                    private_sha256=digest(path.read_bytes()),
                )
                replay_summaries.append(summary)
            a0 = study_reference(stock, ix, "A0", scenario, exclusions)
            immutable_write(
                TARGET / "references" / f"{receipt}-{scenario}-A0.json",
                canonical(json.loads(json.dumps(a0, default=str))),
            )
            main_summary = next(
                s
                for s in replay_summaries
                if s["receipt"] == receipt and s["scenario"] == scenario and s["model"] == "D1"
            )
            main_summary["A0_net"] = a0["analysis"]["summary"]["project_net"]
            main_summary["D1_minus_A0"] = str(D(models["D1"]["net"]) - D(main_summary["A0_net"]))
            main_summary["D1_minus_TREND"] = str(D(models["D1"]["net"]) - D(models["TREND"]["net"]))
            main_summary["D1_minus_BUY_HOLD"] = str(
                D(models["D1"]["net"]) - D(models["BUY_HOLD"]["net"])
            )
            main_summary["placebo_net"] = None
            main_summary["placebo_missing_reason"] = placebo_reason
            if placebo is not None:
                ps, pi, pd = placebo
                p_result = event_replay(ps, pi, pd, costs, "D1", exclusions)
                immutable_write(
                    TARGET / "references" / f"{receipt}-{scenario}-PLACEBO.json",
                    canonical(p_result),
                )
                main_summary["placebo_net"] = p_result["summary"]["net"]
                main_summary["D1_minus_PLACEBO"] = str(
                    D(models["D1"]["net"]) - D(main_summary["placebo_net"])
                )
            else:
                main_summary["D1_minus_PLACEBO"] = None
            pre = [r for r in raw if r.exchange_date < entry]
            observed_receipt = [r for r in raw if r.exchange_date == event.receipt_date]
            entry_price = next(r.open for r in stock if r.exchange_date == entry)
            main_summary["prior20_runup"] = str(pre[-1].close / pre[-21].close - 1)
            main_summary["entry_gap_from_last_observed_close"] = str(
                entry_price / pre[-1].close - 1
            )
            main_summary["receipt_day_close_observed"] = bool(observed_receipt)
            main_summary["post_entry_close_return_decay"] = [
                str(r.close / entry_price - 1) for r in stock if r.exchange_date >= entry
            ][:5]
            market_proxy, previous_qty = D(0), 0
            for day in event_result["daily"]:
                market_proxy += (
                    previous_qty
                    * D(day["prior_close"])
                    * (D(day["index_close"]) / D(day["index_prior_close"]) - 1)
                )
                previous_qty = day["quantity"]
            main_summary["market_direction_pnl_proxy"] = str(market_proxy)
            main_summary["net_minus_market_direction_proxy"] = str(
                D(main_summary["net"]) - market_proxy
            )
            main_summary["market_comparison_scope"] = (
                "PRIOR_INVENTORY_INDEX_DIRECTION_PROXY_NOT_TRADABLE_OR_RISK_MATCHED"
            )
            if observed_receipt:
                before_receipt = [r for r in raw if r.exchange_date < event.receipt_date]
                main_summary["receipt_date_close_return"] = (
                    str(observed_receipt[0].close / before_receipt[-1].close - 1)
                    if before_receipt
                    else None
                )
    atomic_json(
        TARGET / "discovery.json",
        dict(
            coverage=dict(coverage),
            candidates=candidates,
            rejected=rejected,
            histories_loaded=len(histories),
        ),
    )
    result = dict(
        protocol_sha256=digest(protocol),
        protocol_commit=manifest["protocol_commit"],
        candidate="D1_TREASURY_ACQUISITION_DECISION",
        parameter_combinations=1,
        collection_complete=True,
        authenticated_requests=budget["used"],
        maximum_requests=600,
        list_pages=len(manifest["pages"]),
        documents=len(manifest["documents"]),
        selected_disclosures=len(rows),
        source_normalized_sha256=selected["normalized_sha256"],
        original_decision_events=coverage["original_exact_title"],
        coverage=dict(coverage),
        eligible_events=len(candidates),
        modeled_executable_events=len(
            {
                s["receipt"]
                for s in replay_summaries
                if s["model"] == "D1" and s["scenario"] == "BASE" and s["executions"] > 0
            }
        ),
        independent_company_count=len({c["symbol"] for c in candidates}),
        independent_entry_date_count=len({c["entry"] for c in candidates}),
        bear_event_count=sum(
            s["bear"] for s in replay_summaries if s["model"] == "D1" and s["scenario"] == "BASE"
        ),
        rejected=rejected,
        summaries=replay_summaries,
        economic_metrics_missing_reason="NO_ELIGIBLE_REAL_DISCLOSURE_EVENTS"
        if not replay_summaries
        else None,
        net_operating_pnl=None
        if not replay_summaries
        else "SEE_INDEPENDENT_EVENT_REFERENCE_SUMMARIES_NOT_POOLED_PNL",
        statistical_tests={
            "executed": False,
            "reason": "PREREGISTERED_MINIMUM_EVIDENCE_NOT_MET",
            "primary_family": ["D1-CASH", "D1-TREND", "D1-PLACEBO"],
            "company_clusters": len({c["symbol"] for c in candidates}),
            "entry_date_clusters": len({c["entry"] for c in candidates}),
            "holm_adjusted_p": None,
            "company_bootstrap_CI": None,
            "date_block_bootstrap_CI": None,
        },
        decision="D_EVENT_INSUFFICIENT_EVIDENCE",
        economics_executed=bool(replay_summaries),
        risk_gate="NOT_PASSED_ACTUAL_CLOSE_WEIGHT_CAP_BREACH_OR_INTRADAY_UNVERIFIED",
        actual_weight_cap_breach_event_count=len(
            {
                s["receipt"]
                for s in replay_summaries
                if s["model"] == "D1" and s["scenario"] == "BASE" and s["weight_cap_breach_days"]
            }
        ),
        allocation_approved=False,
        actual_fill_economics=None,
        confirmatory_status="NOT_EXECUTED",
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        kis_requests=0,
        limitations=[
            "CURRENT_SURVIVOR_UNIVERSE_NOT_PIT",
            "DATE_ONLY_PUBLICATION",
            "MODELED_OPEN_NOT_ACTUAL_EXECUTION",
            "B001_ONLY_APPROVED_DISCLOSURE_SCOPE",
            "NO_INDEPENDENT_OOS",
            "UNRESOLVED_CORRECTION_FAMILIES_QUARANTINED",
            "MINIMUM_EVIDENCE_30_FAMILIES_10_COMPANIES_20_DATES_5_BEAR_EVENTS_NOT_MET",
            "ACQUISITION_SPACING_NONCOMPLIANT",
        ],
    )
    if len(candidates) >= 30:
        raise ValueError("MINIMUM_REACHED_REQUIRES_COMPLETE_FROZEN_STATS_AND_CONTROLS")
    atomic_json(PUBLIC / "results.json", result)
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "original_events": result["original_decision_events"],
                "eligible_events": len(candidates),
                "references": len(replay_summaries),
            }
        )
    )


if __name__ == "__main__":
    main()
