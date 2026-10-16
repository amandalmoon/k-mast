# KM-003 전략 코드와 기능 검증

## 실행

기존 잠금 의존성과 Python 3.11+를 사용한다. 기본 실행은 네트워크·키가 필요 없다.

```powershell
.\.venv\Scripts\python -m kmast.simulation.cli --output data/km003
.\.venv\Scripts\python scripts/verify.py --milestone km003
```

설치된 wheel에서는 `kmast-alpha`도 가능하다. 같은 출력 경로로 재실행하면 context,
config, signal, reference, metrics, trial 불변 파일과 Mock journal hash를 대조한다.
정책/코드/데이터 변경 시 새 출력 경로를 사용한다. 과거 결과를 덮어쓰지 않는다.
개발 중 초안은 로컬 `data/km003-draft1`에 남겼으며 최종 증거는
`artifacts/km003/functional-v1`이다. SQLite는 Git에 넣지 않고 논리 이벤트/상태를 보존한다.

## 책임 경계와 입력

기존 `strategies/interfaces.py` 및 ARCH-01 시험을 변경하지 않았다. 새 순수 규칙 구현은
`kmast.alpha.rules.decide(Context, AlphaConfig, revision)`다. broker, network, OMS를
import하지 않으며 ALPHA-001이 alpha 패키지 전체의 의존성/동적 실행을 검사한다.
기존 MarketEvent만으로 OHLCV·호가·유니버스를 추측하지 않는다. KM-001 Observation의
`complete`, quality, RAW, KRX, REGULAR, 명시 봉 경계를 검사하는 `observation_bar` 어댑터와
별도 typed Context를 사용한다. 품질 잠금을 제거해 전략에 밀어 넣지 않는다.

Bar는 완료시각과 available_at, 실제 거래 notional/volume, raw 가격을 가진다. 현재
가격·종목 유니버스·지수·호가·과거 동일 경과시간 거래량·사건 baseline을 각각 가용시각으로
검사한다. 누락 봉을 압축하거나 0으로 채우지 않으며 explicit grid가 필요하다.
벤치마크는 단일 일별 시계열이다. 실제 조정/분할 연속성이 해결되지 않은 종목은 A가
진입하지 않는다. 원본의 source_hash/data_origin을 이어받으며 REAL_UNVERIFIED는 승인이 아니다.

결과는 기존 비음수 절대 SignalIntent 전체 snapshot이다. 이전 소유 종목도 snapshot에
포함하고 제외·상폐·만기에는 0을 출력한다. target_weight 합은 1 이하이며 현재 보유의
추가 매수로 손실을 물타기하지 않는다. 실제 LIVE 자본 가중치는 Literal 0이다.
신호 만기, 예측 horizon, 원래 포지션 exit_deadline, 가장 이른 체결 시각은 서로 구분한다.

## 동결 후보 카드

모든 수치는 `candidate-v1`의 **연구 가정**이며 최적값/실전 한도가 아니다. 이 버전에는
튜닝 탐색·레짐·동적 최적화가 없다. 네 슬롯이 있다고 네 전략에 실전 자본을 배분하지 않는다.

| 전략 | 경제 가설·대립 설명 | 진입·입력 | 유지·종료·실패 |
|---|---|---|---|
| A TREND_RS | 정보의 점진 반영/지속 자금배분; 시장·업종 상승 대용일 수 있음 | 기본 이전 20개 유효 일봉 high 돌파, 같은 시각 지수 대비 수익률 차이≥0, turnover≥1,000, ATR/가격에 1% 변동성예산으로 크기 조절·상한 25% | 기존 포지션은 이전 창 평균 이상이면 유지, 원래 5일 상한·5% 손실 무효화·유니버스 제외 시 0; V자 반전/분할 연속성/정지 위험 |
| B ORB_MOMO | 개장 수요 불균형의 지속; 단순 시장 추세일 수 있음 | 완성 5분 또는 15분 범위 후 별도 완성 분봉 종가가 상단 돌파, 실제 누적 notional VWAP 이상, 이전 세션의 같은 경과시간 RVOL≥1.2 | 돌파/필터 실패·stop·장중 deadline이면 0; 범위 완료 전 고가나 하루 전체 거래량 금지 |
| C MEAN_REV | 일시적 유동성 충격의 복원; 정보충격/역선택일 수 있음 | fresh midquote가 실제 VWAP보다 1% 이상 낮음, spread≤0.5%, 사전 유동성 회복 표식, 정보충격 표식 없음 | 이격 해소·stop·장중 deadline이면 0; 체결가 bounce만으로 진입하지 않음, 손실 중 증액 없음 |
| D EVENT_FLOW | 사건별 예상/과거 기준 대비 차이의 지연 반영; 사전 반영·수급 노출일 수 있음 | EARNINGS_SEASONAL은 사전 계절 기준 대비 실적, BUYBACK_EXECUTED는 사전 기준 대비 실제 취득량, INDEX_DEMAND는 사전 기준 대비 확인 수요를 각각 별도 config로 선택 | 5일 상한·stop·정정된 기준 차이 음전 시 0; 기본 실행은 EARNINGS_SEASONAL, 컨센서스 surprise로 부르지 않음 |

