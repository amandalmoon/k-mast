# DF-015 KIS 전송 보안 조사

판정: **DF015_TRANSPORT_PROTECTION_PENDING** / **B_ORB_STREAM_TRANSPORT_BLOCKED**.
기존 캐시에 공식 PAPER TLS 경로가 입증되지 않았다. 제공자가 그러한 서비스를 전혀 제공하지 않는다고 단정할 근거도 없다. 최신 FAQ·공지·API Reference·비공개 전용선 지원 여부는 UNKNOWN이다. 이번 단계는 지시된 오프라인 조사이며 새 문서 조회·인증·WebSocket·TLS 시험은 0회다.

## 확인한 공식 근거

공식 저장소 고정 커밋 `2077773a69a428daf63e148182511f068cc45de3`의 다음 네 원문을 로컬에서 SHA-256으로 재검증했다. 원문은 기존 private store에 보존하고 새 코드로 복사·실행하지 않았다. URL은 출처 표시이며 이번 단계에 새로 접속한 기록이 아니다. 전체 해시는 `artifacts/df015/results.json`의 `sources`에 있다.

| 공식 원문 | 확인한 사실 | 입증하지 못하는 것 |
|---|---|---|
| [kis_devlp.yaml](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/kis_devlp.yaml) | `vops=ws://ops.koreainvestment.com:31000`, `vps=https://openapivts.koreainvestment.com:29443` | 다른 공식 TLS 서비스의 존재/부재, 현재 권한 |
| [kis_auth.py](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_user/kis_auth.py) | 180행에서 PAPER `vops` 선택, 491/498행에서 승인키 취득·WS 헤더 구성, 717행에서 선택 URL로 연결 | 평문 최종 구간의 암호화, 현재 계정의 시세 권한 |
| [국내 WebSocket 함수](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_user/domestic_stock/domestic_stock_functions_ws.py) | KRX 체결·호가의 demo 분기 및 47/63개 필드 | 실제 PAPER 제공·품질·동시 구독 허용 |
| [README](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/README.md) | 공식 샘플의 이용 맥락 | 장기 저장권·추가 계약·보안 SLA |

`ws://`는 TLS WebSocket이 아니다. HTTPS로 승인키를 발급해도 다음 평문 WS 메시지에 키를 넣으면 해당 구간의 기밀성·서버 인증이 보장되지 않는다. 샘플에 존재하는 특정 암호화 데이터의 AES 복호화 함수는 승인키·전체 호가/체결 메시지의 종단 간 보호를 입증하지 않는다. 일반 VPN은 VPN 출구 이후 구간을 자동 보호하지 않으며 로컬 프록시의 TLS도 제공자까지 이어지는 보호의 증명이 아니다.

공식적으로 승인된 wss 호스트·포트, 암호화 전용선, 인증서 정책을 확인하지 못했다. `ws`를 `wss`로 바꾸거나 포트를 추측해 시험하지 않았다. 최신 지원 여부를 확인했다고 표현하지 않는다. API 포털 보안 문서와 공개 FAQ/지원 공지는 캐시만으로 서비스별 결론을 낼 수 없어 NULL이다.

## 공급자 문의 초안 — 전송하지 않음

> KIS PAPER의 KRX 체결 H0STCNT0와 호가 H0STASP0를 사용하려 합니다. 공식 설정의 `ws://ops.koreainvestment.com:31000` 대신 제공자 서버까지 승인키와 시세를 암호화하는 공식 지원 경로가 있습니까? 정확한 URL·포트·서비스 범위와 TLS 버전, 서버 인증서 이름/신뢰 체인 검증 정책, 프록시/전용선 사용 시 마지막 구간의 보호 책임을 서면으로 안내해 주십시오. PAPER의 네 구독 허용 여부·개장 전 구독 가능시각·수신 누락/정정/취소·VI/정지/재개·KRX/NXT 분리 규격, 보관·분석 허용 범위와 비용도 확인 부탁드립니다. 키·계좌정보는 첨부하지 않습니다.

서면 답변을 받더라도 문서상 경로 확인(`DF015_SECURE_PATH_DOCUMENTED`)과 런타임 TLS 서버 인증은 별도다. 후속 프로토콜과 새로운 인간 실행 승인이 필요하며 DF-014의 주소·날짜·예산은 자동 변경하지 않는다.
