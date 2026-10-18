# DF-017R1: unauthenticated preflight

Status: **DF017R1_PREFLIGHT_INCOMPLETE**. No execution authorization exists for
this pilot. This report is an evidence ledger, not a canonical approval record.
The original collector, gate and empty TRUSTED_REVIEWS remain unchanged.

## Frozen scope

Baseline: 9bff5ddef584cb1ad85b86b45e133d2b6376aee7.
Proposal: artifacts/df016/PILOT_PROPOSAL.json, SHA-256
f1e5a852caebcb383fc947e75136a2ae3f88b87bc91f2d728310e4a301304d0b.
Its 22 ordered requests remain byte-identical.

The proposed window remains 2026-10-20 08:55–09:22 KST (end exclusive),
073240 and 462860, PAPER/KRX J. APIs: FHKST03010200,
FHPST01060000, FHKST01010200. Authentication at most once; 22 logical quotes;
45 total attempts including failures/retries, at most two attempts per quote;
at least 3.10 seconds after response completion. Raw cap 128 MiB, total cap
256 MiB; private retention at most 30 days. No accounts, orders, cancellations,
LIVE, WebSocket or approval-key issuance. A scope description is not approval.

## Evidence assessment as of 2026-10-18

| Required fact | Finding | Limitation / next evidence |
|---|---|---|
| Account-specific PAPER entitlement | UNKNOWN | Public endpoint documentation and possession of keys do not establish this account's active permissions. Obtain a dated provider service approval or official account-specific response, with identifiers redacted. |
| Applicable rate and minimum interval | UNKNOWN | Official notice index advertises rate notices, but an index/search snippet does not establish applicable customer tier or current body text. 3.10s is the frozen local floor, not a certified provider limit. |
| 30-day raw retention and research rights | UNKNOWN | General strategy-development guidance does not expressly establish the required storage/research rights. |
| Derived/hash retention | UNKNOWN | Neither a local hash nor this report establishes provider permission. Obtain an explicit applicable official provision or response. |
| Oct 20 trading day and special opening | UNKNOWN | General regular-session rules and Tuesday weekday arithmetic cannot certify a dated special-opening/closure decision. Recheck official dated KRX notices before the window. |
| Oct 20 status of both securities | UNKNOWN | Current/history disclosures cannot certify future suspension, resumption, VI or market phase. Need dated official security notices and contemporaneous qualified market-state observations; lack of search hits is not clearance. |
| PC clock synchronization/error bound | NOT SYNCHRONIZED / error UNKNOWN | w32tm status exited 0 but explicitly reported leap indicator 3 (unsynchronized), stratum 0, no last successful sync and Local CMOS Clock. Configuration query returned access denied (2147942405). No independently measured <=0.5s bound exists. No resync, service changes or remote time probes were performed. |
| Actual HTTPS peer/TLS policy | UNKNOWN | Public PAPER domain matches the frozen HTTPS host/port. Code requires trusted CA/hostname and TLS>=1.2, disallows overrides and redirects. No actual broker TLS handshake or runtime peer certificate was observed. |

Official public sources checked:

- [KIS usage guide](https://apiportal.koreainvestment.com/about-howto)
- [KIS official notices](https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/)
- [KRX equity market guide](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp)
- [KRX KIND](https://kind.krx.co.kr/)
- KIS public API specification metadata for the three exact routes, linked in
  the source manifest. These documentation requests contain no keys and are
  not broker market-data or authentication requests.

Retrieval failures, dynamic shells, and generic pages do not prove an absence
of restrictions. Private source bytes, retrieval times, hashes and local clock
command outputs are retained under data/data-first-private-df017r1-audit/;
public manifests contain provenance only. Hashes show byte identity only.
Existing DF016 source evidence documents PAPER routes; it does not prove live
availability or active account permissions.

## Approval and independent review

The current user instruction explicitly withholds API execution approval.
Earlier domestic daily-price, overseas, and disclosure approvals do not cover
this new intraday pilot. No human statement is fabricated or canonicalized.
No approval pair is registered; no execution or retention task is scheduled.
No credentials were loaded to execute broker requests.

After the missing official evidence is supplied, a human must approve the
exact scope above and its proposal hash. A separate independent review must
check provenance, freshness, applicability and the original statement, then
review any canonical approval/preflight hash registration as its own change.
Offline consistency tests in this change are not that independent approval.
Registration alone must not execute collection. Manual collection still needs
all original runtime gates and the original window. At or after 09:22 KST on
Oct 20, use DF017R1_MISSED_COLLECTION_WINDOW; never substitute a date silently.

Status transitions are conditional, not outcomes of this report:
PREFLIGHT_INCOMPLETE while mandatory evidence is missing; PENDING_HUMAN_APPROVAL
only after preflight is complete; APPROVED_NOT_EXECUTED only after exact approval
and independent registration; ACTUAL_SUPPLY_OBSERVED only with real responses;
PARTIAL_DATA_QUALIFICATION only with inspected data, separately from economics.

## What can be concluded

Actual KIS PAPER HTTPS supply is unverified. There are no new broker responses,
bar ranges, measured response latencies, quote snapshots or observed signal
availability times. These quantities remain NULL. The documented 30-row current
day bar limit does not verify bar-label start/end semantics. Requeries can reveal
changes but cannot certify correction finality. Separate exchange opening,
bar end, request, response and validation times remain necessary. A subsequent
quote snapshot is not a fill. ORB5/ORB15 stay HOLD until semantics, market state
and causal availability are qualified. Twenty eligible prior sessions are still
needed for RVOL. No economic or execution claim follows from this preflight.

RVOL_NOT_READY; ECONOMIC_EDGE_UNVERIFIED; LIVE_NOT_APPROVED;
B_ORB_STREAM_TRANSPORT_BLOCKED.

## Validation and closure

All 32 local verification commands passed, including 735 existing tests,
Ruff/format, strict mypy (96 source files), sdist/wheel, OMS/Alpha/joint synthetic
replays, V2/V3 and DF003–017 independent evidence checks. Existing tests,
collector and gate were not modified. No new trading/runtime feature was added.
The preflight checker is an offline consistency check and grants no authority.
The preservation/secret audit found 22,350 preexisting
private files unchanged and zero credential matches. No API execution occurred.
Initial lint diagnostics caused by temporary research helpers were retained
privately; helpers were moved into the ignored audit store and lint rerun passed.
See artifacts/df017r1/checks.json and preservation-audit.json for actual evidence.
Exact final-SHA Python 3.11/3.12 CI is checked after push and linked in the delivery
message; local success alone does not establish remote CI success.
