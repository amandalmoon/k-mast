# KM-005R1 Closure Report

2026-10-17 KST. **KM005R1_EXTERNAL_EVIDENCE_PENDING / ECON_NOT_EXECUTED / LIVE_NOT_APPROVED**.

## 1. 권위 상태와 범위

공식 저장소 `https://github.com/amandalmoon/k-mast.git`, 브랜치 `km-005r1-data-evidence`.
fetch 후 시작 HEAD와 origin/km-005는 모두
`68532f7d5558816eb1acdcf7ba408f9ac45a9a13`이었다.
KM-005 구현 98f562d 및 종료 68532f7의 계보, Closure·qualification·cost-evidence와
기존 audit의 모든 소스/증거 해시를 대조했다. 원본 규격과 이전 시험을 보존했다.
새 구현 SHA는 `c34c1b0af8b4f7327cf848b1c074aca215151f1d`다.
종료 보고서의 자기참조 SHA는 넣지 않으며 최종 응답에서 Closure SHA·최종 원격 HEAD를 제출한다.

이번 단계는 Shadow나 새로운 수익성 실험이 아니다. 외부 근거를 더 확보하고 실제로 필요한
상품·허가·사용자 결정을 구체화하는 범위를 완료했다.

## 2. 실제로 해소한 항목

**2026-10-06 KIS 데이터 정책 FAQ의 상세 본문을 확보했다.** 이전에는 검색 제목과 잘린 목록만 있었다.
공식 상세 페이지가 사용하는 공개 endpoint와 post ID를 확인하여 본문을 읽고 응답·본문 해시를 남겼다.
본인 투자·분석 목적의 개인 PC 저장·가공·분석에 대한 직접 설명을 확인했다.
따라서 로컬 저장·분석 자체에 근거가 없다는 이전 공백은 해소했다.

여전히 기간 제한 없는 보관·종료 후 이용, 명시적인 비공개 백테스트 적용, 비복원 집계 공개의
구체 조건까지 직접 확인한 것은 아니다. 다른 목적과 제3자 제공을 허용한 것으로 해석하지 않는다.
고객별 적용 계약·특약의 독립 확인도 남아 있다.

공식 문서의 URL·제목·게시일·버전·확인일·관련 조항 및 해시는
[권리·공급원 보고서](KM005R1_DATA_RIGHTS_AND_SOURCE_REPORT.md)와
`artifacts/km005r1/official-documents.json`에 있다.
공개 FAQ 본문 SHA는 `e02cb60a9c668e533844bcf988aedf7ecc6346ebd0e8fa5f121bf1e38153bbeb`다.

## 3. 권한 계약의 변경 범위

새 PurposeGrant/RightsDocument는 일시 조회·메모리 분석·백테스트·원/정규화 장기 보관·집계 공개·
제3자 제공·개인 의사결정을 분리한다. 직접 문구와 해석, 제한 조건과 미확인을 각각 기록한다.
공식 본문을 확보하지 못했거나 근거 문서가 일치하지 않는 허용 주장은 승인하지 않는다.
메모리 분석을 허용하는 데 장기 저장권까지 요구하지 않도록 목적 평가를 분리했다.

기존 LicenseScope와 G1·Alpha 입력·Risk/OMS·비용 계약은 수정하지 않았다.
새 목적 판정은 G1 또는 거래 승인이 아니다. 현재 파이프라인은 백테스트·지속 저장·PIT 자료를
필요로 하므로 전체 G1을 자동 통과시키지 않았다.
목적별 실제 평가 결과는 `artifacts/km005r1/assessment.json`에 있다.

## 4. 데이터 공급·비용에 대한 결론

KIS는 현재 bounded adapter 재사용이 가능하지만 과거 master·상폐·정지·기업행위 bundle이 미확보다.
KRX 맞춤자료와 코스콤 과거정보의 공식 공급 경로를 확인하고 필요한 bundle 명세를 구체화했다.
견적 금액은 아직 미확정이며 0원이나 무료로 표시하지 않았다.

DataGuide는 공식 가격표가 첫 계정 연 720만원+VAT지만 같은 문서가 대량 추출·DB 구축을 제한한다.
따라서 단순 Excel 구독을 데이터 파이프라인 권한으로 구매하도록 권고하지 않는다.
상품별 별도 저장/추출 계약과 PIT·상폐 제공의 서면 확인이 선행돼야 한다.
이전 단계의 일반 벤더 후보보다 비용·이용 제한을 구체적으로 확인했다.

[확보 계획](KM005R1_ACQUISITION_PLAN.md)은 필요한 상품·기간·권리·비용·API 개발 조건,
공급자 문의 명세와 사용자 승인 순서를 담는다. KIS 문의 초안을 작성했으나 발송하지 않았다.
어떠한 유료 상품도 구매하지 않았다.

## 5. 기존 180행의 실제 판정

005930 RAW 60 / ADJUSTED 60 / KOSPI INDEX 60, 독립 주식 관측일 60일을 재검증했다.
기간 2026-07-20~10-16, KRX 일봉이다. 모든 원본·정규화·manifest 대조가 성공했고
이번 검사에서 기존 Parquet SHA를 별도로 보존했다. 원자료를 수정하거나 공개하지 않았다.
중복·상충 관측 키 0이며 결측률은 공식 기대 calendar 부재로 계속 null이다.

