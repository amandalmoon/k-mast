# KM-004 종료 보고서

작성일: 2026-10-17 KST. 최종 상태: **KM004_BASELINE_CODE_READY_DATA_HOLD**.
경제성 **ECONOMIC_EDGE_UNVERIFIED**, 실전 **LIVE_NOT_APPROVED**. 이번 완료 범위는
데이터 부분 확보, 공동계좌 보존성, 제한된 배분 진단과 차단 검증이다.
실제 데이터에 근거한 순이익 판단까지 연결하는 목표는 아직 충족하지 못했다.

## 1. 저장소·브랜치·커밋 계보

저장소는 `https://github.com/amandalmoon/k-mast.git`, 작업 브랜치는 `km-004`다.
시작 HEAD는 `b9e8574cb6adfffc7b50350f502c4c21d0bd702f`이며 KM-003 구현
`d6198b88c23233f5a483735e4e8841534535d76b`와 종료 커밋
`1b615a58842f29fa80565a6cbc4ba83ab1462dcd`가 선행한다.
원격 읽기 검사에서는 `km-001`의 `a7bb5399ee2f65145bc91e358e0fe05c8785f9ce`만 확인했다.
후속 로컬 구현의 원격 독립 검증을 주장하지 않는다. 이번 작업은 원격 push/PR/merge를 수행하지 않았다.
구현 SHA는 `artifacts/km004/audit.json`의 `implementation_head`에 고정한다.

## 2. 기존 214개 회귀시험 결과

변경 전 KM-003 소스 해시 불일치 0건, 이전 실제 자료 4행의 원본/Parquet/계보 재검증 성공.
기존 KM-003 214개 PASS, 이후 환경설정 검사 6개 포함 220개 PASS를 각각 실행했다.
변경 후 기존 220개 역시 PASS. 테스트를 삭제하거나 기존 기대값을 완화하지 않았다.
원문은 `artifacts/km004/baseline-regression214.stdout.log`,
`baseline-regression220.stdout.log`, `regression220.stdout.log` 및 `baseline.json` 참조.

## 3. 실제 시장 데이터 확보 시도와 실제 결과

사용자가 지정하고 입력한 외부 `.env`만 읽었다. 설정 환경은 PAPER다.
이번 작업의 인증 시도 3회, 시장자료 GET 4회, 합계 7회이며 계좌 조회·주문·취소는 각각 0회다.
공개 공식 소스 다운로드는 이 인증 API 횟수와 별개다.

첫 실행은 원주가 60행과 조정주가 60행을 받은 후 지수 PAPER 환경 허용 검사에서 요청 전에 차단됐다.
공식 고정 버전에서 지수 일봉의 real/demo 지원을 확인해 해당 경로만 추가했다.
두 번째 실행은 기존 주가 캐시와 지수 50행, 세 번째는 캐시와 이전 구간 지수 10행을 사용했다.
빈 continuation이 전체 범위 완료를 보장하지 않아 날짜를 한 번 뒤로 제한 조회했다.
실패 시도도 `real-collection-attempt1.json`에 보존했다.

최종 실제 180행: 005930 원주가 일봉 60 + 조정주가 일봉 60 + KOSPI 0001 일봉 60.
기간 2026-07-20~2026-10-16. 독립적인 주식 관측일은 60일이며 180일로 계산하지 않는다.
4개 dataset manifest의 원본 해시, Parquet 바이트 해시, 행 내용 해시를 로컬 재검증했다.
직전 마일스톤의 실제 4행은 별도 이력이며 이번 180행에 중복 가산하지 않았다.

## 4. 사용권한·데이터 품질 및 DATA_READY 범위

**LICENSE_HOLD / DATA_PARTIAL**. 현재 DATA_READY 범위는 없다.
API 접근 성공이 연구·재배포·상업 사용권을 증명하지 않는다. 원자료는 Git 제외 private store에 보관했다.
KRX 예상 거래일 격자의 근거가 없어 결측률은 null이다. 주가와 지수 관측일 집합의 일치는 확인했다.
공식 과거 공표시각, 세션, 종목 생존·상폐 이력, 수정주가 기업행동 이력은 미검증이다.
수집 시각을 과거 available_at으로 소급하지 않았다. RAW와 ADJUSTED를 중복 수익으로 합치지 않는다.
`data-diagnostic.json`은 입력 게이트 차단과 실제 손익 null을 기록한다.

