# K-MAST v1.2 | 국내 주식 멀티전략 자동매매 시스템

> **최종 구현 기준:** 2026-10-16 · `FINAL_IMPLEMENTATION_BASELINE`  
> **목표:** 위험 하드 제약을 준수하면서 **실제 체결비용·반복 운영비 차감 후 지속 가능한 순운용이익**을 창출하는 자동매매 플랫폼  
> **실전 상태:** 미구현 · 수익성 미검증 · `LIVE_NOT_APPROVED`

**[최종 구현 기준선 승인서](IMPLEMENTATION_BASELINE.md)**를 먼저 읽는다. 이 패키지는 v1.1의 안전·회계·검증 계약을 유지하면서, 순수익 목표/포트폴리오 최적화/개발의 경제적 우선순위를 구체화했다. 실제 코드 구현이나 수익 보증은 아니다.

## 권위 설계 문서 8개

| 코드 | 문서 | 주요 책임 |
|---|---|---|
| 00 | [프로젝트 총괄 계획서](00_프로젝트_총괄_계획서.md) | **실제 순운용이익** 목표, 범위, 자본/계좌, 승인 |
| 01 | [시스템 아키텍처 및 인터페이스](01_시스템_아키텍처_및_인터페이스.md) | Alpha/Allocator/Risk/OMS 경계, 신호·장부·성능 계약 |
| 02 | [알파 전략 및 레짐 명세](02_알파_전략_및_레짐_명세.md) | 네 알파의 경제적 가설, 순수익 우선순위, 레짐 |
| 03 | [데이터 및 KIS API 연동 규격](03_데이터_및_KIS_API_연동_규격.md) | PIT·시장구분·체결 비용·운영비 원천·기업행위 |
| 04 | [포트폴리오·리스크 및 주문관리](04_포트폴리오_리스크_및_주문관리_규격.md) | **마코위츠 기반 + 하드 위험제약하 순수익 최적화**, 위험예산·OMS |
| 05 | [백테스트·포워드 검증](05_백테스트_포워드_검증_프로토콜.md) | 순수익 경제성, OOS, 통계 검증, LIVE Gate |
| 06 | [운영·보안·배포 SOP](06_운영_보안_배포_SOP.md) | 수익·위험/비용 모니터링과 재시작·중지·권한 |
| 07 | [개발 로드맵·마일스톤·승인 기준](07_개발_로드맵_마일스톤_승인기준.md) | KM-000~KM-008, 수익/안전 결합 종료 조건 |

## 변경·근거·이전

- [v1.2 승인서](IMPLEMENTATION_BASELINE.md): 무엇이 확정됐고 아직 무엇이 미검증인지.
- [v1.1→v1.2 이전 지침](MIGRATION_V1_1_TO_V1_2.md): 기존 문서/코드의 유지·추가 범위와 필수 시험.
- [변경 이력](CHANGELOG.md): 8개 문서의 상세 변경점.
- [v1.1 감사 기록](AUDIT_V1_1.md): 이전 재감사 18개 발견사항의 역사적 계보. v1.2 자체의 OOS 실행 증거는 아님.
- [근거 자료](SOURCES.md): 종전 문헌·공식 자료의 확인 범위와 한계.
- [BASELINE_V1_1_SHA256.json](BASELINE_V1_1_SHA256.json): 사용한 v1.1 파일의 SHA-256.
- [DOCUMENT_QA_V1_2.json](DOCUMENT_QA_V1_2.json): 문서 구조·링크·표·계약 검사 결과. **금융 성능 시험과 구분.**
- [SHA256SUMS.txt](SHA256SUMS.txt): 문서 무결성.

## 가장 중요한 설계 원칙

1. **수익이 목적, 연구는 수단.** 순운용손익·현금 대비 가치·위험 한도의 조합으로 평가한다.
2. **안전은 하드 제약.** 수익 높은 거래도 결제/리스크/시장·데이터/계좌 한도를 우회하지 않는다.
3. **통합 포트폴리오.** 전략은 독립 판단·비음수 절대 비중을 제출하되 중앙 Allocator·Risk·OMS가 최종 계좌 수량을 결정한다.
4. **단순 모델 우선.** 적격 알파·고정/위험예산 기준선으로 시작해 공분산/레짐/동적 최적화는 독립 증분 성과가 있을 때만 채택한다.
5. **수익/통계/운영 각각의 승인.** 문서 승인·코드 통과·경제성·LIVE 권한을 서로 혼동하지 않는다.

## 작업지시서는 별도 채팅 프롬프트

