# KIS 읽기 어댑터 가정과 확인 범위

확인일: 2026-10-16 (Asia/Seoul). 계좌 인증·시세 요청·주문 호출은 실행하지 않았다.

| 항목 | 공식 근거와 확인 내용 | KM-000 구현 / 미확인 |
|---|---|---|
| REST 인증 | [KIS 공식 포털](https://apiportal.koreainvestment.com/intro)에서 Appkey/App secret으로 토큰 발급 후 REST 호출 구조 확인 | AuthProvider 인터페이스, 메모리 토큰, 잠금·만료·계좌/환경 검사. 실제 발급 구현 없음 |
| REST 환경 | [공식 환경 샘플](https://github.com/koreainvestment/open-trading-api/blob/main/kis_devlp.yaml)에서 prod/vps 및 실전/모의 키·계좌 분리 확인 | LIVE `https://openapi.koreainvestment.com:9443`, PAPER `https://openapivts.koreainvestment.com:29443`의 정확 일치 검사 |
| WebSocket | 공식 포털은 별도 접속키 후 연결 구조 안내 | 상태·재연결 generation·동기화 계약만 구현. 실제 소켓·접속키 발급 없음 |
| 토큰 수명 | [공식 인증 샘플](https://github.com/koreainvestment/open-trading-api/blob/main/examples_user/kis_auth.py) 참조 | 고정 수명 가정 없이 provider의 issued_at/expires_at 사용. 30초 갱신 여유는 내부 정책이며 브로커 제한이 아님 |
| 요청 제한 | 사용자 계좌·TR·가입 시점의 실제 적용 한도 미확인 | 기본 한도 숫자 없음. RatePolicy에 명시 근거와 간격을 주입. 프로세스 내 환경/계좌 공통 및 TR pacing, 다중 프로세스 조율은 KM-001 이후 |
| TR ID·읽기 경로 | 동적 `/docs` 요청은 `/intro`로 리다이렉트됨. 개별 TR 계약 확인 완료로 간주하지 않음 | 기본 허용 경로 0개. 테스트 경로와 TR은 SYNTHETIC. KM-001에서 개별 공식 문서와 대조 후 코드 리뷰 필요 |
| 시장·수수료·구매력 | 계좌 자료 없음 | 세율·수수료·잔고·주문가능금액·체결 범위를 확정하지 않음 |

어댑터는 주입된 GET transport만 사용한다. 기본 네트워크 transport는 없으며,
주문/취소 메서드는 무조건 PermissionError다. ReadRoute의 경로 검사는 보조 장치다.
문자열 필터만으로 모든 API의 읽기 전용 성격을 증명할 수 없으므로 실제 경로 등록은
공식 TR 확인과 KM-001 구현 감사가 선행되어야 한다.

키 환경 라벨 검사는 구성 혼용을 막지만 실제 키가 어느 계좌에 발급되었는지를 오프라인에서
증명하지 못한다. 실제 키·계좌 권한 확인은 후속 단계의 별도 작업이다. 현재 테스트는 가상 값만 사용한다.
