# DF004 종료 보고서

연구 판정은 **EWY_EXPLORATORY_SIGNAL_NOT_SUPPORTED**다. EWY를 Alpha A에 편입하지 않는다.
기술 준비, 데이터 적격성, 경제성, LIVE 승인을 분리한다.

| 구분 | 실제 상태 |
|---|---|
| 기술 | 별도 ForeignBar·인과 매핑·96 Reference·독립 회계 검사 구현 |
| 데이터 | EWY251세션·공통 KR217일 확보, 엄격 공표시각0일; 일부 provenance 미확인 |
| 경제성 | 탐색 채택 근거 불충족; ECONOMIC_EDGE_UNVERIFIED |
| 실전 | LIVE_NOT_APPROVED; 실계좌·주문·취소·배포·병합0회 |

프로토콜 원격 커밋 `52c0838d5837d3b6116c0165806658b911ef2c64`는 공급원 응답/결과 확인 전에 별도로 push했다.
354개 기준 시험을 먼저 확인했으며 기존 V2 72·V3 90·DF003 216개 결과와 preflight에서 고정한
원본 파일을 변경하지 않았다. 허용한 기존 파일 변경은 README·CI·검증 스크립트·의존성뿐이다.

최종 로컬 검증은 `artifacts/df004/checks.json`와 JUnit·각 stdout/stderr에 기록한다.
기존354개 + 신규32개 = **386 PASS**를 실제 최종 검증했다.
Ruff·format·mypy·build, OMS/Alpha/joint 재생, 이전 V2/V3/DF003 독립 회계와 신규96개 회계를 실행한다.
비공개 경로는 Git 제외하고 키 값을 출력하지 않은 정확 문자열 유출 검사를 수행한다.

수집 한도9/12요청·인증2/2는 지켰다. 원응답 보존1페이지/가격 필드 해시3페이지,
초기 요청간격 최대2.618ms 미달 및 후속 경로 기록 오류를 숨기지 않았다.
최종 코드의 응답후3.05초 대기·캐시·누적 예산·단일 실행 잠금을 오프라인 시험했다.
수정 뒤 실제 인증 재검사는 하지 않았다. 데이터 적격성 완전 통과로 표현하지 않는다.

최초 실행 source hash는 implementation-contract.json에 보존한다. 종료 시 실행 스크립트의
문자열 줄바꿈 및 기존 계약 재실행 가드만 추가했으며, preservation-audit.json은 이를 제거한
소스의 원래 SHA와 AST 동등성을 확인한다. 연구 엔진 바이트는 최초 실행 이후 변경하지 않았다.

최종 브랜치 `codex/df004-ewy-leadlag`를 정상 push하고 정확한 원격 HEAD의 Python3.11/3.12
GitHub Actions 결과를 확인한다. 원격 결과 확인 전 CI PASS를 주장하지 않는다.
최종 SHA의 CI 증거는 순환 커밋을 피하기 위해 Git 제외 `data/data-first-final/df004/remote-ci.json`에 남긴다.

세부 근거: [데이터·정렬](DF004_DATA_COLLECTION_AND_TIME_ALIGNMENT.md),
[신호·경제성 평가](DF004_EWY_SIGNAL_EVALUATION.md), `artifacts/df004/results.json`.
