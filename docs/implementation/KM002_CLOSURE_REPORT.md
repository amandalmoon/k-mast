# KM-002 Milestone Closure Report

작성일: 2026-10-16 (Asia/Seoul).
판정: **KM002_LEDGER_OMS_MOCK_READY**.
추가 상태: **KM001_REAL_DATA_HOLD / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED**.

## 1. Authoritative State

| 항목 | 확인 결과 |
|---|---|
| Repository | `C:\Users\User\Desktop\k-mast` |
| Remote | `https://github.com/amandalmoon/k-mast.git` |
| Branch | 로컬 `km-002` |
| Starting HEAD | `a7bb5399ee2f65145bc91e358e0fe05c8785f9ce` |
| 검증한 Closing HEAD / 구현 Commit SHA | `9bd281209cbc0eb1b49ae917ec8396d758f47cfd` |
| 이전 구현 | `364c18f710ad0f37e094085c8cd040a6475ad718`, 시작 HEAD의 조상 확인 |
| 미커밋 파일 | 구현 커밋 직후 없음. 본 보고서와 audit.json은 후속 종료 문서 커밋에 포함 |
| 원격 작업 | 공개 공식 예제 읽기만 수행. push·배포·실계좌 접근 없음 |

Closing HEAD는 시험한 구현을 고정한 SHA다. 이 보고서 자신의 SHA를 자기참조하지 않는다.
보고서 포함 최종 HEAD는 `git rev-parse km-002`, 보고서 커밋은
`git log -1 --format=%H -- docs/implementation/KM002_CLOSURE_REPORT.md`로 확인한다.
최종 응답에는 보고서 커밋을 별도 명시한다. 이전 원본·시험·증거를 삭제하거나 덮어쓰지 않았다.
개발 중 `scenarios-v1`은 로컬 보존·Git 제외했고, 최종 증거는 `scenarios-v2`다.

## 2. 이전 마일스톤 회귀

시작 상태의 실제 재실행은 **98 PASS / 0 FAIL / 0 SKIPPED**였다.
[시작 pytest 로그](../../artifacts/km002/baseline-pytest.stdout.log),
[시작 JUnit](../../artifacts/km002/baseline-junit.xml),
[시작 정적 검사·빌드 결과](../../artifacts/km002/baseline-checks.json).
종료 때 원래 5개 시험 파일을 따로 실행해 **98 PASS / 0 FAIL / 0 SKIPPED**를 확인했다.
[종료 회귀 로그](../../artifacts/km002/regression.stdout.log).

KM-000 신호·비용·회계 항등식·주문 봉쇄, KM-001 데이터 계약·원본 98개 시험을 변경하지
않았다. root 00~07 원본, IMPLEMENTATION_BASELINE, MIGRATION, 기존 Closure Report,
KM-000/KM-001 artifacts도 시작 HEAD 대비 diff가 없다. 보호 경로와 SHA 근거는
[audit.json](../../artifacts/km002/audit.json)에 있다.

