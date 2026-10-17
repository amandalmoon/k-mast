# DF-010 KIS price collection

Protocol preregistration: remote commit f2c6691, before new outcome inspection. The human subsequently explicitly approved the three stock windows, PAPER only, at most two authentications and twenty total attempts, at least 3.10 seconds after each response. Indices were excluded from new collection and reused from verified DF005 caches.

Actual: 7 requests = 1 PAPER token request + 6 successful stock pages; no retries, new indices, LIVE authentication, accounts, orders or cancels. Minimum observed response-to-request gap 3.103604 seconds. Each frozen window returned RAW and ADJUSTED: 131290 62+62 rows (2022-10-27 to 2023-01-25); 081660 60+60 (2025-01-13 to 2025-04-11); 002840 61+61 (2025-02-10 to 2025-05-09). Weekend endpoints do not imply missing synthetic rows. Matching cached index slices contain 62, 60 and 61 observations.

827 existing normalized-store manifests were inventoried. No matching target stock history was present in the DF005 panel; other legacy stores cover later dates. Source cache hashes, independent basis identities and copied index hashes are in artifacts/df010/cache-audit.json. Rows are not interpolated. Historical KRX basic-information snapshot dates are never substituted for market sessions.

Private source: data/data-first-private-df010-prices/. Exact safe response bytes are immutable, SHA-256 linked to normalized records and per-page record hashes. Auth response bodies are never stored. The persistent journal reserves failures and authentication before network I/O; per-query attempts are capped at two, global attempts twenty, authentication two. OS locking prevents duplicate active collection; restart retains consumed budget. Timing uses perf_counter with a rechecking loop and persisted wall time. Strict path/TR/symbol/date validation rejects accounts and trading. Sources executed for collection and explicit approval metadata are retained privately.

The collector supports safe cache resume; no failure retry was needed in this run. Provider fields indicate action candidates, not complete action or halt histories. Those limitations are qualification gates below, not erased flags.
