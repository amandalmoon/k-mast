# DF014 stream collection report

**Actual PAPER authentication: 0. Connection attempts: 0. Subscriptions: 0. Quotation frames: 0.** No market-data pilot has run. `results.json` separates four symbol/channel rows, each with NULL success/first/last/rate/latency metrics and zero observed message/byte counts. Costs and actual coverage remain NULL, not zero-cost/zero-opportunity estimates.

The default-off collector is isolated from strategies, OMS, risk and account/order APIs. It has exact PAPER host, date/time, symbol and channel allowlists. A hash-bound human approval and independent preflight evidence are checked before keys are loaded or network I/O begins. Constructors do not authenticate. There is no account-notice subscription, order path, automatic LIVE fallback or scheduler.

Connection phases are OFF, AUTH_RESERVED, APPROVED, CONNECTING, SUBSCRIBING, STREAMING, GAP and STOPPED. STREAMING means all four requested subscriptions were acknowledged; it does not mean research quality is ready. Unrequested or duplicate acknowledgements fail closed. Acknowledgement availability cannot precede receipt. Source market-state/correction knowledge remains distinct from channel acknowledgement.

Immutable hash-chained reservation files are written before attempts. Authentication <=1, connection attempts <=2, registrations <=8, unregistrations <=4 and all application/protocol control responses <=2,400 are persistent caps. Failed or interrupted attempts remain consumed after restart. Native WebSocket Ping/Pong/Close frames are metered as well as application JSON heartbeats; automatic client keepalive is disabled. Completed send calls are distinguished from reservations, and neither proves wire delivery. Closing the socket ends subscriptions; zero unsubscribe messages is within the cap. A process restart validates data/budgets but cannot acquire another approval key: keys are memory-only and the single authentication allowance is never reset.

A single process lock surrounds the active run. The receive thread timestamps each completed receive immediately with UTC and monotonic nanoseconds and feeds a bounded 256-frame queue. Library buffering is bounded to 16 messages, each <=1 MiB. The receiver starts before registration messages are sent. Queue overflow, storage/integrity defects, exhausted budgets and an elapsed window stop collection; only a bounded transport interruption may consume the second connection. Reconnect never repairs missing opening data. Incoming frames outside the frozen receipt window are not admitted as observations.

Global receive sequence and per-symbol filtered frame ordinal are both retained. The filtered ordinal prevents other subscribed symbols from creating artificial local sequence gaps in the unchanged single-symbol DF013 engine; it is explicitly not an exchange sequence. Parse completion and final validated availability are separately measured after archive/quality work. Unknown source dates, clock synchronization or market/correction states remain blocking flags. Raw frames and detailed receipt/validation records are private.

Approval responses and control messages can carry key material. Only safe categories, constrained provider codes and response hashes are retained; raw key/config/AES/control bodies and exception inputs are not logged. Socket library logging is suppressed. Invalid or unsafe frames are hash-only with a classification; no synthetic repair is attempted.

## Storage engineering evidence — synthetic only

The original FrameArchive is unchanged and reused in bounded 128-frame segments. A separate guard reserves temporary-write headroom before raw/journal writes, enforces the cumulative 1 GiB raw bound and reserves 8 MiB of the 3 GiB total for control bookkeeping. The collector store must be isolated. Final byte deltas use the three actual target files rather than repeatedly scanning a growing segment. Atomic raw/receipt/journal publication, append-only metadata fsync, orphan/partial-line detection and post-run hashes support integrity auditing. Incomplete journals are rejected on restart, not silently truncated.

|Same 2,048 unique synthetic frames|Initial directory scan|Target-file accounting|
|---|---:|---:|
|Elapsed seconds|95.0399|26.3653|
|Frames/second|21.5488|77.6777|
|95th percentile per-frame write seconds|0.07720|0.02683|
|Maximum per-frame write seconds|0.12949|0.08869|
|Final logical file bytes|1,365,534|1,365,534|

Both versions' raw frames, receipts, journals and metadata are independently byte/hash-equivalent; initial evidence is retained. This is local synthetic durable-I/O performance, not actual KIS traffic, a 35-minute soak guarantee or provider capacity. A combined real stream faster than processing can exhaust the queue and HOLD. No acquisition rate is assumed merely because the optimized benchmark is faster.
