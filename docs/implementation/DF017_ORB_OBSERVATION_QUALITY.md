# DF-017 ORB 관측 품질

실제 수집이 없으므로 다음 여덟 판정은 모두 **NULL**이다: SOURCE_OK, SCHEMA_OK, TEMPORAL_OK, MARKET_OK, CORRECTION_OK, ORB5_OK, ORB15_OK, POST_SIGNAL_QUOTE_OK. 실제 ORB 범위·후속 후보·호가도 NULL이다. 실패 원인은 새 인간 승인 및 독립 사전검증 부재다. 합성 PASS는 이 NULL을 채우지 않는다.

SOURCE는 공식 PAPER에서 원응답을 받고 무결성을 감사했는지, SCHEMA는 필드·타입·숫자·시각 구조가 맞는지다. TEMPORAL은 완성 봉과 실제 가용시각·라벨 의미, MARKET은 당시 세션/시장/VI/정지, CORRECTION은 필요한 수정·누락 계보를 의미한다. SOURCE가 좋아도 ORB를 승인하지 않는다. 실제 공급이 성립해도 현재 미해결 의미로 완전 적격 ORB가 0개일 수 있다.

오프라인 진단기는 성공한 실제 source와 정상 schema를 독립적으로 표현할 수 있지만 라벨·시장·정정이 미검증이면 연구 게이트는 False/HOLD다. 합성 origin은 실측 SOURCE/SCHEMA를 NULL로 유지한다. 연구 게이트를 열기 위해 기존 DF-016의 unknown flag를 제거하지 않는다.

완성 범위와 이후 완성 봉 종가 돌파까지가 연구 범위다. 신호 검증 뒤 별도 요청한 유효 호가만 후속 스냅샷이며 체결이 아니다. execution_verified=False, 손익 NULL, 경제성 미검증이다. 이전 적격 20거래세션이 없어 RVOL_NOT_READY이며 당일 자료로 대체하지 않는다.
