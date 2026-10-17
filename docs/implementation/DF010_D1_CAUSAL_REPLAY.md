# DF-010 frozen D1 causal replay

The unchanged DF006 event_replay and ReferencePortfolio/Ledger contracts produced 24 separate accounts: two qualifying events, four models and three cost scenarios. Each starts with KRW 10,000,000; target is an absolute 25%, deadline five calendar days, previous-close stop/correction rules unchanged. Prior-volume capacity, limit prices, order expiry and partial residuals are preserved. These overlapping case accounts are not a feasible pooled portfolio.

Fees/sell-tax/slippage bps/fill fraction: BASE 3/20/5/1; STRESS 10/30/20/1; PARTIAL 3/20/5/0.5. Operating expense KRW 100 per observed replay day, cash interest zero. These are research scenarios, not verified historical tariffs. RAW-open fills are counterfactual, not real executions. Slippage appears once inside fill prices; gross less slippage, commissions, tax and operating costs reconciles to net. Realized and unrealized price PnL are separated.

| Code | Scenario | Net KRW | D1 minus CASH | D1 minus BUY_HOLD | D1 minus TREND | Final shares | Unfulfilled reduction days |
|---|---|---:|---:|---:|---:|---:|---:|
|081660|BASE|180753.58|181553.58|0.00|181553.58|0|0|
|081660|STRESS|166860.34|167660.34|0.00|167660.34|0|0|
|081660|PARTIAL|77647.84|78447.84|0.00|78447.84|5|3|
|002840|BASE|10951.50|11551.50|0.00|11551.50|0|0|
|002840|STRESS|9991.61|10591.61|0.00|10591.61|0|0|
|002840|PARTIAL|18063.41|18663.41|0.00|18663.41|1|3|

No qualified case has D1-specific incremental profit over BUY_HOLD. Different D1/TREND results do not identify causation: the diagnostic market rose 3.02% and 7.70% over the corresponding replay diagnostic windows. Public results.json includes fees, slippage, operating costs, exposure, MDD, worst day, ES, turnover, quantities, residuals and control differences. Detailed observed prices, signals and trades remain private.
