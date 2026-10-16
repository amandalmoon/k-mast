# 근거 자료 및 적용 범위

> K-MAST v1.2의 방법론 참고. 원 자료 확인 범위는 v1.1 감사 당시 기준(2026-10-16).

[문서 목록](README.md) · [v1.1 감사 기록](AUDIT_V1_1.md)

## 자료 해석

**주의:** v1.2는 v1.1에서 검토한 방법론 출처를 승계하지만, 외부 연구가 K-MAST 전략의 경제적 수익이나 한국 시장의 최신 브로커 규격을 입증한 것은 아니다. v1.2의 포트폴리오 목적함수·수익 KPI·승격 기준은 사용자와 협의한 설계 선택이다. 실증과 계좌 적용 한도 확인은 별도 단계다.


- **내부 기준:** 사용자가 제공한 v1.0 Markdown 8개와 README 전체 835줄을 읽었다. 이는 설계 감사의 원본이며 실제 성과자료가 아니다.
- **외부 근거:** 아래 원 논문·저자 공개본·학술 출판사·공식 기관 자료의 표시된 범위를 검토했다. 모든 논문의 전체 데이터/코드를 재현했다는 뜻이 아니다.
- **설계 확장:** 목표/증감량 계약, NAV 보존, 게이트, 구독 정책, 한국 계좌 적용은 본 감사의 추론·설계 제안이다.
- **미검증:** 한국 시장의 알파 수익, 실제 계좌 수수료·세금·구매력, 전체 호가자료, 실제 KIS 인증·주문·실행 품질.
- 작업논문과 출판본의 연도·버전은 구분한다. 원문을 묶음에 재배포하지 않으며 근거 링크만 제공한다.

## R01

**Gârleanu, N. & Pedersen, L. H. (2013). Dynamic Trading with Predictable Returns and Transaction Costs.**  
The Journal of Finance, 68(6). 저자 공개 원문.

- 원문/기관: <https://people.stern.nyu.edu/lpederse/papers/DynamicTrading.pdf>
- 확인 범위: 검색으로 제공된 원문 초록·모형 설명 확인.
- 이 문서에서 사용하는 근거: 거래비용과 예측 신호의 감쇠속도를 함께 고려하는 동적 배분의 원리.
- 적용 한계: 다른 자산·효용·비용 모형의 결과다. KIS 단타의 최적 집행 속도나 수익률을 직접 입증하지 않는다.

## R02

**DeMiguel, V., Garlappi, L. & Uppal, R. (2009). Optimal versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy?**  
The Review of Financial Studies. JSTOR 학술 원문.

- 원문/기관: <https://www.jstor.org/stable/pdf/30226017.pdf>
- 확인 범위: 원문 초록·연구 목적·결과 설명 확인.
- 이 문서에서 사용하는 근거: 표본 외 포트폴리오 최적화에서 추정오차가 분산 효과를 상쇄할 수 있어 단순 배분 기준선이 필요하다는 근거.
- 적용 한계: 1/N이 모든 시장·목적에서 최적이라는 뜻은 아니다. 국내 네 알파 조합의 성과는 별도 검증한다.

## R03

**Ledoit, O. & Wolf, M. (2004). Honey, I Shrunk the Sample Covariance Matrix.**  
The Journal of Portfolio Management. 저자 공개 원문.

- 원문/기관: <https://www.ledoit.net/Honey_2004.pdf>
- 확인 범위: 원문 서론·방법론 설명 확인.
- 이 문서에서 사용하는 근거: 표본 공분산 추정오차 및 수축 추정의 필요성.
- 적용 한계: 수축은 구조변화·꼬리의존성을 자동 해결하지 않으며 실제 계좌 위험 상한을 보장하지 않는다.

## R04

**Bailey, D. H. & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality.**  
The Journal of Portfolio Management 게재 연구의 저자 공개본.

