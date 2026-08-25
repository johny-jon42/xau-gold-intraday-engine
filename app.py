import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

from config import SYMBOL
from data import get_ohlcv, google_news, news_score
from engine import analyze_timeframe, score_setup

st.set_page_config(
    page_title="XAU/USD Intraday Engine",
    page_icon="🥇",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px;}
.metric-card {border:1px solid rgba(128,128,128,.25); border-radius:14px; padding:14px;}
.small {font-size:.85rem; opacity:.75;}
.signal {font-size:2rem; font-weight:800;}
</style>
""", unsafe_allow_html=True)

st.title("🥇 XAU/USD Intraday Engine")
st.caption("15m context → 5m confirmation → 1m execution • Analysis only")

@st.cache_data(ttl=55)
def scan():
    market = get_ohlcv(SYMBOL)
    analyses = {tf: analyze_timeframe(df) for tf, df in market.items()}
    news = google_news()
    nscore, details = news_score(news)
    result = score_setup(analyses["15m"], analyses["5m"], analyses["1m"], news_score=nscore)
    return market, analyses, result, nscore, details

try:
    market, a, result, nscore, news_details = scan()
except Exception as e:
    st.error(f"Scanner error: {e}")
    st.stop()

top = st.columns(4)
top[0].metric("Signal", result["signal"])
top[1].metric("Confidence", f"{result['confidence']}/100")
top[2].metric("Long", result["long_score"])
top[3].metric("Short", result["short_score"])

st.caption("Last scan: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

tabs = st.tabs(["📈 Chart", "🧠 Structure", "📰 News", "📋 Rules"])

with tabs[0]:
    df = market.get("1m", pd.DataFrame()).copy()
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.tail(300)
        fig = go.Figure(go.Candlestick(
            x=df.index,
            open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"],
            name="XAU/USD"
        ))
        fig.update_layout(
            height=650,
            margin=dict(l=10,r=10,t=20,b=10),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No 1-minute market data is currently available from the selected feed.")

with tabs[1]:
    cols = st.columns(3)
    for col, tf in zip(cols, ["15m","5m","1m"]):
        s = a[tf]["structure"]
        col.subheader(tf)
        col.metric("Bias", s["bias"])
        col.write("BOS:", s["bos"] or "—")
        col.write("CHoCH:", s["choch"] or "—")
        sweep = a[tf]["sweep"]
        col.write("Liquidity sweep:", sweep["type"] if sweep else "—")
        pdz = a[tf]["premium_discount"]
        col.write("Zone:", pdz["zone"] if pdz else "—")

    st.subheader("Signal reasoning")
    left, right = st.columns(2)
    left.markdown("**LONG**")
    for x in result["long_reasons"]:
        left.write("• " + x)
    right.markdown("**SHORT**")
    for x in result["short_reasons"]:
        right.write("• " + x)

with tabs[2]:
    st.metric("Gold news score", nscore)
    st.caption("Positive = bullish gold bias; negative = bearish gold bias. This is a keyword-based prototype, not investment advice.")
    for item in news_details[:20]:
        st.write(f"**{item['delta']:+}** — {item['title']}")

with tabs[3]:
    st.markdown("""
**15m**
- Establish directional context.
- Detect meaningful swings, liquidity, OBs and FVGs.

**5m**
- Require BOS/CHoCH, liquidity sweep and/or displacement confirmation.

**1m**
- Look for the execution trigger: micro BOS/CHoCH, sweep and FVG.

**Signal thresholds**
- 85–100: A+ setup
- 75–84: Valid setup
- 65–74: Watch
- Below 65: No trade

The prototype never places orders.
""")

if st.button("🔄 Refresh now", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
