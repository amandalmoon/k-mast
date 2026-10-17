"""Render requested repository Markdown tables from public aggregates only."""

import json
from decimal import Decimal as D
from pathlib import Path


def money(v):
    return f"{D(v):,.2f}"


def percent(v):
    return f"{D(v) * 100:.3f}"


def main():
    root = Path(__file__).resolve().parents[1]
    r = json.loads((root / "artifacts/df003/results.json").read_bytes())
    base = [s for s in r["summaries"] if s["scenario"].startswith("BASE")]
    lines = [
        "<!-- DF003_GENERATED_TABLES -->",
        "",
        "## BASE A 후보: 노출·위험·비용",
        "",
        (
            "금액은 원, 평균 비중·MDD는 %, 회전율은 매수+매도 금액/초기자본이다. "
            "후보 ID 순서이며 수익 순위가 아니다."
        ),
        "",
        "|종목|후보|순손익|평균 주식비중|MDD|보유일|체결|명시 비용|회전율|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in base:
        if s["candidate"].startswith("A"):
            lines.append(
                f"|{s['symbol']}|{s['candidate']}|{money(s['project_net'])}|{percent(s['average_close_exposure'])}|{percent(s['mdd'])}|{s['actual_holding_days']}|{s['executions']}|{money(s['explicit_cost'])}|{D(s['turnover']):.4f}|"
            )
    lines += [
        "",
        "## 같은 청산·비중의 진입 대조",
        "",
        (
            "마지막 열은 사후 노출 정합 현금 대비 손익 차이다. "
            "실제 계좌 손익이나 동일 전체 위험 성과가 아니다."
        ),
        "",
        "|종목|쌍|A 순손익|T 순손익|A−T|POSTHOC_DIAGNOSTIC 차이|",
        "|---|---|---:|---:|---:|---:|",
    ]

    def lookup(symbol, scenario, candidate):
        return next(
            s
            for s in r["summaries"]
            if (s["symbol"], s["scenario"], s["candidate"]) == (symbol, scenario, candidate)
        )

    for p in r["comparisons"]:
        if p["scenario"].startswith("BASE") and p["type"] == "ENTRY_ONLY_MODEL_CONTROL":
            a, b = (
                lookup(p["symbol"], p["scenario"], p["a"]),
                lookup(p["symbol"], p["scenario"], p["b"]),
            )
            c = p["exposure_control"]
            delta = (
                money(D(c["a_cash_excess_scaled"]) - D(c["b_cash_excess_scaled"]))
                if c["a_cash_excess_scaled"] is not None and c["b_cash_excess_scaled"] is not None
                else "NULL"
            )
            lines.append(
                f"|{p['symbol']}|{p['a']}/{p['b']}|{money(a['project_net'])}|{money(b['project_net'])}|{money(p['net_delta'])}|{delta}|"
            )
    lines += [
        "",
        "## 비용·부분체결 민감도",
        "",
        "|종목|후보|BASE|STRESS|PARTIAL|PARTIAL 최종 감축 상태|",
        "|---|---|---:|---:|---:|---|",
    ]
    for s in base:
        if s["candidate"].startswith("A"):
            stress = lookup(s["symbol"], "STRESS_10FEE_30TAX_20SLIP_100OPEX", s["candidate"])
            partial = lookup(s["symbol"], "PARTIAL_HALF_FILL", s["candidate"])
            lines.append(
                f"|{s['symbol']}|{s['candidate']}|{money(s['project_net'])}|{money(stress['project_net'])}|{money(partial['project_net'])}|{partial['execution_safety']['status']}|"
            )
    lines += [
        "",
        "## BASE 기존 기준선",
        "",
        "|종목|기준선|순손익|평균 주식비중|MDD|실제 보유일|",
        "|---|---|---:|---:|---:|---:|",
    ]
    for s in base:
        if s["candidate"] in ("CASH", "BUY_HOLD", "HOLD_25", "TREND_25"):
            lines.append(
                f"|{s['symbol']}|{s['candidate']}|{money(s['project_net'])}|{percent(s['average_close_exposure'])}|{percent(s['mdd'])}|{s['actual_holding_days']}|"
            )
    lines += [
        "",
        "## BASE 후보의 청산 기여",
        "",
        (
            "진입·청산 명시 비용을 배분한 실현 손익이며 운영비 전이다. "
            "FIFO 매칭 수는 독립 왕복거래 수와 같지 않다."
        ),
        "",
        "|종목|후보|청산 이유|FIFO 수|비용 후 실현 기여|",
        "|---|---|---|---:|---:|",
    ]
    for s in base:
        if s["candidate"].startswith("A"):
            for reason, b in s["exit_contributions"].items():
                lines.append(
                    f"|{s['symbol']}|{s['candidate']}|{reason}|{b['fifo_matches']}|{money(b['net'])}|"
                )
    lines += [
        "",
        (
            "모든 보유기간 bucket·매수/매도 금액·실현/미실현·변동성·베타·최악 종가일은 "
            "공개 results.json에 있다."
        ),
        "",
    ]
    path = root / "docs/implementation/DF003_ALPHA_ABLATION_REPORT.md"
    initial = path.read_text(encoding="utf-8").split("<!-- DF003_GENERATED_TABLES -->")[0]
    path.write_bytes((initial + "\n" + "\n".join(lines)).encode())


if __name__ == "__main__":
    main()
