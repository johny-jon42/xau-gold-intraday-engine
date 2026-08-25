# XAU/USD Intraday Structure & News Engine

A free, rules-based prototype for automated XAU/USD analysis using 15m → 5m → 1m structure.

## What it detects

- Swing highs/lows
- Support/resistance zones
- Liquidity pools and sweeps
- BOS (Break of Structure)
- CHoCH / MSS
- Order blocks
- Fair Value Gaps (FVG)
- Displacement
- Premium/discount
- 15m → 5m → 1m confluence
- Gold-related news from Google News RSS
- DXY proxy and US 10Y yield context when available
- 0–100 directional score
- LONG / SHORT / WAIT
- CSV signal journal

## Data

The prototype uses Yahoo Finance through `yfinance` for market data. Yahoo Finance currently lists Gold at about $4,714.50 in the web interface, but exact XAU/USD availability and intraday history can vary by feed. The scanner therefore fails safely when a feed is unavailable.

News is pulled from Google News RSS without a paid API key.

For macro context, the optional FRED connector can use:
- DTWEXBGS — nominal broad US dollar index
- DGS10 — US 10-year Treasury yield

FRED's API requires a free API key for direct API access, so the code makes this connector optional.

## Install

Python 3.11+ recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Run

One scan:

```bash
python main.py --once
```

Continuous scan every 60 seconds:

```bash
python main.py --loop 60
```

Web dashboard:

```bash
streamlit run dashboard.py
```

## Important

This is an analysis and research engine, not an execution bot. It does not place trades.

The detector rules are intentionally explicit so the strategy can be backtested and improved rather than relying on subjective chart interpretation.
