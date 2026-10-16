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

## KM-001 공식 대조 (2026-10-16)

공식 Git commit: `2077773a69a428daf63e148182511f068cc45de3`.
최초 확인: 2026-10-16 19:39:58 KST. 파일 15개의 URL·SHA-256은
[official_sources.json](../../artifacts/km001/official_sources.json)에 있다.
이전 KM-000 표는 당시 상태이며 아래는 이번 구현 상태다.

| 기능 | GET 경로 (`/uapi/domestic-stock/v1/quotations/` 아래) | TR | 공식 샘플 지원/범위 |
|---|---|---|---|
| 일봉 | `inquire-daily-itemchartprice` | `FHKST03010100` | real/demo 동일 TR, 호출당 최대 100행 안내 |
| 당일 분봉 | `inquire-time-itemchartprice` | `FHKST03010200` | real/demo, 호출당 최대 30행, 전일자 미제공 안내 |
| 과거 분봉 | `inquire-time-dailychartprice` | `FHKST03010230` | 실전 최대 120행, 최대 1년 보관 안내. 계좌 실제 범위 UNVERIFIED, PAPER 차단 |
| 현재가 | `inquire-price` | `FHKST01010100` | real/demo 동일 TR |
| 호가/예상체결 | `inquire-asking-price-exp-ccn` | `FHKST01010200` | real/demo 동일 TR |
| 업종 현재지수 | `inquire-index-price` | `FHPUP02100000` | U, KOSPI 0001/KOSDAQ 1001. PAPER 지원 UNVERIFIED이므로 차단 |

각 파일은 `examples_llm/domestic_stock/<underscore_name>/<underscore_name>.py`다.
예: [공식 일봉 샘플](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py).
응답 열은 같은 폴더의 `chk_<name>.py`와 대조했다.

공통 파라미터는 `FID_COND_MRKT_DIV_CODE`, `FID_INPUT_ISCD`다. J/KRX, NX/NXT,
UN/통합을 분리한다. 지수는 U만 사용한다. 일봉은 날짜1/2·기간 D·`FID_ORG_ADJ_PRC`
(1 원주가, 0 수정주가)를 추가한다. 분봉은 시간1·과거 포함 N을 명시한다. 당일은
`FID_ETC_CLS_CODE=""`, 과거는 날짜1·`FID_FAKE_TICK_INCU_YN=N`을 추가한다.
검증된 요청과 생성된 파라미터가 정확히 일치해야 전송된다. 미래 시간 cursor를 차단한다.

응답 필드: 일봉 `stck_bsop_date/stck_oprc/stck_hgpr/stck_lwpr/stck_clpr/acml_vol`,
분봉 `stck_bsop_date/stck_cntg_hour/stck_oprc/stck_hgpr/stck_lwpr/stck_prpr/cntg_vol`,
현재가 `stck_prpr/acml_vol`, 호가 `bidp1/askp1/bidp_rsqn1/askp_rsqn1`, 지수
`bstp_nmix_prpr`를 사용한다. 현재가 누적 거래량을 단일 체결량으로 해석하지 않는다.

일봉은 응답 최저 날짜 전일로 cursor를 이동하는 `daily_pages`를 최대 5페이지 이내에서
지원한다. 응답 수만으로 기간 coverage를 인증하지 않는다. 분봉은 단일 응답 경로만
지원하며 자동 cursor 확장은 UNVERIFIED이다. 지수 샘플은 `tr_cont=M`에 후속 N을 안내하며
요청/응답 continuation은 표현하지만 무제한 자동 페이지 요청은 하지 않는다.

### 시간·봉·세션의 미확인 경계

당일 분봉 샘플은 미래 cursor와 첫 미완성 봉의 거래량에 관한 주의사항을 포함한다.
샘플만으로 봉 라벨이 시작/종료 중 무엇인지 확정하지 않아 `BAR_INTERVAL_UNVERIFIED`로
잠근다. 표시용 1분 구간은 잠정값이며 complete=false다. 실제 완료봉·ORB 검증을 주장하지 않는다.
당일 일봉의 최종성 역시 별도 확인 전 잠근다. 과거 일봉의 날짜를 15:30 공개시각으로
만들지 않고 event_time=None, DATE_ONLY를 유지한다. 역사적 공개 지연을 복원하지 않은
데이터는 수집 이후에만 available하다. 수정주가 계수의 과거 공개 이력이 없으면 잠근다.

