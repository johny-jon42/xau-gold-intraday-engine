import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from config import SYMBOL
from data import get_ohlcv, google_news, news_score
from engine import analyze_timeframe, score_setup, build_trade_plan, simple_backtest

st.set_page_config(page_title="XAU/USD Intraday Engine", page_icon="🥇", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>.block-container{padding-top:1rem;padding-bottom:2rem;max-width:1450px}.stMetric{border-radius:12px}</style>", unsafe_allow_html=True)
st.title("🥇 XAU/USD Intraday Engine")
st.caption("15m context → 5m confirmation → 1m execution • Analysis only • Prototype data feed")

@st.cache_data(ttl=55)
def scan():
    market=get_ohlcv(SYMBOL)
    analyses={tf:analyze_timeframe(df) for tf,df in market.items()}
    news=google_news(); ns,details=news_score(news)
    result=score_setup(analyses["15m"],analyses["5m"],analyses["1m"],news_score=ns)
    plan=build_trade_plan(analyses["15m"],analyses["5m"],analyses["1m"],result)
    return market,analyses,result,ns,details,plan

try: market,a,result,nscore,news_details,plan=scan()
except Exception as e:
    st.error(f"Scanner error: {type(e).__name__}: {e}")
    st.info("If this is a new deployment, open Manage app → Reboot app after the GitHub files finish updating.")
    st.stop()

c=st.columns(5)
c[0].metric("Signal",result["signal"]); c[1].metric("Confidence",f"{result['confidence']}/100")
c[2].metric("LONG",result["long_score"]); c[3].metric("SHORT",result["short_score"]); c[4].metric("News",nscore)
st.caption("Last scan: "+datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
if plan:
    p=st.columns(5); p[0].metric("Entry",f"{plan['entry']:.2f}"); p[1].metric("Stop",f"{plan['sl']:.2f}"); p[2].metric("TP1",f"{plan['tp1']:.2f}"); p[3].metric("TP2",f"{plan['tp2']:.2f}"); p[4].metric("Risk",f"{plan['risk']:.2f}")
    st.warning("This is an automatically calculated study plan, not a broker order or financial advice.")

tabs=st.tabs(["📈 Annotated Chart","🧠 Structure","📰 News","🧪 Backtest","📋 Rules"])
with tabs[0]:
    tf=st.selectbox("Chart timeframe",["15m","5m","1m"],index=2)
    df=a[tf]["data"].tail(300).copy()
    if not df.empty:
        fig=go.Figure(go.Candlestick(x=df.index,open=df["open"],high=df["high"],low=df["low"],close=df["close"],name=SYMBOL))
        # Swing levels / liquidity
        for level in a[tf]["liquidity"]["equal_highs"]: fig.add_hline(y=level,line_dash="dot",annotation_text="EQH")
        for level in a[tf]["liquidity"]["equal_lows"]: fig.add_hline(y=level,line_dash="dot",annotation_text="EQL")
        for level in a[tf]["liquidity"]["swing_highs"][-4:]: fig.add_hline(y=level,line_dash="dash",opacity=.35)
        for level in a[tf]["liquidity"]["swing_lows"][-4:]: fig.add_hline(y=level,line_dash="dash",opacity=.35)
        # OB rectangles and FVG rectangles
        for o in a[tf]["ob"][-6:]:
            if o["index"] in df.index or o["index"]<=df.index[-1]:
                x0=max(o["index"],df.index[0]); fig.add_shape(type="rect",x0=x0,x1=df.index[-1],y0=o["bottom"],y1=o["top"],line_width=1,fillcolor="rgba(0,200,120,0.10)" if o["type"]=="BULLISH" else "rgba(220,80,80,0.10)")
        for f in a[tf]["fvg"][-6:]:
            if f["index"]<=df.index[-1] and f["active"]:
                x0=max(f["index"],df.index[0]); fig.add_shape(type="rect",x0=x0,x1=df.index[-1],y0=f["bottom"],y1=f["top"],line_width=0,fillcolor="rgba(80,140,255,0.12)")
        sw=a[tf]["sweep"]
        if sw: fig.add_hline(y=sw["level"],line_width=3,annotation_text="LIQ SWEEP")
        if plan:
            fig.add_hline(y=plan["entry"],line_dash="dash",annotation_text="ENTRY")
            fig.add_hline(y=plan["sl"],line_dash="dot",annotation_text="SL")
            fig.add_hline(y=plan["tp1"],line_dash="dot",annotation_text="TP1")
            fig.add_hline(y=plan["tp2"],line_dash="dot",annotation_text="TP2")
        fig.update_layout(height=650,margin=dict(l=5,r=5,t=20,b=5),xaxis_rangeslider_visible=False,template="plotly_dark")
        st.plotly_chart(fig,use_container_width=True)
    else:
        st.warning("No market data returned for this timeframe. The free Yahoo feed can temporarily omit 1m XAU/USD data; the engine will not fabricate candles.")

with tabs[1]:
    cols=st.columns(3)
    for col,tf in zip(cols,["15m","5m","1m"]):
        s=a[tf]["structure"]; col.subheader(tf); col.metric("Bias",s["bias"]); col.write(f"BOS: {s['bos'] or '—'}"); col.write(f"CHoCH: {s['choch'] or '—'}")
        col.write(f"Liquidity sweep: {(a[tf]['sweep'] or {}).get('type', '—')}"); col.write(f"Zone: {(a[tf]['premium_discount'] or {}).get('zone', '—')}")
    l,r=st.columns(2); l.markdown("**LONG reasons**"); [l.write("• "+x) for x in result["long_reasons"]]; r.markdown("**SHORT reasons**"); [r.write("• "+x) for x in result["short_reasons"]]

with tabs[2]:
    st.metric("Gold news score",nscore)
    st.caption("Headline relevance/direction model. It is a filter, not a claim that headlines predict price.")
    for item in news_details[:20]:
        st.write(f"**{item['delta']:+}** — {item['title']}")

with tabs[3]:
    st.subheader("Rolling 5m rule backtest")
    st.caption("This is a simple research test of the current rule set. It is not a tick-accurate execution backtest and must not be treated as proof of profitability.")
    df5=market.get("5m",pd.DataFrame())
    if not df5.empty:
        bt=simple_backtest(df5)
        b=st.columns(5); b[0].metric("Trades",bt["trades"]); b[1].metric("Wins",bt["wins"]); b[2].metric("Losses",bt["losses"]); b[3].metric("Win rate",f"{bt['win_rate']}%"); b[4].metric("Net R",bt["net_r"])
    else: st.warning("5m data unavailable for backtest.")

with tabs[4]:
    st.markdown("""### Rules\n**15m:** directional context and major liquidity/OB/FVG.\n\n**5m:** BOS/CHoCH + sweep/displacement confirmation.\n\n**1m:** execution trigger and location.\n\n**News:** transparent gold/USD/rates/yields headline score.\n\n**Risk:** the engine only calculates a study entry/SL/TP; it does not place trades.\n\n**Next validation step:** compare this backtest with a properly timestamped economic-calendar dataset and broker-quality XAU/USD candles before using signals with real money.""")

if st.button("🔄 Refresh now",use_container_width=True):
    st.cache_data.clear(); st.rerun()
