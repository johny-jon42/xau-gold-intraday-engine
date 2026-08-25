# XAU/USD Intraday Engine V7

SMC analysis-only dashboard for manual execution.

**15m context → 5m confirmation → 1m execution**

Features:
- XAU spot / GC futures transparent fallback
- SMC structure: BOS, CHoCH, liquidity sweeps, FVG, order blocks, premium/discount
- Manual execution plan: Entry, SL, TP1, TP2, break-even trigger
- Balance + risk percentage based position sizing
- Editable XAU contract size (oz per 1.00 lot)
- Entry/SL/TP/BE lines on the chart
- News direction vs event-risk separation
- No broker order execution

Position sizing is an estimate. Broker contract specifications vary; verify contract size, tick value, spread, minimum lot, and margin requirements before placing a trade.