- 원문/기관: <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>
- 확인 범위: 원문 초록·DSR 입력/가정 설명 확인.
- 이 문서에서 사용하는 근거: 다중 시도·선택편향·비정규성과 Sharpe 해석.
- 적용 한계: DSR은 미래정보 누출·부정확한 체결·모델 소멸을 보정하지 않는다. 독립 시도 수와 표본 가정도 필요하다.

## R05

**Lo, A. W. (2002). The Statistics of Sharpe Ratios.**  
Financial Analysts Journal. JSTOR 학술 원문.

- 원문/기관: <https://www.jstor.org/stable/pdf/4480405.pdf>
- 확인 범위: 원문 초록·시간 집계 설명 확인.
- 이 문서에서 사용하는 근거: 자기상관과 추정오차가 Sharpe 측정·연환산에 미치는 영향.
- 적용 한계: 특정 펀드의 수치 사례를 K-MAST의 오차 크기로 이전하지 않는다.

## R06

**Harvey, C. R., Liu, Y. & Zhu, H. (2016). … and the Cross-Section of Expected Returns.**  
The Review of Financial Studies 게재 연구. 연결은 NBER Working Paper 20592(2014).

- 원문/기관: <https://www.nber.org/papers/w20592>
- 확인 범위: NBER 공개 초록·작업논문 본문 발췌 확인.
- 이 문서에서 사용하는 근거: 금융 연구에서 많은 요인·모형을 탐색한 뒤 일반 유의성 기준을 쓰는 문제.
- 적용 한계: 논문의 특정 t값을 모든 K-MAST 전략의 일률적 승인 기준으로 옮기지 않는다. 작업논문 버전과 출판본을 구분한다.

## R07

**Nagel, S. (2012). Evaporating Liquidity.**  
The Review of Financial Studies, 25(7). DOI 10.1093/rfs/hhs066.

- 원문/기관: <https://www.jstor.org/stable/pdf/23263557.pdf>
- 확인 범위: 원문 초록·유동성 공급 설명 확인.
- 이 문서에서 사용하는 근거: 단기 반전 수익을 유동성 공급의 보상으로 해석하고 시장 스트레스에 따라 기대보상이 달라질 수 있음을 분석.
- 적용 한계: 미국 주식 연구가 한국 장중 VWAP 롱온리의 실행 가능한 수익을 입증하지 않는다. 스트레스의 높은 기대보상과 청산 위험은 함께 검토한다.

## R08

**Daniel, K. & Moskowitz, T. J. (2016). Momentum Crashes.**  
Journal of Financial Economics, 122(2), 221–247. 연결은 NBER Working Paper 20439(2014).

- 원문/기관: <https://www.nber.org/papers/w20439>
- 확인 범위: NBER 초록·출판 정보 확인.
- 이 문서에서 사용하는 근거: 모멘텀의 불리한 조건부 손익·급반등 국면을 별도 시험할 필요성.
- 적용 한계: 롱숏 모멘텀의 메커니즘과 국내 롱온리 A/B는 같지 않다. 특정 붕괴율을 가져오지 않는다.

## R09

**Almgren, R. & Chriss, N. (2001). Optimal Execution of Portfolio Transactions.**  
Journal of Risk. DOI 10.21314/JOR.2001.041.

- 원문/기관: <https://www.risk.net/journal-risk/2161150/optimal-execution-portfolio-transactions?overridden_route_name=entity.node.canonical>
- 확인 범위: 출판사 초록·서지 확인.
- 이 문서에서 사용하는 근거: 집행 속도·변동위험·일시/영구 시장충격의 절충.
- 적용 한계: 선형 비용 등의 연구 가정을 KIS 소액 주문에 그대로 적용하지 않는다. 용량·충격 계수는 실측 또는 보수적 범위가 필요하다.

## R10

**Perold, A. F. (1988). The Implementation Shortfall: Paper vs. Reality.**  
The Journal of Portfolio Management, 14(3), 4–9.

