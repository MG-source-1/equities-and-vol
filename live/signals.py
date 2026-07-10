"""
Live target-weight computation for the investor portfolio.

Reuses the SAME weight functions the backtests use — the live target is
"the last row of the backtest run through today", not a reimplementation:

  GARP   — strategies.garp_momentum.backtest._compute_monthly_weights
           + the daily regime/vol-targeting logic from run_garp_backtest
  TRIAD  — strategies.triad.backtest.compute_*_weights (unshifted rows)
  T-bill — BIL absorbs ALL capital the engines leave uninvested (minus a
           small cash buffer), not just the structural 10% sleeve. The
           backtests credit the T-bill rate on every uninvested dollar, so
           the live account must actually hold BIL with it: when the risk
           overlays cut exposure to 40%, ~58% of the account sits in BIL,
           not idle cash. The 10% sleeve is simply the sweep's floor when
           the engines are fully deployed.

Timing convention: every function here answers "what should I hold from
TODAY'S CLOSE onward", i.e. the weight the backtest would apply to
tomorrow's return. For the monthly sleeves this is handled by appending a
synthetic next business day to the price index, so month-end rebalance
decisions made today flow into the final row.
"""

import os
import time

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.alpaca import fetch_bars
from live.config import (
    DATA_YEARS, DATA_CACHE_DIR, EDGAR_REFRESH_DAYS,
    WEIGHT_GARP, WEIGHT_TRIAD, TBILL_TICKER, CASH_BUFFER,
)

from strategies.garp_momentum import config as garp_cfg
from strategies.garp_momentum.backtest import _compute_monthly_weights
from strategies.garp_momentum.fundamentals import build_garp_history

from strategies.triad import config as triad_cfg
from strategies.triad.backtest import (
    compute_leader_weights, compute_stock_dip_weights, compute_index_dip_weights,
)

# SPY is needed for GARP's regime filter; BIL is the T-bill sleeve.
ALL_SYMBOLS = sorted(set(garp_cfg.TICKERS)
                     | {triad_cfg.INDEX_TICKER, "SPY", TBILL_TICKER})


# ── Data ──────────────────────────────────────────────────────

def fetch_live_bars() -> dict:
    """
    Fresh OHLC bars for every symbol (no disk cache — live data).

    The free Alpaca data plan rejects SIP requests covering the most recent
    15 minutes (HTTP 403), so `end` is capped at now − 16 minutes. During a
    15:35 ET rebalance run, today's "close" is therefore the ~15:19 price —
    an acceptable proxy for the auction close the backtest assumes.
    """
    end   = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=16)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (pd.Timestamp.now() - pd.DateOffset(years=DATA_YEARS)).strftime("%Y-%m-%d")
    return {s: fetch_bars(s, start, end, "1Day",
                          cache_dir=DATA_CACHE_DIR, verbose=False, use_cache=False)
            for s in ALL_SYMBOLS}


def _extend_one_day(df: pd.DataFrame) -> pd.DataFrame:
    """Append a synthetic next business day (ffilled) so that month-end
    rebalance decisions made today appear in the final weight row."""
    nxt = df.index[-1] + pd.offsets.BDay(1)
    ext = df.reindex(df.index.append(pd.DatetimeIndex([nxt]))).ffill()
    return ext


def _refresh_edgar_if_stale() -> None:
    """Delete EDGAR caches older than EDGAR_REFRESH_DAYS so new filings
    flow into the GARP score. Backtests keep caches permanent; live can't."""
    cutoff = time.time() - EDGAR_REFRESH_DAYS * 86400
    stale  = False
    for t in garp_cfg.TICKERS:
        p = os.path.join(DATA_CACHE_DIR, f"garp_hist_{t}.pkl")
        if os.path.exists(p) and os.path.getmtime(p) < cutoff:
            stale = True
            break
    if not stale:
        return
    print("[signals] EDGAR caches stale — refreshing fundamentals …")
    for f in os.listdir(DATA_CACHE_DIR):
        if f.startswith("garp_hist_") or f.startswith("edgar_facts_"):
            os.remove(os.path.join(DATA_CACHE_DIR, f))


# ── Sleeve targets (weights within each sleeve, before capital split) ─

