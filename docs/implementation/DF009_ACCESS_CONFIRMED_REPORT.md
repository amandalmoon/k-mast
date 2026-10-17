# DF009 approval-confirmed continuation

This supplements, rather than rewrites, the access-pending report at `1df749114f4bc69b6b9bb37a3643cd1bde5c427e`. The user subsequently supplied a KRX screenshot showing both basics services approved for 2026-10-17 through 2027-10-16. Collection resumed under the original frozen 12-event, 46-query, 92-attempt scope. No target, market, date or price endpoint was added.

The original 401 response, budget, source versions and report remain unchanged. A separate continuation namespace imports that request as consumed event 1. The first query therefore had exactly one remaining attempt. A successful retry became event 2, followed by the other 45 unique queries: cumulative 47 requests, comprising one 401 and 46 HTTP 200 responses. No failure was refunded. A later authentication, hash or clock failure cannot reuse the one-time access-confirmation waiver. The new store holds the original process lock as well as its own lock during acquisition.

The completed acquisition returned 46 market/date snapshots spanning 23 selected dates, from 2022-10-25 through 2025-04-10. It yielded 60,886 observed rows and 2,886 distinct standard security codes. These are dated snapshots, not a continuous PIT market panel and not 2,886 independent strategy experiments. Resume elapsed time was 278.622475 seconds, including offline schema review and cached replay. The minimum observed response-completion-to-next-start UTC gap was 3.140361 seconds, with no gap below 3.05 seconds; the independent checker also audits same-run performance-clock gaps.

Actual responses exposed two schema assumptions that were too restrictive: valid six-character short codes can include letters, and a KRX-listed security can have a non-KR ISIN prefix. The original parser and its failed normalization attempts remain preserved. A separately versioned parser retains those securities without numeric coercion, dropping rows or inventing a Korean code. Cache reprocessing used zero additional calls. Executed source versions are content-addressed and immutable. Public results exclude the full raw and normalized security tables, which remain private.

## Identity result

All twelve original DART corporate IDs were reconfirmed. Eight events from eight distinct corporations now have a corroborated point-in-time security link and then-listed market. Four remain unresolved: two lack DART stock-code candidates, and two candidate codes are absent from the two approved markets at the event date. Absence is not proof of delisting; KONEX and unlisted status are not reconstructed by guesswork.

The eight links combine the original document's explicit corporate ID/legal name, the official DART code candidate, exact official filing-date KRX security presence, standard/short-code separation, listing chronology, ordinary-share type, uniqueness across both markets, and agreement of the preceding-date snapshot. It is not a company-name-only match or a current-master backfill. Exact outer Korean corporate-form markers and documented common-share name suffixes are treated as structural variants; originals remain intact. This normalization was reviewed after inspecting actual payloads and is disclosed as such, not represented as a fully preregistered string algorithm or confirmatory economic evidence. Current DART company-name metadata does not overwrite contemporaneous original-document names.

One receipt-number prefix differs from the official `rcept_dt`. The frozen target date agrees with `rcept_dt`; that explicit filing date governs the join. No publication hour or artificial trading session was created from either date. Full delisting/halt history and corporate-action/rename/merger/transfer history remain separate pending fields: agreeing adjacent snapshots does not prove a complete lifetime history. No historical price, PnL or new strategy result was calculated.

Within the existing complete B001 census through 2025-10-08, all eight linked events have a safe bounded correction check for original through event+30 calendar days: either no same-corporation D1 revision exists, or the original document's explicitly labeled initial-submission date already resolves the revision to a different original. This is scoped census evidence, not a claim that corrections after the coverage endpoint cannot exist. Later revision contents are never backfilled into an original signal. Eleven of the twelve total targets meet this bounded correction check; only eight also meet identity requirements.

## Next data proposal

The five-event/three-company entry minimum is met for preparing a price-collection proposal. The three companies are selected by the original frozen hash rank, without prices or PnL:

| Historical symbol | Original receipt | Proposed daily-data interval |
|---|---|---|
| 131290 | 20221226000280 | 2022-10-27 through 2023-01-25 |
| 081660 | 20250314001638 | 2025-01-13 through 2025-04-13 |
| 002840 | 20250409002291 | 2025-02-08 through 2025-05-09 |

`artifacts/df009r1/next-price-proposal.json` specifies RAW/adjusted daily and matching index inputs, the existing official read-only paths, approximately six stock and three index pages, proposed authentication ceiling two, retry-inclusive ceiling twenty, and at least 3.10 seconds after completion. This is a proposal only and requires new price-scope approval; no KIS/LIVE authentication or price call was made. Actual session availability, 21 warmup sessions, corporate actions, halts and original D1 execution rules must pass separate gates before replay. Price/session-qualified events remain zero.

The pilot used 5.875 cumulative shared snapshot requests per corroborated event, not a scalable marginal cost estimate for the entire 620-title universe. No full-universe success rate or independent economic experiment count is inferred. D1 identity recovery remains viable; a forced switch to B ORB on the previous generic 401 is unwarranted. The previous ORB supply plan remains a contingency and was not executed.

## Validation and safety

New evidence lives in `artifacts/df009r1` and private continuation stores. The older DF009 results and all preceding strategy/accounting evidence are preserved. The verification suite records full pytest, the separately selected 486-test regression, Ruff/format, mypy, sdist/wheel, OMS/Alpha/joint replay and previous independent accounting checkers. Preservation audits check the previous private snapshot and every file at baseline `1df7491`, except explicitly extended verifier/CI files. Final exact-SHA Python 3.11/3.12 CI is verified after push and recorded in the final chat and private CI proof.

Actual local results: all 23 commands passed; full pytest 492 PASS, prior regression 486 PASS, mypy over 82 source files, and both distribution builds passed. The independent checker reopens original DART XMLs and KRX rows to verify corporate IDs, short/standard codes, issuer names, stock classes and listing chronology. Preservation verifies 11,026 prior private files and the 1,390-file legacy raw tracked snapshot byte for byte, plus all 1,516 baseline Git contents except verifier/CI extensions. Eighteen preexisting Git-versus-worktree CRLF/LF differences are reported separately and not rewritten or treated as evidence changes. Secret matches: zero.

`ECONOMIC_EDGE_UNVERIFIED` and `LIVE_NOT_APPROVED` remain unchanged. New price calls, KIS/DART authenticated requests, economic trials, account queries, orders and cancels are all zero.
