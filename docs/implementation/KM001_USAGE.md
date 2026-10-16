# KM-001 로컬 실행

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python -m kmast.data.cli fixture --output data/km001
.\.venv\Scripts\python scripts/verify.py --milestone km001
```

기본 실행은 합성 Fixture만 사용한다. 검증 스크립트는 외부 서비스와 인증 없이 실행한다.
실제 연결은 이번 작업에서 수행하지 않았다. 사용자가 별도 허용하고 로컬 보호 경로에
BrokerConfig JSON을 직접 설정한 뒤에만 아래 형식으로 선택할 수 있다.

```powershell
.\.venv\Scripts\python -m kmast.data.cli read --allow-network-readonly --credentials-file <보호된_로컬_파일> --symbol 005930 --operation daily --start 2026-10-14 --end 2026-10-15 --interval-seconds <계좌별_승인된_간격> --max-requests 5 --output data/km001
```

경로/키/계좌번호를 코드·Git·채팅에 넣지 않는다. credential JSON은 저장소 외부에 두고
environment/credential_environment/account_environment, 정확한 endpoint, app_key/app_secret,
account_ref를 사용한다. 예시 secret 파일은 생성하지 않는다. LIVE 브로커 환경은 실전 시세
서버를 의미하며 Runtime LIVE 모드/주문 권한을 뜻하지 않는다. 기존 RuntimeConfig LIVE 차단은 유지한다.

단일 실행은 기본 7일·심볼 1개·최대 5회(인증 포함)로 제한하며 GET 재시도는 최대 3회다.
동일 output/request는 불변 캐시를 사용하므로 재다운로드하지 않는다. 최신 snapshot이
필요한 새 수집은 새 output/run을 사용한다. 현재 실행은 한 페이지이며 장기 수집은
검토된 daily_pages helper와 manifest 단위로 확장해야 한다. 분봉 장기 자동수집은 미검증이다.

수집 시 세션/원천 시각/역사적 PIT가 확인되지 않으면 데이터는 보존하되 품질을 잠근다.
프로그램 성공 exit code는 DATA_READY나 수익성 승인이 아니다. 실제 연결을 하기 전에
공식 TR·계좌별 유량·자료권한·범위를 확인해야 한다.

WebSocket은 `KISStream` API로 제공한다. 허용 TR은 H0STCNT0/H0STASP0 두 개다.
NetworkPermit·KISAuth·clock·슬롯/health 한도를 명시적으로 주입하고 subscribe/collect를
호출해야 연결한다. 자동 재연결은 ACK 후 snapshot_provider로 재동기화하며 공급자가 없거나
원천 시각/세션 근거가 불완전하면 SYNCING/GAP 잠금을 유지한다. 보유종목 감시를 포기하는
슬롯 계획은 거부한다. 실제 소켓 통합은 별도 승인된 범위에서 검증해야 한다.

Raw/normalized 파일은 덮어쓰지 않으며 같은 수집 ID의 다른 내용은 quarantine에 보존하고
중단한다. Parquet는 조회 가능한 공통 열과 정확한 Decimal/시간 계약을 보존한 payload_json을
함께 저장한다. manifest는 원본/Parquet/정규화 해시를 연결한다. 재로딩 시 무결성을 검사한다.
정정은 기존 데이터셋을 고치지 않고 새 원문/버전으로 추가해야 한다.