- 원문/기관: <https://www.pm-research.com/content/iijpormgmt/14/3/4>
- 확인 범위: 출판사 원문 검색본문·Harvard 서지 확인.
- 이 문서에서 사용하는 근거: 이상적 포트폴리오와 실제 실행 사이의 비용 및 미체결 기회차이 측정.
- 적용 한계: 실제 회계 비용과 반사실 기회비용은 다르다. 본 명세의 간단한 IS 식은 기호·평가시점을 명시한 적용 예다.

## R11

**Hansen, P. R. (2005). A Test for Superior Predictive Ability.**  
Journal of Business & Economic Statistics. JSTOR 학술 원문.

- 원문/기관: <https://www.jstor.org/stable/pdf/27638834.pdf>
- 확인 범위: 원문 초록·bootstrap 구현 설명 확인.
- 이 문서에서 사용하는 근거: 여러 대안과 기준선의 예측/손실 차이를 비교하는 SPA 및 의존성을 고려한 재표본화.
- 적용 한계: 검정의 정상성·표본·후보군 조건을 검토해야 한다. SPA PASS가 데이터 오류나 거래 불가능성을 해결하지 않는다.

## R12

**Fama, E. F. & French, K. R. (2015). A Five-Factor Asset Pricing Model.**  
Journal of Financial Economics, 116, 1–22.

- 원문/기관: <https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002323>
- 확인 범위: 출판사 서지와 대학 공개 게재본의 검색본문에서 초록·요인 정의를 확인. 출판사 직접 본문 요청은 접근 제한(403)이 있었음.
- 공개 게재본: <https://breesefine7110.tulane.edu/wp-content/uploads/sites/16/2019/09/Fama-French-5-factor-model-JFE.pdf>
- 이 문서에서 사용하는 근거: 시장 외에도 규모·가치·수익성·투자 등의 노출을 고려하는 성과 귀속의 배경.
- 적용 한계: 이 논문은 K-MAST의 한국 팩터 데이터가 아니다. 실제 사용 팩터의 정의·PIT·통화·시장 일치는 별도 검증한다.

## R13

**한국거래소. General Procedures of Trading / Settlement / Trading Hours.**  
공식 KRX 거래·결제 안내.

- 원문/기관: <https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp>
- 확인 범위: 공식 웹 검색본문 확인.
- 이 문서에서 사용하는 근거: 주식 T+2 결제, 정규장 및 시간외 구분.
- 적용 한계: 당일 매도대금 재사용·출금·주문가능금액은 사용자 브로커 계좌 조건을 따로 확인해야 한다. 실제 사용자 계좌는 조회하지 않았다.

## R14

**한국투자증권. API 호출 유량 안내(REST, 웹소켓), 본문 표기 2026.04.20 기준.**  
공식 KIS 공지.

- 원문/기관: <https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/d0d1a83f-6f8d-4437-9700-6d26702fd989>
- 확인 범위: 공식 검색본문 확인; 직접 HTML 본문 가시성 제한 기록.
- 이 문서에서 사용하는 근거: 일반 실전18/초·모의1/초·WebSocket 합산41건 및 계좌 단위 안내.
- 적용 한계: 동적 페이지 직접 추출은 내용이 비었으나 같은 공식 페이지의 검색본문에서 수치를 확인했다. 계좌 특례·실제 적용 한도는 미확인이다.

## R15

**한국투자증권. Open API 신규 고객 초당 호출 제한 안내.**  
공식 KIS 공지. 본문 시행 표기 2026.04.03 17:00.

- 원문/기관: <https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/c1113824-17c7-47a7-b7b8-8880506a847c>
- 확인 범위: 공식 검색본문 확인; 직접 HTML 본문 가시성 제한 기록.
- 이 문서에서 사용하는 근거: 신규 신청 시 3일 동안 3건/초 제한, 모의계좌 제외 안내.
- 적용 한계: 사용자의 신규/갱신 상태·정확한 계좌 적용은 미확인이다.

## R16

