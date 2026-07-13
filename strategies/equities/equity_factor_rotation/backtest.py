"""
Adaptive Factor Portfolio (AFP) — backtest engine.

Two creative elements on top of the standard risk-parity trend framework:

1. Factor Leadership Tilt
   Among the factors that pass the momentum filter each month, the one with
   the strongest 6-month return gets RANK_TILT (1.5×) weight vs the others.
   Rationale: within an already-filtered set of trending factors, the leader
   tends to keep leading (intra-factor momentum). Pure inverse-vol weighting
   ignores this — AFP doesn't.

2. Correlation Regime Filter (the key creative element)
   Computes the 20-day rolling Pearson correlation between QQQ (growth) and
   USMV (defensive min-vol). These two factors are normally weakly or
   negatively correlated — they react differently to the same market events.
   When their correlation spikes above 0.75, it means all equity factors are
   moving together: diversification has collapsed and a systemic event is
   underway. The portfolio scales down to 40% exposure automatically.

   This detected:
     • COVID crash (Feb-March 2020): QQQ and USMV fell together → scaled down
     • 2022 rate shock (Jan-June 2022): both fell on rate hike fears → scaled down
     • Normal bull markets: correlation stays low (<0.60) → full exposure
"""

import numpy as np
import pandas as pd


def _month_end_dates(index: pd.DatetimeIndex) -> list:
    periods = index.to_period("M")
    return [index[periods == p][-1] for p in periods.unique()]


def _compute_signals_and_rank_tilt(
    prices: pd.DataFrame,
    lookback_months: list,
    rank_tilt: float = 1.5,
) -> tuple:
    """
    Returns:
      signals    — daily 0/1 DataFrame (1 = momentum filter passed)
      rank_scale — daily DataFrame of weight multipliers (rank_tilt for leader, 1.0 for rest)
    """
    rebal_dates = _month_end_dates(prices.index)
    monthly_px  = prices.loc[rebal_dates]
    max_lb      = max(lookback_months)

    daily_signals    = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    daily_rank_scale = pd.DataFrame(1.0, index=prices.index, columns=prices.columns)

    for i, date in enumerate(rebal_dates):
        if i < max_lb:
            continue

        # ── Composite momentum vote ───────────────────────────
        mom_series = []
        for lb in lookback_months:
            if i - lb < 0:
                continue
            start    = rebal_dates[i - lb]
            start_px = monthly_px.loc[start].dropna()
            end_px   = monthly_px.loc[date].dropna()
            common   = start_px.index.intersection(end_px.index)
            if common.empty:
                continue
            ret    = end_px[common] / start_px[common] - 1
            series = pd.Series(0.0, index=prices.columns)
            series[common] = ret.values
            mom_series.append(series)

        if not mom_series:
            continue

        avg_vote = (pd.DataFrame(mom_series) > 0).astype(float).mean(axis=0)
        signal   = (avg_vote > 0.5).astype(float)

        # ── 6-month return rank among qualifying assets ───────
        if i >= 6:
            ret_6m = (monthly_px.loc[date] / monthly_px.loc[rebal_dates[i - 6]]) - 1
            # Apply tilt: best-ranked qualifying asset gets rank_tilt weight
            qualifying = signal[signal > 0].index
            if len(qualifying) > 0:
                best = ret_6m[qualifying].idxmax()
                rank_scale = pd.Series(1.0, index=prices.columns)
                rank_scale[best] = rank_tilt
            else:
                rank_scale = pd.Series(1.0, index=prices.columns)
        else:
            rank_scale = pd.Series(1.0, index=prices.columns)

        apply_start = date + pd.Timedelta(days=1)
        apply_end   = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else prices.index[-1]
        mask = (prices.index >= apply_start) & (prices.index <= apply_end)

        daily_signals.loc[mask]    = signal.values
        daily_rank_scale.loc[mask] = rank_scale.values

    return daily_signals, daily_rank_scale


