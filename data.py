
from urllib.parse import quote_plus
from datetime import datetime, timezone, timedelta
import re
import math
import pandas as pd
import requests
import feedparser
import yfinance as yf

from config import TIMEFRAMES, SYMBOL_SPOT, SYMBOL_FUTURES, NEWS_MAX_AGE_HOURS, HIGH_IMPACT_WINDOW_MIN, ELEVATED_IMPACT_WINDOW_MIN


OHLCV = ["open", "high", "low", "close", "volume"]


def _flatten_columns(df):
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        cols = []
        wanted = {"open", "high", "low", "close", "adj close", "volume"}
        for col in x.columns:
            parts = [str(p) for p in col]
            match = next((p for p in parts if p.strip().lower() in wanted), parts[0])
            cols.append(match)
        x.columns = cols
    else:
        x.columns = [str(c).strip() for c in x.columns]
    x = x.loc[:, ~x.columns.duplicated(keep="first")]
    x.columns = [str(c).lower().replace(" ", "_") for c in x.columns]
    return x


def normalize_ohlcv(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV)
    x = _flatten_columns(df)
    missing = [c for c in ["open", "high", "low", "close"] if c not in x.columns]
    if missing:
        return pd.DataFrame(columns=OHLCV)
    if "volume" not in x.columns:
        x["volume"] = 0.0
    for c in OHLCV:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["open", "high", "low", "close"]).copy()
    if not isinstance(x.index, pd.DatetimeIndex):
        try:
            x.index = pd.to_datetime(x.index)
        except Exception:
            pass
    if isinstance(x.index, pd.DatetimeIndex):
        if x.index.tz is None:
            x.index = x.index.tz_localize("UTC")
        else:
            x.index = x.index.tz_convert("UTC")
    return x.sort_index()


@__import__("functools").lru_cache(maxsize=24)
def _download_cached(symbol, interval, period):
    try:
        raw = yf.download(
            symbol, period=period, interval=interval,
            progress=False, auto_adjust=False, threads=False
        )
        return normalize_ohlcv(raw)
    except Exception:
        return pd.DataFrame(columns=OHLCV)


def _download(symbol, interval, period):
    # Cache at the Python process level so one scan never hammers Yahoo with
    # repeated identical requests. This is important on Streamlit Cloud.
    return _download_cached(symbol, interval, period).copy()


def _periods_for(tf):
    if tf == "1m":
        return ["7d", "5d", "3d", "1d"]
    if tf == "5m":
        return ["60d", "30d", "10d", "5d"]
    return ["60d", "30d", "10d"]


def get_ohlcv_with_meta():
    market = {}
    meta = {}
    # One primary request per source/timeframe, then at most one short-period
    # retry. This dramatically reduces Yahoo rate-limit failures.
    primary_period = {"15m": "60d", "5m": "60d", "1m": "7d"}
    retry_period = {"15m": "30d", "5m": "30d", "1m": "3d"}
    for tf, cfg in TIMEFRAMES.items():
        found = pd.DataFrame()
        source = None
        attempts = []
        for symbol in [SYMBOL_SPOT, SYMBOL_FUTURES]:
            for period in [primary_period[tf], retry_period[tf]]:
                attempts.append(f"{symbol}:{period}")
                df = _download(symbol, cfg["interval"], period)
                if not df.empty and len(df) >= 30:
                    found = df
                    source = symbol
                    break
            if not found.empty:
                break
        market[tf] = found
        meta[tf] = {
            "source": source, "bars": int(len(found)), "attempts": attempts,
            "is_proxy": source == SYMBOL_FUTURES, "available": not found.empty,
            "requested_interval": cfg["interval"],
        }
    return market, meta


def get_ohlcv(symbol=SYMBOL_SPOT):
    market, _ = get_ohlcv_with_meta()
    return market


def _parse_time(value):
    if not value:
        return None
    try:
        ts = pd.to_datetime(value, utc=True)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def google_news(query="gold OR XAUUSD OR Federal Reserve OR CPI OR NFP OR Treasury yields OR US dollar"):
    url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
        out = []
        for e in feed.entries[:60]:
            out.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "published": e.get("published", ""),
                "summary": re.sub(r"<[^>]+>", " ", e.get("summary", "")),
                "source": "Google News",
                "impact": None,
            })
        return out
    except Exception:
        return []


def forex_factory_calendar():
    # Public calendar RSS. We use it as an event-risk feed, not as a trading signal.
    url = "https://www.forexfactory.com/calendar/rss"
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        out = []
        for e in feed.entries[:100]:
            text = " ".join([
                e.get("title", ""), e.get("summary", ""), e.get("description", "")
            ])
            title = e.get("title", "")
            # Forex Factory exposes impact in different fields depending on feed version.
            impact = str(
                e.get("impact", "") or e.get("ff_impact", "") or
                e.get("category", "") or ""
            ).lower()
            if "high" in impact:
                impact = "HIGH"
            elif "medium" in impact or "med" in impact:
                impact = "MEDIUM"
            elif "low" in impact:
                impact = "LOW"
            else:
                impact = None
            out.append({
                "title": title,
                "link": e.get("link", ""),
                "published": e.get("published", ""),
                "summary": re.sub(r"<[^>]+>", " ", text),
                "source": "Forex Factory",
                "impact": impact,
            })
        return out
    except Exception:
        return []


