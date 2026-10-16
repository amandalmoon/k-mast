# KM-005R1 최소 확보·외부 결정 계획

이 문서는 수집 승인이 아니다. 현재는 **EXTERNAL_EVIDENCE_PENDING**, 실제 추가 수집 0행이다.

## 1. 최소 의존성과 승인 순서

| 우선순위 | 필요한 자료/결정 | 요청 대상·완료 증거 | 상태 |
|---|---|---|---|
| 1 | 비공개 백테스트와 보관기간·종료 후 사용 | KIS 공식 서면 답변, 문서 버전·조항·목적별 범위 | EXTERNAL_EVIDENCE_PENDING |
| 2 | 과거 master/상폐/정지·권리·calendar·공표 정책 bundle | KRX 맞춤자료·코스콤 견적과 sample schema, 날짜별 snapshot/정정 예시 | EXTERNAL_EVIDENCE_PENDING |
| 3 | 구매 예산·계약할 공급원과 저장/연구 목적 | 사용자 결정, 해당 목적의 계약·견적 승인 | USER_DECISION_REQUIRED |
| 4 | 유한 수집 범위 | 종목·기간·인증 환경·최대 요청수·재시도·저장 위치 명시 승인 | USER_DECISION_REQUIRED |
| 5 | A의 전체 경로와 현금·단순 비교 | 적격 입력으로 기존 Alpha/Reference/OMS/Bridge 사용, 비용 모드 명시 | NOT_EXECUTED |
| 6 | 확인적 G0/OOS | 아래 미결정 값·구간·한도·승인 역할 동결 | NOT_FROZEN |

전체 시장 결과를 위해 당시 종목군과 이후 상폐 종목을 포함할 수 있어야 한다.
현재 생존 종목만의 수년 가격은 이 요건을 충족하지 않는다.

## 2. 공급자에 요청할 최소 상품 명세

견적 후보 연구 범위는 KOSPI/KOSDAQ 보통주 2019-01-01~2025-12-31이다.
이는 여러 국면을 포함할 공급 가능성 문의 범위이며 평가 구간이나 OOS를 확정한 것이 아니다.

- 일별 당시 전체 종목 master: 상장·폐지·정지·재개, 코드/시장 변경·업종, 적용일과 공표/정정 시각.
- 원 OHLCV·거래대금, 지수·업종, 과거 revision과 수정계수·분할·병합·배당 권리/효력/지급일.
- 공식 거래일·특별장·휴장·세션 정의, 집계 venue, 제공 지연·확정·정정 정책.
- 원본/정규화 로컬 저장과 이용 종료 후 보관·재사용, 비복원 집계 공개 조건.
- 최초 구매·월/연 구독·갱신·재다운로드·정정본 비용, VAT, 호출/반출 상한, 파일/API schema.

KRX·코스콤의 실제 견적은 **미확정이며 0원이 아니다**. DataGuide의 공개 첫 계정 연 720만원+VAT는
위 DB 구축 권한이나 bundle 견적이 아니다. 구매를 진행하지 않는다.

## 3. 첫 실제 수집 제안 — 승인 전 실행 금지

권리와 공급 bundle이 확인된 뒤, 먼저 2021-01 한 달의 역사적 master·calendar·기업행위 파일과
당시 적격 종목 최대 2개의 RAW 일봉, 해당 시장 지수로 파일 기반 수직 경로를 검사하는 것을 제안한다.
종목은 승인된 당시 master에서 사전 규칙으로 정하고 수익을 보고 선택하지 않는다.
상폐 이력의 실제 제공 여부는 별도 schema/원본 샘플로 검증하며 상폐 종목 사후 선택 수익을 제시하지 않는다.
월의 실제 거래일 수·기업행위 유무·종목코드는 공급자 자료 확인 전 임의로 생성하지 않는다.

기본은 네트워크 OFF다. 유료 계약·API 환경·endpoint별 페이지 수가 아직 정해지지 않아 요청수도
임의로 승인하지 않았다. 승인 요청서에는 최대 인증/시세 요청수·종목·날짜·재시도와
`data/km005r1-private-*` 같은 Git 제외 절대 저장 경로를 확정해야 한다.
지금 추가 인증을 요청하지 않는 이유는 권리·공급 범위·비용이 아직 정해지지 않았기 때문이다.
기존 KIS 최대 2심볼·유한 기간·request budget·pacing·캐시·resume 계약을 우회하지 않는다.

