# KM-000 Milestone Closure Report

작성일: 2026-10-16 (Asia/Seoul). 판정: **KM000_CONTRACT_READY**.
경제성: **ECONOMIC_EDGE_UNVERIFIED**. 실전: **LIVE_NOT_APPROVED**.

## 1. Authoritative State

| 항목 | 실제 상태 |
|---|---|
| Repository | `C:\Users\User\Desktop\k-mast` 로컬 Git. 원격 없음 |
| Branch | `km-000` |
| Starting HEAD | 작업 시작 시 Git 없음. 제공 원본 보존 HEAD: `09362323ebac4c75eafbfd5dd1bbbaf68f60e910` |
| Closing HEAD / Commit SHA (실행 코드) | `c464c80e1d4426c010d3feec9667df7712b7b5fc` |
| 작업 디렉터리 | `C:\Users\User\Desktop\k-mast` |
| 미커밋 변경 | 코드 종료 커밋 직후 없음. 본 보고서는 후속 문서 커밋으로 추가 |

위 Closing HEAD는 테스트한 구현과 원문 로그를 포함하는 고정 SHA다. 보고서 자신의 SHA를
본문에 자기참조하지 않는다. 보고서 추가 후 최종 Git HEAD는 `git rev-parse HEAD`, 보고서
커밋은 `git log -1 --format=%H -- docs/implementation/KM000_CLOSURE_REPORT.md`로 확인한다.
원본 18개 파일을 첫 커밋에 보존했다. README에는 실행 안내만 추가했으며 다른 원본 명세는
수정하지 않았다. 원격 생성·push·배포를 수행하지 않았다.

## 2. 구현 결과

생성 파일과 책임:

| 파일 | 책임 |
|---|---|
| `src/kmast/__init__.py`, `demo.py` | 버전과 합성 이벤트의 오프라인 실행 |
| `src/kmast/core/base.py`, `enums.py` | frozen/extra-forbid 계약, 유한 Decimal, 모드·정책·장부 타입 |
| `core/config.py`, `clock.py` | fail-closed 설정, 환경 분리, 주입 가능한 실시간/재생 시계 |
| `core/events.py` | 시장·공개 이벤트, 수집/가용/라벨 시점 및 공개 경계 |
| `core/contracts.py` | 신호, 완전 snapshot 교체, 예산/현금, 목표수량, 위험·포트폴리오 결정, 손익 대사 |
| `core/study.py` | 미정 경제성 설정 및 G3 자동 PASS 차단 |
| `data/normalization.py`, `data/replay.py` | 명시 입력 검증, 중복·정정·가용성 순서와 결정적 해시 |
| `brokers/interfaces.py`, `brokers/kis/adapter.py` | Mock, 주문 봉쇄, 인증/토큰·GET transport·호출 제한·소켓 상태 계약 |
| `strategies/interfaces.py` 및 각 패키지 `__init__.py` | 브로커 capability 없는 전략 인터페이스 |
| `tests/conftest.py`, `test_contracts.py`, `test_broker.py`, `test_study.py`, `tests/__init__.py` | 합성 Fixture, 네트워크 봉쇄, 실제 계약 시험 |
| `configs/research.yaml`, `shadow.yaml`, `paper.yaml`, `live.yaml`, `study.yaml` | 안전 모드 및 미정 연구 설정 예제 |
| `pyproject.toml`, `requirements-dev.lock`, `MANIFEST.in` | 패키징·고정 의존성·sdist 테스트 포함 |
| `.github/workflows/ci.yml`, `scripts/verify.py` | CI 정의 및 로컬 검증/원문 로그 수집 |
| `.gitignore`, `.gitattributes`, `.env.example`, `AGENTS.md` | 비밀 제외·줄바꿈·비활성 기본값·개발 경계 |
| `docs/specification/v1.2/README.md` | 루트 권위 문서 색인 |
| `docs/implementation/CONTRACT_STATUS.md`, `API_ASSUMPTIONS.md`, 본 보고서 | 계약 대응·제약·공식 자료 대조·종료 판정 |
| `artifacts/km000/*` | JUnit, 검사별 stdout/stderr, 환경/소스 해시, wheel 실행 로그 |

