# KM-003 Milestone Closure Report

작성일: 2026-10-16 (Asia/Seoul).
최종 판정: **KM003_STRATEGY_CODE_READY_DATA_HOLD**.
기술 구현 GO / 실제 데이터·경제성 HOLD / **ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED**.

## 1. Repository / Branch / Starting HEAD / Closing HEAD

| 항목 | 실제 상태 |
|---|---|
| Repository | `C:\Users\User\Desktop\k-mast` |
| Remote | `https://github.com/amandalmoon/k-mast.git` |
| Branch | 로컬 `km-003` |
| Starting HEAD | `9389040a83b6b0d646d90dd3d4b6f620f5c38c84` |
| 검증한 Closing HEAD / 구현 commit | `d6198b88c23233f5a483735e4e8841534535d76b` |
| KM-002 구현 | `9bd281209cbc0eb1b49ae917ec8396d758f47cfd`, 존재 및 조상 관계 확인 |
| 시작 working tree | 깨끗함 |
| 구현 커밋 직후 | 미커밋 변경 없음. 이 보고서·audit.json은 후속 문서 커밋 |
| 원격 변경 | push / PR / merge / deployment 없음 |

시작 시 `git ls-remote --heads origin`은 km-001의 a7bb539…만 반환했다. KM-002 구현과
종료 보고서는 로컬의 두 후속 커밋으로 존재하며 원격 누락은 미푸시 상태와 일치했다.
[실제 원격 응답](../../artifacts/km003/baseline-remote-heads.stdout.log),
[시작 HEAD](../../artifacts/km003/baseline-starting-head.stdout.log).
원격을 갱신하거나 기존 커밋을 강제 재작성하지 않았다.

Closing HEAD는 시험한 구현의 SHA다. 자기참조를 피하기 위해 보고서 자신의 SHA를
본문에 넣지 않는다. 보고서 포함 최종 HEAD는 `git rev-parse km-003`, 보고서 커밋은
`git log -1 --format=%H -- docs/implementation/KM003_CLOSURE_REPORT.md`로 확인하며 최종 응답에 별도 명시한다.

## 2. 기존 164개 회귀시험 결과

시작: **164 PASS / 0 FAIL / 0 SKIPPED**.
[사전 감사](../../artifacts/km003/baseline.json),
[시작 pytest 원문](../../artifacts/km003/baseline-pytest.stdout.log),
[시작 JUnit](../../artifacts/km003/baseline-junit.xml).
KM-002 audit의 소스 byte hash 불일치 0, 구현 SHA 계보를 확인한 뒤 전략 개발을 시작했다.

종료: 기존 7개 시험 파일만 별도 실행해 **164 PASS / 0 FAIL / 0 SKIPPED**.
[종료 회귀 원문](../../artifacts/km003/regression.stdout.log).
기존 core/data/broker/execution/strategies 인터페이스, conftest, 기존 시험, KM-000~002 증거,
00~07 원본과 IMPLEMENTATION_BASELINE/MIGRATION을 변경하지 않았다.
[보호 경로·diff·소스 hash 감사](../../artifacts/km003/audit.json).

## 3. A~D 전략별 실제 구현 범위

`kmast.alpha`에 typed Context/Config, 순수 결정 규칙, 기존 SignalIntent 전체 snapshot,
독립 reference와 데이터/연구 게이트를 추가했다. `simulation.bridge`가 기존 KM-002에
연결하며 전략은 이 계층·broker·network·OMS를 import하지 않는다. ALPHA-001은 새 alpha
패키지 전체를 검사한다. 기존 strategies Protocol과 ARCH-01은 원본 그대로다.