새 계약은 execution 패키지에 추가했다. 원본 NAV의 총부채를 수수료/세금/기타로 분리해
각각 한 번 차감하며, 외부 운영비는 원본 PerformanceBridge를 수정하지 않고 wrapper에
분리했다. horizon과 청산기한을 동일시하지 않고 별도 명시 기한을 도입했다.
해석과 영향은 [CONTRACT_STATUS](CONTRACT_STATUS.md#km-002-후속-구현과-계약-해석)에 기록했다.

## 3. Account Ledger

결제현금, 매도미수금, 매수채무, 매수예약, 주식/FIFO lot, 결제된 매도가능 수량,
매도예약, 배당미수금, 수수료/세금/기타부채, 자본흐름을 구현했다.
금액은 KRW Decimal 최대 소수 2자리, 주식은 정수다. 내부 계산에 float 연산을 사용하지 않는다.
체결비용 귀속은 수량 비례 내림 후 마지막 귀속에 잔액을 배정한다.

```
NAV = cash + AR - AP + marked_positions + dividend_receivable
    - other_liabilities - fees_payable - taxes_payable
```

예약금은 자산 소멸이나 비용이 아니다. 계좌/귀속의 현금·부채·수량·NAV·총손익 보존과
`NAV - capital_flows = gross_pnl + income - expenses`를 매 원자 이벤트 뒤 검증한다.
결제는 명시 eligible_dates와 override를 사용하며 금요일 거래가 다음 화요일에 결제되는
합성 사례를 검증했다. 실제 KRX 캘린더나 브로커 매도대금 재사용 승인은 아니다.

FIFO 실현/미실현 손익은 경제 원장이다. 세무 원가는 UNVERIFIED_NOT_TAX_LEDGER다.
내부 A→B 이전은 계좌 수량·NAV를 바꾸지 않고 기준가격·가상 현금·총손익을 보존한다.
origin 원가·시각·소유·기한·lineage를 유지하므로 이전으로 손실을 초기화하지 않는다.
외부 재고는 EXTERNAL로 격리하고 시작 시가를 현물 자본유입으로 기록한다. 전략의
0주 목표가 EXTERNAL을 매도하지 않는다. 정지/오래된 시세는 실제 청산 가능 가격이 아니다.

## 4. Risk Engine

L1~L5의 세션·단위·가격·신호 만기·시세 신선도, 전략 예산/보유/야간/기한/손실,
종목·업종·gross·계좌손실·현금·예약, 정지/VI/유동성·공동충격, 대사/UNKNOWN/재시작
잠금을 검사한다. EXTERNAL과 미체결 매수를 계좌 위험에 포함하며 대기 매도로 매수위험을
상계하지 않는다. 공동 위험은 명시 동시충격이며 통계 공분산 모델은 아니다.

| 한도 | demo의 합성 값 | 승인 상태 |
|---|---|---|
| 종목 / 업종 / gross | 0.8 / 0.9 / 0.95 | SYNTHETIC_ONLY |
| sleeve 노출 / 야간 노출 | 0.5 / 0.95 | SYNTHETIC_ONLY |
| 계좌 / sleeve 손실 | 5,000 / 3,000원 | SYNTHETIC_ONLY |
| 공동 충격 / 허용 손실 | 20% / 3,000원 | SYNTHETIC_ONLY |
| 유동성 참여 / 시세 나이 / 승인 수명 | 10% / 30초 / 10초 | SYNTHETIC_ONLY |
| 야간 / 청산기한 | 합성 허용 / 명시 sleeve 기한 | 실전 승인 없음 |
| 손실 상태 추가 매수 | 금지, origin 원가 기준 | 완화 설정 없음 |

한도·승인 표식이 미확정이면 HOLD다. ALLOW/REDUCE/REJECT/HOLD/
RISK_REDUCTION_REQUIRED를 이유·계좌 hash·목표 hash·정책 버전·만기와 기록한다.
ALLOW라도 경제적 무거래 조건을 통과해야 계획할 수 있다. 계획 직전 시각으로 위험을
재검사한다. 한도 초과 상태의 부분 위험감축은 허용하되 실행 불가능 시장·대사 상태는
우회하지 않는다. 정지된 재고 100주는 마지막 평가액과 함께 그대로 남는다.

## 5. OMS

INTENT→TARGET→RISK_APPROVED→SUBMITTING 이력을 생성하고 ACKNOWLEDGED,
PARTIALLY_FILLED, FILLED, REJECTED, CANCEL_PENDING, CANCELLED, UNKNOWN,
RECONCILING을 명시 전이표로 제한했다. SUBMITTING은 로컬 Mock 상태이며 전송 함수가 없다.
[전체 상태표·예약 정책](KM002_USAGE.md#주문-상태복구).

client_order_id는 계좌/목표버전/종목/방향으로 결정된다. event_id/exec_id 중복 내용은
한 번만 반영하고 같은 ID의 상충 내용은 거부한다. FILL-before-ACK와 늦은 ACK를 처리한다.
취소 요청 후 추가 부분체결과 UNKNOWN 부분체결은 불확실 상태·잔여 예약을 유지한다.
동일 목표 재요청은 기존 미체결을 다시 생성하지 않는다. 상반 대기는 HOLD한다.

SQLite WAL + FULL transaction에 이벤트와 checkpoint를 함께 저장하고 hash chain 및
genesis부터의 재생으로 복구한다. 실제 자식 프로세스의 `os._exit(77)`을 commit 직전
주입해 미커밋 분개 소멸·기존 상태 보존·OS 잠금 해제를 검증했다. 이벤트/checkpoint
변조와 checkpoint 삭제를 탐지했다. 재시작은 항상 잠금이며 Mock 계좌·주문·체결 전체
대사와 새 위험 검사 후에만 재개한다. 취소 확정도 전체 대사가 맞아야 예약을 해제한다.

동일 계좌 reference의 별도 DB 경로·프로세스에서 두 번째 작성자가 거부되는 것을
Windows에서 확인했다. 단일 호스트 OS 잠금이며 PostgreSQL·다중 호스트 fencing·HA는
미지원이다. 이미 처리한 동일 종목 체결보다 오래된 새 경제 체결은 자동 FIFO 재작성 대신
시간순 재구성 요구 오류로 중단한다. 서명 없는 hash는 악의적 전체 원장 재작성 방어가 아니다.

## 6. Portfolio

PBASE_FIXED의 명시 예산과 전체 SignalIntent snapshot으로 목표를 집계한다. 계좌 NAV×
예산을 sleeve 목표자본으로 사용하며 정수화 후 현금·위험을 다시 검사한다. A=100/B=50/
C=50에서 C의 절대 목표를 20으로 바꾸면 합계 170과 매도 delta 30이다. EXTERNAL은 별도다.
원본 SignalIntent→Aggregator→Risk→Mock 계획 경로도 시험했다.

초기 A/B/C/D 가상 현금은 4,000/3,000/2,000/500원이고 CENTRAL은 500원이다.
미투자 현금과 중앙 예비금은 보존하며 자본 자동 재배분은 하지 않는다. 원본
PortfolioDecision으로 예상 추가수익·실행비용·불확실성·benchmark·이유를 기록한다.
예상 개선 ≤ 비용+완충이면 HOLD_TARGET이다. 위험감축은 별도 RISK_REDUCTION이다.
Reference는 별도 고정 현금 Mock을 연결했고 실제 귀속 장부에 합산하지 않았다.
동적 최적화·학습된 배분·알파 모델·실전 한도·실제 청산 정책은 미승인/미구현이다.

## 7. Economic Accounting

원본 PerformanceBridge로 계좌 NAV 변화, 외부 자본흐름과 실현+미실현 총손익·이자·배당·
수수료/세금·계좌 내 운영비를 대사한다. ProjectPerformance는 계좌 밖 운영비를 별도 빼서
프로젝트 `NET_OPERATING_PNL_KRW`를 반환한다. 외부 서버비를 계좌 인출로 만들지 않는다.
외부 운영비 20원만 발생한 시험에서 계좌 NAV=10,000원, 계좌손익=0원,
프로젝트 순운영손익=-20원이었다.

배당미수 인식 후 입금은 수익 한 번이다. 입출금·내부 자본 이전은 투자수익이 아니다.
체결가에 들어 있는 spread/impact와 미체결 기회비용을 실제 PnL에서 중복 차감하지 않는다.
실제 브로커/세법 비용, 실제 배당·원천징수·권리처리, 기업행위 자동 분개와 실제 시장
원가/시각 검증은 남아 있다. 평가자료 부족 시 VALUATION_UNVERIFIED이며 수익성 검증이 아니다.

## 8. 통합 테스트 결과

최종 **164 PASS / 0 FAIL / 0 SKIPPED** = 기존 98 + 신규 66개 사례다.
신규 필수 38개 ID는 파라미터화 포함 41개 사례, 추가 경계·장애 시험은 25개 사례다.
[전체 원문 로그](../../artifacts/km002/pytest.stdout.log),
[JUnit](../../artifacts/km002/junit.xml), [전체 명령/종료코드](../../artifacts/km002/checks.json).

```powershell
.\.venv\Scripts\python scripts/verify.py --milestone km002
.\.venv\Scripts\python scripts/audit_km002.py --implementation-head 9bd281209cbc0eb1b49ae917ec8396d758f47cfd
```

| 검증 | 실제 결과와 원문 로그 |
|---|---|
| 기존 98개 회귀 | PASS, regression.stdout.log |
| Ruff / format | PASS, ruff.stdout.log / format.stdout.log |
| mypy | 42 source files PASS, mypy.stdout.log |
| sdist / wheel | PASS, build.stdout.log |
| 기존 demo | PASS, demo.stdout.log |
| A~F Mock 통합 / 저장 후 재실행 | PASS, mock-demo.stdout.log / mock-replay.stdout.log |
| 생산 장부 코드를 import하지 않는 별도 JSON 산술 검사 | PASS, independent-accounting.stdout.log |
| wheel 설치 후 체크아웃 밖 실행·6개 hash 동일 | PASS, wheel-smoke.stdout.log / wheel-detail.log |

위 로그는 모두 `artifacts/km002/`에 있다. 별도 산술 검사는 동일 작업에서 작성한 검사기로
코드 경로를 분리한 것이며 외부 감사기관의 독립 승인을 뜻하지 않는다. CI 정의를 확장했지만
원격 CI는 실행하지 않았다. 원문 .log의 CRLF는 byte 보존용 -text 설정으로 유지한다.
Git whitespace 검사의 CR 표시는 소스 코드 공백 오류로 해석하지 않는다.

| 필수 ID | 증거/범위 |
|---|---|
| LED-001~010 | 매수/매도·결제·비용·중복·순서·입출금·이전·EXTERNAL·reference |
| CASH-001~004 | 예약의 비비용성·UNKNOWN 예약·현금 정책·매도가능량 |
| OMS-001~008 | 전이·부분체결·취소·UNKNOWN·발견 체결·중복 목표·재시작·대사 오류 |
| RISK-001~007 | 종목·전략·계좌·시세/세션·손실·감축·미승인 정책 |
| PORT-001~003 | 절대 목표·버전/계좌 결합·중앙현금 |
| PNL-001~003 | 실현/미실현·계좌 밖 운영비·비용/배당 한 번 |
| OPS-001~002 | 원자 rollback/replay·프로세스 간 작성자 잠금 |
| SAFE-002 | 실제 MockBroker 주문/취소 봉쇄·execution 의존성 경계 |

각 ID의 실제 함수/행번호/파라미터 사례는 audit.json의 `tests.required_id_mapping`에 있다.
추가 25개 사례는 강제 종료, 3종 손상, UNKNOWN/취소 확정 대사, 승인 중 시세 노후화,
비용·만기 결합, stale revision, 5종 공동 한도, 청산기한, 소액 비용 귀속, overfill,
무거래, 원본 신호 통합, 상반 대기, 부분 감축, 승인 이전 체결 거부, reference 타입,
6개 시나리오의 이벤트 이식/재생을 포함한다.

| 합성 시나리오 | 최종 수량 | 최종 NAV(원) | 확인한 결과 |
|---|---:|---:|---|
| A 정상 거래 | 0 | 10,016 | 부분 매수→결제→가격 상승→매도→결제, 비용 후 +16 |
| B 목표 합산 | 170 | 9,996 | 200주에서 C 목표 20으로 변경, 30주만 매도 |
| C timeout/발견 부분체결 | 4 | 9,999 | UNKNOWN 대사·재개, 예약 64원, 주문 한 개 |
| D 현금 부족 | 0 | 10,000 | 대기 매수 600주/예약 6,005원 유지, 추가 목표 거부 |
| E 외부 재고 | 50 | 10,500 | 현물 유입 500원, 투자손익 0, 주문 없음 |
| F 손실·정지 | 100 | 9,499 | 추가 매수 중단·감축 계획·정지 후 보유/예약 지속 |

시나리오 입력/상태/journal hash는 각각
[A](../../artifacts/km002/scenarios-v2/A/manifest.json),
[B](../../artifacts/km002/scenarios-v2/B/manifest.json),
[C](../../artifacts/km002/scenarios-v2/C/manifest.json),
[D](../../artifacts/km002/scenarios-v2/D/manifest.json),
[E](../../artifacts/km002/scenarios-v2/E/manifest.json),
[F](../../artifacts/km002/scenarios-v2/F/manifest.json)에 있다. seed 표식은 20261016이며
확률 시장 모델은 없다. events.json과 final-state.json도 같은 폴더에 보존했다.
코드 SHA는 1절, 실행 당시 Windows 파일 byte SHA-256은 audit.json에 있다. 체크아웃의
자동 줄바꿈 변환은 byte hash를 달리할 수 있으며 Git commit과 논리 상태 hash로 구분한다.

개발 중 stale-quote 시험의 잘못된 과거 mark 주입을 시계 진행 방식으로 수정했고,
정적 타입/포맷 오류를 해결했다. 최종 실행에는 실패나 skip이 없다. 이후 추가한 감사
스크립트는 Ruff 검사와 실제 실행을 별도로 확인했으며 금융 실행 코드는 바꾸지 않았다.

## 9. 외부 API 준비 상태

공식 공개 고정 커밋의 잔고·주문체결·정정취소가능·매수가능 함수/필드표 및 WS 계좌 통보를
대조했다. 상세 근거는 [API_ASSUMPTIONS의 KM-002 절](API_ASSUMPTIONS.md#km-002-계좌-읽기-계약-조사-2026-10-16)과
[9개 원천 hash](../../artifacts/km002/official_account_sources.json)에 있다.
과거 주문체결 TR의 주석 CTSC9115R와 코드 CTSC9215R 충돌을 미해결로 기록했다.
정정취소가능의 PAPER 지원·계좌 상품별 권한·유량·보관기간·페이지 일관성은 미확인이다.
WS의 CNTG_YN=2 체결과 접수를 구별했지만 초 단위 통보의 고유 체결 ID는 검증되지 않았다.

BrokerAccountReader / BrokerOrderReader / BrokerFillReader와 Fake 공급자 및 대사만 구현했다.
expected_mock_snapshot은 장부에서 만든 합성 기대값이며 실제 broker observation이 아니다.
계좌 조회 endpoint는 기존 Wire 허용목록에 추가하지 않았다.
실제 KIS 인증 0회, 계좌 조회 0회, 실제 시장자료 0행, 실제 주문/취소 각 0회다.
실제 adapter 준비에는 ID·현금/부채/매도가능·체결일·결제·비용 매핑, TR 충돌 해결,
권한/페이지/시간·중복·누락 및 보안/운영 승인이 필요하다.

## 10. 최종 판정

**KM002_LEDGER_OMS_MOCK_READY**.

Gate A 장부 보존, B 주문 상태/예약/복구, C 포트폴리오 위험, D 합성 통합/재생/회귀/빌드,
E 주문 봉쇄/읽기 분리/비밀 비노출/무푸시를 위 증거의 로컬 Mock 범위에서 충족했다.
이 판정은 운영 브로커·PostgreSQL·분산 실행 준비나 실자금 주문 승인이 아니다.

**KM001_REAL_DATA_HOLD / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED** 유지.
원격 push·배포·실제 인증/주문·KM-003 시작은 수행하지 않았다.

## 11. Next Milestone Readiness

KM-003 입력은 KM-001의 PIT/가용시각/정정계보/세션/품질 상태를 가진 MarketEvent와
정규화 manifest다. Alpha A~D는 기존 SignalIntent 전체 snapshot만 생산하며 broker/OMS를
import하지 않아야 한다. 고정 자본예산·명시 청산기한과 Aggregator→Risk→MockExecution을
연결하고, 합성 Fill/Notice/Account Reader·주입 시계·journal로 실행 결과를 재현할 수 있다.

수익률·비용은 기존 ReturnUnits/Forecast와 CostModel/PerformanceBridge에 맞추고 계좌,
실제 귀속, 독립 reference 성과를 분리해야 한다. 이번 reference는 현금 최소 Mock이며
전략별 독립 체결 시뮬레이션·비용·배당/기업행위 연동은 KM-003 준비 작업이다.
현재 실제 전략 입력 데이터는 확보되지 않았다. A~D의 필요 데이터 범위·PIT 증거·거래량/
호가·기업행위·비용 가정·세션 캘린더를 확보/검증한 뒤에만 경제성 시험을 해석할 수 있다.
누수 없는 walk-forward/OOS, 반복시험 통제, 실제 비용·청산불능·운영비, 고정배분 대비
증분 성과와 위험 한도 검증이 경제성 승인 선행조건이다. **KM-003은 자동 실행하지 않는다.**
