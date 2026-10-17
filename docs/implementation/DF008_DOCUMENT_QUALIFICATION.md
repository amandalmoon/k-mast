# DF008 document qualification

Scope was frozen and pushed at `bd3325f` before retrieval. The user then approved the exact 60 originals and 29 potential corrections, maximum 178 key-bearing requests, document.xml only. No unused request slot authorizes another receipt.

| Stage | Original denominator 60 | Potential correction denominator 29 |
|---|---:|---:|
| Attempted | 60 | 29 |
| Safe ZIP received | 60 | 24 |
| Receipt XML parsed and document verified | 54 | 22 |
| Matching explicit corporate ID | 54 | 22 |
| Direct acquisition primary body and planned fields | 54 | 22 |
| Historical stock-code mapping verified | 0 | 0 |
| Price and session qualified | 0 | 0 |

The first ten met the frozen continuation thresholds: ten ZIPs, seven parsed documents, seven corporate IDs. No sample substitution or threshold change occurred. Eight returned ZIPs contain XML that the strict parser rejects (six originals, two corrections; XML invalid-token error code 4). Five correction responses returned provider status `014`. Those responses remain hashed and stored; they were not retried because they are definitive unavailable-document responses. Missing evidence remains NULL rather than an invented negative fact or a silently repaired XML document.

All 89 attempts completed in 306.791662 seconds between the first start and final completion, including the probe/resume interval. Response time totaled 8.642589 seconds. There were 89 transmissions, no retries, no authentication-issuance calls, and 390,029 response bytes. Minimum observed UTC completion-to-next-start gap was 3.124559 seconds; minimum high-resolution guarded gap was 3.1213329000020167 seconds. There were zero gaps below 3.05 seconds. The independent checker also recomputes same-process performance-clock gaps from actual response completion.

The collector was network-disabled by default, held an OS lock, consumed persistent reservations before I/O, journaled completion, wrote immutable responses and atomic caches, and retained executed source bytes before the first authenticated call. Resume reused the first two cached responses without another request. Crash-unknown attempts remain consumed. Cached hashes and scope are checked before reuse. Auth/quota/spacing or sensitive-response failures halt persistently. Logs contain no key-bearing URL or configuration values.

Public per-receipt states, response and normalized hashes are in `artifacts/df008/document-qualification.json`. Raw bytes, normalized details, event journals, executed sources and diagnostic evidence remain in the Git-ignored DF008 private store. No new price or economic trial was run.
