# XAU/USD SMC Intraday Engine V9

Mobile Streamlit analysis app for manual XAU/USD trading.

## Architecture
15m directional context → 5m liquidity/SMC setup → 1m execution confirmation → manual trade plan.

## SMC rules
- Confirmed swing highs/lows using 2-bar pivot confirmation.
- BOS/CHoCH based on closed-candle breaks of confirmed pivots.
- Liquidity sweep requires wick through prior pivot and close back inside.
- Displacement requires body >= 1.15 ATR.
- FVG minimum gap is 0.08 ATR.
- Order block requires a strong displacement candle and last opposite candle.
- Zones are invalidated only by later closes through their far edge.
- Entry requires the full 5m setup and 1m execution checklist.

## Risk
User enters balance, risk %, contract size, lot step, minimum lot, spread and slippage. Position size is normalized to broker lot step and rejected if the minimum lot would exceed selected risk.

## Data
XAUUSD=X is the primary source. GC=F is a transparent research fallback. Execution-grade trade levels are only allowed when all 15m/5m/1m feeds are XAU spot. For actual broker-grade execution, use a broker-quality feed with matching symbol/contract specifications.

## Validation
The validation engine replays 15m→5m→1m closed-bar logic, uses the first tradable 1m candle after confirmation, and conservatively treats same-candle SL+TP as SL. This is research, not proof of profitability.

## Manual execution only
The app never connects to a brokerage account or places orders.
