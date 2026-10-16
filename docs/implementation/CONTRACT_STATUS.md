# KM-000 계약 상태

판정 범위: v1.2 오프라인 스키마·검증기·재생·Mock. 수익성/실거래/OOS 승인이 아니다.

| 요구 | 구현 | 증거 |
|---|---|---|
| TASK-001 | core/config.py, configs/*.yaml, 주문 봉쇄 | CFG-01/02, broker tests |
| TASK-002 | events.py, clock.py, PointInTime | DATA-01/02, publication/label tests |
| TASK-003 | SignalIntent, TargetSnapshot, SnapshotStore | SEM-01~04 |
| TASK-004 | CapitalBudget, CashResidual, StrategyTarget, PortfolioTarget, PortfolioDecision, RiskDecision, RiskLimitSnapshot | PORT-01/03/04/05 |
| TASK-005 | PerformanceBridge 계좌 NAV 대사 | COST-02, PNL-01/02 |
| TASK-006 | ReturnUnits, Forecast, validate_optimizer_inputs | COST-01, PORT-04 |
| TASK-007 | StudyContract, study.yaml, G3 HOLD | VAL-08 |
| TASK-008 | AuthProvider, TokenManager, ReadRoute, KISReadAdapter, AccountRateLimiter, StreamState, MockBroker | test_broker.py, API_ASSUMPTIONS.md |
| TASK-009 | normalize, replay, 해시·정정 계보·주입 시계 | DATA-03, REPLAY-01, corrections test |
| TASK-010 | pyproject, lock, pytest/ruff/mypy/build, CI, AGENTS | artifacts/km000/checks.json |

## 정책

- 금액/비중은 유한 Decimal, 수량은 비음수 정수, 알 수 없는 필드는 거부한다.
- 모든 계약은 frozen. 신뢰 경계에서 model_validate를 사용한다. Pydantic의 검증 우회용
  model_construct/model_copy(update=...)는 운영 입력에 사용하지 않는다.
- snapshot은 완전 교체만 지원한다. expected_symbols는 생산자가 제출하는 완전성 manifest다.
  누락된 종목은 새 목표 0의 의미다. 외부 전략 유니버스 대사·DB transaction은 KM-002 범위다.
- 동일 source/event_id 및 동일 내용은 중복 제거한다. 내용이 다르면 오류로 중단한다.
  정정은 새 ID와 supersedes_id, 증가 revision을 가져야 한다. 갈라지는 정정 계보는 거부한다.
- 재생은 available_at, received_at, source, event_id로 안정 정렬한다. event_time으로 과거에
  앞당기지 않는다. 늦게 온 과거 이벤트도 원래 발생시각을 유지한다. 미래 가용 입력은 거부한다.
- 정정 전 이벤트는 삭제하지 않는다. 입력 hash, 출력 hash, 코드/설정/시계/정정 정책을 보존한다.
- historical availability는 acquired_at과 공개 근거를 필수로 받고 수집일을 공개일로 치환하지 않는다.
- 비용 후 실현수익은 별도 타입이다. gross 예측/위험 단위가 일치해야 최적화 입력 검증을 통과한다.
  최적화 알고리즘과 기간 변환은 미구현이다.
- actual_exec_effect 및 unfilled_opportunity_cost는 설명용이다. 실제 손익에서 재차 차감하지 않는다.
- RiskDecision의 승인은 제한된 계약 검사이며 실제 계좌 위험엔진이 아니다. 어떤 결과도 주문을 활성화하지 않는다.
- 비밀은 SecretStr, repr/serialization 제외, 구성/인증/transport 오류는 고정 메시지로 외부에 전달한다.
  raw ValidationError.errors(), traceback locals, HTTP 본문/헤더를 로그에 기록하지 않는다.
- Python의 모듈 경계는 샌드박스가 아니다. ARCH-01은 전략 import 허용목록과 위험한 동적 호출을 검사한다.
  실제 전략·OMS 구현 시 capability 경계 및 통합 시험을 확장한다.

## CONTRACT_CONFLICT 기록

실행 프롬프트와 KM-DOC-01/03의 시험 ID 일부는 같은 번호에 다른 시나리오를 붙인다.
예: 문서 SEM-02는 200→170, 프롬프트 SEM-02는 합계>1이다. 의미 계약 충돌은 없으며,
프롬프트의 21개 ID를 테스트명에 사용하고 문서의 수량 예시·불완전 snapshot·PIT·정정도 추가 시험했다.
정책의 서술형 별칭(FIXED_BUDGET_BASELINE 등)은 KM-DOC-04의 Policy ID와 대응한다.
실행에 영향을 주는 미해결 계약 충돌: 없음. 실제 API 제한 미확인은 API_ASSUMPTIONS에 별도 보류한다.

## 후속 상태 분류

| 상태 | 범위 |
|---|---|
| PASS | 실행된 KM-000 계약 테스트, 정적 검사, 로컬 빌드·demo |
| FAIL | 최종 검증 0. 초기 ruff 긴 줄 위반은 수정 후 재검증 |
| SKIPPED | 로컬 pytest 0 |
| NOT_IMPLEMENTED | 실제 수집/인증/소켓, OMS/계좌 회계/전략/최적화/OOS/G3 판정기 |
| NOT_APPLICABLE | KM-000의 실제 주문·실자금 수익성 검증; 수행하지 않음 |

ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED. GitHub Actions 정의는 있으나 원격 실행은 미수행.