이 묶음에는 파일형 작업지시서를 넣지 않는다. 기존 KM-000 채팅 프롬프트를 그대로 실행할 경우 v1.0/v1.1 필드·경제성 기준이 충돌할 수 있으므로 v1.2 계약을 우선 반영해야 한다. 필요한 경우 실행 프롬프트를 채팅으로 별도 발행한다.

## 완료 판정

`FINAL_IMPLEMENTATION_BASELINE` / `GO_FOR_V1_2_IMPLEMENTATION` / `ECONOMIC_EDGE_UNVERIFIED` / `LIVE_NOT_APPROVED`.

## KM-000 로컬 구현 (2026-10-16)

Python 3.11+에서 아래 명령으로 설치·검증한다. 최초 의존성 설치에는 패키지 저장소 접근이
필요하다. 설치 후 계약 테스트·빌드·demo는 API 키와 외부 서비스 없이 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python scripts/verify.py
.\.venv\Scripts\python -m kmast.demo
```

Linux/macOS에서는 `.venv/bin/python`을 사용한다. `scripts/verify.py`는 pytest, ruff,
포맷, mypy, sdist/wheel 빌드와 demo를 실행하고 `artifacts/km000/`에 원문 로그를 남긴다.
오프라인 설치가 필요하면 먼저 해당 플랫폼용 wheel을 별도 확보해야 한다.

- [KM-000 종료 보고서](docs/implementation/KM000_CLOSURE_REPORT.md)
- [계약·범위·시험 대응표](docs/implementation/CONTRACT_STATUS.md)
- [KIS 공식 자료 대조 및 미확인 가정](docs/implementation/API_ASSUMPTIONS.md)

`configs/live.yaml`은 의도적으로 로더에서 거부된다. 다른 모드도 주문/취소가 봉쇄되어 있다.
환경변수는 권한을 활성화하지 않는다. 실제 인증·수집·주문 transport는 구현하지 않았다.
위 기존 설계 문서의 미실행 표기는 원본 문서 작성 시점의 상태이며, 현재 코드 증거와 구별한다.
루트 `SHA256SUMS.txt`는 제공 원본의 목록이다. README에 이 실행 안내를 추가했으므로
원본과의 대조는 보존 커밋 `09362323ebac4c75eafbfd5dd1bbbaf68f60e910`을 사용한다.

## KM-001 읽기 전용 데이터 경로

공식 KIS 샘플에 맞춘 제한된 REST/WS 통신과 원본→정규화→Parquet→manifest→재로딩을
구현했다. 기본 실행은 합성 Fixture이며 실제 시장 데이터 준비 상태는 보류다.

```powershell
.\.venv\Scripts\python -m kmast.data.cli fixture --output data/km001
.\.venv\Scripts\python scripts/verify.py --milestone km001
```

[실행법과 연결 조건](docs/implementation/KM001_USAGE.md) ·
[데이터 가용성 행렬](docs/implementation/DATA_AVAILABILITY_MATRIX.md) ·
[KM-001 종료 보고서](docs/implementation/KM001_CLOSURE_REPORT.md).
실제 인증/시장 데이터 조회·주문·취소는 이번 작업에서 수행하지 않았고 KM-002도 자동 시작하지 않는다.

## KM-002 Mock 계좌·위험·OMS

합성 계좌의 Decimal/FIFO 장부, 결제·예약, 전략 귀속, 고정예산 목표 집계, 위험 검사와
영속 Mock 주문 상태기계를 추가했다. 실계좌 주문 전송 기능은 없다.

```powershell
.\.venv\Scripts\python -m kmast.execution.demo --output data/km002
.\.venv\Scripts\python scripts/verify.py --milestone km002
```

[실행 계약과 한계](docs/implementation/KM002_USAGE.md) ·
[KM-002 종료 보고서](docs/implementation/KM002_CLOSURE_REPORT.md).
실제 데이터·경제성·LIVE 승인은 계속 보류이며 KM-003은 자동 실행하지 않는다.

## KM-003 Alpha 코드·독립 reference

기존 SignalIntent를 출력하는 A 추세/상대강도, B ORB, C 평균회귀, D 사건 규칙과
독립 reference·기능 재생 경로를 추가했다. 실제 시장자료와 비용 검증은 HOLD다.

```powershell
.\.venv\Scripts\python -m kmast.simulation.cli --output data/km003
.\.venv\Scripts\python scripts/verify.py --milestone km003
```

[전략·reference 실행 계약](docs/implementation/KM003_USAGE.md) ·
[데이터 조사·확보 계획](docs/implementation/KM003_DATA_PLAN.md) ·
[KM-003 종료 보고서](docs/implementation/KM003_CLOSURE_REPORT.md).
기능용 합성 손익은 시장 수익성 증거가 아니며 KM-004는 자동 실행하지 않는다.

## KM-004 데이터 부분 확보·공동계좌 기준배분

실제 일봉 180행을 private store에 확보했다. 사용권·PIT·실제 비용 검증이 부족해
실제 경제성 평가는 HOLD다. 공동계좌 FIXED 보존성과 위험배분 후보 진단은 합성 기능시험이다.

```powershell
.\.venv\Scripts\python scripts/verify.py --milestone km004
.\.venv\Scripts\python -m kmast.portfolio.demo --output data/km004-joint
```

[KM-004 종료 보고서](docs/implementation/KM004_CLOSURE_REPORT.md).
위 검증은 인증이나 시장 조회를 실행하지 않는다. 로컬 실제 자료 재검사는
`python -m scripts.diagnose_km004`로 수행한다. 수집 스크립트는 별도 명시 실행에만 사용한다.
자동 PBASE_RISK 승격, LIVE, 원격 push 및 KM-005 실행은 비활성 상태다.

## KM-005 실제 자료 적격성·경제성 게이트

Alpha A candidate-v1과 기존 장부·OMS 계약을 유지한 채 이용권한, 원/수정 관측일 중복,
품질, 비용 provenance, G0/OOS 버전 동결을 검사한다. 실제 경제성은 데이터 부족으로 실행하지 않았다.

```powershell
.\.venv\Scripts\python scripts/verify.py --milestone km005
.\.venv\Scripts\python -m kmast.research.cli --output artifacts/km005/offline
```

두 명령은 인증·시세 조회 없이 실행되며 자료가 없으면 명시적인 HOLD와 null 성과지표를 반환한다.
[데이터·권한 조사와 보완 경로](docs/implementation/KM005_DATA_QUALIFICATION.md)를 참고한다.
완료된 작업의 정상 push는 사용자 상시 승인 범위다. 실전과 KM-006은 활성화하지 않는다.

## Data-first 실제 가격 탐색

승인된 읽기 전용 수집과 Alpha A 탐색 재생을 완료했다. 기존 적격성 게이트를 유지하며
별도 `EXPLORATORY_REAL_DATA` 결과를 제공한다. `ECONOMIC_EDGE_UNVERIFIED` 상태다.
[실제 결과·가정·재현 명령](docs/implementation/DATA_FIRST_EXPLORATORY_REPORT.md)을 참고한다.
`python scripts/verify.py --milestone data-first`는 인증 없이 312개 테스트와 기존 재생을 검증한다.

## DF-002 인과성·손익 감사

V2 72개를 보존·재현하고 시점별 입력 계보와 개장 체결 가정을 수정한 V3를 별도 생성했다.
평균 실제 노출·현금·비용·부분체결·실현/미실현 및 기준선을 비교했다.
[DF-002 종료 보고서](docs/implementation/DF002_CLOSURE_REPORT.md)를 참고한다.
`python scripts/verify.py --milestone df002`는 저장된 비공개 자료를 이용한 독립 회계검사를 포함한다.
추가 인증·수집·주문 없이 실행하며 경제적 우위와 LIVE는 미승인이다.

## DF-003 보유기한·진입 대조 연구

새 결과 전에 규칙을 동결하고 216개 독립 Reference로 A0~A3·진입 대조군·기준선을 비교했다.
기존 candidate-v1·V2·V3와 Risk·OMS·Ledger를 보존한다.
[DF-003 종료 보고서](docs/implementation/DF003_CLOSURE_REPORT.md)를 참고한다.
`python scripts/verify.py --milestone df003`는 저장된 자료와 기존 331개 회귀시험을 검증한다.
모든 새 후보는 REVISE이며 실제 실행·경제성·LIVE는 미승인이다. EWY는 데이터 계약만 준비했다.

## DF004 EWY research

DF004 price-only exploration: 251 observed EWY sessions, 217 common Korean dates,
96 independent references. `EWY_EXPLORATORY_SIGNAL_NOT_SUPPORTED`;
`ECONOMIC_EDGE_UNVERIFIED` / `LIVE_NOT_APPROVED`. Publication, execution and
corporate-action limitations remain. No strategy or trading approval changed.
See [DF004 closure](docs/implementation/DF004_CLOSURE_REPORT.md) and
[evaluation](docs/implementation/DF004_EWY_SIGNAL_EVALUATION.md).
