"""
Adaptive Factor Portfolio — strategy-specific parameters.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# ── Universe: equity factor ETFs ──────────────────────────────
TICKERS = {
    "QQQ":  "Invesco Nasdaq-100 ETF (Growth / Tech)",
    "QUAL": "iShares MSCI USA Quality Factor ETF",
    "MTUM": "iShares MSCI USA Momentum Factor ETF",
    "USMV": "iShares MSCI USA Min Vol Factor ETF",
}

# ── Signal ────────────────────────────────────────────────────
LOOKBACK_MONTHS      = [1, 3, 6, 12]   # composite momentum vote windows
RANK_TILT            = 1.5             # top-ranked factor gets this weight multiplier

# ── Correlation regime filter ─────────────────────────────────
# Measures QQQ vs USMV rolling correlation as a diversification health signal.
# When growth and defensive factors move together, equity diversification has
# collapsed → reduce risk exposure.
CORR_WINDOW          = 20     # days for rolling correlation
CORR_HIGH            = 0.75   # above this → scale × 0.4  (crisis)
CORR_MID             = 0.60   # between mid and high → scale × 0.7 (caution)
                               # below mid → scale × 1.0  (healthy)

# ── Sizing ────────────────────────────────────────────────────
TARGET_VOL           = 0.15   # 15% — primary equity portfolio, more aggressive
MAX_WEIGHT           = 0.50   # 50% cap per factor (only 4 assets)
MAX_LEVERAGE         = 1.5
VOL_LOOKBACK         = 20
DRAWDOWN_STOP        = 0.12
TRANSACTION_COST     = 0.001
