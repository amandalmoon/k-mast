"""Render requested DF005 reports from actual aggregate evidence."""
# ruff: noqa: E501

import json
from decimal import Decimal as D
from pathlib import Path


def main():
    proof = Path("artifacts/df005")
    r = json.loads((proof / "results.json").read_bytes())
    a = json.loads((proof / "collection-and-preservation-audit.json").read_bytes())
    folder = Path("docs/implementation")

    def write(name, text):
        (folder / name).write_bytes(text.encode())

    write(
        "DF005_DATA_PANEL_AND_LINEAGE.md",
        f"""# DF005 국내 과거 패널·계보

## 확보한 범위

기존6종목·2025-2026 탐색표본을 재사용하지 않고 새50종목을 검토했다.
2022-09-01~2025-10-16의 약3년 가격+워밍업 수집에서 실제 관측이 있는 종목은 **{a["stocks_with_observations"]}개**다.
원주가 **{a["unique_stock_raw_rows"]:,}행**, 수정주가 **{a["unique_stock_adjusted_rows"]:,}행**,
KOSPI·KOSDAQ 지수 **{a["unique_index_rows"]:,}행**을 확보했다. 지수는 각각761개 관측일이다.
현재 마스터에서 고정한494120은 승인 기간 가격을 반환하지 않았으며 사후 교체하지 않았다.
개별 종목의 실제 시작/종료·행수는 공개 `collection-and-preservation-audit.json`에 기록했다.

프로토콜은 `342ddff2c811b20fbcad39dd85384a1787b25ce1`로 먼저 원격 push했다.
시장별25개는 이전부터 보관한2026-10-17 마스터의 ST그룹·6자리·끝자리0 종목 중 기존6개를
제외하고 SHA256('DF005_V1:'+symbol) 순위로 정했다. ETF가 섞인 전체 숫자 코드를 쓰지 않았다.
이 규칙도 현재 생존주식 휴리스틱이며 당시 적격 보통주/PIT 표본의 증명이 아니다.
가격이나 사후 손익으로 종목을 선정·교체하지 않았다. 각 시장 첫15개/뒤10개의 기술/검증 분리도 사전 고정했다.

## 실제 API와 신뢰성

사용자의 별도 PAPER 읽기 전용 승인으로 국내 일봉 `inquire-daily-itemchartprice`/`FHKST03010100`,
지수 일봉 `inquire-daily-indexchartprice`/`FHKUP03500100`만 호출했다.
공식 [국내 일봉 예제](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py)는
한번에 최대100건과 수정0/원주가1을 안내한다. 실제 응답을 통해 과거 구간 제공을 확인한 뒤 확대했다.
공식 샘플은 참고 자료로만 보관하고 실행/import/재배포하지 않았다.

실제 **803/900요청·인증1/2회**, 시세802응답이다. 계좌·주문·취소·LIVE 인증0회다.
첫 과거/최근10개 조회는 모두 비어 있지 않았으며 인증 포함11요청으로 확인했다.
원래 DF004 인증 예산을 재사용하지 않았다. 추가 인증·정정 재조회는 실행하지 않았다.
802개 시세 응답 모두 wire bytes와 SHA256을 보존했다. 인증 응답은 민감하므로 hash·길이·상태만
남기고 원문/토큰을 저장하지 않았다. 비밀/계좌 필드를 포함한 응답도 원문 비저장+hash/사유로 처리한다.
실제 이번 수집의 시세 원문 보류 건은0이다. 실패 HTTP·비밀 응답·중단 후 소진 요청 보존은 모의 전송으로 시험했다.

응답 수신→다음 요청 시작의 실제 최소 간격은 **{a["minimum_response_complete_to_request_seconds"]}초**다.
응답 완료 후3.05초를 wall/monotonic clock으로 확인하고 누적 예산은 전송 전에 atomic write한다.
Windows/Linux OS 잠금은 중복 실행을 막고 프로세스 종료 시 해제되어 안전 재개가 가능하다.
기본 네트워크는 OFF이며 명시적 승인 실행 인자가 필요하다. PAPER 환경·종목·기간·두 경로/TR을 검증한다.
실패를 예산에서 지우지 않고 자동 예산 갱신·LIVE fallback·무제한 재시도는 없다.

wire SHA→정제 canonical SHA→Provenance→dataset→개별 정규화 레코드 hash를 연결했다.
총 페이지 행수 {a["normalized_page_rows"]:,}에는 사전 조회와 전체조회가 중복될 수 있으므로
경제 필드가 같은 종목/날짜/가격기준만 중복 제거했다. 서로 다른 정정은 덮어쓰지 않고 HOLD한다.
실제 수신/수집 시각을 과거 공표시각으로 바꾸지 않았다. SESSION_UNVERIFIED와 지수 공표 flag도 유지한다.

원시 시세·상세 거래·입력 snapshot은 Git 제외 `data/data-first-private-df005-*`에만 보관한다.
기존 DataStore 정규화/검증과 immutable write를 재사용했다. 원래 network/replay/OMS/Risk/Ledger는 변경하지 않았다.

## 적격성·누락

지수 관측일에 맞는200일 이상 평가와21일 워밍업, 원/수정 가격·거래량·거래대금·완료 상태를 검사한다.
IPO/누락, 정지 의심 또는 필요한 수치0, 기업행위 계보가 없는 비상수 조정계수는 종목-연간 구간 전체를 보류한다.
일부 불리한 날짜만 제거하거나 시세를 합성하지 않았다.

150개 목표 구간 중 최종 **{r["references"] // 15}개**가 적격이고 **{len(r["exclusions"])}개**가 보류다.
후보3·기준선2 × 비용3 = 구간별15개로 최종 **{r["references"]:,}개 독립 Reference**를 평가한다.
잠정 V2의0.001 계수 허용 오차는 사전 프로토콜의 엄격한 비상수 보류 규칙보다 느슨했다.
최종 V3에서0 기준으로 수정하고9구간/135개 잠정 Reference를 제외했다. 수익을 보기 전 입력 계수만으로 고정했으며
잠정 결과·실행 소스도 보존했다. 동일 입력·동일 실행 함수 AST·기존 코드 hash를 확인한 유효 결과만 재사용했다.

거래정지 event/PIT 상폐·종목군·공표시각·정확한 기업행위 원장·과거 업종은 확보하지 못했다.
0거래량이나 차트 공백을 공식 거래정지 사유로 단정하지 않는다. 수정주가는 체결가격으로 쓰지 않는다.
미수정/수정계수 일정은 해당 구간에 알려진 변화가 없다는 진단일 뿐 기업행위 완전성의 증명이 아니다.
업종 주도권·업종별 기여·폭넓은 반도체 제외 검증은 NULL이다. 원래 삼성전자/하이닉스가 제외됐다는 사실과
새50종목이 모두 비반도체라는 주장은 다르다.

수능·연초 지연개장6일은 사전 `session-eligibility-v1.json`의 공식 거래소/증권사 공지에 근거해
09:00 실행과 적격 보유 세션 집계에서 제외했다. 가격·mark는 보존한다.
파생 함수 namespace에 명시한 신규 적격성 버전을 사용하며 원래 모듈 global/함수를 변경하지 않았다.
완전한 거래소 PIT/정지 캘린더를 확보했다고 주장하지 않는다.
""",
    )
    lines = [
        "# DF005 Alpha 독립성·경제성 평가",
        "",
        "A0·A1·T 판정은 모두 **EXPLORATORY_ONLY**다. 현재 생존 종목 선택·과거 공표/업종/기업행위/체결 한계 때문에 확인적 OOS 또는 독립 경제성 승인으로 승격하지 않는다.",
        "A1 교체 근거는 재현되지 않았다. 잠금16종목에서 A1−A0 연간10만원 이상 개선은 BASE·STRESS 모두3개, MDD·ES 모두 악화 없음은4개·5개다. 세 1차 Holm p는 모두1이다.",
        "",
        f"원래6개를 제외한 {len({s['symbol'] for s in r['summaries']})}개 종목의 {r['references'] // 15}개 적격 연간 구간에서 {r['references']:,}개 Reference를 계산했다. 잠금 종목 중 마지막 연간 구간에 적격인 {len(r['validation_symbols'])}개, 공통 {r['validation_distinct_dates']}거래일을 날짜 군집 검정에 사용했다.",
        "",
        "## 기간·비용별 실제 결과",
        "",
        "각 Reference의 초기자본1천만원, 운영비100원/일, 현금 이자0이다. 아래 평균은 독립 계좌 산술평균 진단이며 공동계좌 손익이 아니다. 목표 상한은 A0/A1/T .25이며 BUY_HOLD는 원래 거의 전액 참고선으로 위험 정합 대상이 아니다.",
        "",
        "| 구간 | 비용 | 모델 | 종목수 | 평균 순운용손익 | 현금초과 양수 | 최악 Reference MDD | 평균 ES5 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for g in r["groups"]:
        if g["scenario"] == "PARTIAL" or g["model"] in {"CASH", "BUY_HOLD"}:
            continue
        lines.append(
            f"| W{g['window']} | {g['scenario']} | {g['model']} | {g['references']} | {D(g['mean_independent_net']):,.2f} | {g['positive_cash_excess']}/{g['references']} | {D(g['worst_reference_mdd']):.2%} | {D(g['mean_ES5']):.2%} |"
        )
    lines += [
        "",
        "W1=2022-10-17~2023-10-16, W2=2023-10-17~2024-10-16, W3=2024-10-17~2025-10-16. 원래2025-2026 표본과 겹치지 않지만 현재 마스터를 이용했으므로 생존편향이 남는다.",
        "",
        "## 잠금 검증 구간의 증분·위험",
        "",
        "| 비용 | 적격 종목 | A1−A0 ≥10만원 | A1−T ≥10만원 | A1 MDD·ES 모두 악화 없음 | 관측 노출·변동성 근접 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sc, c in r["validation_criteria"].items():
        lines.append(
            f"| {sc} | {c['references']} | {c['A1_increment_100000_over_A0']} | {c['A1_increment_100000_over_T']} | {c['A1_risk_no_worse']} | {c['observed_exposure_volatility_matched']} |"
        )
    lines += [
        "",
        "최소 경제적 차이는 연간 Reference당10만원(초기자본1%)으로 사전 동결했다. A1은 A0/T 대비 각각60% 이상에서 이를 재현하고, BASE·STRESS 모두80% 이상에서 MDD·ES가 악화되지 않아야 한다.",
        "평균 노출 차이2%p 이내·NAV 변동성비0.9~1.1은 관측 진단이며 전체 위험 정합 전략의 구현이 아니다. 사후 노출 비례 계산은 POSTHOC_DIAGNOSTIC이며 배분에 쓰지 않는다.",
        "",
        "## 날짜 군집 검정",
        "",
        "최종 연간·잠금 종목의 같은 날짜별 Reference 차이를 평균한 뒤20거래일 circular block, B2000, seed505를 적용했다. 3개 1차 검정 Holm α.05, centered two-sided p와95% 구간이다. 종목×날짜를 독립 시장 실험으로 부풀리지 않는다.",
        "",
        "| 1차 항목 | 날짜당 평균 차이(KRW) | 95% 구간 | Holm p | 기각 |",
        "|---|---:|---|---:|---|",
    ]
    for e in r["primary_endpoints"]:
        lines.append(
            f"| {e['name']} | {e['observed']:,.2f} | [{e['ci95'][0]:,.2f}, {e['ci95'][1]:,.2f}] | {e['holm_p']:.6f} | {e['reject']} |"
        )
    lines += [
        "",
        "유의성만으로 생존편향·실제 체결·과거 공표 검증을 대체하지 않는다. 종목/월 제외와 상위5일·종목 기여 집중도는 results.json에 보존했다.",
        "검증 구간의 KOSPI 약세 관측은18일로 사전 최소30일에 못 미쳤다(KOSDAQ 약세42일). 따라서 서로 다른 국면을 충분히 확보한 독립 검증이라고도 할 수 없다.",
        "",
        "## 국면·비용·실행 해석",
        "",
        "국면은 전일까지 관측 가능한 지수20일 수익률(±5%), 연율화20일 변동성(≥25%/≤15%), 종목5일/20일 거래대금 비율(<0.5)로 정의했다. 과거 업종 정보가 없으므로 업종 교체 국면은 NULL이다.",
        "종목·연간·비용·모델별 국면 진단에 순손익·현금초과·관측 노출·자본점유·ES·최악일·실제 연속 NAV의 국면 중 관측 최대낙폭·회전율·수수료/세금/슬리피지·체결수·위험감축 미이행을 기록했다. 이는 해당 국면에서 계좌를 재시작하거나 그 국면만 거래한 전략이 아니다.",
        "BASE는 fee3bp/tax20bp/slip5bp, STRESS10/30/20, PARTIAL 기본비용·가상 절반체결이다. 실제 과거 세율·계약 요율을 인증한 값은 아니다. 비용 단일 계상과 현금/수량/NAV를 독립 검사한다.",
        "A0/A1/T의 신호·stop·절대 target·현금·한도·lot·만료는 동결 경로를 재사용했다. 09:00+1초 anchor는 실제 개장 경매 체결 증거가 아니며 공급자 수신시각을 과거 가용시각으로 위장하지 않는다.",
        "PARTIAL의1주 잔존·target0 청산 실패는 RISK_REDUCTION_HOLD로 남긴다. 잔여 수량을 자동 성공 체결로 만들거나 종료 손익을 개선하지 않았다. 개별 stop 손익·보유기간·미이행은 독립 요약에 있다.",
        "BUY_HOLD는 원래 거의 전액 보유 참고선이므로 .25 후보와 같은 전체 위험으로 비교하지 않는다. 프로토콜의 포괄적 cap 문구와 동결 참고선 사이의 모호성을 별도 실행 후속 문서에 명시했다.",
        "",
        "## 전략 조치",
        "",
        "A0는 검증 기준선으로 유지하되 실전 배분은0이다. A1은 기존5/6 결과만으로 A0를 교체하지 않으며, 새로운 구간의 증분·위험·비용 재현성을 이 표와 함께 판단한다. T는 동결 대조군으로 유지한다. A2/A3/EWY H1은 재최적화하지 않았다.",
        "INDEPENDENT_EVIDENCE_SUPPORTED는 부여하지 않는다. 현재 필요한 것은 더 많은 지표 탐색이 아니라 PIT/상폐/정지/기업행위 계보와 실제 실행 증거, 독립 구간에서 고정 위험 조건의 재현이다.",
        "",
    ]
    write("DF005_ALPHA_VALIDATION.md", "\n".join(lines))
    write(
        "DF005_CLOSURE_REPORT.md",
        f"""# DF005 종료 보고서

## 필수 질문에 대한 답

1. **확대 범위:** 새50종목 검토, 실제{a["stocks_with_observations"]}종목. 약3년 평가와 워밍업 구간의 원/수정주가 각각{a["unique_stock_raw_rows"]:,}행, 지수{a["unique_index_rows"]:,}행이다. 적격 {len({s["symbol"] for s in r["summaries"]})}종목·{r["references"] // 15}연간 구간·{r["references"]:,} Reference를 계산했다.
2. **PIT·상폐·정지·기업행위:** 현재 마스터와 실제 가격/0거래량/조정계수 진단까지 확인했다. 과거 종목군·상폐/정지 사건·정확한 기업행위 원장·PIT 업종은 미확보다. 이로 인한 구간 보류를 사후 종목 교체나 합성값으로 보충하지 않았다.
3. **기존 반도체 표본 밖의 비용 후 결과:** BASE 평균 독립 Reference 순손익은 W1 A0−47,552원/A1−100,344원, W2−29,676원/−12,396원, W3+2,794원/+24,294원이다. 마지막 구간의 일부 양수 결과가 세 구간 전체의 반복 가능한 양의 경제성을 입증하지 않는다. 원래6개는 제외됐지만 과거 업종이 미확인이라 '시장 전체/비반도체 전체' 재현으로 일반화하지 않는다.
4. **위험 고려:** 잠금16종목에서 A1의10만원 이상 A0 개선은 BASE·STRESS 모두3/16, MDD·ES 모두 악화 없음은4/16·5/16이다. 사전60%·80% 기준에 못 미친다. 관측 노출·변동성 근접도6/16·7/16뿐이며 전체 위험 정합 전략으로 승인하지 않는다. Holm p는 세 항목 모두1이다.
5. **남은 장애:** PIT/상폐/정지·기업행위/정정 이력·과거 공표·정확한 전체 캘린더·업종·실제 장중 체결/호가·실제 비용 검증, 동일 위험을 구현한 후속 독립 확인이 필요하다. 단순 개장가 모형을 실전 체결로 인증하지 않는다.
6. **전략 조치:** A0 기준선 유지, A1 교체·LIVE 배분 보류, T 대조군 유지. 기존 A2/A3/EWY H1 재최적화 없음. 후보 판정은 모두 EXPLORATORY_ONLY이며 중앙 포트폴리오와 LIVE 승인은 별도다.

## 상태와 증거

EXPLORATORY_REAL_DATA / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED / 확인적 OOS 미실행.
기존 시작 SHA `1dd51f6da527efd2a93d799e188f16494ba10759`와386 PASS를 먼저 확인했다.
프로토콜 선행 push SHA `342ddff2c811b20fbcad39dd85384a1787b25ce1`와 세션 적격성/엄격 계수 자격 기록을 보존한다.
기존 V2/V3/DF003/DF004, candidate-v1, Risk/OMS/Ledger, 비공개 원본의 바이트 보존을 검사했다.

신규27개를 포함한413개 시험, Ruff·format·mypy·sdist/wheel, OMS/Alpha/joint 재생,
이전 회계·신규 독립 회계·정규화 계보·원본 보존·비밀정보 검사의 실제 결과는 `artifacts/df005/checks.json`에 기록한다.
최종 검증 실행 결과가 근거이며 실행 전 PASS를 추정하지 않는다.

수집은803/900요청·인증1/2회, 시세 원응답802개, 최소 응답후 간격{a["minimum_response_complete_to_request_seconds"]}초다.
실계좌 조회·주문·취소·LIVE 인증·배포·PR 병합0회다. 원시 시세와 상세 거래는 Git 제외다.
최종 수집기는 fsync 후 immutable 파일을 원자적으로 공개하며, 응답 journal 완료 후 예산 교체 전
중단도 복구한다. 수집 종료 후 추가 보강은 오프라인 시험으로 검증했으며 재인증하지 않았다.

초기 귀속 모듈의6종목 전용 sector lookup 실패는 V1 시도에 보존했다. V2에서 원본은 보존하고
nullable 업종 lookup만 바꾼 별도 귀속 모듈을 추가해 알려진 종목의 회계 동일성을 시험했다.
잠정 V2의 미등록 조정계수 허용 오차는 최종 V3에서0으로 수정했다. 전 단계 결과와 소스를 보존하고,
입력 hash와 실행함수 AST/기존 코드 hash가 같은 유효 결과만 재사용했다. 후보 신호·체결·비용을 재최적화하지 않았다.

검증된 변경만 `codex/df005-domestic-panel-validation`에 정상 push한다.
정확한 최종 SHA의 Python3.11/3.12 Actions를 확인하고, 순환 커밋을 피하기 위해 최종 CI 증거는
Git 제외 `data/data-first-final/df005/remote-ci.json`에 남긴다. 원격 확인 전 성공을 주장하지 않는다.

관련 문서: [패널·계보](DF005_DATA_PANEL_AND_LINEAGE.md), [후속 실행 연구](DF005_INTRADAY_EXECUTION_FOLLOWUP.md).
""",
    )


if __name__ == "__main__":
    main()
