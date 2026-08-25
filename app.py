
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from engine import analyze
from data import load_all
import config

st.set_page_config(page_title="XAU/USD Intraday Engine V6", page_icon="🥇", layout="wide")

st.title("🥇 XAU/USD Intraday Engine V6")
st.caption("15m context → 5m confirmation → 1m execution • analysis only")

with st.sidebar:
    st.header("Settings")
    refresh = st.slider("Refresh interval (seconds)", 30, 300, 60, 30)
    rr2 = st.slider("TP2 risk/reward", 1.5, 5.0, 2.5, 0.25)
    news_hold = st.slider("News hold threshold", 50, 100, 70, 5)
    st.info("The engine does not place orders. Entry/SL/TP/BE levels are analytical trade-plan levels.")
    if st.button("🔄 Refresh now"):
        st.rerun()

data = load_all()
result = analyze(data, rr2=rr2, news_hold=news_hold)

if result["data_warning"]:
    st.warning(result["data_warning"])

m1,m2,m3,m4 = st.columns(4)
m1.metric("Setup", result["setup_label"])
m2.metric("Confidence", f'{result["confidence"]}/100')
m3.metric("Direction", result["direction"])
m4.metric("News risk", f'{result["news"]["risk"]}/100')

st.caption(result["source_line"])

if result["trade_plan"]:
    p=result["trade_plan"]
    st.subheader("🎯 Actionable Trade Plan")
    c1,c2,c3,c4,c5,c6=st.columns(6)
    c1.metric("Entry", f'{p["entry"]:.2f}')
    c2.metric("Stop Loss", f'{p["sl"]:.2f}')
    c3.metric("TP1", f'{p["tp1"]:.2f}')
    c4.metric("TP2", f'{p["tp2"]:.2f}')
    c5.metric("BE trigger", f'{p["be_trigger"]:.2f}')
    c6.metric("R:R TP2", f'{p["rr2"]:.2f}R')
    st.info(p["instructions"])
else:
    st.warning(result["trade_message"])
    if result["triggers"]:
        st.subheader("📍 Trigger levels — wait for confirmation")
        t1,t2=st.columns(2)
        with t1:
            st.metric("Long trigger", f'{result["triggers"]["long"]:.2f}')
            st.caption("Only valid after 5m + 1m bullish confirmation.")
        with t2:
            st.metric("Short trigger", f'{result["triggers"]["short"]:.2f}')
            st.caption("Only valid after 5m + 1m bearish confirmation.")

st.divider()

tabs=st.tabs(["📈 Chart","🧠 Structure","📰 News","🧪 Validation","📋 Rules"])
with tabs[0]:
    tf=st.selectbox("Chart timeframe", ["15m","5m","1m"], index=1)
    df=data.get(tf)
    if df is None or df.empty:
        st.error(f"No usable {tf} data.")
    else:
        st.line_chart(df["Close"].tail(250), height=420)
        levels=result["levels"].get(tf,{})
        if levels:
            st.write("**Key levels**")
            st.dataframe(pd.DataFrame([levels]), use_container_width=True)
        st.caption(f"{tf}: {len(df)} bars • {data['source'].get(tf,'unknown')}")

with tabs[1]:
    for tf in ["15m","5m","1m"]:
        s=result["structure"][tf]
        st.subheader(tf)
        st.write({
            "Bias":s["bias"],
            "Trend score":s["trend_score"],
            "BOS":s["bos"],
            "CHoCH":s["choch"],
            "Liquidity sweep":s["sweep"],
            "Displacement":s["displacement"],
            "FVG":s["fvg"],
            "OB":s["ob"],
        })

with tabs[2]:
    n=result["news"]
    c1,c2,c3=st.columns(3)
    c1.metric("Directional score", f'{n["direction_score"]:+d}')
    c2.metric("Event risk", f'{n["risk"]}/100')
    c3.metric("Gold bias", n["bias"])
    if n["items"]:
        st.dataframe(pd.DataFrame(n["items"]), use_container_width=True)
    else:
        st.info("No news items were retrieved. Event-risk is therefore conservative.")

with tabs[3]:
    st.subheader("Closed-bar research validation")
    st.caption("This is a research backtest, not proof of profitability. It never uses future candles to create a historical signal.")
    st.write(result["validation"])

with tabs[4]:
    st.markdown("""
**15m bias**
- Determine directional context from swing structure, EMA alignment and displacement.
- A 15m range is not an automatic rejection; it becomes directional only when trend score ≥ 60 or ≤ 40.
- Otherwise the engine stays neutral.

**5m confirmation**
- Must agree with 15m direction.
- Requires a confirmed BOS/CHoCH or liquidity sweep + displacement.
- Entry zone must be near an FVG or order block.

**1m execution**
- Requires same direction, a fresh sweep or structure break, and displacement.
- Entry is placed at the retracement/zone, not at the candle close.

**Invalidation**
- Long: closed 1m candle below sweep/OB invalidation.
- Short: closed 1m candle above sweep/OB invalidation.
- Setup expires after 3 one-minute bars without trigger.

**Risk management**
- SL is structural, capped at 0.6–2.5 ATR.
- TP1 = 1R; TP2 = user-selected R multiple.
- Move SL to breakeven only after TP1/1R is reached, never before.
- If high-impact event risk ≥ threshold, the engine returns NEWS HOLD instead of an entry.

**Important:** analysis only; verify price, spread and broker feed before trading.
""")

st.caption(f"Last scan: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} • Auto refresh configured: {refresh}s")
