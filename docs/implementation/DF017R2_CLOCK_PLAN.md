# DF017R2 Windows 시간 복구·측정 계획 — 실행 미승인

읽기 전용 진단 결과: W32Time Running / Manual, 비관리자 프로세스.
status/verbose는 종료코드 0이나 leap 3, stratum 0, Local CMOS Clock,
마지막 오류 1(시간 데이터 없음), 유효한 마지막 성공 동기화 시각 없음.
source 및 configuration은 2147942405(접근 거부); peers 조회 종료코드는 0이며
원문은 비공개로 보존했다. peers 조회 성공도 유효한 시계 동기화의 증거는 아니다.
서비스가 실행 중이라는 사실이나 phase offset 0은 동기화·실제 오차의 증거가 아니다.
초기 R1의 모든 원문과 종료코드는 보존하며 새 원문도 private audit에만 보관한다.

## 해결 구분

- 로컬 확인 완료: 서비스 실행 여부, 권한 부재, 접근 거부, 미동기화 상태.
- 사용자 조치/허가 필요: 관리자 터미널에서 기존 시간 원본·도메인 정책 확인 및 복구.
- 별도 외부 통신 허가 필요: 신뢰할 시간 기준에 대한 직접 offset/RTT 관측.
- 미확정 원인: DNS, UDP 123, 원본 서버, 도메인 정책 중 무엇이 문제인지는 UNKNOWN.
  방화벽 해제, 레지스트리 변경, 서비스 재등록, 수동 시스템 시각 설정을 제안 실행하지 않는다.

## 검토 가능한 최소 실행안

1. 사용자에게 복구 허가를 받은 후 사용자가 관리자 터미널에서
   `w32tm /query /configuration`, `/query /source`, `/query /peers`를 확인한다.
   도메인 관리 PC이면 승인된 조직 시간 계층을 유지하고 외부 서버로 바꾸지 않는다.
2. 기존 공식 시간 원본이 올바른 경우에만 관리자 터미널에서
   `w32tm /resync`를 1회 시도한다. 이 명령은 외부/조직 시간 원본에 통신하고
   시스템 시각을 보정할 수 있으므로 현재 실행하지 않는다. 실패 시 재시도하지 않는다.
   잘못된 원본이면 변경할 대상과 설정을 새로 제시하고 별도 허가를 받는다.
   본 작업은 UAC 창을 자동 열거나 권한을 우회하지 않는다.
3. 별도 허가 후 time.windows.com 및 time.cloudflare.com에 대해 각각
   `w32tm /stripchart /computer:<원본> /period:2 /samples:6 /rdtsc`를 1회씩 수행한다.
   총 12개 표본, 명령별 재시도 0회, 명령별 최대 30초 timeout.
   DNS와 UDP NTP 통신이 발생한다. 기존 NTP 설정·시스템 시각을 변경하지 않는다.
   실제 원본 이름·주소·시간·RTT·offset 및 명령 실패를 private로 보존한다.
4. 위 측정은 보안 인증된 절대 시간 보증이 아니다. 대상의 공식 운영 근거,
   경로/서버 불확실성, 왕복 지연·분산, 두 기준 간 불일치를 함께 검토한다.
   단순 abs(offset)<=0.5만으로 통과시키지 않는다. 각 표본의 보수적
   abs(offset)+RTT/2 및 확인 가능한 서버/측정 불확실성을 합한 경계가 <=0.5초이고,
   양 원본·표본이 일관되며 W32Time의 유효한 동기화 상태가 확인될 때만
   CLOCK_SYNCHRONIZED_AND_MEASURED를 검토한다. 추가 오차 상한이 미확인이면 HOLD.
   timeout/누락/음수 RTT/잘못된 stratum/leap/구식 표본/원본 불일치는 HOLD.

Microsoft 공식 설명: https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/Windows-Time-Service-Tools-and-Settings

Cloudflare 공식 원본 설명: https://developers.cloudflare.com/time-services/ntp/usage/

## 관측 당일 운영 정책 — 구현·가동 아님

허가된 운영자가 시작 전 60초 이내에 동기화 상태와 실제 오차를 재검사한다.
관측 중에는 허가된 별도 측정 예산으로 60초마다 재검사하고 매 broker 요청 직전에
측정의 freshness와 <=0.5초 경계를 확인한다. 추가 NTP 운영 예산을 승인받기 전에는
이 정책을 활성화하지 않는다. 측정 age>60초, clock jump, 동기화 실패, 상한 초과,
원본 교체/불확실성 발생 시 즉시 신규 요청을 중단하고 CLOCK_HOLD를 기록한다.
인증 재발급·날짜 변경·다른 원본으로의 자동 fallback을 하지 않는다.
기존 수집기의 monotonic/UTC jump 검사는 절대 시계 오차 측정을 대체하지 않는다.
외부 watchdog 결과를 기존 승인 게이트에 자동 등록하지 않는다. 이 운영 절차의 실제
적용과 중단 동작이 독립 검토되기 전 수집은 허용되지 않는다.
