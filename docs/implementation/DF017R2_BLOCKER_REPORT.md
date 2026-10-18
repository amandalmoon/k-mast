# DF017R2: 실행 전 차단 요인 해소 현황

## 원격 기준선 확인

DF017 기준은 9bff5ddef584cb1ad85b86b45e133d2b6376aee7이다.
R1 원격 브랜치를 git ls-remote와 GitHub ref API로 새로 조회한 결과는
2421129aae6157eaadac13bc0093348a1b3892f2이다. GitHub run 39113102362의
head_sha가 같고 Python 3.11/3.12 두 job 모두 completed/success임을 새 API
응답으로 확인했다. 이전 보고서의 완료 문구만 신뢰하지 않았다.

[R1 CI](https://github.com/amandalmoon/k-mast/actions/runs/39113102362)

원격 응답 원문은 data/data-first-private-df017r2-audit/에 보존하고,
공개 집계는 artifacts/df017r2/r1-remote-verification.json에 기록했다.
새 작업 브랜치는 codex/df017r2-blocker-resolution이다.

## 해결한 부분과 남은 부분

| 항목 | 실제 확인/산출물 | 남은 차단 |
|---|---|---|
| R1 최종 원격 SHA·CI | 새 원격 조회로 확인 완료 | 없음 |
| 시간 서비스/권한 진단 | Running/Manual, 비관리자, 설정·원본 조회 접근 거부 | 관리자 확인·복구 미허가/미실행 |
| 외부 시간 오차 표본 | 사용자의 별도 측정 허가 후 두 원본 각 6표본 요청 | 6/12 실패, 절대 오차 상한 UNKNOWN |
| 동기화 복구 | 시각·설정 변경 0회, resync 0회 | 측정 후에도 leap 3/Local CMOS Clock, CLOCK_HOLD |
| PAPER 권한·유량·보관 | 공식 문의 문안 작성 | 공식 답변 미수신, PROVIDER_RIGHTS_PENDING |
| 승인·시장 일정/종목 상태 | 실행 전 확인 목록 및 최소 probe 제안 | 새로운 실행 승인 및 공식 당일 근거 없음 |
| 실제 시세/ORB/QUOTE | 신규 broker 호출 0회 | 모든 실측 결과 NULL |

실행 상태: **CLOCK_HOLD / PROVIDER_RIGHTS_PENDING / COLLECTION_APPROVAL_PENDING**.
CLOCK_SYNCHRONIZED_AND_MEASURED 및 PROVIDER_RIGHTS_VERIFIED는 성립하지 않는다.
2026-10-18 현재 창은 아직 지나지 않았다. 2026-10-20 09:22 KST 이상이면
**MISSED_COLLECTION_WINDOW**로 취급하며 새 날짜를 지정하거나 기존 승인을 재사용하지 않는다.
이 보고서는 시점별 증거이며 실행 승인 게이트가 아니다.

## 실제 NTP 측정과 한계

사용자가 허용한 범위는 외부 읽기 전용 오차 측정뿐이다. time.windows.com 및
time.cloudflare.com 각각 6표본, 2초 간격, 명령별 최대 30초, 재시도 0회로 실행했다.
두 명령은 종료코드 0이었지만 개별 표본 실패가 있었으므로 종료코드만으로 성공 처리하지 않았다.
Windows 원본 2/6 성공, Cloudflare 원본 4/6 성공; 오류 0x800705B4·0x80072733를
원문에 보존했다. 성공 offset은 약 -0.319963~-0.333709초이며
abs(offset)+RTT/2 최댓값은 0.34905685초였다. 이는 관측된 지연 보정 참고값이다.
서버·경로의 추가 불확실성 및 인증된 절대 시간 보증이 확보되지 않았고 누락도 있어
실제 <=0.5초 오차 상한으로 승격하지 않는다. 시스템 시간 자체를 보정하지 않았다.
측정 후 로컬 재조회도 미동기화로 확인됐다.

원문·시각·명령·종료코드·SHA는 private, 표본 offset/RTT와 실패 집계는
artifacts/df017r2/ntp-observations.json에 보관한다. 로컬 UTC 시각은 미동기화 시계의
기록이며 신뢰할 외부 타임스탬프로 사용하지 않는다.

[Microsoft w32tm 명령 의미](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/Windows-Time-Service-Tools-and-Settings)
및 [Cloudflare 공식 NTP 원본](https://developers.cloudflare.com/time-services/ntp/usage/)을
참고했다. NTP 질의는 broker 인증이나 시세 호출이 아니다. 자세한 복구 허가 범위,
관리자 수동 절차와 장중 freshness/즉시 중단 정책은 DF017R2_CLOCK_PLAN.md에 있다.
이 정책의 구현·가동·추가 NTP 예산은 승인되지 않았다.

## 공식 답변 및 실행 전 적격성

DF017R2_KIS_INQUIRY.md는 사용자가 검토할 미전송 문의 초안이다. 세 TR별 PAPER
지원·계정별 제한·연구/보관·파생자료/해시·분봉 START/END·확정/정정·필요 신청을
각각 질의한다. 자동 전송하지 않았고 공식 답변은 NULL이다.

수집 전에는 (1) 새 인간 실행 승인, (2) 적용 가능한 공식 서비스/권리 증거,
(3) 원본 proposal SHA 및 22개 정확한 호출, (4) KRX 당일 거래일·특별개장,
(5) 073240·462860 공식 정지/재개·시장상태, (6) 실제 PC 오차 상한,
(7) 고정 HTTPS 서버·CA/hostname/TLS 정책을 모두 독립 검토해야 한다.
현재 공개 경로의 PAPER 문서화와 정적 TLS 정책은 실제 계정 권한·런타임 TLS 연결의
증거가 아니다. 장중 시장상태, 최초 체결, 분봉 라벨, 완성·정정은 각각 UNKNOWN이며
실제 관측 후에도 ORB 적격성을 자동 승인하지 않는다.

자체 문서·해시·boolean 및 본 일관성 검사기는 독립 승인 검토가 아니다.
TRUSTED_REVIEWS는 비어 있으며, 원본 수집기와 22개 요청은 변경하지 않았다.

## 서비스 권한을 확정할 수 없을 때의 최소 대안

CAPABILITY_PROBE_PROPOSAL.json은 기존 22개 관측과 별개의 **미승인 제안**이다.
기존 날짜 2026-10-20의 09:01:20~09:04:00 KST, 073240만, PAPER/J,
인증 1회+세 TR 각 1회, 재시도 0회, 총 4회, 응답 완료 후 3.10초로 한정한다.
원문 3 MiB/전체 8 MiB/응답당 1 MiB, 최대 30일 private 보관을 제안한다.
원시 인증 응답·비밀정보를 보관하지 않는다. 실행기는 구현하지 않았다.

이 제안은 이번 원격 커밋으로 결과 확인 전에 등록되지만 실행 승인/승인 등록부 항목이 아니다.
권한 불확실성은 probe의 연구 질문이 될 수 있으나 데이터 이용권 자체를 우회하지 않는다.
필요한 권리 증거(또는 최소 진단에 한정한 공식 허용), 정확한 새 사용자 승인,
시계·달력·종목 상태·TLS 검증과 별도 독립 코드/프로토콜 검토가 모두 필요하다.
기존 수집기에 다른 call 목록을 밀어 넣거나 빈 게이트를 우회하지 않는다.
성공 응답이 와도 보관권·분봉 의미·ORB·경제성 증거로 승격하지 않는다.
범위를 수정하면 새 해시와 새 승인을 받아야 한다. 시각을 놓치면 MISSED이며
다른 날짜·종목·API로 대체하지 않는다.

RVOL_NOT_READY / ECONOMIC_EDGE_UNVERIFIED / LIVE_NOT_APPROVED /
B_ORB_STREAM_TRANSPORT_BLOCKED를 유지한다. 새 전략·수익률 실험은 추가하지 않았다.

## 검증 및 인계

기존 735개 테스트를 변경 없이 보존했고 33개 로컬 검증 명령이 통과했다.
Ruff/format, mypy(96개 src 파일), sdist/wheel, 기존 OMS/Alpha/중앙 포트폴리오
합성 재생, V2/V3 및 DF003~017R1 증거의 독립 검사를 포함한다. 신규 전략이나
추가 테스트 수를 성과로 삼지 않았다. NTP 원문 표본/오류/해시도 --private 검사에서
재계산했다. 22,441개 기존 비공개 파일과 기존 명세/수집기/
승인 게이트가 보존됐고 비밀정보 검출은 0건이다.

GitHub에 정상 push 후 정확한 최종 SHA의 Python 3.11/3.12 CI를 별도로 확인하고
최종 전달 메시지에 링크한다. 로컬 PASS를 원격 CI 성공으로 대신하지 않는다.
남은 사용자/외부 조치는 관리자 시간 복구의 별도 허가·실행, KIS 문의 검토/제출과
공식 답변, 당일 시장 근거 및 별도 수집 승인이다. 문의 자동 전송·시각 복구·시세
수집은 수행하지 않았다. 이 단계의 완료는 실행 적격성 승인을 의미하지 않는다.
