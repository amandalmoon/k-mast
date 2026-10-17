"""DF007 source-only census and independent exposure accounting; no network or OMS."""

import json
import re
from collections import defaultdict
from decimal import Decimal as D
from hashlib import sha256
from typing import Any, Literal


def read_census_page(
    raw: bytes, expected_sha256: str, begin: str, end: str, page: int
) -> dict[str, Any]:
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("RAW_PAGE_HASH_CONFLICT")
    body: dict[str, Any] = json.loads(raw)
    if body.get("status") != "000" or int(body["page_no"]) != page:
        raise ValueError("PAGE_METADATA_CONFLICT")
    for row in body["list"]:
        if not begin <= row["rcept_dt"] <= end or not receipt_ok(row):
            raise ValueError("RECEIPT_OUTSIDE_SCOPE_OR_INVALID")
    return body


def classify_title(title: str) -> tuple[str, str]:
    text = "".join(title.split())
    markers = re.findall(r"\[([^\]]+)\]", text)
    kind = (
        "CANCEL"
        if any("철회" in m or "취소" in m for m in markers)
        else "CORRECTION"
        if any("정정" in m for m in markers)
        else "ATTACHMENT"
        if "첨부추가" in markers
        else "EXTENSION"
        if "연장결정" in markers
        else "ORIGINAL"
        if not markers
        else "OTHER_REVISION"
    )
    base = re.sub(r"^\[[^\]]+\]", "", text)
    while base.startswith("["):
        base = re.sub(r"^\[[^\]]+\]", "", base)
    exact = {
        "D1": ("자기주식취득결정",),
        "D2": ("자기주식취득신탁계약체결결정",),
        "DISPOSAL": ("자기주식처분결정",),
        "TRUST_TERMINATION": ("자기주식취득신탁계약해지결정",),
        "TRUST_AMENDMENT": ("자기주식취득신탁계약변경결정",),
        "TRUST_EXTENSION": ("자기주식취득신탁계약연장결정",),
        "RETIREMENT": ("주식소각결정", "자기주식소각결정"),
    }
    for family, names in exact.items():
        if base in set(names) | {"주요사항보고서(" + n + ")" for n in names}:
            if "연장결정" in markers and family == "D2":
                return "TRUST_EXTENSION", kind
            return family, kind
    if (
        "자기주식" in base
        and any(v in base for v in ("결과", "완료", "보고서"))
        and "결정" not in base
    ):
        return "ACTUAL_ACQUISITION_OR_COMPLETION", kind
    return ("AMBIGUOUS_SELF_STOCK" if "자기주식" in base else "OTHER"), kind


def receipt_ok(row: dict[str, Any]) -> bool:
    return bool(
        re.fullmatch(r"[0-9]{14}", row.get("rcept_no", ""))
        and re.fullmatch(r"[0-9]{8}", row.get("corp_code", ""))
        and re.fullmatch(r"[0-9]{8}", row.get("rcept_dt", ""))
    )


def register_source_receipt(
    registry: dict[str, dict[str, Any]], row: dict[str, Any]
) -> Literal["NEW", "DUPLICATE", "CONFLICT"]:
    if not receipt_ok(row):
        raise ValueError("INVALID_RECEIPT_IDENTITY")
    receipt = row["rcept_no"]
    if receipt in registry:
        return "DUPLICATE" if registry[receipt] == row else "CONFLICT"
    registry[receipt] = row
    return "NEW"


