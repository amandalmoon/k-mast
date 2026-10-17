# DF004 데이터 수집 및 시간 정렬

기준선 `daefa1d8f6c6ec34279b1c4b7a401ffedd6c83ad`, 프로토콜 선행 원격 커밋
`52c0838d5837d3b6116c0165806658b911ef2c64`. 프로토콜과 Alpha A candidate-v1, 기존 V2·V3·DF003는 보존한다.

## 실제 접근과 저장 범위

사용자가 별도로 허용한 PAPER 읽기 전용 EWY 조회만 실행했다. 승인 한도는
2025-10-17~2026-10-16, 인증 최대2회, 총12요청, 최소3초 간격이었다.
실제 누적은 **9요청·인증2회·시세7회**, 계좌·주문·취소·LIVE 인증은 모두0회다.
실패한 요청도 예산에서 차감한다. 인증 횟수는 소진되어 추가 인증을 하지 않는다.

`dailyprice`, TR `HHDFS76240000`: AMS/MODP0 3페이지에서 기간 내 **251개** 실제 일봉을 확보했다.
최근 AMS 100행은 MODP0/1 가격 필드가 동일했다. NYS/MODP0·1은 HTTP200이나 가격 행이0개였다.
PAPER에서 조회된다는 실제 응답을 확인했으며 LIVE로 전환하지 않았다.
최초 페이지당100행이며 마지막 일자보다 하루 이전 BYMD로 이동했다.
응답이 승인 시작일 이전 행까지 포함하면 연구 입력에서는 제외한다.

공식 [KIS backtester](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/backtester/kis_backtest/providers/kis/data.py)는
동일 endpoint/TR, MODP1 adjusted 주석과 과거 일자 cursor를 사용한다.
독립적인 자체 구현만 추가했으며 공식 샘플 코드를 import/복제하지 않았다.
MODP0 비수정 해석은 MODP1 설명의 보완적 추론이다. 최근100행의 동일성은 전체 과거 조정 정책의 증명이 아니다.
이 불확실성과 정규장 가격 범위의 공급자 확인 부재를 품질 flag로 유지한다.

비인증 Stooq CSV 경로는 시세 대신 브라우저 검증 HTML을 반환했다. 이를 우회하지 않았다.
현재 발행사 NAV 자료는 기준일과 실제 과거 공표시각을 동시에 입증하지 못해 NAV 경로만 보류했다.

원시 데이터는 `data/data-first-private-df004-ewy/`, 세부 재생은
`data/data-first-private-df004-results/`에만 저장한다. 모두 Git 제외다.
기존 DataStore의 raw_path·digest·immutable_write를 활용하되 숫자 KRX 종목만 허용하는 기존
Provenance/Observation을 완화하지 않았다. 별도 ForeignBar 스키마로 EWY를 보존한다.
캐시를 재사용하고 해시가 다르면 중단한다. 연결 실패는 재시도하지 않으며 예산은 재개 후에도 누적된다.
최종 collector는 단일 실행 잠금과 atomic budget 교체를 사용한다.

**수집 감사 편차:** 최초3페이지는 정제 가격 필드 SHA256만 남아 wire-byte 해시가 아니다.
후속 보완 조회의 원응답1페이지는 private raw store에 저장됐으나 상대경로 기록 오류로 중단됐다.
최초251개 행의 연구 입력은 유지되며 이를 전체 원응답 보존으로 표현하지 않는다.
요청 시작 시각의 최소 간격은2.997382초로 승인3초보다2.618ms 짧았다.
이를 적합하다고 소급 처리하지 않았다. 최종 코드에서는 이전 응답 완료 후3.05초 대기하며,
모의 전송 시험으로 수정 경로를 확인했다. 재인증을 통한 재검사는 하지 않았다.

## 시간 정렬

tzdata2026.5의 America/New_York·Asia/Seoul과 UTC를 고정 사용한다.
공식 [NYSE core hours](https://www.nyse.com/trade/hours-calendars)와
[2025~2027 공휴일·조기종료 달력](https://s2.q4cdn.com/154085107/files/doc_news/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar-2024.pdf)을 참고했다.
정규09:30~16:00, 해당 조기종료13:00을 시간대 변환하며, 확인하지 않은 연도는 거부한다.
지원 기간의 공식 예정 세션 누락은0개다. 예기치 않은 거래소 운영 변경까지 입증한 자료는 아니다.

EWY 실제 세션 종료+60분을 **탐색용 모델 가용 시각**으로만 사용한다.
실제 수신·수집 시각2026-10-17은 변경하지 않으며 역사적 공표시각으로 대체하지 않는다.
과거 공표시각이 입증된 엄격 경로 날짜 수는 **0**이다.
각 실제 미국 세션은 최초 적격 한국08:00 의사결정에 한 번만 대응한다.
한국 휴장 중 여러 미국 세션이 누적되면 가장 최근 완료 세션만 사용한다.
미국 휴장 후 같은 신호를 반복하지 않는다. 국내 거래일은 기존 두 지수의 관측일에 근거하며
공식 KRX PIT 캘린더를 확보한 것으로 주장하지 않는다.

전 평가기간의 현금 원장은 **224일**, 모든 모델의 공통 매매 적격일은 **217일**이다.
제외일: 2025-11-28, 2026-01-02, 2026-01-20, 2026-04-06, 2026-06-22, 2026-07-06, 2026-09-08.
2026-01-02는 일반09:00 가정에서 제외하고 운영비는 현금 원장에 남겼다.
이전 연구의223일 평가는 수정하지 않았다. 미국251개 세션을 한국217개 독립 평가일과 혼동하지 않는다.

유지 flag: CORPORATE_ACTION_HISTORY_UNVERIFIED, HISTORICAL_PUBLICATION_UNVERIFIED, INDEX_HISTORICAL_RELEASE_UNVERIFIED, MODP0_PRICE_BASIS_INFERRED, PROVIDER_SESSION_SCOPE_UNVERIFIED, SESSION_UNVERIFIED.
분봉·09:05 실제 체결·NAV 공표 이력·FX/SOXX 시각 증거·분할/분배금 이력은 미확보다.
없는 가격을 생성하거나 품질 flag를 제거하지 않았다.