실시간 체결 `H0STCNT0`, 호가 `H0STASP0`는 공식
[WS 함수](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_user/domestic_stock/domestic_stock_functions_ws.py)를 대조했다.
필드 배열은 각각 47/63개이며 정확한 개수·TR·레코드 수를 검사한다. 체결의 BSOP_DATE와
HHMMSS를 KST→UTC로 변환한다. 호가는 날짜가 없어 수신일 기준임을 표시하고 원래 시각
문자열을 보존한다. 실제 event_time은 만들지 않으며 품질 잠금을 유지한다.
REST 호가 역시 원천 시각·날짜 확인 없이는 재동기화 승인에 사용할 수 없다.
세션 코드를 임의 확정하지 않고 `SessionInterval`의 명시적 캘린더 근거가 없으면 UNKNOWN이다.
초기 주문 시장 KRX 정규장 계약은 변함없다. NXT/통합을 관측하는 것은 주문 권한이 아니다.

### 인증·통신·유량

REST token은 `/oauth2/tokenP`에 client_credentials/appkey/appsecret, WebSocket 접속키는
`/oauth2/Approval`에 client_credentials/appkey/secretkey POST다. 토큰은 응답의 expires_in과
주입 시계로 관리하며 메모리에만 둔다. 키·토큰·응답 헤더는 저장/출력하지 않는다.
실전/모의 REST endpoint는 기존 표의 정확한 주소만, WS는 공식 환경 샘플의
`ws://ops.koreainvestment.com:21000` / `:31000`만 사용한다. WS 주소는 공식 샘플의
평문 ws 규격을 반영하며 실제 연결 보안·사용 환경의 최종 승인은 별도 미검증이다.

구독/해제는 tr_type 1/0, custtype P, header approval_key와 body.input의 tr_id/tr_key를
사용한다. ACK 전 데이터, 비허용 TR, 암호화된 계좌 통보, 필드 수 불일치를 차단한다.
PINGPONG은 제어 메시지로 처리한다. 연결 실패는 gap을 보존하고 유한 횟수만 재연결한다.
새 세대 ACK와 검증된 fresh quote snapshot이 확보되기 전에는 READY가 될 수 없다.
snapshot_provider를 주입하면 ACK 뒤 자동 재동기화하며, 미주입·미검증 자료는 잠금을 유지한다.
소실 틱은 생성하지 않는다. 보유종목을 우선하는 구독 계획과 명시 슬롯 한도를 사용한다.

