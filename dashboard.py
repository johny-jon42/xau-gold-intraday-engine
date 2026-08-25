import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import SYMBOL
from data import get_ohlcv, google_news, news_score
from engine import analyze_timeframe, score_setup

st.set_page_config(page_title="XAU/USD Intraday Engine", layout="wide")
st.title("XAU/USD Intraday Structure Engine")
st.caption("15m context → 5m confirmation → 1m execution. Analysis only; no order execution.")

if st.button("Refresh scan"):
    st.cache_data.clear()

market = get_ohlcv(SYMBOL)
a15 = analyze_timeframe(market["15m"])
a5 = analyze_timeframe(market["5m"])
a1 = analyze_timeframe(market["1m"])

news = google_news()
nscore, details = news_score(news)
result = score_setup(a15, a5, a1, news_score=nscore)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Signal", result["signal"])
c2.metric("Confidence", result["confidence"])
c3.metric("Long", result["long_score"])
c4.metric("Short", result["short_score"])

st.subheader("Timeframe structure")
st.write({
    "15m": a15["structure"],
    "5m": a5["structure"],
    "1m": a1["structure"],
})

if not market["1m"].empty:
    df = market["1m"].tail(300).copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    fig = go.Figure(data=[go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"]
    )])
    fig.update_layout(height=650, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Reasons")
st.write("LONG:", result["long_reasons"])
st.write("SHORT:", result["short_reasons"])

st.subheader("Gold news score")
st.metric("News score", nscore)
for item in details[:15]:
    st.write(f"{item['delta']:+} — {item['title']}")
