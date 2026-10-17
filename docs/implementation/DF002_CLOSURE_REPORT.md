# DF-002 closure report

기술 판정은 **DF002_CAUSAL_REPLAY_VERIFIED**다. 선언된 탐색 모델의 인과성·재현·회계 검증 범위이며, 실제 개장 체결이나 전략 수익성 승인이 아니다. **EXPLORATORY_REAL_DATA / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED**를 유지한다. 확인적 OOS, G2/G3, 실제 주문·취소·배포·병합은 수행하지 않았다.

## 완료 범위

- 원격·로컬 기준 SHA 확인, 312개 기준 시험 통과, 원본 V2 72개 파일 완전 재생 일치.
- 시점별 신호 입력 hash·계보·보유 상태 식별자 수정, 당일 최종 거래량의 개장 실행 판단 사용 제거.
- 동결 Alpha A 규칙·원본 사양·OMS·위험 엔진 보존. 파라미터 최적화·새 candidate 없음.
- V3 90개 독립 재생: 6주식 × 3시나리오 × 5모형. 기존 72개 경제적 주문·체결·최종 손익은 동일하며 ID만 변경.
- 일별 노출·현금·NAV·비용·잔량, FIFO 실현/미실현, 청산 이유, 시장 방향 proxy, 기준선 손익 차이의 정확한 회계 연결.
- 원자료와 거래 상세는 Git 제외 비공개 보관. 공개 집계·hash만 커밋한다. 추가 인증·시세 조회 0건.

## 핵심 답변

삼성전자 +536,495.75원의 제한된 수익은 평균 주식 비중 4.4247%·보유 45/223일이라는 낮은 노출과 진입/기한/손절 경로에서 발생했다. 평균 현금 95.5753%는 이자를 벌지 않았고 상승 노출·하락 위험을 함께 줄였다. 초기 25% 보유 기준선의 평균 실제 노출은 39.8261%이므로 손익을 단순 비교해 예측력 부족을 단정할 수 없다.

전일 보유분 종가손익 531,100원 중 시장 방향 산술 proxy 364,038.77원, 지수 대비 잔여 167,061.23원이다. 당일 거래의 체결-종가 변화 114,978.20원을 합치고 수수료·세금·운영비를 차감한다. 이는 회계적 분해이며 거래 시점의 경제적으로 유의미한 예측력을 입증하지 않는다. 그 부분은 **미검증**이다.

하락 종목의 상대적 손실 축소는 대부분 현금 유지와 낮은 평균 노출로 설명 가능하다. 6개 생존 종목·1년·일봉·미검증 실행 가정만으로 시장 전체 우위나 통계적 유의성을 주장하지 않는다.

## 재현과 증거

```powershell
.\.venv\Scripts\python scripts/run_df002.py --reproduce-v2
.\.venv\Scripts\python scripts/analyze_df002.py
.\.venv\Scripts\python scripts/check_df002_evidence.py --private
.\.venv\Scripts\python scripts/verify.py --milestone df002
.\.venv\Scripts\python -m scripts.audit_df002
git diff --check
```

저장된 비공개 수집자료가 필요한 명령이다. CI에서는 공개 집계 회계와 합성 회귀시험을 검사하며 비공개 원자료 재생을 했다고 주장하지 않는다. 기존 계약·신규 시험·Ruff·format·mypy·sdist/wheel·이전 장부/OMS 재생의 실제 결과는 `artifacts/df002/checks.json`, `junit.xml`, 감사 manifest에 기록한다.

로컬 실제 검증은 **331 PASS = 기존 312 + 신규 19, 실패·건너뜀 0**이다. Ruff·format·mypy(65개 소스)·sdist/wheel·기존 OMS/Reference/공동계좌 재생·V2 보존 재검사·V3 독립 회계가 모두 통과했다. 공개 로그는 UTF-8/LF 및 줄 끝 공백만 정리했고 원 subprocess 바이트는 비공개 검증 폴더에 보존한다. 새 실데이터 요청 없이 완료했다.

구현 SHA `ac395296d3dfc2add28209607fbe8fe552c7fa71`의 [GitHub Actions](https://github.com/amandalmoon/k-mast/actions/runs/38995855244)는 Python 3.11·3.12 모두 성공했다. 두 로그에서 각각 331 passed, mypy 65개 소스 통과, sdist/wheel 생성과 DF002 독립 회계 PASS를 확인했다. 정확한 SHA·작업·단계·로그 발췌는 `artifacts/df002/remote-ci-implementation.json`에 보존한다.

[인과성 감사](DF002_CAUSAL_AUDIT.md), [손익 원인 분해](DF002_ALPHA_PROFIT_ATTRIBUTION.md)를 함께 읽는다. 기본 시나리오와 비용·부분체결은 변경하지 않았다. 과거 사양을 수정하지 않는 별도 후보 가설은 추후 사전 등록 마일스톤에서만 검증한다.

추가 데이터 요청은 이번에 하지 않는다. 향후 실제 개장 체결 검증에는 과거 시가 경매·호가·체결·거래정지 자료, 총수익 검증에는 기업행사·배당 이력, 업종 조정에는 PIT 업종 분류·업종지수가 필요하다. 제공 가능 기간과 API가 확인되지 않아 기간·요청량·권한을 임의 가정하지 않는다. 캐시에는 해당 증거가 없으며 새 인증 수집은 별도 범위를 제시한 뒤 승인받아야 한다.
