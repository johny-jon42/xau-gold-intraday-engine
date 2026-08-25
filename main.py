from __future__ import annotations
import argparse, time, json, os
from datetime import datetime, timezone

from config import SYMBOL
from data import get_ohlcv, google_news, news_score
from engine import analyze_timeframe, score_setup

JOURNAL = "signals.csv"

def run_once():
    market = get_ohlcv(SYMBOL)
    analyses = {tf: analyze_timeframe(df) for tf, df in market.items()}

    news = google_news()
    nscore, news_details = news_score(news)

    result = score_setup(
        analyses["15m"], analyses["5m"], analyses["1m"],
        news_score=nscore
    )

    now = datetime.now(timezone.utc).isoformat()
    price = None
    if not market["1m"].empty:
        price = float(market["1m"]["close"].iloc[-1])

    row = {
        "timestamp_utc": now,
        "price": price,
        "signal": result["signal"],
        "confidence": result["confidence"],
        "long_score": result["long_score"],
        "short_score": result["short_score"],
        "news_score": nscore,
        "15m_bias": analyses["15m"]["structure"]["bias"],
        "5m_bos": analyses["5m"]["structure"]["bos"],
        "5m_choch": analyses["5m"]["structure"]["choch"],
        "1m_bos": analyses["1m"]["structure"]["bos"],
        "1m_choch": analyses["1m"]["structure"]["choch"],
        "15m_sweep": analyses["15m"]["sweep"]["type"] if analyses["15m"]["sweep"] else "",
        "5m_sweep": analyses["5m"]["sweep"]["type"] if analyses["5m"]["sweep"] else "",
        "1m_sweep": analyses["1m"]["sweep"]["type"] if analyses["1m"]["sweep"] else "",
        "long_reasons": " | ".join(result["long_reasons"]),
        "short_reasons": " | ".join(result["short_reasons"]),
    }

    import pandas as pd
    pd.DataFrame([row]).to_csv(
        JOURNAL, mode="a", header=not os.path.exists(JOURNAL), index=False
    )

    print(json.dumps({
        "time_utc": now,
        "price": price,
        "signal": result["signal"],
        "confidence": result["confidence"],
        "long_score": result["long_score"],
        "short_score": result["short_score"],
        "news_score": nscore,
        "15m": analyses["15m"]["structure"],
        "5m": analyses["5m"]["structure"],
        "1m": analyses["1m"]["structure"],
        "long_reasons": result["long_reasons"],
        "short_reasons": result["short_reasons"],
    }, indent=2, default=str))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", type=int, default=0)
    args = p.parse_args()

    if args.loop:
        while True:
            try:
                run_once()
            except Exception as e:
                print("SCAN ERROR:", repr(e))
            time.sleep(args.loop)
    else:
        run_once()
