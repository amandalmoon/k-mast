# KM-002 Mock 계좌·위험·OMS 실행 계약

## 실행

Python 3.11+와 기존 잠금 의존성을 사용한다. 키·계좌번호·네트워크 없이 실행한다.

```powershell
.\.venv\Scripts\python -m kmast.execution.demo --output data/km002
.\.venv\Scripts\python scripts/verify.py --milestone km002
```

wheel 설치 후에는 `kmast-mock --output data/km002`도 가능하다. 첫 명령을 같은 출력 경로로
다시 실행하면 저장 이벤트를 재생해 기존 manifest의 상태·journal hash를 확인한다.
SQLite가 없는 체크아웃은 `events.json`으로 SQLite를 재구성한다. 기존 증거와 다른 결과는
덮어쓰지 않고 오류로 중단한다. 정책·코드 변경 시 새 출력 디렉터리를 사용한다.
`scenarios-v1`은 개발 중 로컬 초안이며 최종 증거는 `artifacts/km002/scenarios-v2`다.

## 장부와 보존

`src/kmast/execution/`은 기존 broker 패키지를 import하지 않는 합성 실행 계층이다.
Account Ledger는 계좌 경제 상태의 권위 모델이지만 이번 입력은 전부 합성이다.
A/B/C/D, EXTERNAL, CENTRAL의 Attribution Ledger 합은 계좌 수량·NAV·총손익과 일치한다.
ReferenceSleeve는 별도 기준자본 비교 계약이다. demo는 4,000원 고정 현금 reference를
별도 출력하며 실제 계좌 또는 귀속 합계에 더하지 않는다. 실제 알파 reference 수익률은 미구현이다.

KRW Decimal, 가격·금액 소수 최대 2자리, 수량은 엄격한 비음수 정수다. 초과 소수는
자동 반올림하지 않고 거부한다. 주식 수는 lot_size 배수로 내림한다. 공동 체결 비용은
실제 체결 귀속 수량에 비례하여 앞 귀속을 0.01원 단위로 내림하고 마지막 귀속에 잔액을
배분한다. 공통 운영비 기본 귀속은 CENTRAL이며 명시적 sleeve 배분도 가능하다.
브로커 수수료·세금의 실제 원 단위 절사 정책은 미확인이다.

```
NAV = settled_cash + unsettled_receivables - unsettled_payables
    + marked_positions + dividend_receivable
    - other_liabilities - fees_payable - taxes_payable
```

수수료·세금은 other_liabilities에 재포함하지 않는 별도 부채다. reserved_buy_cash는
NAV 비용이 아니다. 보수적 현금은 settled_cash에서 매수채무·예약금·수수료·세금·기타부채를
차감하며 매도미수금 재사용을 허용하지 않는다. broker_buying_power와 withdrawal_available은
별도 관측값이다. 신규 매수는 보수적 현금과 관측 구매력 모두를 통과해야 한다.

체결일에는 주식/AR/AP 및 비용 부채를 기록하고, 주입 캘린더의 다음 두 유효 거래일에만
결제한다. 휴장일은 eligible_dates에서 제외하며 overrides로 특별 결제일을 지정한다.
예시 캘린더는 합성 정책이며 실제 KRX 결제 승인 자료가 아니다. 실제 매도 가능 수량이
없으므로 합성 정책은 결제된 재고만 매도 가능하게 취급한다.

경제적 취득원가는 FIFO이며 수수료·세금은 별도 비용이다. 세무·브로커 원가와 동일하다고
주장하지 않는다(`UNVERIFIED_NOT_TAX_LEDGER`). EXTERNAL 초기 재고는 관측 시가를 시작
경제 원가와 현물 자본유입으로 사용하고 과거 취득원가는 origin_unit_cost로 별도 보존한다.
내부 이전은 관측 기준가격으로 가상 현금을 교환하고 송신 귀속의 가상 실현손익과 수신
귀속의 새 경제 원가를 기록한다. 계좌는 그대로이며 origin 원가·시각·소유·lineage·기한은
이어진다. 물타기 판정은 원래 계좌 원가를 사용한다. 기업행위 계보 필드는 보존하지만
KM-001 기업행위를 자동 계좌 분개하는 엔진은 이번 범위가 아니다.

