# XAU/USD SMC Intraday Engine V10

Mobile-friendly Streamlit research/decision-support app for manual XAU/USD trading.

## Important
- No broker login and no automated order execution.
- XAU spot data is required for execution-grade levels.
- GC=F can be enabled only as an explicitly labelled research proxy.
- Validation is OFF by default so the live dashboard starts quickly on mobile. Enable it from the sidebar when needed.
- The system is not a guarantee of profitability.

## V10 fixes
- Removes the expensive validation run from every dashboard refresh.
- Bounds validation to a recent sample so it is usable on a phone.
- Adds timeouts and caching to market-data requests.
- Avoids automatically trying futures unless the user explicitly enables the proxy.
- Fixes BOS/CHoCH direction mapping in the execution and validation logic.
- Keeps risk sizing, entry/SL/TP/BE, news hold, and manual execution plan.
