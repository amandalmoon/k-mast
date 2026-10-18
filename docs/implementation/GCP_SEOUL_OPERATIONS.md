# GCP 서울 관측 호스트 운영·시계·보안 계약 — 설계만

이 문서는 설치/배포 스크립트가 아니다. VM·서비스·GCP 인증·비용·broker 호출을 생성하지 않았다.
기존 DF017 수집기와 TRUSTED_REVIEWS를 수정하지 않았으며, 구현/독립 검토 전 모든 실행은 HOLD다.

## 한 대의 VM과 지속 상태

승인 후 후보는 Ubuntu 24.04 LTS, e2-medium(4 GiB) 한 대다. e2-small(2 GiB)은
메모리 압박·pyarrow/에이전트 공존을 먼저 시험해야 한다. 동시 대규모 연구/빌드는 로컬·CI에 두고
VM은 승인된 읽기 전용 관측만 담당한다. Spot·MIG·복제 collector·자동 autoscale은 사용하지 않는다.

코드는 root 소유 /srv/kmast/repo의 검증된 정확한 SHA/lockfile로 고정한다.
별도 PD를 repo/data에 일반 mount하며, symlink로 기존 STORE 경로 제한을 우회하지 않는다.
data/data-first-private-df016-pilot의 고정 경로/원본 해시/정규화 lineage/예약 선차감,
단일 프로세스 lock·atomic write·누적 예산을 그대로 유지한다. Git 제외는 암호화나 접근 통제가 아니므로
전용 unprivileged UID, 0700 디렉터리, 최소 파일 권한과 디스크 암호화/접근 제어도 필요하다.
quota·디스크 여유·write/fsync 실패는 인증/추가 요청 전에 HOLD한다.

systemd는 서비스 수명·로그·자원 격리에 사용한다. collector는 disabled/default-off,
Restart=no, 부팅/timer/종속 서비스가 자동 실행하지 않는다. boot_id 변경·기존 reservation·오래된 승인,
유실/rollback journal·미확정 마지막 요청이 있으면 수동 감사만 허용하며 토큰 재발급하지 않는다.
재부팅 후 원래 22개 요청의 인증 예산이 복구되는 것으로 처리하지 않는다.
GCE 자동 host 재시작이 있어도 collector는 자동 시작하지 않는다. 예상치 못한 종료·재시작은 HOLD 알림이다.

NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp, 빈 capability set,
UMask=0077와 필요한 data/RAM credential 경로만 쓰기 허용하는 systemd sandbox를 검토한다.
이 설정과 원본 CLI·키 로더·파일 lock·atomic fsync의 Linux 호환성은 실제 VM에서 시험 전 UNKNOWN이다.
현재 CLI가 읽는 Path.home()/.kmast-readonly/.env와 정확한 approval 증거 경로를
임의로 바꾸지 않는다. RAM HOME/credential 전달 adapter는 별도 검토 대상으로 아직 구현하지 않았다.

boot/code만 snapshot하고 raw/normalized data·credentials·tokens·journal을 boot snapshot에 넣지 않는다.
원시 시세 백업은 보관권과 30일 만료의 snapshot/복제본 삭제까지 별도로 검토하기 전 금지한다.
데이터 PD/예약 원장이 유실되면 snapshot에서 예산을 되감지 않고 수집을 중단한다.
새 VM으로 복구할 때도 동일 실행이 다른 VM에서 살아 있지 않음을 확인하기 전 lock을 삭제하지 않는다.
단일 VM/PD의 재해복구와 데이터 손실 한계는 남으며, 복구된 cache hash만으로 예산 완전성을 증명하지 않는다.

## 서비스 계정·Secret Manager·접근 경로

