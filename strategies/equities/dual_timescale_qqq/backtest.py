"""
Dual-Timescale QQQ (DTQ) — backtest engine.

The idea: trend-following and dip-buying profit from opposite market
behaviours — continuation vs overreaction — so running both on the same
instrument produces two nearly uncorrelated return streams (measured daily
correlation ≈ 0.37) without needing a second asset class.

Sleeve 1 — Trend (slow, holds for months)
  Long QQQ while it closes above its 200-day SMA, sized to a 15% annualised
  vol target using 20-day realised vol. In T-bills otherwise. This is
  classic time-series momentum (Moskowitz-Ooi-Pedersen 2012) applied to a
  single index.

Sleeve 2 — Mean reversion (fast, holds for days)
  IBS = (close - low) / (high - low) measures where the day closed within
  its own range. IBS < 0.10 — a close pinned to the bottom of the day's
  range — marks short-term panic. When that happens *inside an uptrend*
  (price > 200-day SMA), the sleeve buys the close and exits when
  IBS > 0.75 or after 3 days. The trend filter is what separates a dip
  from a downtrend: the same signal without it loses money in 2022.

Execution discipline (no lookahead): every signal is computed from data up
to and including today's close, the position is taken at that close, and it
earns from tomorrow's close-to-close return onward. Costs: 10 bps per unit
of turnover on the combined weight.
"""

import numpy as np
import pandas as pd


def compute_trend_weights(
    bars: pd.DataFrame,
    sma_window: int,
    target_vol: float,
    vol_lookback: int,
    max_size: float,
) -> pd.Series:
    """Daily target QQQ weight for the trend sleeve (unshifted — as of that close)."""
    px  = bars["close"]
    ret = px.pct_change()

    in_trend = (px > px.rolling(sma_window).mean()).astype(float)
    realized = ret.rolling(vol_lookback).std() * np.sqrt(252)
    size     = (target_vol / realized).clip(upper=max_size)

    return (in_trend * size).fillna(0.0)


def compute_mr_weights(
    bars: pd.DataFrame,
    entry_ibs: float,
    exit_ibs: float,
    max_hold: int,
    sma_window: int,
    target_vol: float,
    vol_lookback: int,
    max_size: float,
) -> tuple:
    """
    Daily target QQQ weight for the mean-reversion sleeve (unshifted), plus a
    trade log (entry date, exit date, days held, trade return) for reporting.
    """
    px, hi, lo = bars["close"], bars["high"], bars["low"]
    ret = px.pct_change()

    ibs      = ((px - lo) / (hi - lo).replace(0, np.nan))
    sma      = px.rolling(sma_window).mean()
    realized = ret.rolling(vol_lookback).std() * np.sqrt(252)
    size     = (target_vol / realized).clip(upper=max_size)

    weights = pd.Series(0.0, index=px.index)
    trades  = []
    holding = 0            # days held so far (0 = flat)
    entry_i = None

    for i in range(sma_window, len(px)):
        if holding > 0:
            if ibs.iloc[i] > exit_ibs or holding >= max_hold:
                # exit at today's close (position last earned today's return)
                trade_ret = px.iloc[i] / px.iloc[entry_i] - 1
                trades.append({
                    "entry":     px.index[entry_i],
                    "exit":      px.index[i],
                    "days_held": holding,
                    "return":    trade_ret,
                })
                holding = 0
            else:
                holding += 1
                weights.iloc[i] = weights.iloc[i - 1]
                continue

        # entry check (also allows immediate re-entry on the exit day)
        if ibs.iloc[i] < entry_ibs and px.iloc[i] > sma.iloc[i]:
            holding = 1
            entry_i = i
            weights.iloc[i] = size.iloc[i] if np.isfinite(size.iloc[i]) else 0.0

    return weights, pd.DataFrame(trades)


def run_dtq_backtest(
    bars: pd.DataFrame,
    tbill_daily_rate: pd.Series,
    initial_capital: float,
    trend_weight: float,
    mr_weight: float,
    sma_window: int,
    trend_target_vol: float,
    trend_max_size: float,
    mr_entry_ibs: float,
    mr_exit_ibs: float,
    mr_max_hold: int,
    mr_target_vol: float,
    mr_max_size: float,
    vol_lookback: int,
    transaction_cost: float,
) -> tuple:
    """
    Returns (portfolio DataFrame, trade log DataFrame).

    Both sleeves trade the same instrument, so the portfolio holds a single
    combined QQQ weight; uninvested capital earns the T-bill (BIL) rate.
    """
    px    = bars["close"]
    ret   = px.pct_change()
    tbill = tbill_daily_rate.reindex(px.index).ffill().fillna(0.0)

    w_trend = compute_trend_weights(
        bars, sma_window, trend_target_vol, vol_lookback, trend_max_size)
    w_mr, trade_log = compute_mr_weights(
        bars, mr_entry_ibs, mr_exit_ibs, mr_max_hold,
        sma_window, mr_target_vol, vol_lookback, mr_max_size)

    # Weight decided at close t is held over the t → t+1 return
    w_trend_held = (trend_weight * w_trend).shift(1).fillna(0.0)
    w_mr_held    = (mr_weight * w_mr).shift(1).fillna(0.0)
    w_held       = w_trend_held + w_mr_held

    # Skip SMA warm-up so the backtest starts with a live signal
    start_day = px.index[sma_window + 1]

    portfolio_value = initial_capital
    prev_w          = 0.0
    records         = []

    for date in px.index:
        if date < start_day:
            continue
        day_ret = ret.get(date)
        if pd.isna(day_ret):
            continue

        w      = w_held.get(date, 0.0)
        cash_w = 1.0 - w   # negative when both sleeves are fully deployed
                           # (w up to 1.25) → pays the T-bill rate on the
                           # borrowed fraction rather than taking free leverage

        turnover  = abs(w - prev_w)
        tc        = turnover * transaction_cost * portfolio_value
        gross_pnl = (w * day_ret + cash_w * tbill.get(date, 0.0)) * portfolio_value
        net_pnl   = gross_pnl - tc

        # Attribution: each sleeve's share of the day's market P&L
        trend_pnl = w_trend_held.get(date, 0.0) * day_ret * portfolio_value
        mr_pnl    = w_mr_held.get(date, 0.0) * day_ret * portfolio_value

        portfolio_value += net_pnl

        records.append({
            "date":             date,
            "net_pnl":          net_pnl,
            "transaction_cost": tc,
            "portfolio_value":  portfolio_value,
            "weight_trend":     w_trend_held.get(date, 0.0),
            "weight_mr":        w_mr_held.get(date, 0.0),
            "invested_weight":  w,
            "cash_weight":      cash_w,
            "trend_pnl":        trend_pnl,
            "mr_pnl":           mr_pnl,
            "in_regime":        bool(w > 0.01),
        })
        prev_w = w

    df = pd.DataFrame(records).set_index("date")
    dr = df["net_pnl"] / df["portfolio_value"].shift(1)
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df, trade_log
