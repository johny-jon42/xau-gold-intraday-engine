from urllib.parse import quote_plus
import pandas as pd
import requests
import feedparser
import yfinance as yf

from config import TIMEFRAMES

def get_ohlcv(symbol="XAUUSD=X"):
    out = {}
    for tf, cfg in TIMEFRAMES.items():
        try:
            out[tf] = yf.download(
                symbol,
                period=cfg["period"],
                interval=cfg["interval"],
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception:
            out[tf] = pd.DataFrame()
    return out

def google_news(query="gold OR XAUUSD OR Federal Reserve OR CPI OR NFP OR Treasury yields"):
    url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
        return [{
            "title": e.get("title", ""),
            "link": e.get("link", ""),
            "published": e.get("published", ""),
            "summary": e.get("summary", "")
        } for e in feed.entries[:30]]
    except Exception:
        return []

def news_score(items):
    bullish = [
        "dovish","rate cut","rate cuts","lower rates","falling yields",
        "weak dollar","weaker dollar","inflation cools","geopolitical",
        "war","conflict","recession","safe haven","gold demand","central bank buying"
    ]
    bearish = [
        "hawkish","rate hike","rate hikes","higher rates","rising yields",
        "strong dollar","stronger dollar","hot inflation","inflation rises",
        "hawkish fed","yield surge"
    ]
    score = 0
    details = []
    for item in items:
        text = (item["title"] + " " + item["summary"]).lower()
        b = sum(text.count(k) for k in bullish)
        s = sum(text.count(k) for k in bearish)
        if b or s:
            delta = min(20, 4*b) - min(20, 4*s)
            score += delta
            details.append({"title": item["title"], "delta": delta})
    return max(-100, min(100, score)), details

def fred_series(series_id, api_key=None):
    if not api_key:
        return pd.DataFrame()
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order":"desc", "limit":20}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        df = pd.DataFrame(r.json().get("observations", []))
        if not df.empty:
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()
