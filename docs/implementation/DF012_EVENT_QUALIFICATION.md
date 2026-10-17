# DF012 event qualification

Result: **DF012_PARTIAL_EVENT_QUALIFICATION**. Four of the five fixed cases pass bounded technical qualification; full research eligibility remains **zero**.

|Code|Receipt|Modeled entry|Technical result|
|---|---|---|---|
|012330|20221208000397|2022-12-09|Qualified|
|014130|20221026000391|2022-10-27|Qualified|
|352770|20230830001038|None executed|HOLD: nonconstant adjustment factor without action lineage|
|352700|20241105000046|2024-11-06|Qualified|
|041960|20240529000068|2024-05-30|Qualified|

Historical short/standard codes, DART identity, then-market, listing identity and relevant safe correction links reuse the hashed DF009R1 evidence. Qualification uses the unchanged DF006 window function: at least 21 actual observed warmup sessions, matched stock/index sessions, OHLCV and RAW/ADJUSTED checks, frozen holding/followup bounds and special-session exclusions. Duplicate dates and conflicting revisions fail validation. Current downloads do not establish complete historical correction lineage or complete halt/listing lifecycle histories; these fields remain NULL.

Publication evidence supplies receipt dates rather than actual seconds. Entry therefore uses the conservative subsequent eligible observed session, with the existing modeled open-plus-one-second boundary. That is an execution assumption, not an invented publication timestamp or guaranteed executable open. Later corrections are not moved into earlier decisions.

352770 has a RAW/ADJUSTED flag on **2023-08-10**, inside warmup: `flng_cls_code=01`, `prtt_rate=-33.02`, `mod_yn=N`. The same-endpoint official KIS property evidence retained in DF011 defines 01 as rights detachment. The [July 2023 prospectus](https://kind.krx.co.kr/external/2023/07/27/000413/20230727000892/10001.htm) identifies a 0.5 bonus-share plan with an August 11 record date. The [August issuance result](https://kind.krx.co.kr/external/2023/08/10/000314/20230810000750/10800.htm) provides additional paid-issue timing. The complete share/rights/factor reconciliation remains unresolved. No synthetic shares, prices or cash are added, and no PnL replay is run for this held case.

Its original cached DART document also describes the acquisition method as **무상수증**, a noncash receipt. This is retained as a separate interpretation warning: it is not evidence of a cash market buyback. It does **not** introduce a new post-result D1 filter. The frozen D1 event rule is unchanged; the formal replay HOLD comes from the existing action/factor gate. The case stays in the five-case denominator and is not replaced.

Flat adjustment ratios for the other four do not prove absence of all corporate actions or halts. They meet only the frozen bounded gate. Full PIT universes, complete action and halt histories, historical price-vintage lineage and valid non-event controls remain unavailable.

012330 also has provider code 02 on 2022-12-28 in the longer requested history, after the frozen replay ends on December 16 with zero shares. Official same-endpoint KIS metadata identifies 02 as dividend detachment. The issuer's [2023 annual report](https://kind.krx.co.kr/external/2024/03/12/001046/20240312002768/11011.htm) retrospectively confirms the FY2022 common final dividend of 3,000 KRW, resolved at the March 22, 2023 AGM. `outside-replay-action-review.json` preserves source hashes and the limited scope: later decisions are not entry information, no entitlement is added, and actual net payment/timing remain unresolved. This outside-window action does not change the preselected replay interval.

DF011's 131290 HOLD and entitlement sidecars are unchanged: gross rights 30,500/30,500/15,000 KRW for BASE/STRESS/PARTIAL are not actual net cash receipts. No rights are added to legacy or DF012 trading PnL. Official action bytes and hashes are retained privately, with a public `corporate-action-review.json`.
