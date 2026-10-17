"""Render requested aggregate reports from actual DF004 evidence; no price publication."""
# ruff: noqa: E501

import json
from decimal import Decimal as D
from pathlib import Path


def main():
    r = json.loads(Path("artifacts/df004/results.json").read_bytes())
    folder = Path("docs/implementation")
    table = {(s["symbol"], s["scenario"], s["model"]): s for s in r["summaries"]}
    symbols = ["005930", "000660", "035420", "247540", "086520", "028300"]

    def write(name, body):
        (folder / name).write_bytes(body.encode())

    write(
        "DF004_DATA_COLLECTION_AND_TIME_ALIGNMENT.md",
        f"""# DF004 데이터 수집 및 시간 정렬

기준선 `daefa1d8f6c6ec34279b1c4b7a401ffedd6c83ad`, 프로토콜 선행 원격 커밋
`{r["protocol_commit"]}`. 프로토콜과 Alpha A candidate-v1, 기존 V2·V3·DF003는 보존한다.

## 실제 접근과 저장 범위

사용자가 별도로 허용한 PAPER 읽기 전용 EWY 조회만 실행했다. 승인 한도는
2025-10-17~2026-10-16, 인증 최대2회, 총12요청, 최소3초 간격이었다.
실제 누적은 **9요청·인증2회·시세7회**, 계좌·주문·취소·LIVE 인증은 모두0회다.
실패한 요청도 예산에서 차감한다. 인증 횟수는 소진되어 추가 인증을 하지 않는다.

`dailyprice`, TR `HHDFS76240000`: AMS/MODP0 3페이지에서 기간 내 **251개** 실제 일봉을 확보했다.
최근 AMS 100행은 MODP0/1 가격 필드가 동일했다. NYS/MODP0·1은 HTTP200이나 가격 행이0개였다.
PAPER에서 조회된다는 실제 응답을 확인했으며 LIVE로 전환하지 않았다.
최초 페이지당100행이며 마지막 일자보다 하루 이전 BYMD로 이동했다.
응답이 승인 시작일 이전 행까지 포함하면 연구 입력에서는 제외한다.

공식 [KIS backtester](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/backtester/kis_backtest/providers/kis/data.py)는
동일 endpoint/TR, MODP1 adjusted 주석과 과거 일자 cursor를 사용한다.
독립적인 자체 구현만 추가했으며 공식 샘플 코드를 import/복제하지 않았다.
MODP0 비수정 해석은 MODP1 설명의 보완적 추론이다. 최근100행의 동일성은 전체 과거 조정 정책의 증명이 아니다.
이 불확실성과 정규장 가격 범위의 공급자 확인 부재를 품질 flag로 유지한다.

비인증 Stooq CSV 경로는 시세 대신 브라우저 검증 HTML을 반환했다. 이를 우회하지 않았다.
현재 발행사 NAV 자료는 기준일과 실제 과거 공표시각을 동시에 입증하지 못해 NAV 경로만 보류했다.

원시 데이터는 `data/data-first-private-df004-ewy/`, 세부 재생은
`data/data-first-private-df004-results/`에만 저장한다. 모두 Git 제외다.
기존 DataStore의 raw_path·digest·immutable_write를 활용하되 숫자 KRX 종목만 허용하는 기존
Provenance/Observation을 완화하지 않았다. 별도 ForeignBar 스키마로 EWY를 보존한다.
캐시를 재사용하고 해시가 다르면 중단한다. 연결 실패는 재시도하지 않으며 예산은 재개 후에도 누적된다.
최종 collector는 단일 실행 잠금과 atomic budget 교체를 사용한다.

**수집 감사 편차:** 최초3페이지는 정제 가격 필드 SHA256만 남아 wire-byte 해시가 아니다.
후속 보완 조회의 원응답1페이지는 private raw store에 저장됐으나 상대경로 기록 오류로 중단됐다.
최초251개 행의 연구 입력은 유지되며 이를 전체 원응답 보존으로 표현하지 않는다.
요청 시작 시각의 최소 간격은2.997382초로 승인3초보다2.618ms 짧았다.
이를 적합하다고 소급 처리하지 않았다. 최종 코드에서는 이전 응답 완료 후3.05초 대기하며,
모의 전송 시험으로 수정 경로를 확인했다. 재인증을 통한 재검사는 하지 않았다.

## 시간 정렬

tzdata2026.5의 America/New_York·Asia/Seoul과 UTC를 고정 사용한다.
공식 [NYSE core hours](https://www.nyse.com/trade/hours-calendars)와
[2025~2027 공휴일·조기종료 달력](https://s2.q4cdn.com/154085107/files/doc_news/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar-2024.pdf)을 참고했다.
정규09:30~16:00, 해당 조기종료13:00을 시간대 변환하며, 확인하지 않은 연도는 거부한다.
지원 기간의 공식 예정 세션 누락은0개다. 예기치 않은 거래소 운영 변경까지 입증한 자료는 아니다.

EWY 실제 세션 종료+60분을 **탐색용 모델 가용 시각**으로만 사용한다.
실제 수신·수집 시각2026-10-17은 변경하지 않으며 역사적 공표시각으로 대체하지 않는다.
과거 공표시각이 입증된 엄격 경로 날짜 수는 **0**이다.
각 실제 미국 세션은 최초 적격 한국08:00 의사결정에 한 번만 대응한다.
한국 휴장 중 여러 미국 세션이 누적되면 가장 최근 완료 세션만 사용한다.
미국 휴장 후 같은 신호를 반복하지 않는다. 국내 거래일은 기존 두 지수의 관측일에 근거하며
공식 KRX PIT 캘린더를 확보한 것으로 주장하지 않는다.

전 평가기간의 현금 원장은 **{r["valuation_days"]}일**, 모든 모델의 공통 매매 적격일은 **{r["common_dates"]}일**이다.
제외일: {", ".join(r["excluded_dates"])}.
2026-01-02는 일반09:00 가정에서 제외하고 운영비는 현금 원장에 남겼다.
이전 연구의223일 평가는 수정하지 않았다. 미국251개 세션을 한국217개 독립 평가일과 혼동하지 않는다.

유지 flag: {", ".join(r["quality_flags"])}.
분봉·09:05 실제 체결·NAV 공표 이력·FX/SOXX 시각 증거·분할/분배금 이력은 미확보다.
없는 가격을 생성하거나 품질 flag를 제거하지 않았다.
""",
    )
    lines = [
        "# DF004 EWY 신호 평가",
        "",
        f"판정: **{r['decision']}**. 탐색 자료에서 사전 채택 기준을 충족하지 못했다.",
        "",
        "EXPLORATORY_REAL_DATA / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED / 확인적 OOS 미실행.",
        "",
        "## 질문별 결과",
        "",
        "Q1. EWY 상승/비상승에 따른 한국장 개장 후 몸통 수익 차이는 약 +0.248%p이나, 날짜 블록 bootstrap95% 구간이 0을 포함한다.",
        "Q2. EWY와 국내지수를 함께 사용한 모델은 국내지수 단독보다 6종목 모두 순손익이 개선됐지만, 3개 1차 검정의 Holm 보정 후 유의하지 않다. 손실 감소를 양의 알파로 해석하지 않는다.",
        "Q3. H1은 BASE·STRESS 모두 현금 초과 양수 종목이 0/6이다. 비용과 평균 노출을 고려한 경제적 채택 근거가 없다.",
        "Q4. 양의 날짜별 H1 현금초과 기여 중 상위5일 비중은 약45.10%다. 종목·월 제외 결과는 results.json에 있으며 소수 상승일 집중과 6개 생존 종목 한계를 유지한다.",
        "Q5. 실제 체결 검증은 없다. 모든 매매 성과는 개장/종가 anchor, 수량 제한과 불리한 슬리피지 가정에 의존한다. 09:05 성과는 NULL이다.",
        "",
        "## 동결한 1차 검정",
        "",
        "217개 한국 날짜를 군집으로 사용했다(상승122·비상승95). 6*N 독립 표본이나 공동계좌로 해석하지 않는다.",
        "circular moving-block bootstrap: block5, B1000, seed404, centered two-sided p, family3 Holm α.05.",
        "",
        "| 항목 | 관측 차이 | 95% 구간 | p | Holm p | 통과 |",
        "|---|---:|---|---:|---:|---|",
    ]
    for name, e in zip(
        ("한국 몸통 수익률", "지수 조합−국내지수 (KRW/날짜)", "종목 조합−국내종목 (KRW/날짜)"),
        r["endpoints"],
        strict=True,
    ):
        lines.append(
            f"| {name} | {e['observed']:.6f} | [{e['ci95'][0]:.6f}, {e['ci95'][1]:.6f}] | {e['p']:.6f} | {e['adjusted_p']:.6f} | {e['reject']} |"
        )
    lines += [
        "",
        "갭 진단은 약+2.005%p로 몸통 차이보다 크다. 이는 사후 진단이며 다중 보정된 추가 1차 발견으로 승격하지 않는다. 신규 개장 매수자는 전일 종가→당일 시가 갭을 얻지 않는다.",
        "",
        "## H1 독립 Reference 손익",
        "",
        "각 Reference 초기자본1천만원, 목표25%. 원화 순운용손익에는 거래비용과 매일100원 운영비가 포함된다.",
        "",
        "| 종목 | BASE 순손익 | STRESS 순손익 | BASE MDD | BASE 평균 개장 노출 | BASE 체결수 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sy in symbols:
        b, s = table[sy, "BASE", "H1_EWY"], table[sy, "STRESS", "H1_EWY"]
        lines.append(
            f"| {sy} | {D(b['net']):,.2f} | {D(s['net']):,.2f} | {D(b['metrics']['max_drawdown']):.2%} | {D(b['average_open_exposure']):.2%} | {b['execution_count']} |"
        )
    lines += [
        "",
        "## 동일 기간 기준선 비교",
        "",
        "아래는 6개 독립 계좌의 산술평균 진단이다. 하나의 공동계좌, 동일 실위험 계좌 또는 최적 포트폴리오 성과가 아니다.",
        "",
        "| 모델 | BASE 평균 순손익 | STRESS 평균 순손익 |",
        "|---|---:|---:|",
    ]
    for model in json.loads(Path("artifacts/df004/DF004_PROTOCOL.json").read_bytes())["models"]:
        means = [
            sum((D(table[sy, sc, model]["net"]) for sy in symbols), D(0)) / 6
            for sc in ("BASE", "STRESS")
        ]
        lines.append(f"| {model} | {means[0]:,.2f} | {means[1]:,.2f} |")
    lines += [
        "",
        "## 회계·체결·불확실성",
        "",
        "BASE fee3bp/sell tax20bp/slippage5bp, STRESS10/30/20은 연구 시나리오이며 실제 계약 요율이 아니다. 운영비100원/일, 현금 이자0, 배당·총수익 추정 없음.",
        "기존 ReferencePortfolio의 현금·lot·수수료·슬리피지·expiry를 그대로 재사용했다. 전일 종가 NAV로 수량을 정하고 매수limit=전일종가×1.05, 사전 수량한도=전일거래량×0.001을 사용한다.",
        "신규 매수 anchor는09:00:01, 1분 expiry. 청산 의사결정15:19, limit=전일종가×0.70, anchor15:30:01, expiry15:31이다. 일봉 기반 가정이며 실제 호가·경매 체결 보장이 아니다.",
        "T/T+1 매도대금 재사용 금지, 잔여 청산 실패는 신규진입 차단과 HOLD, 종료시 강제 유리한 체결 없음. 과거 보유분 갭 PnL은 신규 몸통 PnL과 분리한다.",
        "gross_before_slippage−slippage−commission−tax−operating_cost=net을 독립 Decimal 검사로 확인했다. 기본 metrics.gross_pnl은 슬리피지 반영 후 값이므로 총비용 전 gross와 구분한다.",
        "96개 요약의 gross·commission·tax·slippage·운영비·net·현금초과·회전율·MDD·최악일·무거래일·노출·잔고 및36개 기준선 비교는 artifacts/df004/results.json에서 확인할 수 있다.",
        "노출정합 값은 common=min(평균노출) 기반 POSTHOC_DIAGNOSTIC이며 실제 거래 가능 손익, 동일 전체 위험 또는 배분 입력으로 쓰지 않는다.",
        "미래 미국 같은날 종가를 연결한 잘못된 날짜 매핑은 모두 거부한다. 한 실제 미국 세션 지연 placebo, 국내 전일 정보 대조군, STRESS, prior20 지수 레짐, 종목/월 제외 진단을 함께 보존한다.",
        "Signal ID는 해당 시점의 국소 증거를 사용해 미래 입력의 추가/수정에 영향받지 않는다. 원자료 수정은 별도 재생으로 남겨 기존 산출물을 덮어쓰지 않는다.",
        "시가-only 성과는 ASSUMED_OPEN_EXECUTION_EXPLORATORY_NOT_OBSERVED_TICKS이다. 공표·정규장 범위·기업행위 검증 부족과 기존 한국 생존표본 편향이 있어 확인적 결론 또는 G1/G2/G3/OOS PASS로 승격할 수 없다.",
        "NAV 경로는 NAV_PUBLICATION_UNVERIFIED이며 가격-only 평가와 독립이다. NAV·FX·SOXX·09:05 미확보 값은 NULL로 남겼다.",
        "",
    ]
    write("DF004_EWY_SIGNAL_EVALUATION.md", "\n".join(lines))
    write(
        "DF004_CLOSURE_REPORT.md",
        f"""# DF004 종료 보고서

연구 판정은 **{r["decision"]}**다. EWY를 Alpha A에 편입하지 않는다.
기술 준비, 데이터 적격성, 경제성, LIVE 승인을 분리한다.

| 구분 | 실제 상태 |
|---|---|
| 기술 | 별도 ForeignBar·인과 매핑·96 Reference·독립 회계 검사 구현 |
| 데이터 | EWY251세션·공통 KR217일 확보, 엄격 공표시각0일; 일부 provenance 미확인 |
| 경제성 | 탐색 채택 근거 불충족; ECONOMIC_EDGE_UNVERIFIED |
| 실전 | LIVE_NOT_APPROVED; 실계좌·주문·취소·배포·병합0회 |

프로토콜 원격 커밋 `{r["protocol_commit"]}`는 공급원 응답/결과 확인 전에 별도로 push했다.
354개 기준 시험을 먼저 확인했으며 기존 V2 72·V3 90·DF003 216개 결과와 preflight에서 고정한
원본 파일을 변경하지 않았다. 허용한 기존 파일 변경은 README·CI·검증 스크립트·의존성뿐이다.

최종 로컬 검증은 `artifacts/df004/checks.json`와 JUnit·각 stdout/stderr에 기록한다.
기존354개 + 신규32개 = **386 PASS**를 실제 최종 검증했다.
Ruff·format·mypy·build, OMS/Alpha/joint 재생, 이전 V2/V3/DF003 독립 회계와 신규96개 회계를 실행한다.
비공개 경로는 Git 제외하고 키 값을 출력하지 않은 정확 문자열 유출 검사를 수행한다.

수집 한도9/12요청·인증2/2는 지켰다. 원응답 보존1페이지/가격 필드 해시3페이지,
초기 요청간격 최대2.618ms 미달 및 후속 경로 기록 오류를 숨기지 않았다.
최종 코드의 응답후3.05초 대기·캐시·누적 예산·단일 실행 잠금을 오프라인 시험했다.
수정 뒤 실제 인증 재검사는 하지 않았다. 데이터 적격성 완전 통과로 표현하지 않는다.

최초 실행 source hash는 implementation-contract.json에 보존한다. 종료 시 실행 스크립트의
문자열 줄바꿈 및 기존 계약 재실행 가드만 추가했으며, preservation-audit.json은 이를 제거한
소스의 원래 SHA와 AST 동등성을 확인한다. 연구 엔진 바이트는 최초 실행 이후 변경하지 않았다.

최종 브랜치 `codex/df004-ewy-leadlag`를 정상 push하고 정확한 원격 HEAD의 Python3.11/3.12
GitHub Actions 결과를 확인한다. 원격 결과 확인 전 CI PASS를 주장하지 않는다.
최종 SHA의 CI 증거는 순환 커밋을 피하기 위해 Git 제외 `data/data-first-final/df004/remote-ci.json`에 남긴다.

세부 근거: [데이터·정렬](DF004_DATA_COLLECTION_AND_TIME_ALIGNMENT.md),
[신호·경제성 평가](DF004_EWY_SIGNAL_EVALUATION.md), `artifacts/df004/results.json`.
""",
    )


if __name__ == "__main__":
    main()
