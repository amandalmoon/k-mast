# DF012 price collection

The protocol was pushed before collection at `537814cf034ec25ec3c71a8386aa3ff24da74f9e`. The user subsequently approved its complete PAPER read-only scope. All five target identifiers, receipts and windows remain exactly as frozen in `DF012_PROTOCOL.json`.

Actual consumption was **12 requests: one PAPER authentication and eleven successful quote pages**. There were no failures or retries, against limits of 24 total attempts and two authentications. Ten stock pages contain 610 RAW/ADJUSTED rows; the sole new KOSPI page contains three observations. No accounts, orders, cancellations or LIVE authentication were called. Unused budget is not approval for other requests.

|Code|RAW rows|Adjusted rows|Index window rows|
|---|---:|---:|---:|
|012330|63|63|63|
|014130|61|61|61|
|352770|62|62|62|
|352700|59|59|59|
|041960|60|60|60|

The minimum observed UTC completion-to-next-start gap was 3.108110 seconds. The wire also records and independently verifies monotonic completion gaps, with a 3.10-second rechecking wait. Requests are reserved persistently before I/O; failed attempts remain charged. Process locking, atomic cache writes, immutable safe response bytes, response/record hashes and row lineage support bounded restart. Authentication bodies are hash-only; credentials never enter retained responses.

The index cache supplies 302 of 305 event-window observation slots (99.0164%). These are overlapping window slots, not 302 independent market observations. The missing August 2022 KOSPI window supplies the other three. Cache inputs were rehashed; stock pages were not available before acquisition. Partial or missing sessions are never synthesized.

Raw responses and detailed normalized observations reside only in ignored `data/data-first-private-df012-prices/`; copied index slices are in the separate DF012 cache namespace. Public results contain aggregates and hashes. `cache-audit.json`, `results.json` and the wire journal identify the exact consumed scope and lineage. Previously retained sources remain byte-preserved.
