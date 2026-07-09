"""
BTREND — Broad Cross-Asset Trend — backtest engine.

Per-asset time-series momentum (Moskowitz-Ooi-Pedersen 2012) on a broad
ETF universe:

  Signal   — blended 3/6/12-month momentum per asset, evaluated at each
             month-end close. LONG assets in uptrends, SHORT assets in
             downtrends (or flat, in long-only mode). Each asset is judged
             on its own trend, not ranked against the others.
  Sizing   — sign(momentum) × inverse 60-day vol, normalised so gross
             exposure = 1, each asset capped at ±MAX_WEIGHT. Capped excess
             stays in cash rather than being redistributed.
  Overlay  — portfolio-level vol target (daily scale, capped at 1x,
             lagged one day so it only uses returns known at entry).

The long/short mode is the point of the strategy: the crisis convexity of
managed futures comes from the shorts (2022: short bonds while equities
and bonds fell together). The long-only variant was tested and is strictly
dominated by T-bills as a portfolio diversifier — see the README research
log. Shorting costs are approximated by the turnover cost only; ETF borrow
fees for these liquid tickers (~25-50 bps/yr on the shorted fraction) are
not modelled and would trim the sleeve's return slightly.

Timing convention (repo-wide): weights.loc[t] is the position entered at
the close of t-1 and earns the return ending at t. Month-end decisions at
close D populate rows (D, next month-end] — so they enter at D's close.
Every sizing input at row t uses data through t-1. Capital not consumed by
net exposure earns the T-bill (BIL) rate; costs are TRANSACTION_COST per
unit turnover.
"""

import numpy as np
import pandas as pd


def _month_end_dates(index: pd.DatetimeIndex) -> list:
    periods = index.to_period("M")
    return [index[periods == p][-1] for p in periods.unique()]


def compute_trend_weights(
    closes: pd.DataFrame,
    lookback_days: list,
    asset_vol_lookback: int,
    max_weight: float,
    target_vol: float,
    vol_lookback: int,
    max_leverage: float,
    long_short: bool = True,
) -> pd.DataFrame:
    """Daily target weights (unshifted: row t = position entered at t-1's close)."""
    rets = closes.pct_change()
    mom  = sum(closes.pct_change(lb) for lb in lookback_days) / len(lookback_days)
    avol = (rets.rolling(asset_vol_lookback).std() * np.sqrt(252)).clip(lower=0.02)

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    rebal   = _month_end_dates(closes.index)

    for i, date in enumerate(rebal[:-1]):
        m = mom.loc[date].dropna()
        if not long_short:
            m = m[m > 0]                      # long-only: flat in downtrends
        if m.empty:
            continue                          # no signal → sleeve in cash
        raw = (np.sign(m) / avol.loc[date, m.index]) \
            .replace([np.inf, -np.inf], np.nan).dropna()
        if raw.empty:
            continue
        w = (raw / raw.abs().sum()).clip(-max_weight, max_weight)  # gross=1, capped
        mask = (closes.index > date) & (closes.index <= rebal[i + 1])
        weights.loc[mask, w.index] = w.values

    # Portfolio-level vol target. Realized sleeve return at t is
    # weights[t] * rets[t]; the scale is lagged one day so row t only uses
    # returns known at its entry (t-1's close).
    port_ret = (weights * rets).sum(axis=1)
    realized = port_ret.rolling(vol_lookback).std() * np.sqrt(252)
    scale = (target_vol / realized.replace(0, np.nan)) \
        .clip(upper=max_leverage).shift(1).fillna(1.0)
    return weights.mul(scale, axis=0)


def run_trend_backtest(
    prices: pd.DataFrame,
    tbill_daily_rate: pd.Series,
    initial_capital: float,
    cfg,                          # the strategies.broad_trend.config module
) -> pd.DataFrame:
    returns = prices.pct_change()
    tbill   = tbill_daily_rate.reindex(prices.index).ffill().fillna(0.0)

    weights = compute_trend_weights(
        prices, cfg.LOOKBACK_DAYS, cfg.ASSET_VOL_LOOKBACK, cfg.MAX_WEIGHT,
        cfg.TARGET_VOL, cfg.VOL_LOOKBACK, cfg.MAX_LEVERAGE,
        long_short=getattr(cfg, "LONG_SHORT", True),
    )

    # Warmup: hold cash until the first month-end with a full 12m signal,
    # matching GARP's approach so the portfolio covers the full date range.
    rebal      = _month_end_dates(prices.index)
    warmup     = 13                              # 12m lookback + buffer
    start_day  = None
    for d in rebal[warmup:]:
        future = prices.index[prices.index > d]
        if not future.empty and weights.loc[future[0]].sum() > 0:
            start_day = future[0]
            break
    if start_day is None:
        start_day = prices.index[min(warmup * 21, len(prices.index) - 1)]

    portfolio_value = initial_capital
    prev_w          = pd.Series(0.0, index=prices.columns)
    records         = []

    for date in prices.index:
        if date < start_day:
            tbill_today = tbill.get(date, 0.0)
            net_pnl     = tbill_today * portfolio_value
            portfolio_value += net_pnl
            records.append({
                "date": date, "net_pnl": net_pnl, "transaction_cost": 0.0,
                "portfolio_value": portfolio_value, "invested_weight": 0.0,
                "net_weight": 0.0, "cash_weight": 1.0, "n_long": 0,
                "n_short": 0, "in_regime": False, "holdings": "", "shorts": "",
            })
            continue

        day_ret = returns.loc[date]
        if day_ret.isna().all():
            continue

        w = weights.loc[date].fillna(0.0)
        gross_w     = w.abs().sum()
        net_w       = w.sum()
        cash_w      = max(0.0, 1.0 - net_w)   # capital not consumed by net exposure
        tbill_today = tbill.get(date, 0.0)

        turnover  = (w - prev_w).abs().sum()
        tc        = turnover * cfg.TRANSACTION_COST * portfolio_value
        gross_pnl = ((w * day_ret.fillna(0)).sum() + cash_w * tbill_today) * portfolio_value
        net_pnl   = gross_pnl - tc
        portfolio_value += net_pnl

        longs  = [t for t in prices.columns if w.get(t, 0) > 0.01]
        shorts = [t for t in prices.columns if w.get(t, 0) < -0.01]
        records.append({
            "date":             date,
            "net_pnl":          net_pnl,
            "transaction_cost": tc,
            "portfolio_value":  portfolio_value,
            "invested_weight":  gross_w,
            "net_weight":       net_w,
            "cash_weight":      cash_w,
            "n_long":           len(longs),
            "n_short":          len(shorts),
            "in_regime":        bool(gross_w > 0.01),
            "holdings":         ",".join(longs),
            "shorts":           ",".join(shorts),
        })
        prev_w = w

    df = pd.DataFrame(records).set_index("date")
    dr = df["net_pnl"] / df["portfolio_value"].shift(1)
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df
