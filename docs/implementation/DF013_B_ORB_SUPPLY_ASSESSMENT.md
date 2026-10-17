# DF013 B ORB supply assessment

**B_ORB_OFFLINE_INFRASTRUCTURE_VERIFIED.** The [official KIS repository](https://github.com/koreainvestment/open-trading-api) was inspected at commit `2077773a69a428daf63e148182511f068cc45de3`, with exact source hashes retained privately and in `supply-assessment.json`. No upstream implementation was executed or redistributed.

The [official domestic-stock sample](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_user/domestic_stock/domestic_stock_functions_ws.py) documents real/demo branches for H0STCNT0 and H0STASP0 with matching IDs and the 47/63-field schemas. The [official auth sample](https://github.com/koreainvestment/open-trading-api/blob/2077773a69a428daf63e148182511f068cc45de3/examples_user/kis_auth.py) identifies PAPER/vps approval via `/oauth2/Approval`, using grant_type/appkey/secretkey. These are documentation facts, not current-key entitlement checks. Actual PAPER access, subscription quota, first available subscription time, message loss, delay, fee and historical book coverage remain unverified/NULL. No claim is made that the often-quoted numerical quota is verified for this account.

The code retains market/time/state fields but does not assume they provide complete exchange halt/VI or correction history. Quotes have no business date or unique exchange sequence. Actual permitted responses are required before any supply-ready claim. PAPER failure must not fall back to REAL/LIVE. Account trade-notice channels H0STCNI0/H0STCNI9 are excluded.

## Concrete conditional pilot proposal

|Item|Frozen proposed bound|
|---|---|
|Targets|KOSPI 073240; KOSDAQ 462860|
|Selection|Minimum SHA256(`DF013:market:code`) among cached same-market names with at least 20 observations and median turnover >=1 billion KRW through 2025-10-16; no future return ranking|
|Selection evidence|Both prior20 windows: 2025-09-12–2025-10-16; medians 1,977,273,332 and 5,551,668,483.5 KRW; seven/six eligible cached candidates|
|Current validity|Not established by one-year-old liquidity; listing, market, halt/tradability must be revalidated before execution; no silent replacement|
|Environment|PAPER only; proposed `ws://ops.koreainvestment.com:31000`|
|Channels/subscriptions|H0STCNT0 + H0STASP0 per symbol, four total|
|Date/time|Desired 2026-10-19 08:50–09:25 KST; conditional on an officially confirmed regular session and actual service availability; otherwise postpone and submit a revised explicit date|
|Authentication|At most one PAPER approval request, including failure; no REST token or LIVE approval requested|
|Connections|At most two attempts total, one reconnect maximum; both failed attempts count|
|Outbound bounds|Eight subscription registrations, four unsubscriptions, at most 2,400 heartbeat/control replies; 2,412 outgoing messages total|
|Storage|1 GiB raw hard cap; 3 GiB total local cap including normalization/journals; stop before overflow; no compression savings assumed|
|Path|Git-excluded `data/data-first-private-df013-pilot/`|
|Cost/usage conditions|Provider-specific cost/entitlement and retention terms not independently measured; no paid service purchase or rights expansion assumed; rates/latency/storage price/operator hours NULL|
|Failure policy|No extra authentication, channel, symbol, time or reconnect expansion; disconnect taints opening range; no invented backfill|

These are **caps**, not throughput forecasts or actual resource measurements. A 35-minute observation is intended to include preparation, opening and a completed 15-minute range plus followup. Public official documents and explicit user authorization must resolve security/calendar/permission/quota before real access; a separately authorized bounded PAPER capability check may be required. There were zero new approval calls, connections and subscriptions in DF013. The proposal is not execution approval, a scheduled job, a ready collector, or approval to use LIVE if PAPER cannot supply data.
