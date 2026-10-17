"""Render only public aggregate evidence into the requested repository Markdown report."""

import json
from decimal import Decimal as D
from pathlib import Path


def money(v):
    return f"{D(v):,.2f}"


def pct(v):
    return f"{D(v) * 100:.3f}"


def main():
    root = Path(__file__).resolve().parents[1]
    r = json.loads((root / "artifacts/df002/results.json").read_bytes())
    lines = [
        "<!-- DF002_GENERATED_TABLES -->",
        "",
        "### BASE 6종목 × 5모형",
        "",
        "|종목|모형|순손익|수익률/TWR|평균 주식비중|최대 주식비중|종가 MDD|실제 보유일|체결|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in r["summaries"]:
        if s["scenario"].startswith("BASE"):
            lines.append(
                f"|{s['symbol']}|{s['mode']}|{money(s['project_net'])}|{pct(s['total_return'])}|{pct(s['average_close_exposure'])}|{pct(s['maximum_close_exposure'])}|{pct(s['mdd'])}|{s['actual_holding_days']}|{s['executions']}|"
            )
    lines += [
        "",
        "### Alpha A 비용 민감도",
        "",
        "|종목|시나리오|순손익|수수료|세금|내재 슬리피지|운영비|회전율|체결|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in r["summaries"]:
        if s["mode"] == "ALPHA_A":
            lines.append(
                f"|{s['symbol']}|{s['scenario'].split('_')[0]}|{money(s['project_net'])}|{money(s['commission'])}|{money(s['tax'])}|{money(s['embedded_slippage'])}|{money(s['operating_cost'])}|{D(s['turnover']):.4f}|{s['executions']}|"
            )
    lines += [
        "",
        "### BASE 청산 이유별 비용 후 기여",
        "",
        "|종목|청산 이유|FIFO 매칭 수|비용 후 실현 기여(운영비 전)|",
        "|---|---|---:|---:|",
    ]
    for s in r["summaries"]:
        if s["mode"] == "ALPHA_A" and s["scenario"].startswith("BASE"):
            for reason, bucket in s["exit_contributions"].items():
                lines.append(
                    f"|{s['symbol']}|{reason}|{bucket['fifo_matches']}|{money(bucket['net'])}|"
                )
    lines += ["", "실현/미실현·자본 점유율·평균 현금·업종 미검증 태그는 공개 JSON에 보존한다.", ""]
    path = root / "docs/implementation/DF002_ALPHA_PROFIT_ATTRIBUTION.md"
    initial = path.read_text(encoding="utf-8").split("<!-- DF002_GENERATED_TABLES -->")[0]
    path.write_bytes((initial + "\n" + "\n".join(lines)).encode())


if __name__ == "__main__":
    main()
