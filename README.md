# XAU/USD Intraday Engine — Phone Web App

This is a Streamlit web app for the XAU/USD rules engine.

## What it does

- 15m → 5m → 1m multi-timeframe analysis
- BOS / CHoCH
- Liquidity sweeps
- Order blocks
- FVG
- Premium/discount
- Gold news score
- LONG / SHORT / WATCH / NO TRADE
- Mobile-friendly dashboard
- Candlestick chart

It does **not** place trades.

## Easiest deployment: Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload all files from this folder.
3. Open Streamlit Community Cloud.
4. Create a new app.
5. Select the repository and `app.py`.
6. Deploy.
7. Open the generated HTTPS address from Chrome on your Android phone.

## Local test

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app is designed to work with the existing `engine.py`, `data.py`, and `config.py` files.