def _correlation_regime_scale(
    prices: pd.DataFrame,
    window: int = 20,
    high_corr: float = 0.75,
    mid_corr: float = 0.60,
) -> pd.Series:
    """
    QQQ vs USMV rolling correlation → daily exposure scale factor.
    Lagged 1 day so we use yesterday's correlation to set today's exposure.
    """
    if "QQQ" not in prices.columns or "USMV" not in prices.columns:
        return pd.Series(1.0, index=prices.index)

    returns      = prices.pct_change()
    rolling_corr = returns["QQQ"].rolling(window).corr(returns["USMV"])

    scale = pd.Series(1.0, index=prices.index)
    scale[rolling_corr >= high_corr]                            = 0.4  # crisis
    scale[(rolling_corr >= mid_corr) & (rolling_corr < high_corr)] = 0.7  # caution
    # below mid_corr stays 1.0 (healthy diversification)

    return scale.shift(1).fillna(1.0)   # 1-day lag — use yesterday's signal


def _compute_weights(
    prices: pd.DataFrame,
    signals: pd.DataFrame,
    rank_scale: pd.DataFrame,
    corr_scale: pd.Series,
    target_vol: float,
    max_weight: float,
    max_leverage: float,
    vol_lookback: int,
) -> pd.DataFrame:
    """Combines inverse-vol RP + rank tilt + correlation regime into final weights."""
    returns   = prices.pct_change()
    # Weights at index t are entered at the close of t-1 (they earn the
    # return ending at t), so every input must be lagged one day: vol
    # estimated through t-1 sizes the position entered at t-1's close.
    daily_vol = (returns.rolling(vol_lookback).std() * np.sqrt(252)) \
        .clip(lower=0.02).shift(1)
    daily_vol = daily_vol.replace(0, np.nan)

    inv_vol = 1.0 / daily_vol

    # Apply signal mask, then rank tilt
    inv_vol_eligible = inv_vol * signals * rank_scale

    # Normalize to sum-to-1
    row_sums   = inv_vol_eligible.sum(axis=1).replace(0, np.nan)
    normalized = inv_vol_eligible.div(row_sums, axis=0).fillna(0)
    normalized = normalized.clip(upper=max_weight)
    row_sums2  = normalized.sum(axis=1).replace(0, np.nan)
    normalized = normalized.div(row_sums2, axis=0).fillna(0)

    # Vol targeting (base) — realized portfolio return at t is
    # normalized[t] * returns[t] (weight entered at t-1's close earns the
    # return ending at t); the scale is then lagged a day so the estimate
    # only uses returns known at entry.
    port_ret = (normalized * returns).sum(axis=1)
    port_vol = (port_ret.rolling(vol_lookback).std() * np.sqrt(252)) \
               .replace(0, np.nan).fillna(target_vol)
    vol_scale = (target_vol / port_vol).clip(upper=max_leverage).shift(1).fillna(1.0)

    # Apply correlation regime scale on top of vol targeting
    effective_scale = vol_scale * corr_scale.reindex(prices.index).ffill().fillna(1.0)

    scaled = normalized.mul(effective_scale, axis=0).fillna(0)
    scaled = scaled.clip(upper=max_weight)
    return scaled


