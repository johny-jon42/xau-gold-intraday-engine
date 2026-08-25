from urllib.parse import quote_plus
from datetime import datetime, timezone
import re
import pandas as pd
import requests
import feedparser
import yfinance as yf
from config import TIMEFRAMES


def _flatten_columns(df):
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        # Identify OHLC names regardless of which MultiIndex level Yahoo used.
        wanted = {"open", "high", "low", "close", "adj close", "volume"}
        cols = []
        for col in x.columns:
            parts = [str(p) for p in col]
            match = next((p for p in parts if p.strip().lower() in wanted), parts[0])
            cols.append(match)
        x.columns = cols
    else:
        x.columns = [str(c).strip() for c in x.columns]
    # If duplicate OHLC columns remain, keep the first one.
    x = x.loc[:, ~x.columns.duplicated(keep="first")]
    rename = {c: c.lower().replace(" ", "_") for c in x.columns}
    x = x.rename(columns=rename)
    return x


def _download_with_fallbacks(symbol, interval, periods):
    last = pd.DataFrame()
    for period in periods:
        try:
            raw = yf.download(symbol, period=period, interval=interval,
                              progress=False, auto_adjust=False, threads=False)
            x = _flatten_columns(raw)
            if not x.empty:
                return x
            last = x
        except Exception:
            continue
    return last

def get_ohlcv(symbol="XAUUSD=X"):
    out = {}
    period_fallbacks = {
        "15m": ["60d", "30d", "10d"],
        "5m": ["60d", "30d", "10d"],
        "1m": ["7d", "5d", "3d", "1d"],
    }
    for tf, cfg in TIMEFRAMES.items():
        out[tf] = _download_with_fallbacks(symbol, cfg["interval"], period_fallbacks.get(tf, [cfg["period"]]))
    return out


def google_news(query="gold OR XAUUSD OR Federal Reserve OR CPI OR NFP OR Treasury yields OR US dollar"):
    url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
        return [{"title": e.get("title", ""), "link": e.get("link", ""),
                 "published": e.get("published", ""), "summary": e.get("summary", "")}
                for e in feed.entries[:50]]
    except Exception:
        return []


# News score: direction + relevance + event importance. It is deliberately transparent,
# not an AI sentiment claim and not a substitute for an economic calendar.
BULL = {
    "rate cut": 7, "rate cuts": 7, "dovish": 6, "falling yields": 6,
    "lower yields": 6, "weaker dollar": 6, "weak dollar": 6,
    "inflation cools": 6, "safe haven": 4, "geopolitical": 3,
    "conflict": 3, "war": 3, "central bank buying": 4, "gold demand": 4,
}
BEAR = {
    "rate hike": 7, "rate hikes": 7, "hawkish": 6, "rising yields": 6,
    "higher yields": 6, "strong dollar": 6, "stronger dollar": 6,
    "inflation rises": 6, "hot inflation": 6, "hawkish fed": 7,
}
IMPORTANT = {
    "fomc": 1.6, "federal reserve": 1.5, "fed": 1.3, "cpi": 1.6,
    "nonfarm payroll": 1.6, "nfp": 1.6, "jobs report": 1.5,
    "pce": 1.5, "treasury yields": 1.4, "10-year yield": 1.4,
    "dollar index": 1.3, "dxy": 1.3, "gold": 1.2, "xauusd": 1.3,
}

def news_score(items):
    total = 0.0
    details = []
    for item in items:
        text = re.sub(r"<[^>]+>", " ", (item.get("title", "") + " " + item.get("summary", ""))).lower()
        direction = 0.0
        for k, v in BULL.items():
            if k in text: direction += v
        for k, v in BEAR.items():
            if k in text: direction -= v
        relevance = sum(mult for k, mult in IMPORTANT.items() if k in text)
        if direction == 0 or relevance == 0:
            continue
        # Cap each headline so repeated syndicated wording cannot dominate the score.
        delta = max(-15.0, min(15.0, direction * min(1.8, relevance / 2.0)))
        total += delta
        details.append({"title": item.get("title", ""), "delta": round(delta, 1),
                        "published": item.get("published", ""), "link": item.get("link", "")})
    total = max(-100.0, min(100.0, total))
    details.sort(key=lambda z: abs(z["delta"]), reverse=True)
    return round(total, 1), details


def fred_series(series_id, api_key=None):
    if not api_key: return pd.DataFrame()
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": 20}
    try:
        r = requests.get(url, params=params, timeout=10); r.raise_for_status()
        df = pd.DataFrame(r.json().get("observations", []))
        if not df.empty: df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()