A의 종가 판단은 다음 eligible session 이후만 체결할 수 있다. 장중에 전일 일봉으로
재평가할 때에는 현재 정규장 시각 이후가 최초 체결 시각이다. B/C의 forecast horizon과
deadline은 당일 세션 종료를 넘지 않는다. 주문 TTL 기본 1분은 청산기한을 갱신하지 않는다.
ATR·stop은 확인한 봉/호가를 바탕으로 **목표**를 바꾸며 봉 내부 stop 체결을 만들어내지 않는다.

D는 receipt_date를 장중 시각으로 치환하지 않는다. exact published_at이 없으면 주입
캘린더의 다음 세션 이상을 사용한다. baseline은 공개 경계 이전에 알려져야 한다.
event family의 정정은 동일 계보에서 최신 가용 revision을 선택하며 소비된 사건은 재진입하지
않는다. 자동 DART 원문 해석·컨센서스/수급 추정은 없다. 세 메커니즘이 공통 점수에 섞이지 않는다.

## 독립 reference

각 RefState는 REFERENCE 타입·독립 고정자본·현금·FIFO lot·의도·거절·체결·미체결·비용·
실현/미실현·분할/배당·일별 NAV를 보존한다. 계좌에 합산하지 않는다. 실제/귀속 장부는
KM-002를 그대로 사용하며 연결은 상위 `simulation.bridge`에서만 한다.

체결은 의사결정 **후**의 명시 Tick이 필요하다. ask/bid와 불리한 slippage, 가격상한,
실제 제공된 수용수량×참여 가정, lot_size, 만기·시장 종료를 검사한다. 봉 high/low로
유리한 내부 순서를 추정하지 않는다. 지정가 touch나 마지막 체결가만으로 수동 주문의
queue 체결을 인정하지 않는다. passive 미체결은 만기·수량·예약과 함께 남는다.
실제 호가 잔량이 체결을 보장한다는 가정은 승인되지 않았으며 현재 Tick은 전부 합성이다.

시뮬레이션 체결은 즉시 현금 결제의 경제적 reference다. 운영 계좌의 T+2/매도가능/예약은
기존 KM-002에서 별도로 검사한다. reference로 실제 구매력·결제 가능성을 인증하지 않는다.
분할은 수량과 경제 원가를 역비례 조정하고 배당은 현금에 한 번 반영한다. RAW 가격만
사용하므로 조정가격 배당 이중 반영 경로가 없다. 소수주·cash-in-lieu·대기 주문이 있는
권리처리는 자동 추정하지 않고 오류로 보류한다. 과거 권리의 늦은 입력은 replay가 필요하다.

손익은 `NAV-capital = realized + unrealized + dividends - costs - operating_costs`로
대사한다. slippage는 실제 모의 체결가에만 넣고 명시비용에서 재차 빼지 않는다.
무거래일·현금일·손실 미청산 재고를 공통 일별 panel에 포함한다. 중간 외부 자본흐름을
지원하지 않는 고정자본 reference이므로 TWR는 panel의 연쇄 NAV 수익률이다.
현금 비교는 같은 초기자본과 같은 운영비를 차감한다. 비영(非零) 현금 이자 입력은 합성
대안이며 운영비를 마지막 시점 차감하는 단순 비교다. 실제 금리/청구일은 미검증이다.
미체결 수량과 거절 수량은 주문 단위 설명값이며 독립 거래 기회나 놓친 PnL로 바꾸지 않는다.

metrics에는 gross/거래비용 후/운영비 후 손익, 평균 NAV, TWR, 현금초과, drawdown,
회전율, 청산된 수량의 평균 보유시간, peak 자본/예약, 체결/거절/미체결이 있다.
독립 표본 수는 추정하지 않고 null이다. 실제 시장 기준선 성과도 자료가 없어 null이다.

## 연구 기록과 판정

각 config/context/signal/reference/trial/metrics와 hash를 불변 저장한다. ResearchPlan의
연구/내부검증/잠금 OOS는 겹칠 수 없고 config·data hash 변경 시 새 등록을 요구한다.
현재 날짜 구간은 기능시험용 예약 구조이며 실제 시장 연구 분할이 아니다. Fixture를 이미
봤다는 노출 기록을 보존하고 `oos_authorized=False`로 고정했다. OOS를 실행하거나 통과하지 않았다.

DataEvidence는 실제 행 수·기간·유니버스·상폐/정지·권리·시각·시장·라이선스·비용·원문 hash가
모두 있어야 제한된 준비 상태를 표시한다. 준비 상태만으로 경제 승인은 없다. 실제 데이터가
없는 현재 실행은 항상 KM003_STRATEGY_CODE_READY_DATA_HOLD다.
완료된 기술 시험과 실제 수익성/OOS/LIVE 승인은 별개다.