def garp_target(bars: dict) -> tuple:
    """GARP sleeve target weights as of today's close + diagnostics."""
    closes = pd.DataFrame({t: bars[t]["close"] for t in garp_cfg.TICKERS}).ffill()
    spy    = bars["SPY"]["close"]

    _refresh_edgar_if_stale()
    garp_hist = build_garp_history(list(closes.columns), closes,
                                   cache_dir=DATA_CACHE_DIR)

    ext = _extend_one_day(closes)
    monthly_weights, regime_scales = _compute_monthly_weights(
        ext, garp_hist, spy,
        garp_cfg.TOP_N, garp_cfg.LOOKBACK_MONTHS, garp_cfg.SKIP_MONTHS,
        garp_cfg.GARP_WEIGHT, garp_cfg.MOM_WEIGHT, garp_cfg.MAX_WEIGHT,
    )

    # Latest rebalance decided on or before today (today counts as a
    # rebalance only if it is genuinely the last trading day of its month,
    # which the synthetic-day extension makes explicit).
    today  = closes.index[-1]
    rebals = [d for d in monthly_weights if d <= today]
    last   = max(rebals)
    base_w = monthly_weights[last] * regime_scales[last]

    # Daily vol targeting, replicated from run_garp_backtest
    returns = closes.pct_change()
    recent  = returns.tail(garp_cfg.VOL_LOOKBACK)
    w = base_w.copy()
    if len(recent) >= 10:
        hist_vol = (base_w * recent.fillna(0)).sum(axis=1).std() * np.sqrt(252)
        if hist_vol > 1e-6:
            scale = min(garp_cfg.TARGET_VOL / hist_vol, garp_cfg.MAX_LEVERAGE)
            w = (base_w * scale).clip(upper=garp_cfg.MAX_WEIGHT)

    diag = {
        "rebalance_date": str(last.date()),
        "regime_scale":   regime_scales[last],
        "holdings":       {t: round(v, 4) for t, v in w.items() if v > 0.001},
    }
    return w, diag


def triad_target(bars: dict) -> tuple:
    """TRIAD sleeve target weights (stocks + QQQ) as of today's close."""
    qqq      = bars[triad_cfg.INDEX_TICKER]
    calendar = qqq.index
    tmt_bars = {t: bars[t] for t in triad_cfg.TICKERS}
    closes   = pd.DataFrame({t: b["close"].reindex(calendar)
                             for t, b in tmt_bars.items()}).ffill()

    # Leader weights are masked from (rebal date + 1] — extend so a month-end
    # decision made today lands in the final row.
    w_lead = compute_leader_weights(
        _extend_one_day(closes), _extend_one_day(qqq[["close"]])["close"],
        triad_cfg.LOOKBACK_DAYS, triad_cfg.TOP_N, triad_cfg.LEADERS_TARGET_VOL,
        triad_cfg.REGIME_FLOOR, triad_cfg.SMA_WINDOW, triad_cfg.VOL_LOOKBACK)

    w_sdip = compute_stock_dip_weights(
        tmt_bars, calendar,
        triad_cfg.DIP_ENTRY_IBS, triad_cfg.DIP_EXIT_IBS, triad_cfg.DIP_MAX_HOLD,
        triad_cfg.SMA_WINDOW, triad_cfg.DIP_MOM_DAYS,
        triad_cfg.DIP_PER_NAME, triad_cfg.DIP_MAX_GROSS)
    w_idip = compute_index_dip_weights(
        qqq,
        triad_cfg.IDX_ENTRY_IBS, triad_cfg.IDX_EXIT_IBS, triad_cfg.IDX_MAX_HOLD,
        triad_cfg.SMA_WINDOW, triad_cfg.IDX_TARGET_VOL, triad_cfg.VOL_LOOKBACK,
        triad_cfg.IDX_MAX_SIZE)

    stocks = (triad_cfg.LEADERS_WEIGHT * w_lead.iloc[-1].reindex(closes.columns).fillna(0)
              + triad_cfg.STOCK_DIP_WEIGHT * w_sdip.iloc[-1])
    w = stocks.copy()
    w[triad_cfg.INDEX_TICKER] = triad_cfg.INDEX_DIP_WEIGHT * w_idip.iloc[-1]

    diag = {
        "leaders":   {t: round(v, 4) for t, v in w_lead.iloc[-1].items() if v > 0.001},
        "stock_dips": {t: round(v, 4) for t, v in w_sdip.iloc[-1].items() if v > 0.001},
        "index_dip": round(float(w_idip.iloc[-1]), 4),
    }
    return w, diag


# ── Combined portfolio target ─────────────────────────────────

def compute_targets() -> dict:
    """
    Returns:
      weights  — {symbol: portfolio weight} (target from today's close)
      prices   — {symbol: latest close} for share-count sizing
      diag     — per-sleeve diagnostics for the decision log
    """
    bars = fetch_live_bars()
    asof = max(df.index[-1] for df in bars.values())

    g_w, g_diag = garp_target(bars)
    t_w, t_diag = triad_target(bars)

    combined = pd.Series(0.0, index=ALL_SYMBOLS)
    combined = combined.add(WEIGHT_GARP * g_w, fill_value=0.0)
    combined = combined.add(WEIGHT_TRIAD * t_w, fill_value=0.0)
    # Cash sweep: everything the engines don't want goes to BIL (T-bills),
    # matching the backtests' T-bill credit on uninvested capital.
    engine_gross = float(combined.sum())
    combined[TBILL_TICKER] = max(0.0, 1.0 - CASH_BUFFER - engine_gross)
    combined = combined[combined.abs() > 1e-6]

    prices = {s: float(bars[s]["close"].iloc[-1]) for s in ALL_SYMBOLS}

    return {
        "as_of":   str(asof.date()),
        "weights": {s: round(float(v), 5) for s, v in combined.items()},
        "prices":  prices,
        "diag": {
            "garp":         g_diag,
            "triad":        t_diag,
            "engine_gross": round(engine_gross, 4),
            "bil_sweep":    round(float(combined.get(TBILL_TICKER, 0.0)), 4),
            "gross":        round(float(combined.sum()), 4),
        },
    }
