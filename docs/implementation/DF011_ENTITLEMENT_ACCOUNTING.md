# DF-011 entitlement accounting

CorporateActionEntitlementLedger is a new immutable research sidecar. The original Ledger, ReferencePortfolio, D1 strategy, frozen execution rules and all DF010 results remain untouched. It does not submit orders, create broker cash or revise old NAV.

Entitled quantity uses signed executions and explicit T+2 settlement on observed, externally corroborated dates. It is the quantity settled by the record date, cross-checked against the last entitled trade-day cutoff; it is not the final residual position. Sales after ex-day do not destroy an already earned right. A buy on ex-day settling after the record date does not earn that right. Duplicate execution identities, security conflicts and adjusted-price-plus-cash combinations are rejected.

The two time axes are economic date and evidence-knowledge date. A final amount cannot be recognized before the resolution or before its evidence becomes available on the declared knowledge axis. The frozen D1 receives no sidecar facts: decision_inputs always returns an empty mapping. No 2023/2024 dividend value is backfilled into December 2022 decisions.

| Scenario | Modeled entitled shares | Gross right KRW | Original final shares | Actual net dividend cash | Actual total economic PnL |
|---|---:|---:|---:|---|---|
|BASE|61|30,500|0|NULL|NULL|
|STRESS|61|30,500|0|NULL|NULL|
|PARTIAL|30|15,000|4|NULL|NULL|

These quantities come from the unchanged rejected DF010 price-only diagnostic paths, not an actual shareholder account. Original BASE/STRESS/PARTIAL price-only diagnostic PnL remains -270,805.94/-282,770.17/-124,160.06 KRW. We do not add the gross right to those figures and call the sum a verified return. Their source hashes and non-promotion status remain explicit in each private sidecar.

After final resolution but before the confirmed payment month, the ex-post gross receivable can be reconstructed. At the end of the known paid month, exact outstanding receivable and net paid cash remain NULL because payment-day/account/tax allocation is unresolved; neither an unpaid balance nor investable cash is invented. Verified spendable-cash increment remains zero. This is a recognition gate, not a claim that no economic dividend was paid.

PRICE_ONLY_PNL, ENTITLEMENT_PENDING, DIVIDEND_RECEIVABLE_VERIFIED, CASH_PAYMENT_VERIFIED, TAX_TREATMENT_PENDING and TOTAL_RETURN_VERIFIED are separate states. Gross payment proof does not establish after-tax spendable cash. TOTAL_RETURN_VERIFIED additionally requires verified price path, full required action window, actual payment evidence and investor-specific tax evidence. Modeled and actual total-return fields are separate. Synthetic tests cover the complete state, while the real case remains incomplete.

RAW execution prices and explicit entitlement cash are the chosen basis. ADJUSTED plus dividend cash is rejected; no dividend is counted inside an adjusted-price gain and again as a cash payment. Existing trading fee, transaction-tax, slippage and expense accounting remains unchanged. Dividend withholding is not assumed to be a generic retail rate. No hypothetical reinvestment occurs before verified payment.
