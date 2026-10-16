# KM-001 Milestone Closure Report

작성일: 2026-10-16 (Asia/Seoul).
최종 판정: **KM001_ADAPTER_READY_DATA_HOLD**.
추가 상태: **ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED**.

## 1. Authoritative State

| 항목 | 실제 상태 |
|---|---|
| Repository | `C:\Users\User\Desktop\k-mast` |
| Branch | `km-001` (기존 km-000에서 새로 생성) |
| Starting HEAD | `27ca35ee29639a3e3f05780da9210515cb3667ae` |
| Closing HEAD / 구현 Commit SHA | `364c18f710ad0f37e094085c8cd040a6475ad718` (실행 코드·Fixture·검사 로그) |
| 미커밋 변경 | 구현 커밋 직후 없음. 본 보고서·시험 ID 색인은 후속 문서 커밋으로 추가 |
| 외부 push | 없음. Git remote도 없음 |

Closing HEAD는 검증한 구현을 고정한 SHA다. 보고서 자신의 SHA를 본문에 자기참조하지 않는다.
보고서 추가 후 최종 HEAD는 `git rev-parse HEAD`, 보고서 커밋은
`git log -1 --format=%H -- docs/implementation/KM001_CLOSURE_REPORT.md`로 확인한다.
기존 변경·원본 명세·KM-000 증거를 보존했다. 개발 중 초기 Fixture 출력 폴더는 로컬에
보존하고 Git에서 제외했으며, 최종 증거는 `artifacts/km001/fixture-data-v1/`만 사용한다.

구현 파일: `brokers/kis/{requests,wire_contract,network,pagination,stream}.py`, `ws_columns.json`,
`data/{models,parsers,store,pipeline,readiness,sessions,dart,cli}.py`, 합성 `fixtures/market.json`,
신규 테스트 2개 파일, 공식 자료 감사/Fixture 생성/wheel smoke/로컬 감사 스크립트.
수정 파일과 전체 생성 목록은 `git diff --name-status 27ca35e 364c18f`로 재현할 수 있다.

## 2. KM-000 회귀시험

시작 시 **48 PASS / 0 FAIL / 0 SKIPPED**를 직접 재실행했다.
기존 `artifacts/km000/environment.json`의 소스 해시를 실제 파일과 대조한 결과 불일치 0이었다.
`c464c80…` 구현이 현재 HEAD의 조상이며 후속 `27ca35e…`는 보고서 추가임을 확인했다.
[시작 로그](../../artifacts/km001/baseline.stdout.log), [시작 JUnit](../../artifacts/km001/baseline-junit.xml).

종료 시 기존 테스트 파일 3개를 별도 실행해 **48 PASS / 0 FAIL / 0 SKIPPED**를 확인했다.
[종료 회귀 로그](../../artifacts/km001/regression.stdout.log).
신호·비용·회계·연구 승인·주문 봉쇄 계약과 기존 48개 시험 조건을 변경하지 않았다.
기존 core 및 시험 파일의 diff가 없다는 결과는 [로컬 감사](../../artifacts/km001/audit.json)에 있다.

기존 TokenManager에는 실제 인증 I/O 중 시계가 진행되면 새 토큰을 미래 발급으로 오판할
가능성이 있었다. 발급 후 현재 시각을 다시 읽는 한 줄을 추가하고 지연 발급 시험을 실행했다.
conftest에는 신규 합성 데이터 Fixture만 추가했다.

개발 중 신규 시험의 Fixture scope 오류 2건과 신규 시험의 DataError import 누락 1건을
수정했다. 정적 검사에서 발견한 포맷·미사용 변수·타입 주석도 수정했다.
실패 조건을 삭제하거나 기존 검증을 완화하지 않았다. 최종 실행에는 실패/오류가 없다.

## 3. KIS API 연동

