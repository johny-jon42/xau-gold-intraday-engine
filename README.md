# XAU/USD Intraday Engine v4

Mobile Streamlit dashboard for analysis only.

## Data policy
- Primary intraday source: Yahoo Finance XAUUSD=X.
- Fallback: Yahoo Finance GC=F (COMEX gold futures) when XAU/USD spot candles are unavailable.
- The app never fabricates missing candles.
- 1m is mandatory for an execution-ready setup.

## Signal architecture
15m context -> 5m confirmation -> 1m execution.

### Strict rules
- 15m defines direction.
- 5m must align and show fresh BOS/CHoCH.
- A-grade setup requires a liquidity sweep.
- 1m requires aligned structure + displacement + sweep.
- FVG/OB proximity is confluence, not a standalone signal.
- Entry is invalidated by a closed candle through the structural stop / swept extreme.
- Risk must be 0.60-2.50 ATR.
- Signal expires after 3 one-minute bars.
- High-impact event risk >=55/100 blocks entry.

## News engine
Separate:
1. directional information (bullish/bearish for gold)
2. event risk (whether trading should be avoided)

Sources:
- Google News RSS for relevant headlines
- Forex Factory public calendar RSS for macro-event risk

This is a transparent rule-based filter, not a claim of predictive AI sentiment.

## Important
This is a research/analysis system, not a broker or execution system. Validate on broker-quality data and out-of-sample history before risking money.

## V5 validation upgrade

V5 adds a closed-bar replay and walk-forward validation page. It splits the available 5m sample into a fixed-rule in-sample segment and a final 30% out-of-sample segment, reports win rate, net R, profit factor, max drawdown and session breakdown, and never tunes thresholds to the OOS segment. The historical replay does not fabricate historical news from today's RSS feed; the news filter remains a live risk gate.

### Data reliability

The downloader caches identical Yahoo requests and reduces each timeframe to a primary request plus one retry per source. It tries XAUUSD=X first and GC=F second. The UI always reports which source was used. Missing data causes SAFE MODE rather than synthetic candles.