BULL_WORDS = {
    "dovish": 7, "rate cut": 8, "rate cuts": 8, "cut rates": 8,
    "falling yields": 7, "lower yields": 7, "weaker dollar": 7,
    "weak dollar": 7, "dollar falls": 6, "inflation cools": 6,
    "safe haven": 4, "geopolitical tension": 4, "conflict": 3,
    "war": 3, "central bank buying": 5, "gold demand": 5,
}
BEAR_WORDS = {
    "hawkish": 7, "rate hike": 8, "rate hikes": 8, "hike rates": 8,
    "rising yields": 7, "higher yields": 7, "strong dollar": 7,
    "stronger dollar": 7, "dollar rises": 6, "hot inflation": 7,
    "inflation rises": 6,
}
HIGH_IMPACT_TERMS = [
    "fomc", "fed rate", "interest rate decision", "cpi", "core cpi",
    "pce", "core pce", "nonfarm payroll", "nfp", "payrolls",
    "unemployment rate", "powell", "fed chair", "fed minutes",
    "ism manufacturing", "ism services", "ppi", "retail sales",
]
GOLD_DIRECT = ["gold", "xau", "bullion"]
USD_INDIRECT = ["dxy", "dollar", "usd", "treasury yield", "treasury yields", "10-year yield", "bond yields"]
MACRO_INDIRECT = ["cpi", "pce", "inflation", "nfp", "payroll", "employment", "unemployment", "retail sales", "gdp", "fed", "fomc", "interest rate", "rates"]


def _numbers(text):
    vals = []
    for s in re.findall(r"[-+]?\d+(?:\.\d+)?%?", text):
        try:
            vals.append(float(s.replace("%", "")))
        except Exception:
            pass
    return vals


def _surprise_direction(text):
    """Return gold direction from common actual-vs-forecast macro surprise wording."""
    t = text.lower()
    nums = _numbers(t)
    if len(nums) < 2:
        return 0.0
    actual, forecast = nums[0], nums[1]
    if "unemployment" in t:
        # Higher unemployment generally weakens USD/yields -> supportive for gold.
        return 6.0 if actual > forecast else -6.0 if actual < forecast else 0.0
    if any(k in t for k in ["cpi", "pce", "inflation", "ppi", "payroll", "nfp", "employment", "retail sales", "gdp"]):
        # Stronger-than-expected US growth/inflation/jobs often supports USD/yields -> bearish gold.
        return -6.0 if actual > forecast else 6.0 if actual < forecast else 0.0
    return 0.0


def news_snapshot():
    now = datetime.now(timezone.utc)
    items = google_news()
    calendar = forex_factory_calendar()
    direction = 0.0
    risk = 0.0
    direct = 0.0
    indirect = 0.0
    high_impact = 0
    events = []
    headlines = []

    # Calendar items: prioritize USD events because of their direct macro transmission to gold.
    for item in calendar:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        if not any(k in text for k in ["usd", "dollar", "fomc", "fed", "cpi", "pce", "nfp", "payroll", "unemployment", "ppi", "retail sales", "gdp", "powell"]):
            continue
        ts = _parse_time(item.get("published"))
        age_min = abs((now - ts).total_seconds()) / 60 if ts else 99999
        is_high = item.get("impact") == "HIGH" or any(k in text for k in HIGH_IMPACT_TERMS)
        if is_high:
            high_impact += 1
            if age_min <= HIGH_IMPACT_WINDOW_MIN:
                risk += 45
            elif age_min <= ELEVATED_IMPACT_WINDOW_MIN:
                risk += 25
            else:
                risk += 8
        d = _surprise_direction(text)
        if d:
            direction += d
        if "usd" in text or "dollar" in text or any(k in text for k in MACRO_INDIRECT):
            indirect += d
        events.append({
            "title": item.get("title", ""),
            "impact": item.get("impact") or ("HIGH" if is_high else "MEDIUM"),
            "published": item.get("published", ""),
            "delta": round(d, 1),
            "source": item.get("source", ""),
        })

    # News headlines: score direction, relevance and freshness.
    for item in items:
        text = re.sub(r"<[^>]+>", " ", (item.get("title", "") + " " + item.get("summary", ""))).lower()
        ts = _parse_time(item.get("published"))
        if ts:
            age_h = max(0.0, (now - ts).total_seconds() / 3600)
            if age_h > NEWS_MAX_AGE_HOURS:
                continue
            freshness = max(0.25, 1.0 - age_h / NEWS_MAX_AGE_HOURS)
        else:
            freshness = 0.5

        d = 0.0
        for k, v in BULL_WORDS.items():
            if k in text: d += v
        for k, v in BEAR_WORDS.items():
            if k in text: d -= v

        rel_direct = any(k in text for k in GOLD_DIRECT)
        rel_indirect = any(k in text for k in USD_INDIRECT + MACRO_INDIRECT)
        if rel_direct:
            d *= 1.20
            direct += d * freshness
        elif rel_indirect:
            d *= 0.85
            indirect += d * freshness
        else:
            continue

        surprise = _surprise_direction(text)
        d += surprise
        direction += d * freshness
        headlines.append({
            "title": item.get("title", ""),
            "published": item.get("published", ""),
            "delta": round(d * freshness, 1),
            "relevance": "DIRECT" if rel_direct else "INDIRECT",
            "source": item.get("source", ""),
            "link": item.get("link", ""),
        })

    direction = float(max(-100, min(100, direction)))
    risk = float(max(0, min(100, risk)))
    # Direction is separate from risk. A high-risk event does NOT automatically become bullish/bearish.
    return {
        "direction_score": round(direction, 1),
        "risk_score": round(risk, 1),
        "high_impact_count": high_impact,
        "direct_score": round(direct, 1),
        "indirect_score": round(indirect, 1),
        "events": events[:25],
        "headlines": sorted(headlines, key=lambda x: abs(x["delta"]), reverse=True)[:30],
    }


def news_score(items):
    # Backwards-compatible helper for older imports.
    snap = news_snapshot()
    return snap["direction_score"], snap["headlines"]
