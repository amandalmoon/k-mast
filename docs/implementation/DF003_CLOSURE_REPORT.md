# DF-003 closure report

기술 범위는 **DF003_HYPOTHESIS_AUDIT_VERIFIED**다. 이는 동결한 탐색 프로토콜의 실행·인과 경계·보존·회계 감사 상태이며 실제 체결이나 경제적 채택 승인과 다르다. 경제성은 **EXPLORATORY_REAL_DATA / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED**다.

## 완료 범위

- 원격·로컬 시작 SHA `9b10bbea55d9e74ca9ae0754e6fce91ee433074b` 확인, 기존 331개 시험 재실행.
- 새 결과 전에 JSON 프로토콜·seal 동결. 총 216개 독립 Reference, 후보당 파라미터 조합 1개. 추가 조합 탐색 없음.
- A0와 이전 V3의 18개 시나리오 전체 canonical 결과 일치. 원본 V2 72개·V3 90개뿐 아니라 시작 시 존재한 private store 전체의 바이트 hash 보존 검사.
- A1~A3와 짝지은 T0~T3 진입 대조군, CASH/BUY_HOLD/HOLD_25/TREND_25 비교. 실제 비중·위험·비용·실현/미실현·청산 기여·보유기간별 결과 공개.
- 216개 중 A/T 144개는 새로 재생했고, 규칙이 그대로인 기존 기준선 72개는 검증된 V3를 재사용했다. 원본 V2·V3 독립 회계 검사도 별도로 수행한다.
- 별도 새 폴더 `data/data-first-private-market-v1/df003-hypotheses-v1/`에 상세 216개 보관. 원시 KIS 시세·상세 거래를 Git에 올리지 않는다.
- 추가 인증·시장·계좌·주문·취소 호출 0. candidate-v1, V3 kernel, 기존 Risk·OMS·Ledger 수정 없음.

## 연구 판정과 핵심 답변

A1은 BASE/STRESS에서 각각 5/6종목 순수익이 개선됐으나 사전 MDD 기준은 4/6(요구 5/6)이라 **RESEARCH_CANDIDATE_REVISE**다. A2·A3는 개선 3/6, 위험 기준 2/6, 반도체 외 개선 1개라 둘 다 **RESEARCH_CANDIDATE_REVISE**다. A0는 동결 기준으로 남긴다. 분류를 최종 원화 수익 순으로 바꾸지 않았다.

삼성전자 A0→A1은 순손익 536,495.75→715,691.46원, 평균 주식 비중 4.4247→5.5567%, MDD 1.8195→3.9544%다. A2·A3는 1,305,385.84원·7.6883%·MDD 5.6803%다. 긴 보유가 상승 수익을 더 포착했지만 위험과 노출도 커졌다. 사후 노출 정합 proxy에도 차이는 남지만 실행 가능한 동일 위험 전략이나 예측력 인증이 아니다.

따라서 **5달력일은 수익을 제한하면서 위험도 제한하는 구조이며, 현재 표본으로 정당성·과도성을 확정할 수 없다.** A1은 수정 연구할 가설이지만 교체 승인이 아니고, A2·A3는 반도체 중심 수익과 하락 종목 악화를 함께 보아야 한다. PARTIAL은 모든 A 후보·6종목에서 최종 1주 위험감축 미이행 HOLD다.

## 재현

```powershell
.\.venv\Scripts\python scripts/run_df003.py
.\.venv\Scripts\python scripts/derive_df003_benchmarks.py
.\.venv\Scripts\python scripts/check_df003_evidence.py --private
.\.venv\Scripts\python scripts/verify.py --milestone df003
.\.venv\Scripts\python -m scripts.audit_df003
git diff --check
```

저장된 비공개 자료가 필요하며 위 명령은 네트워크 인증·수집을 실행하지 않는다. 공개 CI는 합성 회귀시험·공개 집계의 회계·프로토콜·연구 분류를 검증한다. CI가 private store에서 실데이터 전체를 재생했다고 주장하지 않는다. 상세 실제 검증은 `artifacts/df003/checks.json`, `junit.xml`, `audit.json`에 연결한다. 공개 로그는 LF·줄 끝 공백만 정리하고 원 subprocess 바이트를 새 private 검증 폴더에 보존한다.

로컬 최종 증거는 **354 PASS = 기존 331 + 신규 23, 실패·건너뜀 0**이다. Ruff·format·mypy(67개 소스)·sdist/wheel·기존 OMS/Reference/공동계좌 재생·V2/V3/216개 독립 회계 검사가 모두 통과했다. CASH·단순 보유·초기 25% 보유·단순 추세 대비 손익과 노출·MDD 차이는 `benchmark-deltas.json`에 216개 별도 기록했다. 이는 추가 전략 실험이 아닌 동일 결과의 산술 비교다.

구현 SHA `bf69787d20fc2c74cfb2c3d3a983f7cdd4183fa3`의 [GitHub Actions](https://github.com/amandalmoon/k-mast/actions/runs/38998105134)는 Python 3.11·3.12 모두 성공했다. 양쪽에서 각각 354 passed, mypy 67개 소스, sdist/wheel, DF003 독립 집계 회계·분류 검사 PASS를 확인했다. 정확한 SHA·작업·단계·로그 발췌는 `artifacts/df003/remote-ci-implementation.json`에 보존한다.

## 한계와 후속 경계

이전부터 소비한 현재 생존 표본 6개·1년, 일봉, 미검증 기업행사·배당·과거 세션 공개시각, 시가 anchor와 미보정 체결비율이라는 한계가 있다. 종가 MDD와 베타는 실제 장중 손실 한도나 중앙 위험 승인이 아니다. 원 데이터 flag와 취득시각을 보존하며 확인적 G1/OOS·G2/G3로 승격하지 않는다.

EWY는 데이터 계약만 준비했다. `DF004_EWY_DATA_CONTRACT.json`은 미국 세션·NAV 기준/공개시각·FX·한국 지수·실제 개장 이후 가격·양국 휴장/DST·비용·정정 계보를 요구한다. EWY 성과는 NULL, DF-004 시작은 false다. 신규 수집·LIVE·PR 병합·배포·실제 주문·취소는 하지 않는다.

[동결 프로토콜](DF003_PROTOCOL.md) · [노출·청산 비교](DF003_ALPHA_ABLATION_REPORT.md) · [실행 견고성](DF003_EXECUTION_ROBUSTNESS.md)
