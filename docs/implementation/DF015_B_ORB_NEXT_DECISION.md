# DF-015 B ORB 다음 결정

현재 결정은 `B_ORB_STREAM_TRANSPORT_BLOCKED`다. 문서상 공식 TLS 경로가 확인되지 않아 `DF015_TRANSPORT_PROTECTION_PENDING`을 유지한다. 공식 서비스 자체의 부재를 입증하지 못했으므로 `DF015_SECURE_PROVIDER_PATH_UNAVAILABLE`로 단정하지 않는다. 시장자료 공급과 연구 적격성은 별도이며 ORB는 HOLD다.

## 시장상태·시간의 미해결 조건

| 항목 | 로컬 근거와 후속 필요 자료 |
|---|---|
| KRX 정규장·특별개장 | DF-014 개장 가정은 정확한 2026-10-19 거래일/특별 일정의 검증이 아님. 공식 일자별 세션 공지와 캘린더 필요 |
| VI·정지·재개 | 공식 샘플의 `TRHT_YN`, `VI_STND_PRC`, `HOUR_CLS_CODE`, `NEW_MKOP_CLS_CODE`, `MARKET_CLS_CODE` 존재를 확인. 필드 존재만으로 시점별 연속매매를 인증하지 않음. 상태 전이 규격과 독립 시점별 상태원 필요 |
| 정정·취소 | 체결 unique ID, 취소/정정 연결, 누락 복구의 완전한 제공 계약 미확인. `corrections_verified=False` 유지 |
| KRX/NXT | 선택 채널은 KRX용 샘플. NXT/통합 거래대금으로 조용히 결합하지 않음. 현재 서비스의 venue 규격 및 실제 검증 필요 |
| PC 시계 | `w32tm /query /status`는 로컬 읽기만 수행, 종료코드·출력 해시 보존. 시간 서비스/offset 검증을 대신하지 못함. 독립 기준과 측정 오차 상한 필요 |
| 시각 정밀도 | 초 단위 공급자 필드로 밀리초 순서나 네트워크 지연을 역산할 수 없음. 수신 UTC·monotonic·검증 완료시각을 구별 |
| 개장 첫 체결 | 최초 수신한 체결이 실제 첫 체결임을 보장하지 않음. 개장 전 구독 ACK와 공급자/독립 누락 기준 필요 |
| 누락 | 공급자 sequence·backfill·독립 event 총수 기준 미확보. 큐 손실·disconnect를 정상 관측으로 처리하지 않음 |

`continuous_verified=False`, `corrections_verified=False`, `clock_sync_verified=False`, `RVOL_NOT_READY`를 유지한다. 공급 성공만으로 ORB5/15·VWAP·RVOL 연구 적격성을 승격하지 않는다.

## 오프라인 성능과 장애

기존 2,048 합성 프레임의 77.68 frames/s는 당시 디스크 경로의 측정값으로 보존한다. 이번 10개 합성 장애 시나리오는 큐 burst, 디스크 지연, 100개 depth-10 호가 행, ENOSPC, 메타데이터/제어 로그 상한, 재시작 후 연결 예산, 완전/불완전 강제 종료, 원문 orphan을 시험했다. 상세 수치는 `artifacts/df015/stress.json`이다.

256프레임 큐의 257번째 입력은 overflow를 명시하고 HOLD한다. 중단 상태에서 빠진 프레임을 관측 성공으로 계산하지 않는다. 디스크 지연 주입은 실제 fsync archive를 사용하지만 실제 네 채널의 최대 메시지율을 측정한 것은 아니다. 공간 부족과 불완전 복구는 HOLD하며 원문을 삭제하거나 결과를 개선하지 않는다. 정상 fsync 후 강제 종료는 무결성 재개 가능 여부만 검증한다. 저장 상한 1/3 GiB, 큐 256은 그대로다. 실제 35분 연속 처리 용량은 NULL이다.

## 파일럿 일정

동결된 2026-10-19 08:50–09:25 KST 제안은 실행 승인이 아니다. 현재 접속·예약은 0이다. `paper_security.pilot_disposition()`은 종료시각 이후 `DF014_MISSED_OBSERVATION_WINDOW`로 판정한다. 기존 보고서 파일을 현재 시각에 맞춰 덮어쓰지 않으며 DF-015 결과의 평가시각과 함께 읽는다. 다른 날짜에 자동 실행하지 않는다.

다음 단계는 공급자 서면 보안 답변과 시장·권한 증거를 확보한 후 새로운 실행 프로토콜을 작성하는 것이다. 실행 승인은 그 이후 별도다. 경제성 `ECONOMIC_EDGE_UNVERIFIED`, 실전 `LIVE_NOT_APPROVED`를 유지하며 수익률 실험을 하지 않는다.
