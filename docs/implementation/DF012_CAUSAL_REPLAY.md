# DF012 frozen D1 technical replay

The unchanged event engine and DF006 qualifier produce 48 reference ledgers: four qualified events, three cost/fill scenarios and CASH/D1/BUY_HOLD/TREND. Each is an independent 10,000,000 KRW reference account, not a pooled portfolio. D1 keeps its absolute 25% entry target, five **calendar** day expiry, prior-close stop/correction handling, capacity, reservations, cash and settlement rules.

BASE uses fee/tax/slippage 3/20/5 basis points; STRESS uses 10/30/20; PARTIAL uses BASE charges with 0.5 fill fraction. Operating expense is 100 KRW per observed replay day and cash interest is zero. These are research scenarios, not measured historical tariffs. Slippage is embedded in fill prices and is not deducted twice.

|Code|BASE net KRW|STRESS net KRW|PARTIAL net KRW|BASE mean stock exposure|BASE final shares|
|---|---:|---:|---:|---:|---:|
|012330|-91,163.00|-103,332.34|-30,716.44|11.3613%|0|
|014130|477.54|310.25|599.94|0.1557%|0|
|352700|-16,318.17|-17,705.85|-16,187.80|2.1230%|15|
|041960|-21,043.15|-25,347.85|-25,075.68|4.3838%|0|

All four D1 ledgers equal their corresponding same-entry BUY_HOLD ledgers in every scenario. 352700 also equals TREND. Other BASE D1-minus-TREND differences are -90,563.00, +1,077.54 and -20,443.15 KRW respectively; their TREND accounts stayed in cash. These are diagnostics, not matched non-event counterfactuals. The small 014130 profit accompanies only 0.156% average capital exposure and cannot be presented as a deployable 25% sleeve return.

352700 retains 15 shares even in BASE/STRESS, with three unfulfilled reduction days. 041960 has one BASE/STRESS unfulfilled reduction day despite eventually ending flat. PARTIAL final quantities are 1, 1, 25 and 25; each has three unfulfilled reduction days. An intent to reduce risk is never treated as a successful fill, and residual holdings retain unrealized PnL. Entry target weight is not a continuous risk cap; DF010's 081660 maximum marked weight of 25.99% remains an unresolved execution/risk distinction. No central live risk controller ran.

`results.json` provides per-model requested and executed quantities, realized/unrealized PnL, charges, turnover, mean/max exposure, drawdown, worst day, expected shortfall, residuals, risk failures and control differences. Private ledgers retain every modeled trade. A separate diagnostic reconstructs pre/post-fill NAV marked at the actual observed RAW open; it preserves the original ledger and verifies cash/quantity after daily operating expense. This mark is not a second real market execution observation.

The held 352770 has no replay PnL. No parameters, targets, holding periods or costs were optimized. Full research eligibility and valid matched non-event controls remain zero; no event-specific causal effect, independent OOS pass, statistical support or economic edge is claimed.
