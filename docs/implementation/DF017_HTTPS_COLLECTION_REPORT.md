# DF-017 HTTPS 수집기 보고

실제 수집은 미실행이다. **실제 REST 인증 0회·시세 0회·TLS 연결 0회·WS 0회**이며 HTTP 상태별 실측·행수·시각·원문/정규화 해시는 NULL이다. 구현 준비와 실제 공급 검증을 분리한다. 공개 집계는 `artifacts/df017/results.json`, 합성 엔진 결과는 `synthetic-engine.json`에 별도로 기록한다.

## 닫힌 실행 경로

수집기는 기본 NETWORK_DISABLED다. `python -m scripts.collect_df017 --execute-approved-paper --approval-record <private-json> --preflight-record <private-json>`는 수동 진입점이며 현재 빈 신뢰 등록부로 인해 실행되지 않는다. 새 명시적 승인과 모든 사전검증의 검토 등록이 필요하다. 키 값은 명령줄이나 문서에 쓰지 않는다. `--help`와 오류는 입력을 노출하지 않는다. 이 명령은 다른 날짜를 기다리거나 예약하지 않는다.

허용 호스트는 `openapivts.koreainvestment.com:29443`이며 `/oauth2/tokenP`와 기존 proposal의 세 GET 경로만 사용한다. raw proposal SHA와 ordinal별 call 전체를 비교하므로 URL·종목·시장·TR·시간 인자·순서를 바꿀 수 없다. 전송기 직접 호출도 동일 승인·고정 call 검사를 거친다. stdlib HTTPSConnection을 직접 사용하므로 환경 HTTP proxy를 사용하지 않으며 redirect를 따라가지 않는다. 환경 CA 파일/디렉터리 override는 거부한다.

기본 CA 신뢰·호스트명 검증·TLS 1.2 이상을 강제한다. TLS handshake가 끝나기 전 appkey/secret/token HTTP 본문·헤더를 보내지 않는다. handshake 후 관측 창을 재확인한다. 이 코드를 모의 객체로 검증했으며 실제 KIS 인증서를 확인한 것은 아니다.

## 예산·시각·실패

각 I/O 전에 hash-chain 불변 예약을 작성한다. 인증 최대 1시도, 각 논리 조회 최대 2시도, 합계 45시도를 영속 복원한다. 401·429·500·TLS/네트워크 실패도 예약을 소비한다. 인증 실패는 재발급하지 않는다. 시세 transient 오류만 같은 ordinal에서 한 번 재시도한다. Retry-After 초/HTTP-date와 등록된 제공자 간격을 우선하고 해석 불가한 지연을 무시해 조기 재시도하지 않는다. 401/403·보안·시계 이상은 중단한다.

전체 응답 종료 또는 실패 종료 시각을 UTC·고해상도 monotonic으로 기록하고 그 이후 최소 3.10초를 기다린다. HTTP 시작을 알 수 없는 예외에는 시작시각을 NULL로 남긴다. 부분 응답을 전체 응답 완료로 표시하지 않는다. TLS·대기·저장 지연으로 늦어진 시각을 그대로 보존한다. earliest-not-before는 성공시각 약속이 아니다. 09:22 이후 새 요청을 시작하지 않고 다음 날 대체하지 않는다.

단일 프로세스 잠금 아래 원문·정규화·예약·결과를 각각 불변 저장하고 해시 계보를 검증한다. 저장량을 먼저 보수적으로 예약한다. 원문 128 MiB/전체 256 MiB를 늘리지 않는다. 인증 응답과 비밀·계좌 필드 또는 알려진 키/토큰이 섞인 시세 응답은 해시만 남긴다. JSON escape를 해제한 키와 문자열도 검사하며, 부분/해독 불가 본문은 비밀정보를 확실히 배제할 수 없어 해시만 보관한다. 토큰은 메모리에만 있다. **중단 후 토큰을 잃으면 기존 예산을 읽기 전용 감사할 수 있으나 재인증·예산 환급·자동 네트워크 재개는 하지 않는다.** 불완전 예약·orphan·임시 파일은 HOLD다.

## 보관·삭제

대상은 정확히 `data/data-first-private-df016-pilot/` 하나다. 최초 시도 예약시각부터 최대 30일로 산정하므로 마지막 수신부터 30일로 연장하지 않는다. 보관권이 등록되지 않으면 수집하지 않는다. 자동 삭제 작업은 없다.

`--retention-plan`은 기존 store의 무결성을 확인한 뒤 파일별 SHA와 만료시각을 private `data/data-first-private-df017-retention-audit/`에 남긴다. `--purge-expired-plan <private-plan>`은 명시적으로 전달된 동일 계획·만료·해시 보관권을 확인한 경우에만 새 pilot store의 해당 파일을 개별 unlink한다. 경로 탈출·symlink·변경된 파일·미만료는 거부한다. 과거 DF001–016 다른 private store는 삭제하지 않는다. 해시 계획을 삭제 전에 저장하며 중도 실패 시 자동 재수집/복구하지 않고 잔존 파일과 계획으로 수동 감사한다. 공급자 계약이 더 엄격하거나 해시 보관을 허용하지 않으면 새 계약/절차 검토 전 실행하지 않는다. 이번 실제 삭제는 0회다.
