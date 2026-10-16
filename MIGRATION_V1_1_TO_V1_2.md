# v1.1 → v1.2 구현 마이그레이션 체크리스트

[최종 구현 승인서](IMPLEMENTATION_BASELINE.md) · [CHANGELOG](CHANGELOG.md)

## 1. 이전 버전 재사용 범위

| 부분 | 조치 |
|---|---|
| `MarketEvent`/PIT/캘린더/기업행위 | 기존 v1.1 계약 유지, 추가 원천비용 검증 |
| `SignalIntent` `target_weight`/`SLEEVE_NAV_WEIGHT` | 동일 계약 유지. 음수·delta를 target으로 취급 금지 |
| 3중 장부와 Ledger 수량/현금 보존 | 동일 계약 유지. 실제/귀속/reference 구분 |
| OMS 상태·UNKNOWN/취소대기·single writer | 동일 계약 유지 |
| Portfolio Allocator | `PortfolioDecision`, PBASE·후보 정책, 현금/ES/stress/요인 제약, 비용/불확실성 no-trade 추가 |
| 수익 대시보드 | `NET_OPERATING_PNL_KRW`, NAV TWR, 현금/고정배분 대비, 자본·위험기여·TCA·운영비 추가 |
| OOS Gate | 주 KPI·현금대안·수익의 추가가치·경제성 GO/HOLD/REJECT 계약 추가 |
| 로드맵 | KM-003 이후 순수익 후보를 조기 평가, KM-004 복잡한 배분은 증분 경제성 검증 조건부 |

## 2. 마이그레이션 시 강제할 테스트

- `PORT-01` 예산·현금의 합, 전략 내 전체 종목 비중 및 최소 주문.
- `PORT-02` 위험기여(총합=전체 변동성, 0 변동성 예외), 업종/요인 노출 재평가.
- `PORT-03` 편익·추가비용·불확실성이 불충분한 목표 변경은 주문 없음. 위험 강제감축은 실행 가능 경로 허용.
- `PORT-04` 서로 다른 H·자본·cost_basis 최적화 입력 거부.
- `PORT-05` 최대 예상수익 후보도 위험 하드 제약 위반이면 거부.
- `ECON-01~03` 순운용이익/현금대안/단순배분 대조, G0 사전 KPI 동결.
- `PNL-01~03` 입출금·배당·이자·수수료·운영비를 중복 없이 계좌 장부에 반영.
- 기존 `SEM/LED/COST/ML/VAL/OMS/RISK/CASH/CAP` 회귀시험은 변경하지 않고 필수로 유지.

## 3. 실행 순서

1. README → IMPLEMENTATION_BASELINE → 00 → 01 → 04 → 05 → 07을 먼저 읽는다.
2. v1.1 구현이 있다면 인터페이스/단위/계좌 스냅샷과 각 테스트를 대조한다. 없으면 v1.2로 새 구조를 생성한다.
3. KM-000에서는 실주문을 차단하고 위 계약을 스키마/CI에 연결한다. **실전 인증키/계좌번호를 프롬프트에 넣지 않는다.**
4. 사용자에게서 실제 자본·손실감내·계좌 자료를 확보하기 전에는 연구 가정값만 쓰고 LIVE에 배포하지 않는다.
5. 승인 기준은 OOS 개봉 이전에 별도로 동결한다. 원화 수익성과 위험 한도를 확인할 증거가 없으면 GO로 승격하지 않는다.

## 4. 미구현과 미결정

실제 모델 수익·실계좌 거래비용·운용비·공분산·ES·최소 필요 자본·브로커의 실시간 체결 범위·실전 계좌 주문 허용은 문서만으로 확정할 수 없다. 자료 부족은 HOLD로 표시한다.

**결론:** `GO_FOR_V1_2_IMPLEMENTATION`, `ECONOMIC_EDGE_UNVERIFIED`, `LIVE_NOT_APPROVED`.