전용 VM 서비스 계정에 두 secret 각각의 roles/secretmanager.secretAccessor만 부여하고,
project 전체 accessor·Editor/Owner·Secret Admin·서비스 계정 키 파일은 사용하지 않는다.
role의 범위는 secret이며, pinned version은 로더의 계약이다. IAM이 한 version만 자동 제한한다고 주장하지 않는다.
로그/메트릭 전송은 필요한 writer 역할만 별도로 검토한다. VM 서비스 계정 토큰은 metadata 경로로
제공되므로 VM 내부 SSRF/침해의 위험을 인정하고 불필요한 사용자·프로세스·패키지를 줄인다.

secret 접근도 자동 startup 작업으로 만들지 않는다. 외부 GCP credential 획득/Secret Manager 조회는
향후 별도 Google 인증·secret 이전 승인 후에만 가능하며, broker 키 읽기는 기존 실행 게이트 이후에만 한다.
키는 RAM의 제한 파일/credential로 전달하고 command line·Git·디스크 이미지·snapshot·journald에 남기지 않는다.
기존 로컬 키·비공개 과거 자료를 이번 작업에서 업로드하지 않았다.
[공식 최소권한 지침](https://docs.cloud.google.com/secret-manager/docs/best-practices),
[secret 단위 IAM](https://docs.cloud.google.com/secret-manager/docs/access-control).

인바운드는 기본 deny, 관리자 SSH만 IAP의 35.235.240.0/20→TCP22 및 승인된 OS Login 사용자로 제한한다.
공개 0.0.0.0/0 SSH·웹 서버·원격 notebook은 두지 않는다.
[IAP TCP forwarding](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding).
외부 ephemeral IPv4가 있다고 inbound를 개방하는 것은 아니다. 공급자가 고정 IP를 요구하면
장중안도 static IP 730h 요금 및 새로운 공급자 승인을 반영해야 한다.

egress는 내부 DNS/metadata NTP, 필요한 Google API HTTPS와 **고정 PAPER 호스트의 TCP29443**를
검토한다. 443만 허용하면 현재 KIS 경로는 동작하지 않는다. VPC firewall이 FQDN allowlist를 제공한다고
가정하지 않으며, DNS 목적지 IP/TTL 갱신·hostname/CA 검증·방화벽 규칙의 일치 검토가 필요하다.
주소 변경이나 TLS 정책 실패를 광범위 인터넷 허용으로 해결하지 않는다. OS 업데이트 경로는
승인된 유지보수 창으로 분리한다. Google API 접근용 Private Google Access와 Public NAT는 역할이 다르다.
VPC 규칙만으로 metadata 접근이 차단된다고 가정하지 않고 guest 프로세스/SSRF 격리를 검토한다.
실제 DNS/TLS/broker capability probe는 별도 승인 전 수행하지 않는다.

평문 ws://, LIVE 호스트, 계좌·주문·취소, WebSocket 승인키 발급은 차단한다.
TLS>=1.2·신뢰 CA·정확한 hostname·redirect/proxy/endpoint override 금지라는 원본 정책을 보존한다.
VPC firewall만으로 URL/TR 차단을 보장하지 않으며, 앱의 고정 경로·22개 순서 검증을 유지한다.

## 시계 검증 계약

chrony는 [Google 내부 NTP](https://docs.cloud.google.com/compute/docs/instances/time-synchronization/configure-ntp)의
metadata.google.internal만 discipline source로 사용하도록 설계한다. DHCP/기본 외부 pool이 섞이지 않는지
확인한다. Windows R2의 두 외부 NTP 측정 승인을 VM 내부/새 날짜 승인으로 재사용하지 않는다.
Google의 leap smear와 외부 stepping 시간원을 섞어 clock을 조정하지 않는다.

E2는 [PTP 기반 accurate time 지원 목록](https://docs.cloud.google.com/compute/docs/instances/time-synchronization/configure-time-sync)에
없으므로 ptp_kvm/호스트 UTC accuracy metric 또는 1ms 수준의 지원 설명을 E2 보장으로 옮기지 않는다.
E2의 실제 정확도·시간 안정성·재부팅 복구 시간은 아직 NULL이다.

향후 승인된 host 시험에서는 boot_id, source/refid, stratum/reach, Leap status, last/RMS offset,
root delay/dispersion, frequency/skew, sample age, chronyc tracking/sources 원문과 SHA를 남긴다.
각 표본의 aware UTC/KST·CLOCK_REALTIME·CLOCK_MONOTONIC·CLOCK_BOOTTIME와 monotonic duration을
함께 기록한다. chrony Normal만으로 true UTC 오차를 보증하지 않는다. 정밀도와 정확도를 구분한다.

0.5초 기준의 분모는 true UTC다. 내부 source offset·root delay/dispersion·표본 age/측정 지연,
서버/경로의 상한과 leap-smear 차이를 포함하는 보수적 오차 경계가 필요하다.
공식 smear 기간과 true UTC와의 차이를 검토하며, smear 자체가 최대 약 0.5초인 시점에는
다른 양의 오차까지 합하면 기준을 넘을 수 있으므로 HOLD한다. 추가 상한이 UNKNOWN이면 PASS하지 않는다.
필요한 독립 UTC 기준과 no-change 측정 방식·통신 예산은 별도 승인/프로토콜로 정한다.
로컬 오프셋이나 root dispersion만으로 독립 UTC 검증을 대체하지 않는다.

부팅/재부팅/host migration 후 최소 5분 관측·60개 연속 정상 표본(1초 간격)의 안정성을 확인하는
시험안을 제안한다. 부족하면 더 기다리거나 HOLD하며 분봉 시각을 임의 보정하지 않는다.
수집 전 60초 이내 fresh 검증, 관측 중 매 요청 전 age/bound 검사 및 60초 단위 재측정을 요구한다.
같은 chrony 동기화 표본을 1초마다 읽은 결과는 독립 NTP 표본 60개가 아니라 안정성 점검이다.
시간 jump·source 변경·Leap 비정상·미확인 smear·상한>0.5초·오래된 표본·측정 실패 시 신규 요청 즉시 중단,
토큰 재발급/재시작/기존 날짜 변경 없이 HOLD한다. 기존 monotonic/UTC 차이 검사는 절대 UTC 오차 증명이 아니다.
위 clock watchdog은 아직 구현·가동·독립 승인되지 않았다.

## 향후 실제 성능 측정과 안전 시험

호스트 승인과 별도로 정확한 broker 인증·가격 범위 승인을 받은 후에만 실제 KIS 측정을 한다.
DNS 시작/종료, TCP 연결, TLS 시작/peer 검증 완료, HTTP 요청 전송, 첫 byte,
본문 완료·validation 완료, 원문/정규화 atomic write·fsync 완료를 monotonic과 UTC로 구분한다.
현재 collector에 없는 세부 timing은 별도의 검토된 계측 adapter가 필요하며 이번에 수정하지 않았다.
호가 snapshot은 체결이 아니고 HTTP 완료 이전의 신호 가용시각을 만들어내지 않는다.

성공한 연결/응답 각각의 p50·p95·p99는 nearest-rank로 계산하고 n, TR, 재사용 여부,
원격주소, 수신량과 timeout/실패/미완료를 따로 보존한다. 실패율 분모는 시도 전체이며,
실패를 0ms로 넣거나 성공만으로 전체 지연을 대표시키지 않는다. 22개 요청의 p99는 희소한
표본 최대값에 가까운 기술 통계이지 SLA 증거가 아니다. 추가 표본 수집은 재승인 대상이다.
디스크 p95/fsync·공간 부족·OOM/kill·VM 재시작·clock jump·중복 lock·budget 복구 실패·
TLS/redirect/secret log 부정 시험에서 잘못된 재인증/재조회가 한 번이라도 있으면 NO-GO다.

알림은 stale heartbeat, HOLD, clock bound, request budget, disk usage, hash-chain 오류,
프로세스 exit/OOM과 VM 재시작으로 제한한다. raw quote/응답 body/계좌/키/승인 원문을 중앙 로그에 넣지 않는다.
알림 전송 자체와 수신자 등록도 별도 승인 후 수행하며 현재 외부 메시지를 보내지 않았다.
