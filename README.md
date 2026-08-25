# XAU/USD Intraday Engine V8

Mobile Streamlit dashboard for manual XAU/USD analysis.

Pipeline: 15m context -> 5m SMC confirmation -> 1m execution.

Features:
- XAU spot with GC futures fallback
- SMC-style BOS/CHoCH, liquidity sweeps, FVG and order blocks
- Entry, stop, TP1, TP2, breakeven and position sizing from balance/risk
- Directional news score and separate event-risk hold filter
- Closed-bar walk-forward research validation with in-sample/out-of-sample stats
- No broker connection and no automatic order placement

## Important
Broker contract size, tick value, spread and minimum lot differ. Verify them before manual execution. Research results are not a guarantee of profitability.