**금융감독원 OpenDART. 공시검색 개발가이드.**  
공식 API 문서.

- 원문/기관: <https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001>
- 확인 범위: 공식 문서 열람 및 필드 확인.
- 이 문서에서 사용하는 근거: 공시 검색·정정 구분·rcept_dt의 날짜 의미 확인.
- 적용 한계: 검색 응답만으로 모든 공시의 장중 최초 공개시각과 시장의 기대치를 확보했다고 볼 수 없다.

## R17

**한국투자증권. 개발자센터 공지 목록.**  
공식 KIS 소개 페이지.

- 원문/기관: <https://apiportal.koreainvestment.com/intro>
- 확인 범위: 공식 페이지 공지 목록 확인.
- 이 문서에서 사용하는 근거: 2026.09.09 KRX 애프터마켓·NXT 제도변경 공지의 존재 확인.
- 적용 한계: 목록 제목만으로 상세 시행일·주문코드·VI 규격을 모두 검증했다고 하지 않는다. 초기 자동주문 범위는 KRX 정규장으로 유지한다.

## R18

**한국투자증권. API 문서 개요.**  
공식 KIS API 기본 규격.

- 원문/기관: <https://apiportal.koreainvestment.com/apiservice>
- 확인 범위: 공식 문서 검색본문 확인.
- 이 문서에서 사용하는 근거: 실전/모의 분리, 인증·시세·주문/조회 구분과 공식 문서 구조.
- 적용 한계: 모든 개별 TR·키·사용자 계좌 기능을 실행 검증한 것은 아니다. 이번 작업은 실제 API 인증/주문을 수행하지 않았다.

## R19

**Markowitz, H. (1952). Portfolio Selection.** *The Journal of Finance*, 7(1), 77–91.

- 원문/출판사: <https://doi.org/10.1111/j.1540-6261.1952.tb01525.x> · JSTOR <https://www.jstor.org/stable/2975974>
- 확인 범위: 학술 출판사·JSTOR의 출판정보 및 평균-분산 모델의 원전 식별. 원 논문 전체를 재현한 것은 아님.
- 이 문서에서 사용하는 근거: 기대수익과 포트폴리오 위험을 함께 고려하는 현대 포트폴리오 이론의 출발점.
- 적용 한계: 예상수익/공분산이 추정 가능하고 정확하다는 보장, 실전 순수익 보장이 아님.

## R20

**Rockafellar, R. T. & Uryasev, S. (2000). Optimization of Conditional Value-at-Risk.** *The Journal of Risk*, 2(3), 21–41.

- 원문/출판사: <https://doi.org/10.21314/JOR.2000.038>
- 확인 범위: 출판 서지·논문 제목 및 CVaR 최적화의 학술적 제안 여부. 특정 구현·수치 결과를 검증했다고 주장하지 않음.
- 이 문서에서 사용하는 근거: 손실 분포의 꼬리위험을 목적함수/제약으로 명시할 수 있다는 방법론.
- 적용 한계: 과거 표본이 충분하지 않거나 시장 구조가 변하면 CVaR 추정이 틀릴 수 있으며 청산 불능·실제 최대손실을 보장하지 않음.

## 감사 대상 v1.0의 계보

`BASELINE_MANIFEST.json`에는 실제로 읽은 원본 파일의 이름·바이트·줄수·SHA-256이 있다. 원본을 수정하지 않고 새 v1.1 디렉터리에 개정본을 작성했다.

과거 PDF·카카오톡은 v1.0의 배경 자료다. 이번 감사는 새로 제공된 Markdown 설계의 경제·퀀트 명세에 집중했으며, 토론 참여자의 개인 매매수익을 검증하지 않았다.

## 정보 갱신 규칙

공식 웹자료의 확인일과 정책 시행일은 다르다. LIVE 준비 시 해당 계좌에 적용되는 시행 중 원문·계약·승인값을 다시 확보한다. 검색본문 확인은 실제 계좌 실측을 대체하지 않는다.
