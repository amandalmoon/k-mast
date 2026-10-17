"""Offline issuer evidence and entitlement sidecar; no new price replay or authentication."""

import json
from datetime import date, datetime
from decimal import Decimal as D
from html.parser import HTMLParser
from pathlib import Path

from kmast.data.panel_acquisition import atomic_json, immutable_write
from kmast.data.store import canonical, digest
from kmast.research.entitlements import (
    CorporateActionEntitlementLedger,
    DividendAction,
    SettledTrade,
    settle_t_plus_two,
    verify_daily_ex_dividend_definition,
)

PUBLIC = Path("artifacts/df011")
SOURCES = Path("data/data-first-private-df011-sources")
PRIVATE = Path("data/data-first-private-df011-entitlements")


class SourceText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def main():
    protocol = json.loads((PUBLIC / "DF011_PROTOCOL.json").read_bytes())
    assert protocol["PREVIOUSLY_OBSERVED_EVIDENCE"]["131290"]["flng_cls_code"] == "02"
    manifest = json.loads((SOURCES / "manifest.json").read_bytes())

    def raw(name):
        record = manifest[name]
        payload = (SOURCES / "raw" / (record["sha256"] + ".bin")).read_bytes()
        assert digest(payload) == record["sha256"] and record["authentication"] is False
        return payload

    def text(name):
        parser = SourceText()
        parser.feed(raw(name).decode("utf-8"))
        return " ".join(" ".join(parser.parts).split())

    detail = json.loads(raw("kis-daily-official-detail"))
    properties = json.loads(raw("kis-daily-official-property"))
    assert verify_daily_ex_dividend_definition(detail, properties)
    field = next(p for p in properties if p["propertyCd"] == "flng_cls_code")
    decision = text("kind-dividend-decision")
    viewer = text("kind-dividend-viewer")
    annual = text("kind-tse-2024-annual")
    settlement = text("krx-settlement-rule")
    notice = text("broker-2022-year-end-notice")
    assert "티에스이" in viewer and "티에스이" in annual[:2000]
    for expected in ["보통주식 500", "2022-12-31", "2023-04-10", "2023-03-24", "2023-02-22"]:
        assert expected in decision
    assert "2023년 3월 24일 주주총회에 의안으로 상정되어 결의 되었습니다" in annual
    assert "배당금은 2023년 4월에 지급되었습니다" in annual
    assert "T+2" in settlement
    assert "12 월 27 일" in notice or "12월 27일" in notice
    used = [
        "kis-daily-official-detail",
        "kis-daily-official-property",
        "kind-dividend-viewer",
        "kind-dividend-path",
        "kind-dividend-decision",
        "kind-tse-2024-annual",
        "krx-settlement-rule",
        "broker-2022-year-end-notice",
    ]
    lineage = dict(
        symbol="131290",
        corp_code="00372226",
        receipt="20221226000280",
        code_meaning=dict(
            endpoint=detail["accessUrl"],
            tr="FHKST03010100",
            field="flng_cls_code",
            value="02",
            meaning="EX_DIVIDEND",
            exact_daily_field_verified=True,
            specification_last_modified=field["lastModifiedDate"],
            archival_2022_specification_verified=None,
        ),
        ex_day="2022-12-28",
        record_day="2022-12-31",
        last_purchase_day="2022-12-27",
        derived_last_purchase_settlement_day="2022-12-29",
        share_class="COMMON",
        gross_cash_per_share="500",
        decision_day="2023-02-22",
        final_resolution_day="2023-03-24",
        scheduled_payment_day="2023-04-10",
        actual_payment_day=None,
        issuer_payment_month="2023-04",
        issuer_payment_month_verified=True,
        actual_account_payment_verified=False,
        investor_dividend_tax=None,
        full_other_action_history=None,
        full_halt_history=None,
        complete_correction_chain=None,
        final_resolution_knowledge_boundary="2024-03-20",
        information_scope="Ex-post issuer evidence; never a December 2022 signal input",
        sources={name: manifest[name] for name in used},
        limitations=[
            "Issuer cash payment month is not exact payment day or investor receipt",
            "Current daily-field spec corroborates meaning, not archived 2022 schema",
            "T+2 current KRX rule corroborated by contemporaneous 2022 broker notice",
            "Complete action/halt/correction history and investor tax remain unknown",
        ],
    )
    atomic_json(PUBLIC / "corporate-action-lineage.json", lineage)
    action = DividendAction(
        identity="DF011_131290_FY2022_COMMON_CASH",
        symbol="131290",
        share_class="COMMON",
        ex_day=date(2022, 12, 28),
        last_purchase_day=date(2022, 12, 27),
        record_day=date(2022, 12, 31),
        declared_day=date(2023, 2, 22),
        resolved_day=date(2023, 3, 24),
        amount_known_on=date(2024, 3, 20),
        gross_per_share=D(500),
        scheduled_payment_day=date(2023, 4, 10),
        actual_payment_day=None,
        payment_evidence_known_on=None,
        issuer_paid_month="2023-04",
        issuer_paid_month_known_on=date(2024, 3, 20),
        identity_verified=True,
        settlement_verified=True,
        amount_verified=True,
        full_action_window_verified=False,
        evidence_hashes=tuple(manifest[name]["sha256"] for name in used),
    )
    # Reuse exact observed index days, with the independently corroborated year-end closure.
    cache = Path("data/data-first-private-df010-cache/20221226000280-1001-RAW.json")
    observed = json.loads(cache.read_bytes())
    days = tuple(date.fromisoformat(r["exchange_date"]) for r in observed)
    assert date(2022, 12, 30) not in days
    assert settle_t_plus_two(date(2022, 12, 27), days) == date(2022, 12, 29)
    snapshots = []
    for scenario in ("BASE", "STRESS", "PARTIAL"):
        old = Path("data/data-first-private-df010-replays/references") / (
            "20221226000280-" + scenario + "-D1.json"
        )
        replay = json.loads(old.read_bytes())
        trades = tuple(
            SettledTrade(
                identity=e[0],
                symbol=e[2],
                trade_day=datetime.fromisoformat(e[1]).date(),
                settlement_day=settle_t_plus_two(datetime.fromisoformat(e[1]).date(), days),
                quantity=e[3],
            )
            for e in replay["reference_state"]["executions"]
        )
        ledger = CorporateActionEntitlementLedger(
            action=action, trades=trades, price_only_pnl=D(replay["summary"]["net"])
        )
        before = ledger.snapshot(date(2023, 1, 5), date(2023, 1, 5))
        receivable = ledger.snapshot(date(2023, 3, 25), date(2026, 10, 17))
        after = ledger.snapshot(date(2023, 4, 30), date(2026, 10, 17))
        assert before["gross_entitlement"] is None
        assert "DIVIDEND_RECEIVABLE_VERIFIED" in receivable["statuses"]
        assert after["net_dividend_cash_verified"] is None and not after["total_return_verified"]
        payload = dict(
            scenario=scenario,
            source_price_path_sha256=digest(old.read_bytes()),
            source_price_path_status="DF010_REJECTED_PREQUALIFICATION_DIAGNOSTIC",
            price_path_promoted=False,
            independent_strategy_replay_executed=False,
            before_final_amount_known=before,
            ex_post_pre_payment_receivable=receivable,
            issuer_payment_month_end=after,
            settlement_calendar_sha256=digest(cache.read_bytes()),
            price_only_diagnostic_pnl=replay["summary"]["net"],
            actual_final_quantity=replay["summary"]["final_quantity"],
            actual_execution=False,
            actual_total_economic_pnl=None,
        )
        encoded = canonical(payload)
        filename = scenario + "-entitlement-sidecar.json"
        immutable_write(PRIVATE / filename, encoded)
        snapshots.append(
            dict(
                scenario=scenario,
                entitled_modeled_shares=ledger.entitled_quantity(),
                gross_modeled_entitlement=receivable["gross_entitlement"],
                verified_spendable_cash_increment="0",
                dividend_tax=None,
                actual_total_economic_pnl=None,
                final_price_path_quantity=payload["actual_final_quantity"],
                private_file=filename,
                private_sha256=digest(encoded),
                source_price_path_sha256=digest(old.read_bytes()),
                price_path_promoted=False,
            )
        )
    plan = json.loads((PUBLIC / "next-price-proposal.json").read_bytes())
    result = dict(
        status="DF011_ACTION_PARTIAL_QUALIFICATION",
        protocol_commit="40636bc",
        protocol_sha256=digest((PUBLIC / "DF011_PROTOCOL.json").read_bytes()),
        corporate_action_lineage_sha256=digest(canonical(lineage)),
        exact_daily_ex_dividend_code_verified=True,
        final_cash_per_common_share="500",
        entitlement_sidecar_reconstructions=len(snapshots),
        sidecars=snapshots,
        new_qualified_strategy_replays=0,
        df010_131290_hold_preserved=True,
        full_research_eligible_events=0,
        actual_payment_day=None,
        actual_dividend_tax=None,
        actual_total_economic_pnl=None,
        previous_price_only_pnl_changed=False,
        next_price_targets=len(plan["targets"]),
        proposed_request_ceiling=plan["retry_inclusive_total_ceiling"],
        proposed_authentication_ceiling=plan["maximum_authentication"],
        new_authenticated_requests=0,
        new_kis_price_requests=0,
        new_authentication=0,
        actual_orders=0,
        actual_cancels=0,
        account_queries=0,
        live_authentication=0,
        controls="PREREGISTERED_DESIGN_ONLY",
        actual_control_selections_executed=0,
        control_boundary_sha256=digest((PUBLIC / "control-eligibility-boundary.json").read_bytes()),
        statistical_tests_executed=False,
        economic_status="ECONOMIC_EDGE_UNVERIFIED",
        live_status="LIVE_NOT_APPROVED",
        limitations=lineage["limitations"]
        + [
            "Modeled executions, not real shareholder/account balances",
            "Rejected price diagnostics are not upgraded by attaching a dividend entitlement",
            "Five expansion events need a new separately approved price scope",
        ],
    )
    atomic_json(PUBLIC / "results.json", result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "entitlement_sidecar_reconstructions",
                    "new_qualified_strategy_replays",
                    "proposed_request_ceiling",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