def identity_flags(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    corp_codes: dict[str, set[str]] = defaultdict(set)
    code_corps: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        code = row.get("stock_code", "")
        if re.fullmatch(r"[0-9]{6}", code):
            corp_codes[row["corp_code"]].add(code)
            code_corps[code].add(row["corp_code"])
    result = {}
    for row in rows:
        flags = ["HISTORICAL_LISTING_STATUS_UNKNOWN", "PIT_CODE_HISTORY_UNVERIFIED"]
        code = row.get("stock_code", "")
        if not re.fullmatch(r"[0-9]{6}", code):
            flags.append("MISSING_OR_AMBIGUOUS_STOCK_CODE")
        if row.get("corp_cls") not in {"Y", "K"}:
            flags.append("NOT_SOURCE_KOSPI_KOSDAQ_LABEL")
        if len(corp_codes[row["corp_code"]]) > 1:
            flags.append("CORPORATION_MULTIPLE_SOURCE_CODES")
        if len(code_corps[code]) > 1:
            flags.append("SOURCE_CODE_MULTIPLE_CORPORATIONS")
        result[row["rcept_no"]] = flags
    return result


def audit_exposure(replay: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct actual model cash/quantity, not a target-weight proxy."""
    capital = D(replay["summary"]["capital"])
    cash, quantity = capital, 0
    path = []
    buy_count = 0
    initial = None
    for signal, day in zip(replay["signals"], replay["daily"], strict=True):
        assert signal["day"] == day["day"]
        before_qty, before_cash = quantity, cash
        pre_nav = cash + quantity * D(day["prior_close"])
        for execution in signal["executions"]:
            qty, price, fee = execution[3], D(execution[4]), D(execution[5])
            cash -= qty * price + fee
            quantity += qty
            if qty > 0:
                buy_count += 1
                if initial is None:
                    order = next(o for o in signal["orders"] if o["side"] == "BUY")
                    target = D(signal["target"])
                    limit = D(order["limit"])
                    expected = int(target * pre_nav / limit)
                    assert order["quantity"] == expected
                    assert qty <= expected and target <= D(".25")
                    mark = D(day["open"])
                    immediate_nav = cash + quantity * mark
                    initial = dict(
                        target=str(target),
                        pretrade_nav=str(pre_nav),
                        limit=str(limit),
                        submitted_quantity=expected,
                        filled_quantity=qty,
                        fill_price=str(price),
                        opening_mark=str(mark),
                        fee=str(fee),
                        postfill_cash=str(cash),
                        postfill_nav=str(immediate_nav),
                        postfill_weight=str(quantity * mark / immediate_nav),
                        postfill_cost_basis_weight=str(
                            quantity * price / (cash + quantity * price)
                        ),
                        decision_at=signal["decision_at"],
                        fill_at=execution[1],
                    )
        cash -= 100
        assert cash == D(day["cash"]) and quantity == day["quantity"]
        nav = cash + quantity * D(day["close"])
        assert nav == D(day["nav"])
        weight = quantity * D(day["close"]) / nav
        assert weight == D(day["exposure"])
        path.append(
            dict(
                day=day["day"],
                quantity=quantity,
                cash=str(cash),
                nav=str(nav),
                weight=str(weight),
                close=str(day["close"]),
                prior_quantity=before_qty,
                prior_cash=str(before_cash),
                buys=sum(e[3] for e in signal["executions"] if e[3] > 0),
                above_research_reference=weight > D(".25"),
                submitted=signal["submitted"],
                reduction_requested=signal["risk_reduction_requested"],
                reduction_filled=signal["risk_reduction_filled"],
                residual_hold=signal["reduction_unfulfilled"],
            )
        )
    assert initial is not None
    assert cash + quantity * D(replay["daily"][-1]["close"]) - capital == D(
        replay["summary"]["net"]
    )
    exceeded = [p for p in path if p["above_research_reference"]]
    return dict(
        initial=initial,
        daily_path=path,
        buy_execution_count=buy_count,
        max_close_weight=str(max(D(p["weight"]) for p in path)),
        above_reference_days=len(exceeded),
        above_reference_without_additional_buy=all(p["buys"] == 0 for p in exceeded),
        price_drift_with_constant_quantity=bool(exceeded)
        and len({p["quantity"] for p in exceeded}) == 1,
        initial_order_target_compliant=D(initial["target"]) <= D(".25")
        and D(initial["postfill_weight"]) <= D(".25"),
        final_quantity=quantity,
        unfulfilled_reduction_days=sum(p["residual_hold"] for p in path),
        pnl_unchanged=True,
    )
