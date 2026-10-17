# DF-011 fixed five-event price proposal

All five remaining DF009R1 identity-mapped events are retained. None is selected or replaced using PnL. The interval is official event date minus 60 to plus 30 calendar days, with at least 21 observed warmup sessions and two observed followups after the existing D1 deadline. Actual qualification may still HOLD for missing prices/actions/halts/settlement evidence.

| Symbol | Receipt | Market | Historical standard code | Official event date | Requested interval | Cached index rows |
|---|---|---|---|---|---|---:|
|012330|20221208000397|KOSPI|KR7012330007|2022-12-08|2022-10-09 to 2023-01-07|63|
|014130|20221026000391|KOSPI|KR7014130009|2022-10-26|2022-08-27 to 2022-11-25|58|
|352770|20230830001038|KOSDAQ|KR7352770002|2023-08-30|2023-07-01 to 2023-09-29|62|
|352700|20241105000046|KOSDAQ|KR7352700009|2024-11-05|2024-09-06 to 2024-12-05|59|
|041960|20240529000068|KOSDAQ|KR7041960006|2024-05-29|2024-03-30 to 2024-06-28|60|

Stock GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice, TR FHKST03010100, RAW and ADJUSTED separately. Matching indices are 0001 for KOSPI and 1001 for KOSDAQ. Existing slices contain 63/58/62/59/60 rows, respectively. The 014130 requested start precedes the DF005 index cache, so one missing KOSPI slice 2022-08-27..2022-08-31 is proposed via GET /uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice, TR FHKUP03500100, RAW. No missing weekdays are generated.

Expected uncovered pages: 10 stock + 1 index = 11. Expected normal calls with one token: 12. Ceiling: 2 authentications + 2 attempts per planned page = 24 total. Minimum wait after response completion 3.10 seconds. Each frozen 91-calendar-date stock window is below 100 possible sessions; pagination beyond the plan or changed target/interval requires a new budget review. Preserve persistent attempt accounting, high-resolution recheck, safe failed raw responses, exact hashes/lineage, atomic cache and process lock in a future approved implementation.

All five request intervals, price bases and historical identity evidence are explicit in artifacts/df011/next-price-proposal.json. Store any future raw prices only under Git-excluded data/data-first-private-df011-prices/. PAPER read-only only; accounts/orders/cancels/LIVE forbidden. The proposal has execution_authorized=false and no approved collector was added. Its execution guard fails closed, including attempts to recycle the DF010 authorization. No new authentication or price request took place in DF011.
