# DF009 historical identity results

Targets were remotely frozen at `fa0927a` before any KRX inspection. The 12-original cohort contains 12 distinct corporations and three events in each of 2022, 2023, 2024 and 2025. It uses DF008's existing ranks among 54 verified originals and excludes the old consumed two-event study. Query paths, specification hashes and 46 distinct date/market calls were subsequently sealed at `d300f3d`, before the authenticated probe. No target was replaced after observing availability or price outcomes.

All 210 prior DART pages were rehashed, reproducing 19,319 unique rows. Each selected original XML was reparsed with its immutable raw and normalized hashes, and its explicit eight-digit corporate ID matched the cached official disclosure row. Corporate identity was independently reconfirmed for all 12 events. Ten have a six-digit DART code candidate; two do not. Three source-market classifications are outside Y/K or unknown. These cases remain in the fixed denominator and are not silently replaced.

| Evidence state | Verified events | Interpretation |
|---|---:|---|
| CORPORATE_IDENTITY_VERIFIED | 12 | Explicit document corporate ID, not a historical stock code |
| HISTORICAL_SECURITY_PRESENT | 0 | All event states NULL; no successful KRX basics response |
| CORP_STOCK_LINK_VERIFIED | 0 | No historical issuer/security link established |
| THEN_LISTED_STATUS_VERIFIED | 0 | Then-market and listing chronology not yet observed |
| DELISTING_AND_HALT_PENDING | 12 pending | No inferred tradability or delisting absence |
| CORPORATE_ACTION_PENDING | 12 pending | No inferred absence of actions or code changes |
| PRICE_AND_SESSION_PENDING | 12 pending | No price calls or fabricated sessions |

One of 46 planned date/market queries was attempted. It returned HTTP/provider 401 and halted collection; the other 45 are unattempted, not 45 failed historical datasets. Successful query dates and market/date responses are zero. Observed historical row count, historical coverage availability, issuer/security conflicts and requests per verified linkage remain NULL because they were not measurable. Additional verified historical mappings relative to DF008: zero. This is an access-pending result, not proof that KRX historical data is absent or that D1 has no alpha.

The offline qualifier separates standard/short codes, raw hash and response-scope validation, exact event-date snapshots, listing chronology, corporation/issuer corroboration, stock class and unresolved rename/transfer/merger/code history. Exact names or current metadata alone cannot pass. Empty lists do not prove delisting. A prior or future snapshot cannot silently replace the event-date record. Halt/action/session gates and publication timestamps remain pending even after a hypothetical identity confirmation. Authored test fixtures establish rejection behavior only and are excluded from market-evidence counts.

Public identifiers, flags and hashes are in `artifacts/df009/event-linkage.json`; the legal-name dossier, source documents, actual failed response, journal and executed sources are private. Prior D1 PnL, Alpha A0/A1 and EWY H1 are unchanged.
