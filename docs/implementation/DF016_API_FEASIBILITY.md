# DF-016 HTTPS 공급 가능성

공식 문서상 공급 경로는 `BAR_ORB_HTTPS_SOURCE_DOCUMENTED`, 실제 수집은 `BAR_ORB_COLLECTION_PENDING_APPROVAL`다. 공식 GitHub의 현재 main SHA `2077773a69a428daf63e148182511f068cc45de3`에 고정한 샘플 8개·설정 1개, 공식 포털 API 메타데이터 3개를 공개 HTTPS로 조회했다. 원문 12개의 SHA-256과 출처는 `artifacts/df016/results.json`에 기록했다. 실행/인증 샘플은 import·실행·재배포하지 않았다. 포털 문서의 응답 예시는 실제 PAPER 응답이 아니다.

| TR / HTTPS GET 경로 | 공식 PAPER 근거 | 반환 구조와 한계 |
|---|---|---|
| FHKST03010200 / `inquire-time-itemchartprice` | 포털 virtualDomain/virtualTrId 및 공식 demo 분기 | 당일만, 호출당 최대 30행. output2에 영업일자·체결시각·OHLC 관련 가격·cntg_vol·누적 거래대금 |
| FHPST01060000 / `inquire-time-itemconclusion` | 포털 동일 TR과 demo 분기 | 시각 지정 당일 체결 조회. 체결시각·체결량·누적량·가격·askp/bidp. 완전한 틱 스트림·누락 없는 과거 자료로 보장되지 않음 |
| FHKST01010200 / `inquire-asking-price-exp-ccn` | 포털 동일 TR과 demo 분기 | output1의 접수시각·매수/매도 10단계·잔량·장운영 코드, output2의 예상체결/VI 코드. 스냅샷이며 체결 증거 아님 |

세 경로의 공식 PAPER root는 `https://openapivts.koreainvestment.com:29443`이다. 요청 시장코드는 J=KRX, NX=NXT, UN=통합으로 문서화돼 있다. 최초 제안은 J만 사용한다. PAPER 계정별 실제 권한·반환 필드·지연·오류·제공 개시시각은 NULL이다. 단순 HTTPS 문서 확인을 KIS 시세 서버의 런타임 접속 시험으로 보고하지 않는다.

각 포털의 `tr_cont`는 다음조회 불가로 명시돼 있다. 당일 분봉은 시각 인자를 과거로 이동하는 별도 요청을 검토할 수 있지만 그 방식의 실제 중복·경계·지연은 미검증이며 무제한 페이지네이션을 구현하지 않았다. 당일시간대별 체결의 최대 행수와 정확한 세션별 보존량은 NULL이다. 계정의 초당/일별 실제 한도도 NULL이며 제안된 3.10초는 자체 보수적 간격이지 공급자 한도를 확인한 값이 아니다.

## 인과성에 영향을 주는 공식 주의사항

당일 분봉 API는 전일 분봉을 제공하지 않는다. 미래시각을 지정하면 현재값으로 미래 구간이 채워질 수 있다. 최신 배열 위치의 거래량은 해당 분봉의 첫 체결 전에 이전 분봉 수량처럼 표시될 수 있다. 따라서 미래 query는 응답이 그럴듯해도 전체 차단하고, 진행 중인 최신 행·첫 체결/거래량 대응 미확인은 적격 ORB 입력에서 제외한다. 원행과 flag는 유지한다.

공식 `stck_cntg_hour`의 설명은 체결시각이다. 이것만으로 분봉 START/END 라벨, 실제 종료시각, 확정 게시 지연, 무거래 구간 처리, 정정 완료를 확정하지 않는다. 이 항목은 UNKNOWN이다. `stck_prpr`를 완성 분봉 종가로 쓰는 의미와 `cntg_vol`의 확정 분봉 수량 대응도 별도 확인이 필요하다. FHPST 문서의 `stck_pbpr`와 예시/샘플의 `stck_prpr` 표기 차이도 실제 응답 전에 조용히 정정하지 않는다. FHPST를 독립적인 첫 체결·누락 완전성 기준으로 삼지 않는다.

KRX의 [정규시장 안내](https://regulation.krx.co.kr/contents/RGL/03/03010100/RGL03010100T1.jsp)는 일반적인 09:00–15:30 세션의 참고 근거다. 해당 제안 날짜의 특별개장·휴장·종목 VI/정지·시계 오차를 인증하는 자료는 아니다. 공시 시각을 보충하거나 시장상태를 정상으로 생성하지 않는다. 공시를 후속 전략 입력으로 사용하려면 실제 공개·수신·검증 시각과 별도 출처 계보가 필요하다.

공식 출처: [당일 분봉](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_time_itemchartprice/inquire_time_itemchartprice.py), [당일 체결](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_time_itemconclusion/inquire_time_itemconclusion.py), [호가](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_asking_price_exp_ccn/inquire_asking_price_exp_ccn.py). 공식 포털 상세 메타데이터의 URL·해시·문서상 필드 전체도 결과 JSON에 보존했다.