공식 commit `2077773a69a428daf63e148182511f068cc45de3`, 최초 확인 시각 2026-10-16
19:39:58 KST. 15개 공식 파일의 경로·URL·hash는 [official_sources.json](../../artifacts/km001/official_sources.json).
[공식 저장소](https://github.com/koreainvestment/open-trading-api)와
[KIS 포털](https://apiportal.koreainvestment.com/intro)을 읽었다.
전체 파라미터·응답·지원 제약은 [API_ASSUMPTIONS](API_ASSUMPTIONS.md)에 기록했다.

| 기능 | Endpoint (quotations 아래) | TR ID | 구현 범위 |
|---|---|---|---|
| 일봉 | inquire-daily-itemchartprice | FHKST03010100 | real/demo, 원/수정주가, bounded backward cursor |
| 당일 분봉 | inquire-time-itemchartprice | FHKST03010200 | real/demo, 미래 cursor 차단·미완성 잠금 |
| 과거 분봉 | inquire-time-dailychartprice | FHKST03010230 | 실전 읽기만, PAPER 미확인으로 거부 |
| 현재가 | inquire-price | FHKST01010100 | real/demo, 누적량과 단일 체결 분리 |
| 호가 | inquire-asking-price-exp-ccn | FHKST01010200 | real/demo, 원천 시각 불명 시 잠금 |
| 지수 | inquire-index-price | FHPUP02100000 | U/KOSPI 0001·KOSDAQ 1001, PAPER 미확인으로 거부 |
| 실시간 체결/호가 | 공식 WS 환경별 주소 | H0STCNT0 / H0STASP0 | KRX 시세만, 구독/해제·ACK·heartbeat·유한 재연결 |

REST는 정확한 환경 endpoint와 고정 quotation 경로만 허용한다. POST는 tokenP/Approval
두 인증 경로만 허용하며 주문/취소/토큰폐기 등의 다른 POST는 차단한다. 호출수·심볼·날짜·
timeout·크기·재시도 수를 제한하고 계좌/환경/TR pacing을 공유한다. 일반 공지의 숫자를
사용자 계좌의 보장 한도로 사용하지 않았다.

WS 시험은 FakeSocket으로 구독·해제 ACK, PINGPONG, 예산·보유종목 우선순위, payload 검증,
gap, 자동 reconnect, 새 세대 ACK 이후 snapshot_provider 재동기화와 stale lock을 검사했다.
원천 시각을 확인할 수 없는 quote를 fresh snapshot으로 승인하지 않는다. 유실 틱을 생성하지 않는다.

실제 KIS 인증/REST/WS 연결은 **미실행**이다. 성공 결과는 가상 응답과 가짜 전송 객체에
대한 계약 시험이다. 실제 사용자 조회 성공/실패 건수는 모두 0이며 이를 실제 연결 PASS로
기록하지 않는다. 공식 포털 개별 TR 직접 조회와 유량 공지 본문은 접근/timeout 제약이 있어
Git 공식 샘플 위주로 대조했다. 포털/샘플 충돌 유무와 사용자 계좌 적용 사양은 미확인이다.

## 4. 데이터 수집 결과

**실제 종목/확보 기간/시장자료: 없음 / 없음 / 0행**.
사용자가 이번 작업에 실제 연결 승인이나 자격 구성을 제공하지 않았으므로 자격정보를
탐색하거나 인증하지 않았다. 사용자 요청에서 허용한 검증 가능한 Fixture 경로를 실행했다.

합성 자료는 005930 형태의 문자열 종목코드와 KOSPI 0001을 사용한다. 2026-10-14~16은
Fixture의 날짜이며 해당 종목의 실제 시세가 아니다. Daily 2, minute 1, price snapshot 1,
quote snapshot 1, index 1, WS trade 1, WS quote 1 = **시장 스키마 8행**, 공시 2행이다.
원본 JSON **9개**, normalized market Parquet+manifest **7세트**, 공시/경제원천/가용성 JSON을 생성했다.

원본은 민감 필드/자유형 메시지/주입된 비밀을 제거한 JSON이다. 원천 hash는 이 보존 대상의
canonical bytes 기준이며 미가공 HTTP 응답 전체 hash라고 주장하지 않는다. 원본 식별자 충돌은
quarantine에 보존하고 중단한다. 재실행은 원본 캐시를 사용해 중복 다운로드하지 않는다.
소스 hash·요청 fingerprint·parser 버전·시점·run ID를 연결하며 load 시 raw/Parquet/manifest를 대조한다.

- [실행 요약](../../artifacts/km001/fixture-data-v1/run_summary.json)
- 일봉 원본 `source_hash`: `b80e0e407a44d77f74af27fc73f3eb10210a3e0e6d286f2a75d657487ab7788e`
- 전체 normalized hash: `b410fd47bf92216af367078c79168dd469e35e9f98571ed68921f29f53dc5cb6`
- 모든 개별 파일 hash: [audit.json](../../artifacts/km001/audit.json)의 evidence_hashes

합성 데이터에서는 0거래량을 유지했고 필수 수치 누락은 오류로 처리했다. 실제 거래일 grid가
없어 결측률은 null이며 0%로 표시하지 않았다. 날짜만 있는 일봉은 event_time을 만들지 않는다.
불완전 분봉·봉 라벨·수정계수 계보·호가 날짜/시각·세션 미확인 상태는 품질 플래그로 잠근다.
원본/정규화 저장의 재실행, 다른 저장소에서의 byte 일치, 손상 감지 및 결정적 재생을 시험했다.

## 5. Alpha별 데이터 준비 상태

| Alpha | 상태 | 실제 기간·해상도 | 부족한 데이터 | 실제 수익성 시험 / 실행비용 근거 |
|---|---|---|---|---|
| A | DATA_BLOCKED | 없음 | 충분한 일봉·PIT universe·지수/업종·기업행위·상장폐지 | 불가 / 실제 근거 없음 |
| B | DATA_BLOCKED | 없음 | 완료 ORB·VWAP/RVOL·지연·spread·부분체결 | 불가 / 실제 근거 없음 |
| C | DATA_BLOCKED | 없음 | 체결/호가·VWAP·유동성·역선택 | 불가 / 실제 근거 없음 |
| D | DATA_BLOCKED | 없음 | 실제 공시·PIT 공개 경계·정정/매핑·사전 기대 기준 | 불가 / 실제 근거 없음 |

[기계 행렬](../../artifacts/km001/fixture-data-v1/DATA_AVAILABILITY_MATRIX.json)과
[설명 행렬](DATA_AVAILABILITY_MATRIX.md)을 제출한다. 실제 자료가 들어와도 license·기간/
정밀도 승인·PIT·coverage·전략별 근거가 없으면 READY가 되지 않는다. DATA_READY 자체도
경제성 또는 LIVE 승인은 아니다.

## 6. 경제성 입력 준비

commission, tax, spread, liquidity, lot size, buying power, settled cash, receivables,
payables, cash interest, server/data/service costs의 **13개 버전 계약**을 연결했다.
[경제 원천 상태](../../artifacts/km001/fixture-data-v1/economic_sources.json)는 모두
UNVERIFIED/null이다. 실제 비용·세금·이자·운영비를 임의로 채우지 않았다.

호가·수량은 합성 schema 시험만 존재한다. 슬리피지/시장충격/부분체결·역선택 추정의
실증 근거는 없다. raw 가격과 기업행위 효과를 구분하고 adjusted 가격에 배당/수량 효과를
더해 이중 계상하는 계약을 거부한다. 실제 회계 반영은 KM-002 범위다.
`NET_OPERATING_PNL_KRW`와 단일 비용 계상, 외부/내부 자금흐름 분리 계약은 유지한다.

## 7. 테스트 및 품질 검증

실제 명령:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pip install pyarrow==21.0.0 websockets==15.0.1
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python scripts/verify.py --milestone km001
.\.venv\Scripts\python scripts/wheel_smoke.py
.\.venv\Scripts\python scripts/audit_km001.py
```

최종 **98 PASS / 0 FAIL / 0 ERROR / 0 SKIPPED**. 기존 48개 + 신규 50개다. 시작/중간/종료
테스트 수를 합산하지 않았다. 필수 KM-001 고유 ID **25개 모두 PASS**:
KIS-001~007, DATA-001~012, DART-001~002, ECON-001~002, SEC-002, SAFE-001.
[ID별 실행 색인](../../artifacts/km001/test_matrix.json), [JUnit](../../artifacts/km001/junit.xml),
[pytest 원문](../../artifacts/km001/pytest.stdout.log).

Ruff check/format, mypy(32 source files), sdist/wheel 빌드, 기존 demo, 신규 data-demo,
기존 48개 회귀가 모두 PASS다. [명령·exit code](../../artifacts/km001/checks.json).
wheel을 `--no-index --no-deps --target`으로 임시 경로에 설치한 뒤 저장소 밖 cwd에서
package data/Parquet/Fixture CLI를 실행했고 normalized 결과가 checkout 실행과 같았다.
[wheel smoke 로그](../../artifacts/km001/wheel-smoke.log).

테스트에서는 socket connect/DNS를 전역 차단하고, HTTP/WS는 FakeWire/FakeSocket 또는
가짜 HTTPSConnection으로 검증했다. 실제 KIS/DART 연결 시험은 **NOT_EXECUTED**이며
오프라인 PASS와 구분한다. GitHub Actions를 갱신했지만 원격 CI는 실행하지 않았다.
로컬 Windows/Python 3.12.10에서만 실행했고 Linux/Python 3.11 실측을 주장하지 않는다.

JUnit SHA-256: `5e09cab19ce3dfd926fba53addf74c7d91088656373324e7da52dfffad7a7faf`.
감사 JSON SHA-256: `7e56adf944655f444a35ae3e05d20f54f52a916c79da62ab1fc20be75ebf0b41`.
이 hash는 실행 당시 로컬 파일 bytes를 기준으로 한다. 테스트 증거는 코드·데이터·설정별
감사 manifest와 함께 보존했으며 원본 문서 QA를 금융 성과 시험으로 합산하지 않았다.

## 8. 보안 및 거래 차단

실제 주문 호출 **0**, 실제 취소 호출 **0**, 실제 인증·계좌/시세 조회 **0**.
공식 문서 웹 열람과 의존성 설치는 수행했다. 실제 자격정보를 읽거나 로그/Git에 기록하지 않았다.
새 네트워크 코드의 기본 permit은 false다. CLI read는 명시 network 플래그·보호된 로컬
credential 파일·pacing을 모두 요구한다. 키는 채팅에 요청하지 않는다.

경로/TR/파라미터 허용목록·환경 분리·권한·총 요청수는 transport 경계에서도 검사한다.
HTTP redirect는 따르지 않는다. raw 응답/로그에 인증 헤더를 저장하지 않고 공개 종목명과
private HTS identity를 구분해 정제한다. 외부 오류 텍스트는 출력하지 않는다.
새 REST/WS 객체의 submit_order/cancel_order는 모두 PermissionError다.
기존 Runtime LIVE 차단과 order_enabled/live_enabled=false 계약을 유지했다.

## 9. Blocker

- 실제 읽기 연결에 대한 별도 사용자 허용과 로컬 자격 구성, 계좌 환경·API 권리 미확인.
- 계좌/앱키/TR별 유량·burst·신규 고객 제한·WS 슬롯·세션 코드 미확인.
- 포털 TR 직접 확인의 접근 제약, 실제 response/지원 환경·보관기간·페이지 연속성 검증 필요.
- 과거 분봉/체결/호가·상장폐지·시점별 universe·기업행위·업종 이력의 실제 확보와 저장권한 없음.
- 봉 라벨·확정 시각·source clock·DART 최초 공개 경계의 근거 부족.
- 실제 수수료·유효일별 세금·현금/결제·운영비·사용자 자본·위험 감내 및 평가정책 미정.
- 분산/다중 프로세스 limiter, 대규모 수집, 실제 DART downloader, full exchange calendar는 미구현.

위 사항은 실제 DATA_READY/경제성 승인 blocker다. 오프라인 어댑터·계약·재현성 경로의
미해결 안전 장애와 구별한다. 현재 코드의 읽기 구현에 대한 실계좌 통합 검증은 남아 있다.

## 10. 최종 판정

**KM001_ADAPTER_READY_DATA_HOLD** — 공식 규격 대조를 반영한 읽기 코드와 오프라인
수집/저장/재생 경로, 98개 시험·정적/타입/빌드·wheel 증거를 제출했다. 실제 자료·권리·
기간·품질 근거가 없어 KM001_DATA_READY_SCOPED를 부여하지 않는다.

**ECONOMIC_EDGE_UNVERIFIED** — 실제 수익성 백테스트/OOS/실행비용 실측을 수행하지 않았다.
**LIVE_NOT_APPROVED** — 실전 모드·주문·취소·자금배분 권한을 활성화하지 않았다.

## 11. 다음 단계 준비 상태

KM-002는 이번 Provenance/Observation, PIT 종목·세션·기업행위, EconomicSource 및
기존 CapitalBudget/RiskDecision/PerformanceBridge 계약을 사용할 수 있다. Fixture 기반
Ledger/Risk/OMS 개발은 가능하나 실제 계좌 승인이 되는 것은 아니다.

실계좌 연동 전 필요한 자료는 다음과 같다.

- 계좌별 versioned 보유수량·매도가능/예약수량·EXTERNAL 귀속·취득원가.
- settled cash, AR/AP, 결제일·매도대금 재사용·broker buying power·출금 가능액의 구분.
- client/broker order ID, 승인 decision/target/account version, 주문시도·ACK·취소대기·부분체결 상태.
- exec ID·체결수량/가격·실제 fee/tax·정정/중복 계보, UNKNOWN 조회/대사와 재전송 금지 규칙.
- 분할/배당 권리·지급·유효일, 비용 schedule, 손익/현금/수량 보존, 단일 writer 복구 규약.

현재 market-data capability에는 계좌 잔고/주문/체결 통보 경로를 넣지 않았다. 해당 읽기
계약은 공식 사양·사용자 계좌 권한을 확인한 뒤 KM-002에서 별도로 설계·시험해야 한다.
**KM-002, 원격 push·배포·실제 매수/매도/취소는 시작하지 않았다.**
