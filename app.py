import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from engine import analyze
from data import load_all

st.set_page_config(page_title="XAU/USD Intraday Engine V7", page_icon="🥇", layout="wide")
st.title("🥇 XAU/USD Intraday Engine V8")
st.caption("SMC: 15m context → 5m confirmation → 1m execution • manual execution only")

with st.sidebar:
    st.header("Trade setup")
    balance = st.number_input("Account balance (USD)", min_value=10.0, value=10000.0, step=100.0)
    risk_pct = st.number_input("Risk per trade (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
    contract_size = st.number_input("XAU contract size (oz / 1.00 lot)", min_value=1.0, value=100.0, step=1.0, help="Set this to your broker's XAU/USD contract specification. Common CFD convention is 100 oz, but brokers differ.")
    refresh = st.slider("Refresh interval (seconds)", 30, 300, 60, 30)
    rr2 = st.slider("TP2 risk/reward", 1.5, 5.0, 2.5, 0.25)
    news_hold = st.slider("News hold threshold", 50, 100, 70, 5)
    st.info("The app never places orders. It calculates a trade plan so you can execute it yourself in your broker account.")
    if st.button("🔄 Refresh now"):
        st.rerun()

data = load_all()
result = analyze(data, rr2=rr2, news_hold=news_hold, balance=balance, risk_pct=risk_pct, contract_size=contract_size)

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
    st.subheader("🎯 EXECUTION TRADE PLAN")
    st.caption("These are planning levels for manual execution in your broker. The app never sends orders.")
    st.success(f"{result['direction']} setup confirmed — execute manually only after the 1m confirmation candle closes.")
    c1,c2,c3,c4,c5,c6=st.columns(6)
    c1.metric("ENTRY", f'{p["entry"]:.2f}')
    c2.metric("STOP LOSS", f'{p["sl"]:.2f}')
    c3.metric("TP1 (1R)", f'{p["tp1"]:.2f}')
    c4.metric("TP2", f'{p["tp2"]:.2f}')
    c5.metric("BE TRIGGER", f'{p["be_trigger"]:.2f}')
    c6.metric("R:R", f'{p["rr2"]:.2f}R')
    q1,q2,q3,q4=st.columns(4)
    q1.metric("Risk $", f'${p["risk_usd"]:,.2f}')
    q2.metric("Position", f'{p["lots"]:.3f} lots')
    q3.metric("Units", f'{p["units"]:.1f} oz')
    q4.metric("Entry zone", p["zone"])
    st.info(p["instructions"])
else:
    st.warning(result["trade_message"])
    t1,t2=st.columns(2)
    with t1:
        st.metric("LONG WATCH / TRIGGER", f'{result["triggers"]["long"]:.2f}')
        st.caption("Not an entry. Wait for bullish 5m + 1m SMC confirmation and a valid retracement/zone.")
    with t2:
        st.metric("SHORT WATCH / TRIGGER", f'{result["triggers"]["short"]:.2f}')
        st.caption("Not an entry. Wait for bearish 5m + 1m SMC confirmation and a valid retracement/zone.")

st.divider()
tabs=st.tabs(["📈 Chart + levels","🧠 SMC Structure","📰 News","🧪 Validation","📋 Rules"])
with tabs[0]:
    tf=st.selectbox("Chart timeframe", ["15m","5m","1m"], index=1)
    df=data.get(tf)
    if df is None or df.empty:
        st.error(f"No usable {tf} data.")
    else:
        d=df.tail(180).copy()
        fig=go.Figure(data=[go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name=tf)])
        p=result.get("trade_plan")
        if p:
            for name,val,dash in [("ENTRY",p["entry"],"solid"),("SL",p["sl"],"dash"),("TP1",p["tp1"],"dot"),("TP2",p["tp2"],"dashdot"),("BE",p["be_trigger"],"longdash")]:
                fig.add_hline(y=val,line_dash=dash,annotation_text=name,annotation_position="top left")
        else:
            for name,val in [("LONG TRIGGER",result["triggers"]["long"]),("SHORT TRIGGER",result["triggers"]["short"])]:
                if val: fig.add_hline(y=val,line_dash="dot",annotation_text=name,annotation_position="top left")
        s=result["structure"].get(tf,{})
        for key,label in [("swing_high","Swing High"),("swing_low","Swing Low")]:
            if s.get(key): fig.add_hline(y=s[key],line_dash="dash",annotation_text=label,annotation_position="bottom right")
        fig.update_layout(height=520,margin=dict(l=10,r=10,t=30,b=10),xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)
        st.caption(f"{tf}: {len(df)} bars • {data['source'].get(tf,'unknown')} • latest candle excluded from structural calculations")

with tabs[1]:
    for tf in ["15m","5m","1m"]:
        s=result["structure"][tf]
        st.subheader(tf)
        st.write({
            "Bias":s["bias"], "Trend score":s["trend_score"], "BOS":s["bos"], "CHoCH":s["choch"],
            "Liquidity sweep":s["sweep"], "Displacement":s["displacement"], "FVG":s["fvg"], "OB":s["ob"],
            "Premium/Discount":s["premium_discount"], "Swing high":s["swing_high"], "Swing low":s["swing_low"]
        })

with tabs[2]:
    n=result["news"]
    c1,c2,c3=st.columns(3)
    c1.metric("Directional score", f'{n["direction_score"]:+d}')
    c2.metric("Event risk", f'{n["risk"]}/100')
    c3.metric("Gold bias", n["bias"])
    if n["items"]: st.dataframe(pd.DataFrame(n["items"]), use_container_width=True)
    else: st.info("No news items were retrieved. Event-risk is therefore conservative.")

with tabs[3]:
    st.subheader("Closed-bar walk-forward validation")
    st.caption("Research only. The test uses only information available before each entry; same-bar SL/TP is treated conservatively as an SL.")
    v=result["validation"]
    st.info(v.get("status","Unknown"))
    if v.get("in_sample"):
        a,b=st.columns(2)
        with a:
            st.markdown("### In-sample")
            st.json(v["in_sample"])
        with b:
            st.markdown("### Out-of-sample")
            st.json(v["out_of_sample"])
        st.markdown("### Combined")
        st.json(v["total"])
    st.caption(v.get("note",""))

with tabs[4]:
    st.markdown("""
### SMC decision chain
**15m:** market structure + EMA alignment + swing progression → directional context.

**5m:** BOS/CHoCH + liquidity sweep + displacement + FVG/OB location → confirmation.

**1m:** same-direction BOS/CHoCH or sweep + displacement + FVG/OB → execution trigger.

**Entry:** the displayed retracement/zone midpoint when available; otherwise current price after confirmation.

**Invalidation:** structural swing/sweep/OB failure. A closed 1m candle through the invalidation level cancels the setup.

**Risk:** dollar risk = balance × risk %. Position size = dollar risk ÷ (entry-to-SL distance × contract size). Verify your broker's contract size, tick value, spread and minimum lot before executing.

**TP1:** 1R. **BE:** move SL to entry only after TP1/1R is actually reached. **TP2:** user-selected R multiple.

**News:** directional news score and event-risk score are separate. High event risk can block an otherwise valid technical setup.

**Important:** the app is analysis-only. It does not connect to or trade your broker account.
""")

st.caption(f"Last scan: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} • Refresh target: {refresh}s")