## 포트폴리오와 위험

`aggregate(state, budget, full_snapshots, now, version, holding_deadlines=...)`는 기존
SignalIntent의 절대 SLEEVE_NAV_WEIGHT 계약을 받아 계좌 NAV × 고정 sleeve 예산 × 목표
비중을 수량으로 내린다. 명시 예산이 현재 sleeve 자본 정책이다. 기존 미투자 현금과
CENTRAL 예비금은 보존하며 자동 자본 이전·동적 최적화는 하지 않는다. 전체 교체에서
빠진 기존 종목은 목표 0이다. 전량 현금의 빈 snapshot은 명시적 신호 만기가 없어 거부한다.
예측 horizon을 청산기한으로 임의 해석하지 않는다. 매수에는 별도 sleeve 청산기한을
제출해야 하며 미제출 시 거부한다. 여러 종목이면 보수적인 공통 sleeve 기한을 사용한다.

대기수량을 차감해 추가 delta를 구한다. 동일 목표 반복으로 기존 대기수량을 다시 주문하지
않는다. UNKNOWN/취소대기/상반 주문은 단순 상계하지 않고 HOLD한다. A 감소와 B 증가의
소유권 변경이 동시에 필요하면 명시 내부 이전 후 다시 평가한다. EXTERNAL은 주문 대상이 아니다.
계좌 전체 집중·공동충격 계산에는 EXTERNAL도 포함한다.

L1 세션·시세 신선도·단위·가격·만기, L2 예산·야간 노출·보유기한·손실,
L3 종목/업종/총노출·현금·예약·계좌손실, L4 정지/VI·제한가격·유동성·공동충격,
L5 대사·UNKNOWN·재시작 잠금을 검사한다. 공동 위험은 지정 동시 가격충격에 대한
보수적 gross 노출이며 통계 공분산 추정기가 아니다. 대기 매도는 대기 매수의 위험을
줄이는 것으로 계산하지 않는다. 합성 정책에도 승인 표식·정책 버전·모든 한도가 필요하다.

| 결정 | 의미 |
|---|---|
| ALLOW | 합성 위험 조건 통과; 경제적 무거래 검사는 별도 |
| REDUCE | 증가 주문 없는 명시적 위험감축이며 실행 제약 통과 |
| REJECT | 확정된 단위·현금·한도·시장 제약 위반 |
| HOLD | 정책/대사/시세 미확인, 충돌 또는 추가 delta 없음 |
| RISK_REDUCTION_REQUIRED | 신규 증가 시 손실 또는 원래 보유기한 위반 |

승인은 계좌/목표 hash, 정책, 이유, 만기와 함께 저장한다. 계획 직전 현재 시각으로 위험을
다시 검사한다. PortfolioDecision의 예상 추가수익 > 실행비용+불확실성 조건을 충족하지
못하면 HOLD_TARGET이며 주문이 없다. 위험감축은 그 경제성 조건과 분리한다. 한도 초과
상태에서 부분 매도로 위험을 줄일 수 있지만 정지·VI·미대사 등 실행 불가능 조건은 통과하지 못한다.
정지된 주식은 장부에 계속 남으며 마지막 가격은 청산 보장이 아니다.

## 주문 상태·복구

정상 생성 이력은 INTENT → TARGET → RISK_APPROVED → SUBMITTING이다. SUBMITTING은
로컬 모의 상태이고 실제 전송 함수는 없다. 전체 허용표는 models.TRANSITIONS에 고정한다.

| 현재 | 주요 다음 상태 |
|---|---|
| SUBMITTING | ACKNOWLEDGED / PARTIALLY_FILLED / FILLED / UNKNOWN / REJECTED |
| ACKNOWLEDGED | PARTIALLY_FILLED / FILLED / CANCEL_PENDING / UNKNOWN |
| PARTIALLY_FILLED | PARTIALLY_FILLED / FILLED / CANCEL_PENDING / UNKNOWN |
| CANCEL_PENDING | CANCEL_PENDING / FILLED / CANCELLED / UNKNOWN |
| UNKNOWN | UNKNOWN / RECONCILING / FILLED |
| RECONCILING | ACKNOWLEDGED / PARTIALLY_FILLED / FILLED / CANCELLED / REJECTED |
| FILLED / CANCELLED / REJECTED | 종료, 역전이 없음 |