수정 파일: `README.md` (로컬 실행법·증거 링크 추가).
전체 정확한 추가/수정 목록은 `git diff --name-status 0936232 c464c80`로 재현 가능하다.

실행 가능한 기능: Pydantic 계약 생성·거부, 전략 전체 목표 교체, 설명용 목표수량 집계,
예산/현금 보존, 원화 손익 대사, 미래정보 차단, 합성 이벤트 재생, Mock 읽기,
주입된 가상 인증/transport의 수명·제한·장애 처리, 패키지 설치 및 CLI demo.

미구현: 실제 KIS 인증/네트워크/소켓, 실제 데이터 수집, 완전한 Ledger/OMS/Risk,
체결/결제/배당 엔진, Alpha A~D, 공분산/레짐/최적화, 수익성 백테스트, OOS 승인기,
TWR 엔진 및 LIVE 거래. 위험감축은 별도 의도 계약만 있으며 실제 실행 경로는 없다.

## 3. v1.2 계약 준수

- 최상위 목적은 위험 하드 제약하 순운용손익. 확인되지 않은 수익성은 주장하지 않는다.
- `target_weight`는 `[0,1]` 절대 sleeve 목표이며 합계는 1 이하다. 음수 delta·옛 필드를 거부한다.
  revision/snapshot 완전성·재전송·오래된 교체를 검사한다. 미완성 목표를 기존 목표와 섞지 않는다.
- 예산 합계와 중앙 예비현금은 1이다. 전략 내부 미투자 현금은 계좌 예산 가중치로 별도 표현한다.
  `PBASE_RISK`는 명시 위험예산·자본 상한을 요구하며 배분 알고리즘은 구현하지 않았다.
- 예상 개선이 비용/불확실성 이하이면 CHANGE_TARGET을 거부한다. RISK_REDUCTION은
  경제 필터와 분리되지만 주문 승인이나 계좌 안전의 증명이 아니다.
- `PerformanceBridge`는 ACCOUNT 장부만 받고 NAV 변화에서 외부 흐름을 제외해 대사한다.
  실제 체결에 포함된 비용·미체결 기회비용은 설명값으로만 남긴다.
- 전략은 브로커를 import하지 않으며 실제 주문/취소는 모든 모드에서 봉쇄된다.
- 문서 ID 차이와 별칭 대응은 [계약 상태](CONTRACT_STATUS.md)에 등록했다.
  실행 의미에 영향을 주는 미해결 `CONTRACT_CONFLICT`는 없다.

## 4. 테스트 증거

