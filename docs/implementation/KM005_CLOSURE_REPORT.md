# KM-005 Milestone Closure Report

작성일 2026-10-17 KST. **KM005_DATA_HOLD / ECON_NOT_EXECUTED / LIVE_NOT_APPROVED**.
기술적으로 적격성·경제성 입력·안전 검사를 보강했다. Alpha A의 실제 비용 후 경제적 가치에 대한
답은 아직 낼 수 없다. 이번 결과는 전략의 성공이나 실패가 아닌, 증거 부족에 따른 평가 미실행이다.

## 1. Authoritative State

공식 저장소: `https://github.com/amandalmoon/k-mast.git`, 작업 브랜치 `km-005`.
Starting HEAD와 fetch 후 `origin/km-004`는 모두
`d9e0778d31b45947316b50438b5515263ee037c8`이었다.
KM-004 원격 Run 38929653134는 정확한 이 SHA에서 Python 3.11/3.12 각각 252 PASS였다.
실제 job 로그 발췌는 `artifacts/km005/prior-ci-test-counts.json`에 있다.

구현 Commit SHA: `98f562d7f6e04366a76b919675a9b51bc249b7c7`.
구현 원격 CI: [Run 38934082020](https://github.com/amandalmoon/k-mast/actions/runs/38934082020).
Closure Commit SHA와 최종 원격 HEAD는 자기참조를 피하기 위해 최종 응답에서 별도로 제출한다.
`git log -1 --format=%H -- docs/implementation/KM005_CLOSURE_REPORT.md`와
`git ls-remote --heads origin km-005`로 확인할 수 있다.
구현 및 종료 커밋을 정상 push하며 강제 push·이력 재작성·PR·merge·배포는 하지 않는다.

## 2. KM-004 회귀 검증

사전 audit의 모든 소스·증거 해시가 일치했다. 기존 **252 PASS / 0 FAIL / 0 SKIPPED**.
종료 시 기존 252개를 신규 시험과 분리하여 다시 실행했고 모두 PASS였다.
KM-000~004 Closure Report와 원본 권위 문서를 대조했다.
00~07 및 IMPLEMENTATION_BASELINE은 원본 바이트를 유지했다.
기존 Alpha, Risk, OMS, Ledger, cost, cash, signal 계약과 기존 252개 시험을 변경하지 않았다.
기존 파일 변경은 검증 runner·README·CI workflow·ignore 정책에 한정한다.

새 research 패키지는 기존 `PerformanceBridge`, `ResearchDataGate`, `StudyContract`,
Alpha adapter 및 데이터 저장소를 사용하는 계약·검사 계층이다. 새 Ledger나 OMS를 만들지 않았다.
개발 중 Ruff 줄 길이·정렬, mypy 타입 오류를 수정했으며 최종 검사에서는 모두 통과했다.

## 3. 데이터 적격성

공급원 KIS, KRX 원주가/수정주가 일봉과 KOSPI 지수. 확보 기간은 2026-07-20~10-16이다.
005930 RAW 60, ADJUSTED 60, 0001 INDEX 60 = **180행 / 독립 주식 관측일 60개**.
별도 과거 4행의 해시도 재검증했고 180행과 날짜가 중복되어 표본을 추가하지 않았다.
신규 수집·인증·계좌 조회는 0회다. 기존 PAPER 수집 환경은 KM-004 보고 근거이며
개별 Observation에는 환경 정보가 없어 이를 별도 미확인 한계로 표시했다.

원본·Parquet·manifest를 기존 DataStore로 다시 검증했다. 각 dataset ID/source hash,
실제 received/acquired 시각, parser 버전·해상도·가격 기준은
`artifacts/km005/local/qualification.json`의 datasets에 있다.
원문은 계속 private store에 있으며 공개 Git에는 가격 행을 추가하지 않았다.

같은 종목·종류·일자·venue·가격 기준의 중복과 상충 키 0, 주가 거래대금 누락 0.
이는 관측된 행 안의 검사이며 누락된 거래일·정지·상폐가 없다는 뜻이 아니다.
RAW와 ADJUSTED를 독립 표본으로 세지 않는다. calendar 분모가 없어 결측률은 null이다.
PIT universe·상폐·정지·업종·기업행위·정정 전 버전·공표시각은 미확보다.
세션·조정 이력·지수 historical release flag가 남아 있다.

사용자가 제공한 [KIS 이용안내](https://apiportal.koreainvestment.com/about-howto)와 공개 footer의
[고객 약관](https://apiportal.koreainvestment.com/api/terms/public?termsType=MARKET)을 확인했다.
공개 API version 28, 본문 제정 2022-08-08, 수정 표시 2024-04-11이다.
제5조 제3항의 개인 프로그램 이용·제3자 제공 제한을 확인했다.
내부 백테스트·장기 저장의 구체적 조건과 사용자 적용 계약은 **UNVERIFIED**이며
전체 연구권한 상태는 **LICENSE_UNVERIFIED**다. 권한이 전부 금지됐다고 판단하지도 않는다.
[공급원·권한 상세 비교](KM005_DATA_QUALIFICATION.md)에 KIS/KRX/OpenDART/벤더의
12개 항목, 공식 출처와 문의 초안을 기록했다. 유료 구매·외부 문의 발송은 하지 않았다.

## 4. Alpha A 검증

정확한 후보는 기존 **AlphaA-candidate-v1**이다. 코드·설정은 변경하지 않았다.
lookback 20, max_weight .25, volatility_budget .01, min_turnover 1000,
min_relative_strength 0, stop_fraction .05, max_holding 5일,
order_lifetime 1분을 기존 설정 그대로 기록했다. 이 숫자를 실전 승인값이나 검증된 최적값으로 보지 않는다.
설정 hash `ffb136fba1b7ec222dc656d48cc16a0a88948fa1d4691d1dca3793f4b597b634`,
Alpha 소스 묶음 hash `dd4e35c825540f83976fa1cb7712a5984992a3c167e2b5b81c796e743030a49b`.

후보 파일 동결과 완전한 G0 계약 동결은 별개다. 기존 데이터 manifest와 함께 candidate-freeze.json에
저장하고, 변경된 코드·설정·데이터로 같은 연구 출력을 재사용하면 거부한다.
후보 탐색은 기존 후보 1개 유지이며 손익을 보고 파라미터를 고르지 않았다.

실제 원주가 60행을 기존 Alpha adapter로 검사했으나 모두 입력 요건 미충족으로 거부됐다.
따라서 실제 신호 발생 사례·진입·종료·체결·요인 성과는 **NOT_EXECUTED_G1_HOLD**다.
검증되지 않은 session/bar interval을 생성하거나 가용시각을 과거로 소급하지 않았다.
다음 세션 이후 체결, 현재 봉 고점과 이전 창 분리, 미래 지수 차단은 합성 계약시험으로 검증했다.
일봉만으로 정확한 지정가 체결·체결률·수용자금을 주장하는 경로도 차단했다.
기존 SignalIntent→PortfolioTarget→Risk→MockExecution 경로는 회귀 재생으로 보존했다.
실제 시세를 그 경로에 연결해 거래한 결과는 아직 없다.

## 5. 실제 데이터 기반 경제성

**실행하지 않았다.** GrossMarketPnL, 수수료·세금, 체결비용, 운영비, NET_OPERATING_PNL_KRW,
NAV, TWR, 현금 초과손익, 기대손익·승률, MDD, Sharpe/Sortino, 회전율, 보유시간,
미체결률, 자본 점유율, 용량, 종목·업종·시장 노출은 모두 null / INSUFFICIENT_EVIDENCE다.
현금·단순 보유·단순 추세·Alpha A·FIXED·RISK의 실제 성과 비교도 실행하지 않았다.
시장 수익과 독자적인 alpha를 판정할 근거가 없다.

실제 수수료·세금·계좌 조건·적용일·spread/impact/지연·부분체결·현금이자·반복비용,
사용자 capital/risk를 확보하지 못했다. `cost-evidence.json`에 값과 적용일을 null로 보존했다.
기본·spread 확대·지연·미체결·유동성 감소·자본 증가 시나리오는 실행 대기 항목이며 성과는 null이다.
비용을 임의 0으로 설정하거나 설명용 비용을 계약값으로 승인하지 않는다.

새 EconomicResult는 기존 PerformanceBridge를 감싸 계좌 외부 운영비만 별도 차감한다.
체결가격에 포함된 spread/impact 및 미체결 기회비용은 다시 장부 비용으로 차감하지 않는다.
계산 모드는 SYNTHETIC_FUNCTIONAL 또는 SIMULATED_REAL_MARKET_DATA로 명시하며
provenance ref가 필수다. ACTUAL_BROKER_REALIZED 모드를 거부한다.
실제 시장자료 Mock 손익을 실계좌 실현손익으로 제시할 수 없다.
합성 단위시험의 산술은 계산·차단 검증이며 시장 수익성 증거가 아니다.

## 6. G0~G3 평가

| Gate | 요구 | 확보 근거·수행 | 판정·부족 |
|---|---|---|---|
| G0 | 후보·데이터·KPI·capital/risk·비용·분할/OOS·불확실성 사전 동결 | 기존 후보와 SHA 고정, 나머지 미정 목록 보존 | HOLD. 확인적 OOS 접근 차단 |
| G1 | 연구·저장 권한, 실제 PIT universe·기업행위·calendar·cost/execution | 180행 해시·관측일·일부 권한 확인 | HOLD. LICENSE/PIT/QUALITY/COST |
| G2 | 비용 후 순기대가치·기준선·위험·용량·독립 증거 | 실행 요건 미달로 실제 계산 없음 | NOT_EXECUTED |
| G3 | 동일 조건 FIXED 대비 다전략 증분가치 | 적격 복수 전략 패널 없음 | HOLD / NOT_EXECUTED |

G0 필수 자본·한도·최소 경제적 차이·신뢰도·표본·구간은 임의 승인하지 않았다.
미성숙 라벨과 변경 후보의 기존 승인 상속을 차단했다. 실제 OOS를 개봉하지 않았다.
경제성 해석은 **ECON_NOT_EXECUTED**이며 ECON_GO/REJECT를 부여하지 않는다.

## 7. 테스트·안전성

로컬 Windows/Python 3.12에서 기존 252 + 신규 33 = **285 PASS / 0 FAIL / 0 SKIPPED**.
신규 요구 ID 전부 실행: DATAQUAL-001~009, STRAT-001~005, EXEC-001~003,
ECON-011~018, VAL-012~016, SAFE-007~009.
JUnit의 ID 대응은 audit.json, 원문은 `artifacts/km005/pytest.stdout.log` 및 `junit.xml`에 있다.
실행 명령은 `python scripts/verify.py --milestone km005`다.
Ruff, format, mypy, sdist/wheel, 기존 demo 및 KM-002~004 replay 모두 PASS.
없는 private 데이터의 HOLD와 null 지표, 경제성 근거의 독립 JSON 검사도 PASS다.
정확한 명령과 exit code는 checks.json에 보존했다.

`python -m kmast.research.cli --output artifacts/km005/local --private-store
data/km004-private-20261016T153108135472Z --manifest artifacts/km004/real-collection.json`은
로컬 해시·입력 적격성 검사만 한다. 인증·조회·계좌·주문·취소 capability를 import하지 않는다.
실제 인증·시장 조회·계좌 조회·주문·취소는 이번 작업에서 각각 0회다.
기존 bounded read 어댑터의 권한은 확대하지 않았다.
공개 원시 시세/환경 파일/DB/Parquet 경로 거부, socket 봉쇄와 기본 permit OFF 시험을 수행했다.
승인된 외부 env의 키 값과 소스·증거 바이트를 로컬 메모리에서 대조하고 값 없이 PASS만 기록했다.
코드·증거·원본 규격 해시는 audit.json에서 확인한다. 공개 약관 읽기와 GitHub CI 조회는 별도 공개 GET이다.

## 8. 원격 검증

정상 push 대상은 `origin/km-005`다. 구현 CI는 위 구현 SHA를 대상으로 한다.
구현 SHA의 Run 38934082020은 completed / success다. Python 3.11 job 117085046171과
Python 3.12 job 117085046400에서 각각 **285 PASS**를 실제 로그로 확인했다.
각 job의 Ruff·format·mypy·build, 신규 시험 포함 전체 pytest,
KM-002~004 재생, 데이터 없는 환경의 HOLD·경제성 근거 검사가 모두 success다.
상태 근거는 `artifacts/km005/remote-ci-implementation.json`과 job 로그 발췌다.
테스트 수와 mypy/build/HOLD 검사 원문 발췌는 `remote-ci-test-counts.json`이다.
원격 코드 시험 PASS는 실제 데이터 적격성·경제성 GO를 뜻하지 않는다.
Closure 커밋은 보고서·감사 증거만 추가하며 최종 원격 HEAD의 CI도 별도로 확인한다.

## 9. 미해결 Blocker

- 기술: 신규 검사·기존 회귀는 통과. 적격 자료를 통한 Alpha 전체 경제성 경로의 통합 증거는 없음.
- 공급원/권한: 개인 적용 약관, 비공개 백테스트·장기 보관, 추가 정책 확인 필요.
- 데이터: 당시 전체 종목군·상폐·정지·기업행위·원/수정 계수·업종·calendar·정정 및 공표시각 필요.
- 비용: 과거 유효일별 fee/tax, 실제 quote/execution·cash interest·운영비 계약 필요.
- 자본/위험: 사용자 연구/확인적 자본과 승인 위험·용량 기준 미정.
- OOS/통계: 연구·검증·locked OOS 구간, 최소 개선·군집 표본·불확실성 방법과 독립 근거 미정.

## 10. 다음 단계

지금은 KM-006 Shadow 자동 진입보다 데이터 보완이 경제적으로 합리적이다.
먼저 공식 문의 초안으로 내부 연구·보관 권한과 PIT/기업행위 공급 범위·견적을 확인한다.
사용자가 승인한 유한 범위로 자료를 확보한 뒤 Alpha A의 작은 전체 경로를 검증하고,
동일 자본·기간·현금·실제 비용 조건의 단순 대안을 비교해야 한다.
유료 구매, 신규 인증 수집 범위 확대, 실전·배포·PR 병합은 수행하지 않았다. KM-006은 시작하지 않는다.

## 11. 최종 판정

**KM005_DATA_HOLD**: 데이터 파이프라인 적격성·경제성 입력·안전 게이트 보강 범위를 완료했다.
**ECON_NOT_EXECUTED**: 실제 비용 후 양의 기대수익과 독자적 alpha는 미검증이다.
**LIVE_NOT_APPROVED**: 실제 주문·취소·사용자 자금·배포 권한은 변경하지 않았다.