[공식 오류코드](https://apiportal.koreainvestment.com/faq-error-code)의 EGW00201을 유량 오류로
분류한다. HTTP timeout/429/5xx 및 해당 오류만 GET 재시도한다(최대 3회, 지수 backoff).
401/403·인증 EGW 오류는 토큰 무효화 후 중단, 미분류 오류도 중단한다. POST는 자동 재시도하지 않는다.
HTTP 본문이 JSON이 아닌 5xx여도 상태를 먼저 분류한다. timeout·응답 크기·총 요청수를 제한한다.
계좌/환경/TR 제한기는 한 프로세스 내 공유가 전제이며 다중 프로세스 조율은 미구현이다.

[일반 유량 공지](https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/d0d1a83f-6f8d-4437-9700-6d26702fd989)는 검색 결과에서
2026-04-20 기준 제목·앱키 단위 안내를 확인했지만 직접 본문 fetch는 timeout이었다.
따라서 이번 감사에서 특정 숫자를 새로 확정하지 않았다. 계좌별 quota, burst, 신규고객 제한,
실제 구독 수는 UNVERIFIED이며 사용자가 선택한 pacing을 보장된 호출량으로 표현하지 않는다.

### OpenDART

[공식 공시검색 가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)는
GET `/api/list.json`, corp_code, stock_code, rcept_no, report_nm, rcept_dt 및
last_reprt_at=N의 정정 포함 정책을 안내한다. `rcept_dt`는 YYYYMMDD 접수일이다.
당일 임의 09:00을 공개시각으로 만들지 않는다. 날짜 경계와 명시적 다음 세션 캘린더 정책으로
보수적 usable_at을 표현하고 acquired_at/first_seen_at을 구분한다. 정정 원문을 보존하며
원접수번호 관계가 없으면 UNRESOLVED다. Registry는 회사·종목·날짜·기존 부모를 대조한다.
이번 단계는 공시 정규화/계보 계약과 Fixture 실행까지이며 실제 DART 다운로드는 미실행이다.
가이드의 페이지 수·개별 키 제한·자료 이용권은 실제 사용자 계정에서 미확인이다.

### 최종 확인 범위

규격 대조와 합성 응답 시험을 완료했으며 실제 KIS/DART 계좌 연결·조회는 하지 않았다.
공식 포털 개별 TR 페이지 직접 대조는 접근 제약이 있어 공식 Git 예제 기준이며,
포털과 예제의 충돌 유무 자체를 완전히 인증하지 않는다. 실제 환경 지원·보관기간·라이선스·
세션 코드·봉 라벨·source clock은 후속 실측 전 UNVERIFIED다.

## KM-002 계좌 읽기 계약 조사 (2026-10-16)

계좌 접근 없이 공식 공개 예제 9개를 다시 확인했다. 고정 원천 커밋은
[`2077773a69a428daf63e148182511f068cc45de3`](https://github.com/koreainvestment/open-trading-api/tree/2077773a69a428daf63e148182511f068cc45de3)이며
함수·chk 필드표·WS 파일 URL 및 byte SHA-256은
`artifacts/km002/official_account_sources.json`에 보존한다. 재확인은 명시 명령
`python scripts/audit_account_api.py`로만 수행한다. 공개 GitHub 조회는 계좌 인증/조회가 아니다.

| 후보 / 공식 함수 링크 | 공식 예제 코드의 LIVE / PAPER TR | 확인 범위·미확인 사항 |
|---|---|---|
| [inquire-balance](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_balance/inquire_balance.py) | TTTC8434R / VTTC8434R | 보유/계좌 요약, 예제 주석 최대 50/20행 |
| [inquire-daily-ccld](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_daily_ccld/inquire_daily_ccld.py) | 최근 3개월 TTTC0081R / VTTC0081R; 이전 코드 CTSC9215R / VTSC9215R | 주석에는 과거 CTSC9115R도 있어 **문서 내부 충돌**, 실제 선택 미확정; 예제 최대 100/15행 |
| [inquire-psbl-rvsecncl](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_psbl_rvsecncl/inquire_psbl_rvsecncl.py) | TTTC0084R / PAPER 미확인 | 정정·취소 가능 주문, 예제 최대 50행; 모의 TR을 추측하지 않음 |
| [inquire-psbl-order](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_llm/domestic_stock/inquire_psbl_order/inquire_psbl_order.py) | TTTC8908R / VTTC8908R | 종목·가격·주문구분별 구매력, 단일 output |
| [ccnl_notice](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_user/domestic_stock/domestic_stock_functions_ws.py) | H0STCNI0 / H0STCNI9 | 암호화 계좌 통보 26필드; 수신일·고유 체결 ID 및 누락 복구는 미검증 |

REST 경로는 모두 `/uapi/domestic-stock/v1/trading/<후보명>`이다(밑줄은 하이픈).
조회도 trading namespace를 사용한다. KM-001 Wire의 닫힌 quotation 허용목록은 그대로이며
이 경로·TR을 transport에 추가하지 않았다. 실전/모의 도메인 존재만으로 계좌 상품·권한·지원이
확인되지는 않는다. 포털 개별 TR의 인증된 상세/실제 응답과 예제 간 일치 여부는 미확인이다.

### 필드·조회 경계

- 잔고: CANO/ACNT_PRDT_CD, AFHR_FLPR_YN, OFL_YN, INQR_DVSN, UNPR_DVSN,
  FUND_STTL_ICLD_YN, FNCG_AMT_AUTO_RDPT_YN, PRCS_DVSN, CTX_AREA_FK100/NK100.
  output1의 pdno/hldg_qty/ord_psbl_qty/pchs_avg_pric/prpr, output2의 dnca_tot_amt,
  prvs_rcdl_excc_amt 등은 의미 확인 후보다. 예수금·가수도 금액을 임의로 결제현금/AP/AR에
  대응시키지 않는다. 0주 행이 남을 수 있다는 예제 주석도 고려해야 한다.
- 일별 주문체결: INQR_STRT_DT/END_DT, SLL_BUY_DVSN_CD, PDNO, CCLD_DVSN,
  INQR_DVSN/INQR_DVSN_1/INQR_DVSN_3, ORD_GNO_BRNO, ODNO, CTX_AREA_FK100/NK100,
  EXCG_ID_DVSN_CD 및 계좌 상품 필드. 최근/이전 3개월을 구분한다. output1의 ord_dt,
  ord_tmd, odno/orgn_odno, ord_qty/tot_ccld_qty/rmn_qty, avg_prvs/tot_ccld_amt는
  누적 주문 상태 후보이며 개별 고유 체결 레코드로 동일시하지 않는다.
- 정정취소가능: INQR_DVSN_1/2, 계좌 상품, CTX 키. odno/orgn_odno, ord_tmd,
  tot_ccld_qty, psbl_qty 등이 있다. psbl_qty는 취소가능량이며 취소 완료 증거가 아니다.
- 매수가능: 계좌 상품, PDNO, ORD_UNPR, ORD_DVSN, CMA_EVLU_AMT_ICLD_YN,
  OVRS_ICLD_YN. ord_psbl_cash, nrcvb_buy_amt/nrcvb_buy_qty, max_buy_amt/max_buy_qty
  구분이 필요하다. 미수 없는 금액/수량과 최대 구매력을 혼동하지 않는다. 실제 재사용·출금
  정책은 계좌별 검증 전 미확정이며 Mock은 별도 보수적 정책을 쓴다.

앞의 세 조회는 예제에서 CTX_AREA_FK100/NK100을 이어받고 응답 tr_cont=M/F이면 다음
요청 tr_cont=N으로 연속조회한다. 모든 페이지의 종결·중복·스냅샷 원자성과 장중 변동,
기간 경계·모의 보관기간은 실제 검증 전 미확인이다. 예제의 행수는 계정 quota나 최종
보장으로 사용하지 않는다. REST 오류는 rt_cd/msg_cd/msg1 및 HTTP/인증 오류와 분리할
예정이며 해당 계좌 TR의 오류 응답/재시도 안전성은 실행 검증하지 않았다.

### 체결통보 정체성과 시각

26필드에는 CUST_ID, ACNT_NO, ODER_NO, OODER_NO, SELN_BYOV_CLS, RCTF_CLS,
ODER_KIND, ODER_COND, STCK_SHRN_ISCD, CNTG_QTY, CNTG_UNPR, STCK_CNTG_HOUR,
RFUS_YN, CNTG_YN, ACPT_YN, BRNC_NO, ODER_QTY 및 추가 계좌/종목/주문 필드가 있다.
예제 설명의 **14번째 CNTG_YN=2가 체결**, 1은 주문·정정·취소·거부 접수 통보다.
ACK/취소 접수를 실제 체결로 분개하지 않는다. 통보는 AES256 key/IV 처리가 필요하지만
이번에는 암호화된 계좌 통보 수신·해독을 구현하거나 접속하지 않았다.

STCK_CNTG_HOUR는 HHMMSS 단위이며 이 필드만으로 유일 체결을 식별할 수 없다.
REST ord_tmd의 실제 정밀도·거래일/수신일 경계와 통보 누락·순서·중복·정정은 미검증이다.
주문번호+초 단위 시간+가격을 고유 execution ID로 임의 합성하지 않는다. Mock의 exec_id는
합성 공급자가 제공한 명시 고유 ID이며 실제 KIS용 ID 확보/증명 정책이 남은 blocker다.

### 구현·미실행 상태

BrokerAccountReader/BrokerOrderReader/BrokerFillReader는 읽기 Protocol이다.
FakeAccountSnapshotProvider/FakeFillNotificationProvider와 전체 snapshot+체결 대사만 구현했다.
expected_mock_snapshot은 장부에서 만든 명시적 합성 기대값이며 독립 브로커 실측 증거가 아니다.
실제 계좌 조회, 실제 KIS 인증, WS 계좌 통보 수신, 실제 주문/취소는 모두 NOT_EXECUTED / 0회다.
TR 충돌, 권한/상품, 실 계좌 페이지 일관성, 고유 체결 ID, 현금/매도가능/결제/비용 매핑과
한도·유량·보안 정책을 확인하기 전에는 실계좌 adapter를 활성화할 수 없다.