실행 환경: Windows, Python 3.12.10, `.venv`. [환경·소스 해시](../../artifacts/km000/environment.json).
아래 명령을 실제 실행했다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pip install setuptools==80.9.0 wheel==0.45.1
.\.venv\Scripts\python scripts/verify.py
```

최종 검증: **48 tests / PASS 48 / FAIL 0 / SKIPPED 0**.
요청된 고유 계약 ID 21개 모두 포함. PORT-04는 8개 단위 불일치 사례로 매개변수화했다.

| Test ID | 상태 | 실제 시험 |
|---|---|---|
| SEM-01 | PASS | 음수 비중 거부 |
| SEM-02 | PASS | 전략 합계 초과 거부 |
| SEM-03 | PASS | 혼합/불완전 snapshot, revision 충돌, 재전송·교체 |
| SEM-04 | PASS | A100+B50+C20=170, 현재200 대비 delta=-30 및 0 목표 |
| DATA-01 | PASS | timezone 없는 시간 필드 거부 |
| DATA-02 | PASS | 미래 데이터·미래 근거 신호 거부 |
| DATA-03 | PASS | 동일 중복 제거·내용 충돌 거부 |
| COST-01 | PASS | UNKNOWN 비용 기준 입력 거부 |
| COST-02 | PASS | 체결효과·기회비용 재차 차감 금지 |
| PORT-01 | PASS | 중앙/전략 내부 현금·예산 보존 |
| PORT-03 | PASS | HOLD와 위험감축 분리·위험 실패 변경 거부 |
| PORT-04 | PASS | H·자본·비용·위험·평가시점·장부 단위 불일치 거부 |
| PORT-05 | PASS | 미승인/위반 한도·낡은 계좌/목표·만료 거부 |
| PNL-01 | PASS | 입금/내부 이전을 수익에서 제외 |
| PNL-02 | PASS | 이자·배당·비용·NAV 단일 계상 대사 |
| CFG-01 | PASS | 기본 주문 off·LIVE 설정 거부·주문/취소 차단 |
| CFG-02 | PASS | 모의/실전 계좌·자격환경·endpoint 혼용 거부 |
| SEC-01 | PASS | 비밀 repr/직렬화 제외·구성 오류 출력 보호 |
| ARCH-01 | PASS | 전략 의존성 허용목록·동적 우회 호출 검사 |
| REPLAY-01 | PASS | 동일 입력·시계·코드/설정의 결정적 출력 |
| VAL-08 | PASS | 미정 설정 G3 HOLD, 승인 bool 활성화 거부 |

추가 시험: 토큰 갱신 잠금/만료/무효화/환경·계좌 scope, 인증 오류 정제,
계좌별 제한, 읽기 transport 주입, 주문 경로 거부, reconnect 동기화 세대,
시계 역행, 공개 경계, historical acquisition, 라벨 성숙, 정정 계보,
비유한 숫자·초과 비중, 고정 위험예산 스키마, 완전한 설정에도 경제성 PASS 금지,
일치하는 최적화 입력의 긍정 사례.

| 검사 명령 (동일 venv python) | 최종 결과 | 원문 |
|---|---|---|
| `-m pytest -q --junitxml=artifacts/km000/junit.xml` | PASS, 48 | [pytest](../../artifacts/km000/pytest.stdout.log), [JUnit](../../artifacts/km000/junit.xml) |
| `-m ruff check .` | PASS | [ruff](../../artifacts/km000/ruff.stdout.log) |
| `-m ruff format --check .` | PASS | [format](../../artifacts/km000/format.stdout.log) |
| `-m mypy src` | PASS, 19 source files | [mypy](../../artifacts/km000/mypy.stdout.log) |
| `-m build --no-isolation` | PASS, sdist + wheel | [build](../../artifacts/km000/build.stdout.log), [stderr](../../artifacts/km000/build.stderr.log) |
| `-m kmast.demo` | PASS, 주문 off / G3 HOLD | [demo](../../artifacts/km000/demo.stdout.log) |
| wheel `pip install --no-deps --target <temp>` 후 외부 cwd에서 import/demo | PASS | [wheel smoke](../../artifacts/km000/wheel-smoke.log) |

처음 실행한 pytest는 36개, 브로커 추가 후 46개, 마지막 48개였다. 합산해서 130개라고
보고하지 않는다. 최초 ruff 검사에 긴 줄 위반이 있었으며 포맷 수정 후 최종 PASS.
실패한 테스트의 조건을 삭제하거나 완화하지 않았다.
고정 의존성은 [lock](../../requirements-dev.lock), 검사 exit code는 [checks.json](../../artifacts/km000/checks.json).
GitHub Actions는 구성만 작성했고 원격 실행은 **NOT_IMPLEMENTED/미실행 증거**로 구별한다.
로컬 Python 3.11/Linux 실행을 주장하지 않는다. CI matrix는 3.11/3.12 예정이다.

## 5. 안전성 결과

RESEARCH 기본, `order_enabled=false`, `live_enabled=false`다. LIVE 모드는 설정 로더가
거부한다. PAPER 역시 주문 기능이 없다. 실제 주문 transport가 없으며 환경변수 변경으로
활성화되지 않는다. `MockBroker`와 `KISReadAdapter`의 주문/취소는 PermissionError다.

실제 키를 요청·입력·사용하지 않았다. 자격정보·계좌 reference·토큰은 SecretStr 및
repr/직렬화 제외이며 `.env`와 키 파일은 Git 제외다. 가상 인증·transport 오류는 고정
메시지로 처리한다. raw validation 입력·traceback locals를 로그로 내보내는 API는 제공하지 않는다.

모든 pytest에서 socket connect/DNS를 막았다. Mock은 가상 읽기/계약 증거이며 실제
브로커 기능시험이 아니다. **실계좌 인증 0, 실제 KIS API 데이터 호출 0, 주문/취소 0**.
공식 문서 웹 열람과 의존성 다운로드는 수행했다.

## 6. 경제적 기능 준비 상태

`NET_OPERATING_PNL_KRW = GrossMarketPnL + CashInterest + DividendIncome
- ExplicitFeesAndTaxes - RecurringOperatingCosts`를 구현했다. GrossMarketPnL은 실제
체결가격에 포함된 스프레드/충격을 포함한다. 기간·초기 자본·종료 NAV·외부 흐름을 명시하며
계좌 내부 이전은 순액 0만 허용한다. TWR을 이 값에서 임의 산출하지 않는다.

기본 예측 비용 기준은 `GROSS_EXPECTATION_WITH_SINGLE_EXECUTION_COST`다. 이미 비용을
차감한 실현수익·UNKNOWN 비용은 gross 최적화 입력으로 쓰지 못한다. H, 자본정책/분모,
통화, 비용모델, 위험 기준, 장부, 평가 캘린더가 일치해야 한다. 10분과 10일을 변환하는
검증되지 않은 연환산 모델은 없다.

정책 ID 5개와 고정/위험예산 설정 계약을 지원한다. 실제 사용자 자본, 승인 위험 한도,
수수료/세금/현금이자, 반복 운영비, 공통 평가기간, 비교 정책, fold/trial manifest,
경제적 최소 개선·신뢰도·용량 규칙은 미확정이다. 합성 테스트의 숫자는 사용자 승인값이 아니다.
`StudyContract`는 미정 값에 HOLD를 반환하며, 값이 모두 채워져도 OOS 증거가 없으므로
NOT_IMPLEMENTED를 반환한다. KM-000 코드 준비와 경제성 승인 완료를 분리했다.

## 7. 미완료 사항 및 Blocker

KM-000 종료를 막는 기술적 장애/필수 문서 누락/미해결 의미 충돌: 없음.

후속 단계 보류 항목:

- KIS 개별 읽기 TR/필드·과거 데이터 범위·계좌 적용 유량·접속키/구독 한도 확인.
- 실제 자격환경·계좌 권한 검증, 데이터 라이선스/coverage, 거래소/정정/기업행위 원천 확보.
- 사용자 운용자본·기존 보유·손실 감내/위험 승인, 실제 비용/운영비 자료.
- 원격 CI 실행 증거, Linux/3.11 실측, 지속 저장소·분산 제한기·완전 회계/위험 검증.

이들은 경제성/LIVE의 blocker이며 KM-000 스키마 준비의 실패로 혼동하지 않는다.
상태 분류: 실행 계약 **PASS**, 최종 **FAIL 0 / SKIPPED 0**,
후속 기능 **NOT_IMPLEMENTED**, KM-000의 실자금 거래 검증 **NOT_APPLICABLE**.

## 8. Next Milestone Readiness

KM-001의 선행 인터페이스는 준비됐다. KM-001은 공식 읽기 TR별 자료 대조 후 제한된
읽기 transport/auth를 구현하고, 시점/출처/원문 hash를 유지하는 수집·가용성 행렬,
종목/세션/기업행위·비용 데이터를 연결해야 한다. 지금의 합성 replay와 token/limit 계약을
실제 수집 실패·재연결·coverage 검증으로 확장하되 주문 봉쇄를 유지한다.

필요 자료는 사용자 계좌의 비밀이 제거된 API 계약/제한·수수료, 이용 가능한 데이터와
라이선스 범위다. 경제성 승인 전에는 자본·손실 감내·평가기간·최소 개선·고정비 기준을
별도로 동결해야 한다. 실전 키를 대화에 붙여 넣지 않는다. **KM-001은 자동 실행하지 않았다.**

## 9. 최종 판정

**KM000_CONTRACT_READY** — Contract / Engineering / Security / Economic Contract의
KM-000 범위를 [실행 코드](../../src/kmast/core/contracts.py),
[계약 대응표](CONTRACT_STATUS.md), [48개 JUnit](../../artifacts/km000/junit.xml),
[검사 exit code](../../artifacts/km000/checks.json), [demo](../../artifacts/km000/demo.stdout.log)로 확인했다.

**ECONOMIC_EDGE_UNVERIFIED** — 실제 시장/OOS/수익성 시험을 수행하지 않았다.
**LIVE_NOT_APPROVED** — 실제 인증·주문·자금 사용은 없으며 권한은 봉쇄되어 있다.
