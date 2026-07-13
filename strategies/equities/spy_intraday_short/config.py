"""
SPY Intraday Afternoon Short — strategy-specific parameters.
Shared params (dates, capital, paths) come from the root config.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# Alpaca 5-minute intraday bars are only available from 2020 onwards.
START_DATE = "2020-01-01"

SYMBOL            = "SPY"
MIN_MORNING_MOVE  = 0.0020   # |09:30-10:00 ret| ≥ this to qualify
MIN_OVERNIGHT_GAP = 0.0010   # |overnight gap|   ≥ this to qualify
TC                = 0.0001   # 1 bp per side
DD_STOP           = 0.08     # 8% drawdown → pause 21 days