## 4. 경제성 입력의 실제 확보 경로

| 항목 | 확보 경로 | 현재 적용 상태 |
|---|---|---|
| 매수/매도 수수료 | KIS 공식 수수료 안내 + 사용자 계약/이벤트·유관비용 적용일의 비밀 제거 증빙 | UNVERIFIED. 일반 요금을 개인 계약값으로 사용하지 않음 |
| 시점별 거래세 | 국가법령정보센터의 시행령 제5조 및 부칙, 시장·기간·면제 조건 | 공식 연혁 경로 확인. 연구 대상 기간이 정해지면 유효일 테이블 대조 필요, 현재 비용값 UNVERIFIED |
| 일봉 실행·지연·spread/impact | 거래 가능 세션·다음 거래 시점·정지/제한·호가/체결, 보수적 범위 등록 | RESEARCH_ESTIMATE로만 설계 가능. 실제 계좌 비용/체결률로 인증하지 않음 |
| 매수/매도 불가 | 시점 master/정지·가격제한·세션 상태 | UNVERIFIED, 청산 불가 노출은 유지해야 함 |
| 서버 운영비 | 선택 서비스의 계약·청구·기간, 실제 결제 증빙 | USER_DECISION_REQUIRED / UNVERIFIED |
| 데이터 구독료 | 목적·범위에 맞는 견적/계약·갱신 조건 | UNVERIFIED. 무료 가정 금지 |
| 현금이자 | 사용자 계좌 약정·지급일과 실제 입금 | UNVERIFIED. 무상 이자를 가정하지 않음 |

상태는 VERIFIED_CONTRACT / OBSERVED / RESEARCH_ESTIMATE / UNVERIFIED로 관리한다.
기존 CostScenario의 CONTRACT enum은 VERIFIED_CONTRACT에 대응하지만 필수 값·증빙·유효일 검사를
통과해야 한다. 원시 시세와 실계좌 거래내역은 공개하지 않는다.

공식 경로:
[KIS 수수료](https://securities.koreainvestment.com/main/customer/guide/_static/TF04ae010000.jsp?tab=2),
[증권거래세법 시행령 연혁](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=280901),
[2026년 시행 개정문](https://www.law.go.kr/lsInfoP.do?lsiSeq=282431&viewCls=lsRvsDocInfoR).
확인일 2026-10-17. 일반 안내·법령의 존재가 개인 적용값 검증 완료를 뜻하지 않는다.

## 5. G0 결정 대장

| 항목 | 담당 결정/근거 | 상태 |
|---|---|---|
| 초기 자본·자본 시나리오 | 사용자 연구 자본 명시, 실전 자금과 분리 | USER_DECISION_REQUIRED |
| 스트레스·ES·손실·집중·용량 한도 | 사용자 위험 수용 + 추정/검증 근거 | USER_DECISION_REQUIRED |
| 비교전략·최소 경제적 개선 | 현금/단순 보유·추세/FIXED, 동일 평가 조건 | USER_DECISION_REQUIRED |
| 평가기간·연구/검증/locked OOS | 실제 제공기간과 독립 사건 수, 사전 disjoint manifest | POLICY_DECISION_REQUIRED |
| 비용·거절·미체결·청산불능 | 계약/실측/추정 구분, 시나리오와 불확실성 범위 | EXTERNAL_EVIDENCE_PENDING |
| 신뢰구간·의존성·표본·탐색 수 | 공통 충격/중첩 보유를 반영한 사전 방법 | POLICY_DECISION_REQUIRED |
| 후보 파라미터·코드 | 기존 candidate-v1와 KM-005 freeze 파일 유지 | FROZEN_CANDIDATE_ONLY |
| 확인적 G0 전체 | 위 승인과 동결 시점이 성과 확인 전임을 입증 | NOT_FROZEN |

데이터를 일부 확보해도 곧바로 G0·G1·G2/G3 완료로 처리하지 않는다.
본 단계에서 OOS를 열거나 KM-006을 시작하지 않는다.