공식 참고: [KIS 고정 버전 지수 일봉 예제](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_daily_indexchartprice/inquire_daily_indexchartprice.py).
파일 해시는 `official-source-proof.json`에 저장했다. 제공자는 `FHKUP03500100`과 U 시장코드를 사용한다.
[KIS 안내](https://apiportal.koreainvestment.com/provider-doc1),
[KIS 공지 목록](https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000002),
[KRX 데이터 안내](https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA003.jsp)는 참고만 했다.
개인에게 적용되는 사용 약관 본문과 허용 범위를 확보하지 못했으며 사용권 승인으로 해석하지 않는다.

## 5. Alpha A~D별 경제성 검증 가능 여부

| 전략 | 확보 범위 | 판정 |
|---|---|---|
| A | 단일 종목 일봉과 지수, 조정/원주가 | DATA_PARTIAL_LICENSE_HOLD |
| B | 검증된 장중 자료 없음 | DATA_BLOCKED |
| C | 검증된 장중·유동성 자료 없음 | DATA_BLOCKED |
| D | 검증된 이벤트·장중 자료 없음 | DATA_BLOCKED |

네 전략 모두 실제 경제성 검증 불가. A의 단일 종목은 생존편향 없는 유니버스가 아니다.
실제 과거 주문 시뮬레이션과 G2/G3 평가를 실행하지 않았다.

## 6. PBASE_FIXED 구현 및 테스트

기존 absolute sleeve target → Aggregator → Risk Manager → Mock OMS 경로를 그대로 사용했다.
A/B/C/D 예산 0.40/0.30/0.20/0.05, 중앙 현금 0.05.
공동계좌 10,000원에서 동일 종목 목표 10/5/5/0주를 통합했다.
부분체결, UNKNOWN, reserve 유지, 재조정, T+2 결제, 귀속 이전, 배당, 분할, 비용, 강제 축소를
하나의 작은 합성 경로로 검증했다. 새로운 OMS나 실제 브로커 주문 연결은 없다.

## 7. PBASE_RISK 구현 및 시험 한계

동일 H·NAV·비용·캘린더·REFERENCE 단위와 가용시각이 맞는 패널만 받는다.
최소 표본, 변동성 floor, cash reserve, cap, 행렬 대칭·PSD·차원 검사,
sample covariance(n-1), wΣw, volatility 및 risk contribution을 구현했다.
알고리즘은 capped inverse volatility 진단이며 최적 risk parity 또는 수익 최적화로 주장하지 않는다.
cap 잔여분은 현금으로 유지한다. 영분산·잘못된 행렬·표본 부족은 HOLD다.
RC 산술 예제: w=(.4,.3), Σ=((.01,.005),(.005,.04)) → 분산 .0064, 변동성 .08,
RC=(.0275,.0525), 합 .08.

`risk-diagnostic.json`의 3표본은 명시적 합성 산술 fixture다. 운영 최소표본 기본값은 30이다.
실제 A~D reference 수익률 패널이 없어 real panel은 HOLD다. 데이터 180행으로 위험모형을 추정하지 않았다.
후보는 PROPOSAL_ONLY이며 자동 승격은 없다. 명시적인 SYNTHETIC 승인으로만 연결 ID를 가진
PBASE_FIXED Mock 예산으로 동결 가능하다. 기존 Risk Engine의 PBASE_RISK 실행 차단은 유지했다.
따라서 동적 PBASE_RISK 공동계좌 실행·경제성 비교의 완료를 주장하지 않는다.

## 8. 포트폴리오 총자산·현금·귀속 보존

실제 계좌 Book와 sleeve attribution Book를 기존 매 이벤트 보존 검사로 대조한다.
UNKNOWN 시 reserve 164.96원을 유지했다. 미투자 sleeve cash와 중앙 cash는 서로 다른 Book다.
내부 A→B 2주 이전은 계좌 전체 PnL을 만들지 않는다. 이후 2:1 분할은 수량·원가를 반대로 변경한다.
배당 20원, 계좌 운영비 5원, 외부 운영비 10원을 구분한다.
분할은 canonical action ID를 기존 event idempotency에 연결한다. 미결 주문·미결제·단주·과거 재처리 필요·
원가 정밀도 불충족은 거부한다. 기계적 분할 mark는 거래 불가이며 새 시세와 계좌 재검증이 필요하다.
기존 state schema에 필드를 추가하지 않아 과거 event hash 계약을 유지했다.

## 9. 리밸런싱과 거래비용 계산 결과

동일 목표 유지 대비 예상 개선에 delay decay를 적용하고 incremental cost + uncertainty를 초과할 때만
변경 요청한다. 동률은 HOLD. stale 계좌/시세, hard risk 실패, 실행 불가는 이익 예상보다 우선한다.
강제 위험감축 요청은 경제적 무거래 구간보다 우선하지만 실행 차단을 우회하지 않는다.
예상 비용은 Book 비용에 기장하지 않는다. 체결·배당·운영비 event만 실제 합성 장부를 변경한다.
BUY 수수료 .20원, SELL 수수료 .05원 + 세금 .10원, 총 체결비용 .35원이다.

## 10. 실제 자료 성과와 합성 기능시험 결과의 구분

실제 자료: 180행 해시·관측일·출처 검사까지만 수행. 실제 자료 PnL=null, 실제 거래 0건.
합성 보존성: 계좌 NAV 10014.65원, 계좌 net 14.65원, 외부비용 포함 프로젝트 net 4.65원.
이는 20 - .35 - 5 - 10의 산술 결과이며 alpha, 연 수익률, 통계적 우위가 아니다.
관측 기간이 과거 자료 확보 기간과 같다는 해석도 금지한다.

## 11. 현금·단순 정책·고정배분 비교

합성 동일 초기자본 10,000원, 동일 7개 평가일과 비용정책으로 비교했다. 무거래일도 포함했다.
현금 유지 net -15원, 독립 reference A~D와 중앙 현금의 예산 가중 net 4.452원,
공동계좌 FIXED net 4.65원. 차이 .198원은 정수 수량 및 공동현금 구조에 따른 것으로 추가 alpha가 아니다.
가중 reference NAV를 실제 공동계좌 NAV로 대체하지 않는다.
실제 단순 매수보유·FIXED·RISK 간 경제적 우열 비교는 NOT_EXECUTED_DATA_HOLD다.

## 12. 신규 테스트 전체 결과 및 원문 로그

기존 220 PASS + 신규 요구 ID 25 PASS + 추가 경계 7 PASS = **252 PASS / 0 FAIL / 0 SKIPPED**.
요구 ID: REALDATA-001~006, PORT-007~013, REBAL-001~004, ECON-006~010, SAFE-004~006.
ID별 함수와 JUnit 대응은 `audit.json`에 기록한다.
`pytest.stdout.log`, `junit.xml`, `checks.json`에 원문 결과가 있다.
Ruff, format, mypy, build, 기존 demo, joint replay, 독립 회계 산술 검사, 외부 경로 wheel 설치 검사,
이전 KM-002 및 KM-003 replay가 모두 PASS다. 원격 CI는 **NOT_EXECUTED**다.

## 13. SHA·Fixture·데이터 manifest

`baseline.json`은 변경 전 소스/시험 해시, `audit.json`은 구현 소스와 증거 파일 SHA-256을 기록한다.
`real-collection.json` 및 timestamp별 manifest에 4개 dataset ID, 수집시각, 조회 범위와 flag가 있다.
원자료는 `data/km004-private-20261016T153108135472Z`이며 Git 제외다.
`artifacts/km004/joint-v1`은 합성 initial/events/final/reference/panel 파일을 담는다.
joint state hash는 `414cc83a353e2addc46670db20a1a79dc78ea3995d8f256876f2ab28d6ae68e5`다.
실제 시장 가격의 원문은 배포하지 않는다. 별도 draft 디렉터리는 로컬에 보존했다.

## 14. 실전 주문 차단 증거

인증/시장조회만 사전 승인 범위 안에서 수행했다. 수집 Wire는 token POST와 두 일봉 quotation GET만 허용한다.
계좌·주문·취소 0회 manifest, MockBroker 주문·취소 차단 시험, 환경설정 trading flag 거부 시험이 있다.
키와 계좌 식별자는 출력하지 않으며 지정 config 값을 메모리 안에서 소스/증거 바이트와 대조했다.
검사 결과는 값 없이 PASS만 기록한다. Risk 정책은 SYNTHETIC_ONLY이며 LIVE 승인이 아니다.

## 15. 해결되지 않은 blocker

적용 가능한 이용약관/연구 권한, PIT 종목 master와 상폐·정지, 공식 과거 공표시각,
거래일·세션 격자, corporate action 이력, 실제 실행 가능한 호가·체결비용, B~D 입력,
충분한 A~D reference 수익률 패널, 독립 confirmatory/OOS 근거가 필요하다.
따라서 실제 순이익, PBASE_RISK 추가 가치, G2/G3 모두 미검증이다.

## 16. KM-005 진입 조건과 선행 작업

위 blocker의 출처·기간·권한 범위를 확정하고, 적격 데이터로 Alpha A의 작은 전체 경로를 먼저 재검증해야 한다.
그 다음 동일 자본/기간/비용의 현금·단순 정책·FIXED 비교와 위험제약 아래의 순이익 검증이 필요하다.
경제성 검증 및 운영 승인과 코드 준비 상태를 분리한다. KM-005는 시작하지 않았다.
원격 push, PR, 배포, LIVE 활성화, 실전 거래에는 별도 승인이 필요하다.

## 17. 최종 GO / HOLD / BLOCKED 판정

로컬 코드 보존성·차단 시험: **GO (SYNTHETIC_ONLY)**.
실제 자료 연구 준비: **HOLD (LICENSE/PIT/QUALITY/COST)**.
경제성: **HOLD / ECONOMIC_EDGE_UNVERIFIED**.
실전 주문·취소: **BLOCKED / LIVE_NOT_APPROVED**.
최종 **KM004_BASELINE_CODE_READY_DATA_HOLD**로 종료한다.