| Alpha | 실제 코드 범위 | 미완료 |
|---|---|---|
| A | 이전 20개 일봉 고점, 정렬된 시장지수 RS, 거래대금, ATR 크기, 추세 유지·stop·원래 만기, 다음 세션 배치 | 실제 일봉 연구, 업종 요인/기여도 추정, 실제 권리 연속성 검증 |
| B | 완성 5/15분 ORB, 이후 확인 분봉, 실제 notional VWAP, 같은 경과시간 RVOL, 장중 종료 | 실제 체결/지연/호가·수용량 연구 |
| C | fresh midquote 이격, spread, 유동성 회복/정보충격 표식, 손실 증액 금지·종료 | 실제 회복/정보충격 분류, passive queue·역선택 비용 추정 |
| D | 사건별 메커니즘 선택, 사전 기준 대비 차이, 공개 경계, 정정 family·소비된 사건·만기 | 실제 원문 NLP/컨센서스/수급/종목 매핑·사건별 시장 연구 |

이 표의 실행 가능성은 코드/합성 입력 경로를 뜻한다. A~D에 실전 자본을 배분하지 않았고
config의 live_capital_weight는 Literal 0이다. 알파 수익성이 검증되었다고 판정하지 않는다.

## 4. 경제적 가설·입력·종료 규칙

