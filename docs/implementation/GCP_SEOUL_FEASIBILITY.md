# K-MAST 서울 GCP 호스트 타당성 — 2026-10-18 KST

판정: **GCP_HOST_NOT_JUSTIFIED** — 현 단계의 상시 유료 이전은 보류한다.
GCP_CLOCK_VALIDATION_PENDING / GCP_SECURITY_REVIEW_PENDING이다.
현재 VM·인증·시세 호출·비용은 모두 0이며, 실제 개선·월 청구액·시계 오차·지연은 NULL이다.
설계와 조건부 비용 시나리오를 완료했을 뿐 GCP_HOST_DESIGN_READY 또는 배포 승인을 선언하지 않는다.
공급권·보관권과 관측 승인 미확인은 호스트 이전으로 해결되지 않는다.

## 기준선과 보존

git ls-remote 및 새 GitHub ref/run/jobs 응답으로 DF017R1의 실제 원격 SHA
**2421129aae6157eaadac13bc0093348a1b3892f2**와 run 39113102362의 동일 head_sha,
Python 3.11/3.12 success를 확인했다. [R1 CI](https://github.com/amandalmoon/k-mast/actions/runs/39113102362).
기존 DF017 기준 9bff5ddef584cb1ad85b86b45e133d2b6376aee7도 보존한다.
현재 로컬 R2 결과를 삭제하거나 되돌리지 않고 9e63f21cb980df72966367b4bdb26b48c5bbb626에서
codex/gcp-seoul-feasibility를 분리했다. 기존 수집기·전략·보안 게이트와 빈 TRUSTED_REVIEWS,
원본 proposal SHA f1e5a852caebcb383fc947e75136a2ae3f88b87bc91f2d728310e4a301304d0b 및
정확한 22개 조회 계약을 그대로 유지한다. R2 NTP 결과는 GCP의 측정값으로 재사용하지 않는다.

## 비용 감사: USD, on-demand, 세전

[공식 VM 가격](https://cloud.google.com/products/compute/pricing/general-purpose)의
서울 지역 hourly/default 열을 추출했다. 기본 표시 지역이나 Cloud Build 분당 가격을 사용하지 않았다.
E2 shared-core는 e2-small 2 GiB·지속 CPU 약 0.5 vCPU, e2-medium 4 GiB·약 1 vCPU이며
노출된 vCPU 2개를 전용 2코어로 가정하지 않는다. CUD·Spot·자동 할인은 적용하지 않았다.

| 항목 | 검증 단가 / 조건 |
|---|---|
| e2-small / e2-medium | $0.02149143 / $0.04298286 per hour |
| 서울 PD Standard / Balanced | $0.052 / $0.13 per GiB-month |
| 서울 Standard snapshot | $0.064 per retained GiB-month |
| 사용 중 외부 IPv4 / 서울 미사용 예약 IP | $0.005 / $0.015 per hour |
| Public NAT | $0.0014 per assigned VM-hour + $0.045 per GiB 양방향 + IPv4 |
| 서울 Premium 인터넷 송신→한국 | 첫 구간 $0.19/GiB; 인터넷 수신 무료 |
| Secret Manager | 활성 version-location $0.06/월, access $0.03/10,000 |
| Logging / custom Monitoring | $0.50/GiB / $0.2580/MiB의 해당 첫 유료 구간 |

디스크·스냅샷: [공식 지역별 표](https://cloud.google.com/compute/disks-image-pricing).
네트워크: [공식 표](https://cloud.google.com/vpc/network-pricing).
사용 중 IPv4와 NAT 단가는 global 표, 미사용 예약 IP는 Seoul 표를 확인했다.
VM에 계속 붙은 정적 IP는 정지 중에도 사용 중 요금이며, 분리한 예약 IP는 미사용 요금이다.
ephemeral IP는 VM 정지 시 반환되므로 장중 비용을 줄이지만 다음 시작 시 주소 변경을 고려해야 한다.

가정: 730h 평균 월 또는 22일×8h=176h. 후자는 08:00~16:00 KST의 비용 예시일 뿐
KRX 거래일 확정·시세 22일 조회 승인·스케줄 생성이 아니다. 디스크는 VM 정지 중에도 한 달 유지한다.
20/30 GiB Balanced 합계는 각각 $2.60/$3.90, Standard는 $1.04/$1.56이다.
기본안은 boot 10 + data 20 GiB Balanced, 월 retained snapshot 5 GiB($0.32),
인터넷 수신 10/송신 1 GiB, secret 2버전·1지역/1,000접근, 로그 1 GiB,
custom metrics 10 MiB다. snapshots 실제 증가량은 UNKNOWN이며 10 GiB이면 $0.64다.

| 30 GiB Balanced + ephemeral IPv4 | 공유 무료량 여유 시 / 월 | 무료량 소진 시 / 월 |
|---|---:|---:|
| e2-small 24시간 | $23.75 | $26.95 |
| e2-medium 24시간 | $39.44 | $42.64 |
| e2-small 176시간 | $9.07 | $12.28 |
| e2-medium 176시간 | $12.85 | $16.06 |

위 합계에는 VM·PD·IPv4·스냅샷·송수신·Secret Manager·Logging·Monitoring이 포함된다.
20 GiB Balanced 대안은 각 합계에서 $1.30 감소한다. Standard 30 GiB는 Balanced 대비
$2.34 감소하지만 실제 fsync 지연/부팅·업데이트 성능은 측정 전 UNKNOWN이다.

공유 무료량은 Secret Manager 6버전/10,000 access(결제 계정), 로그 50 GiB(프로젝트),
유료 custom metrics 150 MiB(결제 계정) 등의 잔여 여부에 달렸다. 무료량 소진 시 위 가정의
추가액은 $3.203이다. 기본 Google 메트릭은 무료이나 Ops Agent의 모든 지표를 무료로 가정하지 않는다.
IPv4의 결제 계정 공용 소액 무료 1시간은 잔여량을 몰라 두 시나리오 모두 차감하지 않았다.
따라서 적용 가능하면 표보다 최대 $0.005 낮아질 수 있다. 표는 실제 청구액이 아닌 보수적 견적이다.
[Secret Manager](https://cloud.google.com/secret-manager/pricing),
[Observability](https://cloud.google.com/stackdriver/pricing).
2027-09-01 시행 예정 alerting 단가를 2026-10 현재 비용에 적용하지 않았다.
VPC Flow/NAT 로그·Prometheus·synthetic monitor·SMS/외부 알림 서비스는 기본안에서 끄며,
추가 시 별도 비용/승인이 필요하다. 장애 알림은 redacted 지표 정책+이메일을 설계하되 전송하지 않았다.

Private VM+Public NAT 대안은 단일 VM에서도 무료가 아니다. NAT IP는 730h 유지하는 가정으로
24시간안은 위 ephemeral 합계보다 $1.517, 176시간안은 $3.5114 높다(처리량 11 GiB).
즉 medium/30 GiB의 무료량 여유 조건은 약 $40.95 또는 $16.37이다.
NAT은 인바운드 공개 IP를 없애지만 외부 목적지 제한을 대신하지 않는다. 기본안에 NAT 비용을
중복 합산하지 않았고, NAT을 매일 생성/삭제하는 자동화도 제안 실행하지 않는다.
NAT 대안에는 Cloud Router 1개가 추가된다. [Cloud Router 자체는 무료](https://cloud.google.com/network-connectivity/pricing)이며
본 안에 BGP/VPN/Interconnect는 없다. 기본 IAP는 [GCP 자원 접근 무료 기능](https://cloud.google.com/iap/pricing)을
사용하며 유료 Chrome Enterprise 기능은 제외한다. [Basic Support](https://docs.cloud.google.com/support/docs/overview)는
기본 포함 범위로 두고 유료 기술 지원을 구매하지 않는다.

## 크레딧과 미확정 비용

[공식 체험 안내](https://cloud.google.com/free/docs/free-cloud-features)의 신규 적격 고객
$300/90일 크레딧은 유효 잔액이 모든 해당 요금을 덮을 때만 현금 지출이 $0인 조건부 사례다.
이때도 위 사용료가 크레딧을 소모한다. 사용자 적격성·잔액·다른 서비스 소모량은 UNKNOWN이다.
서울 e2-small/medium을 미국 특정 지역 e2-micro 무료 VM으로 계산하지 않는다.
체험 종료 후에는 위 정상 단가로 청구되며, 업그레이드하지 않은 체험 계정 종료는 가동 중단 위험이다.

전체 TCO와 실제 월 청구액은 UNKNOWN이다. 세금, KRW 결제 단가/환율, 운영·패치·복구 노동,
계정 계약 할인, 실제 트래픽/스냅샷 증분·알림 과금이 미확인이다. 이 값들을 0으로 합산하지 않는다.
일회성 복구 예: medium VM 2h + 추가 Balanced 30 GiB 24h + IPv4 2h만 해도 약 $0.2242이고,
다운로드·사람의 작업·장애 손실은 별도다. 기본안은 유료 지원·Ubuntu Pro·HA·LB·Cloud DNS
managed zone·KMS 별도 키·Cloud Scheduler를 구매하지 않는다. 필요 시 재견적한다.

정확한 Decimal 계산과 16개 조합은 artifacts/gcp-seoul/cost-scenarios.json,
단가·원문 SHA/URL은 rates.json 및 sources.json에 있다. 페이지의 지역 JSON을 읽었으며
페이지 스크립트나 Google Cloud SDK를 실행하지 않았다. 공개 페이지 수집은 GCP 인증이 아니다.

## 별도 승인에 제출할 자원 목록

**미승인 검토안**: 서울 asia-northeast3-a의 on-demand e2-medium 1대, standard Ubuntu 24.04 LTS,
boot/data Balanced PD 각 10/20 GiB, ephemeral IPv4 1개, 전용 VPC/subnet/firewall 1세트,
전용 VM 서비스 계정 1개, Secret Manager secret 2개·각 pinned version 1개·서울 단일 보관 위치,
boot 전용 snapshot retained 5 GiB-month 가정, redacted log bucket/metrics/email alert 정책.
기본안에는 NAT·LB·외부 서비스 포트·자동 인증·시장데이터·계좌·주문 서비스가 없다.
수량·열린 목적지 정책·미정 project/수신자 필드는 artifacts/gcp-seoul/RESOURCE_APPROVAL_PROPOSAL.json에
별도로 기재했다. 미정 필드는 임의 계정/주소로 채우지 않았으며 실제 신청 전 재검토해야 한다.
서비스 사용을 위해 필요한 Compute/Secret Manager/Logging/Monitoring/IAP/OS Login API 활성화,
IAM 변경, Google 인증, secret 입력과 비용 발생은 모두 별도 승인 전까지 0회다.

월 계획은 176 VM시간, 수신 10/송신 1 GiB, 위 로그·메트릭 상한을 제안하며 정상 사용료는
약 $12.85~$16.06 + UNKNOWN 비용이다. 예비 운영 예산 $25/월(세전·노동 제외)을 제안하지만
견적이나 승인된 지출 상한으로 취급하지 않는다. Billing Budget 50/80/100% 알림은
하드 과금 차단기가 아니고 지연될 수 있다. 디스크·IP·스냅샷은 VM 정지 후에도 따로 확인한다.
월 계획 외 자원·시간·저장량 증가는 재승인 대상이다. 24시간 medium은 약 $39.44~$42.64이며
현 단계에서 정당화하지 않는다. 승인 요청은 이 보고서를 검토한 뒤 새 작업으로 수행할 수 있다.

## Go/No-Go 이유와 실제 개선 검증

로컬의 수동 전원·미동기화 문제를 관리형 호스트/chrony로 개선할 가능성은 있다.
하지만 단일 VM은 HA가 아니며 E2 공유 CPU·호스트 유지보수·네트워크·OOM·디스크 장애가 남는다.
클라우드 IAM/secret/패치/과금 관리가 추가되고, 원격으로 키를 옮기면 공격면도 늘어난다.
원문을 cloud에 저장할 권리, KIS 계정/접속 IP/호스팅 조건과 기존 승인·경로의 Linux 이식은 미검증이다.
먼저 로컬 시간 복구·공식 데이터 권리·독립 관측 승인을 해결하는 편이 현재 연구 효용에 맞다.

향후 자원 승인 후에는 브로커와 무관한 host-only 시험부터 진행한다: 부팅/재부팅 후
시계 안정화, 부하·디스크 full/프로세스 kill·전원 복구에서 journal 보존/복제 방지,
비밀정보 누출/로그 금지/권한 부정 시험을 수행한다. 그 다음에도 broker 승인은 별도다.
현재 기대 1~5ms나 가동률 개선을 측정값으로 기록하지 않았다.

기존 상태: DF017R1_PREFLIGHT_INCOMPLETE / RVOL_NOT_READY / ECONOMIC_EDGE_UNVERIFIED /
LIVE_NOT_APPROVED / B_ORB_STREAM_TRANSPORT_BLOCKED.

## 실제 검증 증거와 범위

기존 735개 테스트를 보존해 모두 통과했고, 총 35개 로컬 검증 명령이 PASS다.
Ruff/format, strict mypy(96개 source 파일), sdist/wheel, 기존 OMS/Alpha/중앙 포트폴리오
합성 재생, V2/V3 및 DF003~017R2 독립 증거 검사, 16개 비용 조합의 Decimal 재계산을 포함한다.
기존 비공개 파일 22,541개와 원본 명세/수집기/22개 계약을 보존했고 비밀정보 검출은 0건이다.
이는 VM 운영·GCP clock·network·IAM 실측 검증이 아니다. 신규 전략이나 실데이터 수익률 실험은 없다.

공개 증거는 artifacts/gcp-seoul/checks.json 및 preservation-audit.json에 있고 원문은 Git 제외
private audit에 보관한다. 검증된 변경을 정상 commit/push하고 정확한 최종 SHA의 Python 3.11/3.12
원격 CI를 별도로 확인해 전달한다. 이 문서 자체를 배포·비용·인증 승인으로 사용하지 않는다.