ACK보다 FILL이 먼저 와도 실제 모의 체결을 반영한다. 늦은 ACK는 신원만 확인하며 상태를
되돌리지 않는다. 취소 요청 후 부분체결은 CANCEL_PENDING을 유지한다. 취소 확정은 최종
누적 체결량 증명이 필요하다. UNKNOWN의 부분체결도 불확실 상태와 잔여 예약을 유지한다.
정확한 exec_id+내용은 한 번만 반영하며 같은 ID의 다른 내용은 거부한다. event_id도 원자적으로
중복 제거한다. client_order_id는 계좌·목표버전·종목·방향으로 결정된다.

SQLite WAL+synchronous FULL의 한 transaction에 이벤트, hash chain, checkpoint를 저장한다.
재시작은 genesis부터 전부 재생하여 상태/hash/checkpoint를 검증하고 항상 런타임 잠금으로
시작한다. Mock snapshot과 체결 사실의 수량·현금·AR/AP·수수료/세금·예약·주문 전체를
대사한 뒤 재개한다. 최종 취소 상태는 대사 전체가 일치할 때만 예약을 해제한다.
새로 발견한 체결 사실은 대사 불일치 때도 보존하고 처리 잠금을 유지한다.

ACK/FILL 순서 역전은 지원한다. 이미 처리된 동일 종목 경제 체결보다 더 오래된 새로운
체결은 FIFO를 조용히 바꾸지 않고 명시적 시간순 재구성 필요 오류로 차단한다. 임의 과거
체결/기업행위 삽입을 자동 수선하는 운영 도구는 미구현이다.

계좌 내부 reference를 기준으로 OS가 보유하는 파일 잠금을 사용한다. 동일 호스트의 다른
DB 경로·다른 프로세스도 같은 계좌의 두 번째 작성자가 될 수 없다. 프로세스 종료 시 OS가
잠금을 해제한다. TTL 기반 강제 인수는 없다. 이 검증은 Windows 단일 호스트 로컬 범위다.
공유 네트워크 파일시스템, 여러 호스트, PostgreSQL fencing/lease, 고가용성은 미지원이다.
hash는 우발/단순 변조 탐지이며 서명·외부 anchor가 없는 악의적 전체 재작성 방어는 아니다.

## 경제성 대사와 범위

`MockExecution.performance(start, starting_nav, opening_state)`는 기존 PerformanceBridge를
계좌 NAV 변화와 외부 자본유입으로 대사한다. 계좌 밖 운영비는 ProjectPerformance에서
별도 차감한다. 계좌 현금을 허위 인출하지 않는다.

```
project NET_OPERATING_PNL_KRW
 = account gross market PnL + interest + dividend
 - explicit fees/taxes - account paid operating costs - externally paid operating costs
```

배당은 미수 발생 때 수익으로 인식하고 지급 때 미수→현금만 이동한다. 입출금과 내부 배분은
자본 흐름이다. 체결가격에 내재한 spread/impact나 미체결 기회손익을 재차 빼지 않는다.
기간 시작 NAV와 opening_state는 같은 경계로 제출해야 한다. 미평가·오래된 시세는 성과와
함께 VALUATION_UNVERIFIED로 표시한다. 이 결과는 Mock 코드 검증이며 실제 수익 증거가 아니다.

실제 KIS 계좌 Reader, 체결 통보 암호 해독/고유 체결 식별, 운영 대사, 실데이터·수수료·세금,
실전 위험 승인과 PostgreSQL 운영 검증은 미완료다. 기존 KM-001의 시세 읽기 허용목록에는
계좌 endpoint를 추가하지 않았다. 어떤 설정도 이 패키지에 실전 주문 기능을 만들지 않는다.
