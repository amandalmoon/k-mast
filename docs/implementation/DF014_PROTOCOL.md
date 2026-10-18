# DF014 preregistered PAPER observation pilot

Baseline `d36f4c40706521686ddd486928c20640a61e7208`. The JSON protocol references the byte hash of the unchanged DF013 proposal and freezes 073240/KOSPI and 462860/KOSDAQ, both KRX trade/quote channels, 2026-10-19 08:50–09:25 KST, PAPER only and all existing caps.

This protocol is not execution authorization. Explicit human approval, independently evidenced current security/calendar/service/entitlement and secure transport preflight are separate gates before authentication. The documented ws endpoint is plaintext; no guessed wss alternative or automatic LIVE fallback is allowed. If protection is not established, do not connect. Old daily-price approvals do not authorize this pilot.

The existing 0–2 second source/receipt bound, >5 second inactivity HOLD, one-second quote freshness, two-second post-boundary guard, exact opening observation and UNKNOWN/correction/quote-date controls remain frozen. Actual clock synchronization must be recorded; seconds-only source timestamps do not yield precise network latency. Store actual receipt and validation completion separately, never invent market state or missing prints. RVOL remains not ready; no economic replay or orders.

A single writer/process lock, persistent pre-I/O reservation, segmented immutable FrameArchive, peak total-file cap and bounded receive queue are required. Failure/reconnect never repairs a missing opening window; authentication is not repeated after restart because approval keys are memory-only and the cap is one. Missed windows require a new explicit date and approval. No scheduled execution is created.