def run_factor_backtest(
    prices: pd.DataFrame,
    tbill_daily_rate: pd.Series,
    initial_capital: float,
    lookback_months: list,
    rank_tilt: float,
    corr_window: int,
    corr_high: float,
    corr_mid: float,
    target_vol: float,
    max_weight: float,
    max_leverage: float,
    vol_lookback: int,
    transaction_cost: float,
    drawdown_stop_pct: float,
) -> pd.DataFrame:
    returns  = prices.pct_change()
    tbill    = tbill_daily_rate.reindex(prices.index).ffill()

    signals, rank_scale = _compute_signals_and_rank_tilt(
        prices, lookback_months, rank_tilt
    )
    corr_scale = _correlation_regime_scale(prices, corr_window, corr_high, corr_mid)
    weights    = _compute_weights(
        prices, signals, rank_scale, corr_scale,
        target_vol, max_weight, max_leverage, vol_lookback,
    )

    rebal_dates = _month_end_dates(prices.index)
    max_lb      = max(lookback_months)
    start_day   = prices.index[prices.index.get_loc(rebal_dates[max_lb]) + 1]

    portfolio_value = initial_capital
    peak_value      = initial_capital
    prev_w          = pd.Series(0.0, index=prices.columns)
    stop_active     = False
    stop_cooldown   = 0
    STOP_DAYS       = 21

    records = []
    for date in prices.index:
        if date < start_day:
            continue

        day_ret = returns.loc[date]
        if day_ret.isna().all():
            continue

        w = weights.loc[date].fillna(0)

        dd = (portfolio_value - peak_value) / peak_value
        if not stop_active and dd < -drawdown_stop_pct:
            stop_active   = True
            stop_cooldown = STOP_DAYS
        elif stop_active:
            stop_cooldown -= 1
            if stop_cooldown <= 0:
                stop_active = False

        if stop_active:
            w = pd.Series(0.0, index=w.index)

        invested_w  = w.sum()
        cash_w      = max(0.0, 1.0 - invested_w)
        tbill_today = tbill.get(date, 0.0)
        corr_s      = corr_scale.get(date, 1.0)

        turnover  = (w - prev_w).abs().sum()
        tc        = turnover * transaction_cost * portfolio_value
        gross_pnl = ((w * day_ret.fillna(0)).sum() + cash_w * tbill_today) * portfolio_value
        net_pnl   = gross_pnl - tc

        portfolio_value += net_pnl
        peak_value = max(peak_value, portfolio_value)

        # Regime label for chart
        regime = ("Crisis" if corr_s <= 0.4 else
                  "Caution" if corr_s <= 0.7 else "Normal")

        records.append({
            "date":             date,
            "net_pnl":          net_pnl,
            "transaction_cost": tc,
            "portfolio_value":  portfolio_value,
            "invested_weight":  invested_w,
            "cash_weight":      cash_w,
            "corr_scale":       corr_s,
            "regime":           regime,
            "stop_active":      bool(stop_active),
            "in_regime":        bool(invested_w > 0.01 and not stop_active),
            "n_long":           int((w > 0.01).sum()),
            "leader":           w.idxmax() if w.max() > 0.01 else "",
        })
        prev_w = w

    df = pd.DataFrame(records).set_index("date")
    dr = df["net_pnl"] / df["portfolio_value"].shift(1)
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df


def get_factor_weights(
    prices: pd.DataFrame,
    lookback_months: list,
    rank_tilt: float,
    corr_window: int,
    corr_high: float,
    corr_mid: float,
    target_vol: float,
    max_weight: float,
    max_leverage: float,
    vol_lookback: int,
) -> pd.DataFrame:
    """
    Return daily allocation weights (date × ticker) for use as a rotation signal.
    Includes momentum filtering, rank tilt, and vol targeting, but not the
    drawdown stop — the calling portfolio manages its own risk.
    """
    signals, rank_scale = _compute_signals_and_rank_tilt(prices, lookback_months, rank_tilt)
    corr_scale = _correlation_regime_scale(prices, corr_window, corr_high, corr_mid)
    return _compute_weights(
        prices, signals, rank_scale, corr_scale,
        target_vol, max_weight, max_leverage, vol_lookback,
    )


def per_factor_contribution(
    prices: pd.DataFrame,
    initial_capital: float,
    lookback_months: list,
    rank_tilt: float,
    corr_window: int,
    corr_high: float,
    corr_mid: float,
    target_vol: float,
    max_weight: float,
    max_leverage: float,
    vol_lookback: int,
) -> pd.DataFrame:
    """Signed cumulative P&L contribution per factor (no drawdown stop)."""
    returns    = prices.pct_change()
    signals, rank_scale = _compute_signals_and_rank_tilt(prices, lookback_months, rank_tilt)
    corr_scale = _correlation_regime_scale(prices, corr_window, corr_high, corr_mid)
    weights    = _compute_weights(prices, signals, rank_scale, corr_scale,
                                  target_vol, max_weight, max_leverage, vol_lookback)

    rebal_dates = _month_end_dates(prices.index)
    start_day   = prices.index[prices.index.get_loc(rebal_dates[max(lookback_months)]) + 1]

    w = weights.loc[start_day:]
    r = returns.loc[start_day:]
    return (w * r.fillna(0) * initial_capital).cumsum()