[동결 후보 카드와 정확한 실행 계약](KM003_USAGE.md#동결-후보-카드).
기본 연구 후보는 candidate-v1이며 파라미터 탐색/최적화는 수행하지 않았다.

- A: 정보의 점진 반영/지속적 자금배분 가설. 이전 high 돌파와 시장 대비 RS≥0,
  turnover≥1,000, 변동성 예산 1%·목표 상한 25%. 이전 창 평균 이상이면 유지하고
  5일 상한/5% 손실 무효화/유니버스 제외 시 0. 시장·업종/저유동성 노출이라는 대립 설명은 미검증이다.
- B: 개장 불균형 지속 가설. 완성 range 뒤의 확인 봉, RVOL≥1.2 및 VWAP 조건.
  필터/돌파 실패·stop·당일 deadline에 목표 0. 이후 고가나 하루 거래량을 앞당기지 않는다.
- C: 일시적 유동성 충격 복원 가설. mid가 VWAP보다 1% 이상 낮고 spread≤0.5%,
  회복 표식/정보충격 제외 조건. 이격 해소·stop·장중 만기 종료. 표식은 합성 입력이며 실제 식별모델이 아니다.
- D: 계절 실적, 실제 자사주 취득, 확인 지수 수요를 각각 별도 config의 사건으로 처리한다.
  기본 EARNINGS_SEASONAL은 사전에 알려진 계절 기준과 비교하며 시장 컨센서스 surprise로
  명명하지 않는다. 기준 차이 음전·정정·stop·만기 종료. 계획을 실제 집행으로 치환하지 않는다.

모든 숫자는 합성 기능시험/연구 후보 가정이며 승인 위험 한도나 최적값이 아니다.
신호 TTL, 예측 horizon, 원래 보유기한은 분리한다. 봉의 stop 조건은 다음 실행 가능
목표를 만들 뿐 그 봉 내부에서 손절가 체결을 가정하지 않는다. 실제 정지 시 목표 0도 체결 보장이 아니다.

## 5. 데이터 출처·기간·해상도·사용권한

**실제 시장자료 0행**. 사용자는 KIS 키 보유와 인증/시세 읽기를 허용했으나 이어서
이번 실행에서는 로컬 키 설정을 하지 않기로 답했다. 이 선택 이후 비밀 탐색·인증·조회·
예약/자동 재시도는 하지 않았다. 키 값을 채팅이나 저장소로 받지 않았다.
사람이 로컬 터미널에서 숨김 입력할 설정 도구만 제공했고 도구는 이번에 실행하지 않았다.

공개 KIS 일봉 예제, 금융위원회 주식시세정보, KRX Open API, OpenDART를 조사했다.
[출처·조건·확보 계획](KM003_DATA_PLAN.md),
[공개 문서 응답/시각/hash](../../artifacts/km003/data-source-audit.json).
금융위원회 페이지의 현재 제4유형/상업·변경·재배포 제한 때문에 바로 채택하지 않았다.
KRX 공개 안내는 브라우징으로 확인했으나 별도 직접 fetch는 실패로 기록했다. 구매·키 신청은 하지 않았다.
API 코드 공개 라이선스를 시장자료 저장·사용·재배포 권한과 혼동하지 않았다.

실제 확보 기간·종목 커버리지·결측률·생존편향·권리·가용시각·비용 추정치는 모두 미확보다.
평가 Fixture는 직접 작성한 A 21개 일봉+동일 날짜 지수(2026-09-17~10-15 평일),
B/C/D 6개 완료 분봉(2026-10-16), 합성 universe/호가/과거 경과시간 거래량/사건이다.
실제 휴장일을 확정한 캘린더가 아니며 source/origin에 SYNTHETIC을 표시했다.
이 Fixture에 대한 작성 권한만 있으며 실제 주식 데이터 라이선스 증거가 아니다.

## 6. Alpha별 DATA_READY / DATA_BLOCKED

| Alpha | 상태 | 주요 blocker |
|---|---|---|
| A | DATA_BLOCKED | 실제 OHLCV/지수, PIT universe·상폐/정지, 권리·calendar·시각·비용/사용권 |
| B | DATA_BLOCKED | 실제 minute/trade/book, RVOL 과거창, VWAP 원체결, 지연/스프레드/수용량 |
| C | DATA_BLOCKED | midquote/trade 동기화, queue/미체결·역선택, 회복/정보충격 근거 |
| D | DATA_BLOCKED | 원공시/공개 경계/정정/매핑, 사전 기대·계절 기준·사건 군집 |

DataEvidence는 실제 행, 기간/심볼, 원문 hash와 모든 준비 항목이 있어야 제한된 준비
상태를 반환한다. 준비 상태도 경제 승인으로 이어지지 않는다. 다운로드 exit code나
합성 표본 수를 DATA_READY로 승격하지 않았다. KM001_REAL_DATA_HOLD를 유지한다.

## 7. PIT·시점 누출 시험

미래 가격/늦게 가용한 지수/완성 전 분봉/미공개 사건은 특징에 들어오지 않는다.
현재 봉 high를 돌파 기준에 포함하지 않으며 일봉 종가 뒤 동일 종가 체결을 하지 않는다.
range 완료 후 새 확인 봉이 필요하고 RVOL은 이전 세션의 같은 경과시간 자료만 사용한다.
미래 known_at·상장 이전·상폐 이후의 universe는 진입을 허용하지 않는다.
같은 시각의 benchmark 중복과 봉 grid 누락은 거부/차단한다.

receipt_date는 시간으로 바꾸지 않는다. exact 시각이 없으면 다음 eligible session의
보수적 가용 경계를 사용하며 사전 baseline은 공개 경계 이전이어야 한다.
정정은 최신 가용 family revision으로 대체하고 상충/중복 계보는 차단한다.
원래 포지션 deadline을 새 신호로 갱신하거나 손실 중 목표를 키우지 않는다.
권리로 인한 raw 가격 단절은 연속성 검증 전 진입을 차단한다.

## 8. Reference Portfolio·현금·손익 보존

각 전략은 별도 REFERENCE 고정자본 10,000원, 현금, FIFO lot, 주문, 거절, 부분/미체결,
명시비용, 실현/미실현, 배당/분할, 평가 시각을 보존한다. 계좌·실제 귀속에 더하지 않는다.

```
reference NAV - initial capital
 = realized + unrealized + dividend - trading costs - operating costs
```

체결은 의사결정 후·최초 세션 이후·만기/시장종료 이전의 명시 Tick만 사용한다.
bid/ask, 불리한 slippage, limit, lot_size와 participation을 적용한다. 마지막 체결가나
봉 high/low만으로 수동 지정가 queue 체결을 만들지 않는다. 비체결·거절은 삭제하지 않는다.
실제 quote가 해당 수량 체결을 보장한다는 승인은 없고 현재 Tick은 합성이다.
reference의 즉시 경제 결제는 실제 KM-002 T+2/매도가능 장부와 구분한다.

분할·현금배당은 고유 ID로 한 번만 반영하며 RAW 가격 경로만 허용한다. 소수주 권리,
대기 주문의 권리 조정, 과거 권리의 늦은 삽입은 자동 추정하지 않고 별도 증거/replay를 요구한다.
무거래일·현금·손실 미청산 재고를 3개의 공통 일별 평가시각에 포함했다. 정지로 B 청산이
실패한 재고와 C passive 미체결이 남는다. 청산불능 표식은 valuation UNVERIFIED로 보존한다.
독립 표본 수는 null이며 3개 일별 관측을 독립 경제 표본 3개로 세지 않는다.

## 9. 거래비용 이전/이후 성과

아래는 **고정된 작성 예제의 산술 결과**다. 실제 시장 백테스트, 후보의 예상 수익률,
OOS 성과나 손익 예측이 아니다. 수익성을 만들기 위해 합성 표본을 확장하지 않았다.
각 reference의 초기자본 10,000원, 세 평가일 총 운영비 3원, 합성 commission 10bps,
sell tax 20bps, 불리한 slippage 5bps·수용량 10%를 사용했다. 실제 비용은 미확인이다.

| Alpha | 비용 전 총손익(원) | 거래비용 후(원) | NET_OPERATING_PNL_KRW | 동일 운영비 현금 대비(원) |
|---|---:|---:|---:|---:|
| A | -191.33 | -193.81 | -196.81 | -193.81 |
| B | -211.26 | -213.68 | -216.68 | -213.68 |
| C | 0 | 0 | -3 | 0 |
| D | -241.20 | -243.61 | -246.61 | -243.61 |

slippage는 체결가에만 포함하고 명시 수수료/세금에서 재차 빼지 않는다. 운영비는 별도
한 번 차감한다. gross에는 실현/미실현 및 배당 수익이 포함되는 비용 전 총손익을 뜻한다.
평균 NAV·TWR·drawdown·회전율·청산 수량 평균 보유시간·peak 자본/예약·체결/미체결/거절은
각 metrics.json에 있다. 청산 표본이 없으면 평균 보유시간도 null이다.

## 10. 실제와 합성 데이터 결과의 구분

실제 자료의 전략 손익·시장초과·비용 적합성·생존편향 없는 연구: **NOT_EXECUTED**.
실제 KIS 인증/시장 조회·주문·취소: **각 0회**.
공개 명세 페이지 읽기와 key 설정 helper 작성은 실제 API 수집이 아니다.

합성 기능 결과는 [functional-v1](../../artifacts/km003/functional-v1/summary.json)에
origin/data_status/economic_status와 함께 보존했다. 이를 근거로
KM003_ALPHA_CANDIDATE_SCOPED, ECON_GO, LIVE_APPROVED를 부여하지 않았다.
실데이터 시점/권리/비용을 충족하지 못하면 높은 합성 수익이 있어도 HOLD다.

## 11. 현금·단순 기준선 비교

동일 초기자본 10,000원·합성 운영비 3원을 사용했다.

| 비교 대상 | 마지막 NAV(원) | 범위 |
|---|---:|---|
| 현금, 합성 일 이자 0 | 9,997 | 동일 운영비, 시장 노출 0 |
| 25% 1회 진입 장기보유 | 9,803.19 | 이 추적에서는 A와 같은 진입/보유, A의 차별 가치 없음 |
| 후보 A~D | 9,803.19 / 9,783.32 / 9,997 / 9,753.39 | 독립 reference, 같은 초기자본·비용 규칙 |
| 고정예산 reference | 9,854.37 | A/B/C/D 40/30/20/5%, CENTRAL 현금 5%, 별도 각 자본에서 lot/비용 재계산 |

고정예산의 순운영손익은 -145.63원이며 이는 네 개의 10,000원 독립 NAV를 실제 계좌에
더한 값이 아니다. 전체 10,000원을 예산별로 나눈 별도 비교 장부다.
자본이 같아도 현금·25% hold·고정예산은 위험/사용자본이 같지 않다. 이 표로 알파나
위험조정 우위를 판정하지 않는다. 실제 시장/업종 기준선 성과는 자료가 없어 null이다.

기존 KM-002 계좌 고정예산 연결은 별도 **기능** 시험이다. 네 snapshot을 한 시각에
집계해 ALLOW→15주 Mock 체결·수수료 1원·귀속 보존을 확인했다. 그 장부는 다른 합성
시세/비용/평가구간이므로 위 reference 성과와 같은 경제 실험으로 비교하지 않는다.

## 12. 신규 테스트·실행 명령·로그·SHA

최종 **214 PASS / 0 FAIL / 0 SKIPPED** = 기존 164 + 신규 50개 사례.
24개 필수 ID는 파라미터화 포함 29개 사례, 신호→기존 OMS 연결 1개, 추가 경계 20개다.

```powershell
.\.venv\Scripts\python scripts/verify.py --milestone km003
.\.venv\Scripts\python scripts/audit_km003.py --implementation-head d6198b88c23233f5a483735e4e8841534535d76b
```

[실행 명령·exit code](../../artifacts/km003/checks.json),
[전체 pytest 원문](../../artifacts/km003/pytest.stdout.log),
[JUnit](../../artifacts/km003/junit.xml),
[시험 ID별 함수/행/실제 사례 및 source/evidence SHA-256](../../artifacts/km003/audit.json).
모든 최종 check exit code는 0이다.

| 확인 | 원문 로그 (`artifacts/km003/`) | 실제 결과 |
|---|---|---|
| 기존 회귀 / 전체 | regression / pytest.stdout.log | 164 / 214 PASS |
| Ruff / format / mypy | ruff / format / mypy.stdout.log | PASS, 51 source files |
| sdist/wheel / 기존 demo | build / demo.stdout.log | PASS |
| Alpha/reference/Mock 통합 | alpha-functional.stdout.log | PASS |
| 저장 후 재실행 | alpha-replay.stdout.log | 동일 상태/논리 hash PASS |
| 생산 장부를 import하지 않는 JSON 산술 대조 | independent-reference.stdout.log | 네 reference·고정예산·귀속·hash PASS |
| wheel 설치 후 체크아웃 밖 실행 | wheel-smoke.stdout.log / wheel-detail.log | 동일 summary/hash PASS |

별도 산술 검사는 같은 작업에서 만든 독립 코드 경로이며 외부 감사기관의 승인으로
표현하지 않는다. CI 정의는 확장했지만 원격 CI는 실행하지 않았다. .log는 원문 byte를
보존하며 Windows CRLF를 자동 수정하지 않는다. audit의 파일 byte SHA는 체크아웃의 줄바꿈
변환에 따라 달라질 수 있어 Git commit 및 논리 JSON hash와 함께 사용한다.

| 필수 ID | 실제 검증 |
|---|---|
| ALPHA-001~004 | 의존성·절대비중·전체 snapshot·신호/청산 만기 분리 |
| PIT-001~004 | 미래 가격·미완성 봉·미공개 공시·당시 universe |
| TREND-001~002 | 이전 high·정렬된 가용 RS |
| ORB-001~002 | range 완성/후속 확인·같은 시간 VWAP/RVOL |
| REV-001~002 | mid/trade 구별·미체결/역선택 보존 |
| EVENT-001~002 | 날짜/시각·정정 대체/소비 중복 방지 |
| REF-001~003 | 독립 NAV·무거래/현금/미실현·실제 장부 분리 |
| COST-004 | 체결 비용/운영비 단일 계상 |
| ECON-004~005 | 합성 경제 승인 거부·비용 후 현금 비교 |
| VAL-011 | config/data 변경 후 OOS 자동 승계 거부 |
| SAFE-003 | 실제 broker submit/cancel 봉쇄 유지 |

개발 중 시험 helper 이름/파서 인자 오류와 메모리 tuple 대 JSON list 반환 차이를 수정했다.
첫 검증 묶음의 보조 스크립트 Ruff/포맷 위반은 수정 후 최종 재실행했다.
초기 실패한 Ruff 묶음은 development-checks에 보존했으며 최종 결과는 실패/skip 0이다.

## 13. 경제성 평가에 남은 blocker

1. 실제 데이터/사용권/PIT universe·상폐·권리·가용시각·공통 시장 grid.
2. 실제 수수료·세금·금리·반복 운영비·종목 최소 단위·시장별 세션/가격 규칙.
3. 실제 장중 spread/지연/부분체결·passive queue·역선택·용량·정지 청산불능 증거.
4. D의 실제 원문·공개 경계·정정/종목/기대치·사건 군집.
5. 사전 경제 임계값·자본/위험을 맞춘 현금/시장/단순 hold/PBASE 대조, 연구/내부검증,
   성숙 라벨·반복시험/노출 통제·새 잠금 OOS와 의존성/불확실성 평가.

현재 trial의 날짜 구간은 기능용 구조이고 AUTHORED_FIXTURE_ALREADY_SEEN 노출을 기록했다.
실제 사전 등록된 연구나 잠금 OOS 통과가 아니다. config/data hash가 바뀌면 새 study가 필요하며
oos_authorized는 False다. 현재 기능 추적의 손익으로 후보를 선택하지 않았다.

## 14. KM-004 준비 상태·실제 데이터 확보 계획

전략별 완전 snapshot·exit deadline·reference 일별 panel과 고정예산 Mock Risk/OMS
연결은 준비됐다. 경제 단위와 장부/비용 계약은 유지한다. 다음 기술 단계에서도 먼저
PBASE_FIXED를 사용하고 실제 증분 경제성 없이 공분산/레짐/동적 최적화를 활성화하지 않는다.

실제 자료 확보는 [KM003_DATA_PLAN](KM003_DATA_PLAN.md)의 순서를 따른다.
사용자가 준비할 때 키 설정→짧고 제한된 기존 read-only 경로의 스키마 확인→사용권과
PIT universe·상폐·일봉·지수·권리·calendar·원문/정규화 manifest를 확보한다.
새 수집시각을 과거 공개시각으로 위조하지 않는다. Alpha A를 먼저 scoped 검증하고,
그 뒤 B/C의 실제 장중 자료와 D의 사건 자료를 확보한 범위에서 확장한다.
키 보유·소량 일봉 다운로드만으로 DATA_READY가 되지는 않는다.
**KM-004는 자동 시작하지 않았다.** 실제 거래·원격 push/PR/merge·배포도 수행하지 않았다.

## 15. 최종 GO / HOLD / BLOCKED 판정

**KM003_STRATEGY_CODE_READY_DATA_HOLD**.

기술 범위 GO: A~D 기계적 규칙·기존 SignalIntent·독립 reference·비용/가용시각·고정예산
Risk/Mock OMS 연결, 기존 164개와 신규 50개 시험, 재생·설치 빌드가 확인됐다.
실제 데이터와 수익 후보·비용 적합성·OOS는 HOLD다.
KM003_ALPHA_CANDIDATE_SCOPED 또는 ECON_GO를 부여할 근거는 없다.

**KM001_REAL_DATA_HOLD / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED** 유지.
안전계약 파손이나 필수 회귀 실패는 없어 KM003_BLOCKED는 아니며, 기술 준비를 실제
순수익 또는 실자금 주문 승인으로 해석하지 않는다.
