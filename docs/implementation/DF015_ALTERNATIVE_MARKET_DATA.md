# DF-015 대체 시장자료 비교

판정: `DF015_ALTERNATIVE_SOURCE_ASSESSMENT_READY`는 비교표와 문의 항목이 준비됐다는 뜻이다. 실제 계약·보안·개장 관측 적격 공급원은 아직 0개다. 이번 단계는 기존 캐시만 조사했으며 아래 후보의 최신 문서나 가격을 조회하지 않았다. 공식 확인 전에는 이용 가능한 상품으로 추천하지 않는다.

| 비교 항목 | KIS PAPER 기존 캐시 | KRX 공식 정보분배/정식 벤더 후보 | LS증권 OpenAPI 후보 | 키움 공식 API 후보 |
|---|---|---|---|---|
| KRX 개별 체결 | 공식 샘플 필드, 실제 제공 UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| 최우선/다단계 호가 | 10단계 필드, 실제 제공 UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| 거래소 이벤트시각 | 초 단위 필드, 실제 정확도 미검증 | UNKNOWN | UNKNOWN | UNKNOWN |
| 실제 수신시각 측정 | 수집기 구현, 실제 측정 없음 | UNKNOWN | UNKNOWN | UNKNOWN |
| 정정·누락·정지/재개 | 완전성/독립 기준 UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| 개장 5/15분 전체 관측 | 미확보 | UNKNOWN | UNKNOWN | UNKNOWN |
| 안전한 인증·최종 구간 | 평문 설정 확인, 보호 경로 UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| 보관·연구 이용권 | 해당 수집 범위 확정 안 됨 | UNKNOWN | UNKNOWN | UNKNOWN |
| 역사 자료 기간 | 동등한 과거 event stream UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| 동시 구독·이용료·셋업/운영비 | NULL | NULL | NULL | NULL |
| 공급원 변경 승인 | 없음 | 없음 | 없음 | 없음 |

후보 식별용 공식 사이트 위치: [KRX](https://www.krx.co.kr/), [LS OpenAPI](https://openapi.ls-sec.co.kr/), [키움 OpenAPI](https://openapi.kiwoom.com/). 이 링크는 검색/문서 확인을 완료했다는 근거가 아니다. 서비스명·지원 범위·가격은 `results.json`에 NULL로 기록했다. 다른 상품을 추측해 호출하지 않았다.

**현재 가장 싼 적격 공급원은 결정할 수 없다.** 비용 비교에는 월 구독·체결/호가 권리·과거 데이터·저장/분석권·셋업·개발/장애 대응·관측 장비/시계 비용을 포함해야 한다. 비용을 확인하지 않고 0원이라고 가정하지 않는다. 우선 기존 KIS 경로의 공급자 서면 답변을 확보하고, 충족하지 못하면 같은 두 종목·네 입력 요구를 기준으로 후보들의 공식 서비스/견적을 비교하는 순서가 합리적이다. 이는 구매·전환·문의 자동 송신 승인이 아니다.

REST 일봉이나 스냅샷을 완전한 체결·호가 기록으로 대체할 수 없다. 체결별 시각, 호가의 순서, 개장 첫 체결과 누락 기준이 필요하다. 공급원 변경은 별도 데이터 계약, endpoint, 보안 검증, 저장권·예산·날짜와 새 실행 승인으로 등록한다. 그 전에는 B ORB의 실제 거래 가능성이나 수익성을 평가하지 않는다.
