# XAU/USD engine configuration

SYMBOL = "XAUUSD=X"

TIMEFRAMES = {
    "15m": {"period": "60d", "interval": "15m"},
    "5m": {"period": "60d", "interval": "5m"},
    "1m": {"period": "7d", "interval": "1m"},
}

SWING_LEFT = 2
SWING_RIGHT = 2

ATR_PERIOD = 14

# Structure confirmation
MIN_BREAK_ATR = 0.10
MIN_DISPLACEMENT_BODY = 0.50
DISPLACEMENT_ATR = 0.80

# Liquidity
EQUAL_LEVEL_ATR = 0.10
SWEEP_MIN_ATR = 0.03

# FVG
MIN_FVG_ATR = 0.05

# Signal thresholds
A_PLUS = 85
VALID = 75
WATCH = 65

# News
NEWS_DECAY_MINUTES = 240
HIGH_IMPACT_BLOCK_MINUTES = 10

# Session times are UTC. Adjust if desired.
SESSIONS = {
    "Asia": ("00:00", "08:00"),
    "London": ("07:00", "16:00"),
    "New York": ("13:00", "22:00"),
}