SESSION_UNVERIFIED, ADJUSTMENT_HISTORY_UNVERIFIED, INDEX_HISTORICAL_RELEASE_UNVERIFIED,
과거 available_at·PIT master·calendar 장애는 **미해소**다.
각 실패조건·필요 증거·공급자·코드 계약 연결은 권리·공급원 보고서의 대응표에 기록했다.
실제 RAW 60행의 기존 Alpha adapter 거부도 유지된다. 세션이나 과거 시각을 생성하지 않았다.

| 상태 구분 | 이번 결과 |
|---|---|
| 기존 수집 자료 접근·무결성 | 180행 검증 성공 |
| 추가 시장자료 수집 | 0행; 신규 승인/공급 bundle 미확정으로 실행 안 함 |
| 목적별 권한 | 개인 로컬 분석·저장 근거 확인, 장기/백테스트 세부 조건 미확인 |
| 시장자료 품질 적격 | 미충족 |
| Alpha A 실제 입력 가능 | 미충족, RAW 60행 거부 |
| 탐색 경제성 | NOT_EXECUTED |
| 확인적 G0/OOS | 미동결/미개봉 |
| 실제 양의 순기대수익 | 미검증 |

## 6. 경제성 입력·G0 외부 의존성

수수료는 일반 안내와 개인 계약을 대조해야 하고, 거래세는 시장·연혁 유효일별 테이블이 필요하다.
일봉 체결·spread/impact·부분체결 가정은 RESEARCH_ESTIMATE이며 실제 비용 계약이 아니다.
반복 서버비·데이터비·현금이자도 실제 계약/청구가 없다. 비용값을 임의 0으로 채우지 않았다.

VERIFIED_CONTRACT, OBSERVED, RESEARCH_ESTIMATE, UNVERIFIED의 의미를 확보 계획에 구분했다.
자본, 스트레스/ES·손실 한도, 공급자/구매 예산, 최소 경제적 개선은 USER_DECISION_REQUIRED다.
평가기간·독립 표본·구간 분리·불확실성 방법·거절/미체결 정책도 미정이다.
candidate-v1의 기존 코드·설정 동결은 유지하지만 확인적 G0 완료로 처리하지 않는다.

권리 답변 → PIT bundle 견적·샘플 → 사용자 예산/수집 범위 승인 → 작은 수직 경로 검증 →
비용·자본·위험·OOS 계약 동결이 다음 순서다. 현재 생존 종목만으로 시장 전체 경제성을 주장하지 않는다.

## 7. 검증·안전성

기존 **285 PASS**를 변경 전과 종료 때 각각 실행했다. 신규 **11 PASS**를 더해
전체 **296 PASS / 0 FAIL / 0 SKIPPED**다.
신규 조건은 목적별 권한·저장 구분·출처·scope, 과거 종목군·기업행위·calendar·날짜형 입력,
추정 비용·G0, 주문/취소·민감 파일 차단이다.
단순 HOLD 시험 수가 외부 증거 해결을 뜻하지 않으며 이번 진전은 공식 FAQ 본문과 실제 공급 제약 확인이다.

`python scripts/verify.py --milestone km005r1`로 pytest/Ruff/format/mypy/sdist·wheel,
기존 demo 및 KM-002~004 replay, 데이터 없는 환경 HOLD와 독립 JSON 검사를 실행했고 모두 PASS다.
원문 stdout/stderr·JUnit·checks는 `artifacts/km005r1`에 보존했다.
개발 중 Ruff 변수명/긴 줄 오류를 고친 뒤 최종 검사에 통과했다.

로컬 `scripts.audit_km005r1`은 이전 hash·명세 바이트·원시 데이터 공개 경로와 승인된 env 키 값을
출력 없이 대조했다. 공개 파일 정책·비밀 검사 PASS. 실제 키 자동 탐색은 하지 않았다.
인증·시장 시세·계좌 조회·주문·취소 0회이며 공개 약관·공급원 문서 GET은 별도다.
KM-006, OOS, PR 병합·배포·실전 활성화는 수행하지 않았다.

## 8. GitHub 검증

정상 push 대상은 `origin/km-005r1-data-evidence`다. 구현 SHA 대상
[Run 38937223672](https://github.com/amandalmoon/k-mast/actions/runs/38937223672)는 completed/success다.
Python 3.11과 3.12 각각 296 PASS를 실제 job 로그에서 확인했다.
Ruff/format/mypy/build·기존 replay·데이터 없는 환경 HOLD 검사도 모두 성공했다.
정확한 SHA·Python matrix·단계 결과는 remote-ci-implementation.json과 로그 발췌로 보존한다.
종료 커밋은 보고서와 증거만 포함하며, 최종 원격 HEAD의 CI도 확인해 최종 응답에 별도로 제출한다.
force push·기존 이력 삭제·기본 브랜치 변경은 없다.

## 9. 최종 판정

**KM005R1_EXTERNAL_EVIDENCE_PENDING**: 공식 FAQ 본문과 개인 분석·저장 근거, 공급자 비용·DB 제한,
목적별 계약 및 외부 결정 목록을 확정했다. 적격 과거 시장자료와 장기·백테스트 세부 조건은 남아 있다.
**ECON_NOT_EXECUTED**: Alpha A 비용 후 수익성을 계산하거나 통과시킨 결과가 없다.
**LIVE_NOT_APPROVED**: 실제 주문·취소·자금·배포 권한은 변경하지 않았다.
