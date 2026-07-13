"""
GARP Momentum — backtest engine.

Two-layer signal:
  1. Composite momentum  — 3m / 6m / 12m price returns with a 1-month skip
     (Jegadeesh-Titman 1993).  Stocks must have positive raw momentum to qualify.
  2. GARP fundamental score — static cross-sectional quality ranking fetched from
     yfinance (PEG, ROE, EV/EBITDA, FCF yield, net margin, D/E).

Allocation logic (monthly rebalance):
  composite_rank = MOM_WEIGHT × mom_rank + GARP_WEIGHT × garp_rank
  → Hold top-N stocks with positive absolute momentum.
  → Weight proportional to GARP score within the selected set (higher quality =
    bigger allocation), capped at MAX_WEIGHT per stock.

Risk overlays:
  • SPY regime filter   — scale exposure down when SPY 3m momentum < -5% (caution)
    or < -10% (defensive), acting as a market-wide drawdown brake.
  • Vol targeting       — scale entire book daily so estimated 20-day portfolio
    vol tracks TARGET_VOL; capped at MAX_LEVERAGE (1.0 — no leverage).
  • Drawdown stop       — if portfolio falls 15% from peak, go 100% cash for 21
    trading days before resuming.
"""

import numpy as np
import pandas as pd


# ── Helpers ───────────────────────────────────────────────────

def _month_end_dates(index: pd.DatetimeIndex) -> list:
    periods = index.to_period("M")
    return [index[periods == p][-1] for p in periods.unique()]


def _momentum_scores(prices: pd.DataFrame, date: pd.Timestamp,
                     lookbacks: list, skip: int) -> pd.Series:
    """
    Composite momentum per ticker at `date`.

    Uses the average of (lb)-month returns measured from
        (date − lb − skip months)  →  (date − skip months)
    so the most recent `skip` months are excluded (reversal avoidance).

    Returns raw average return (not ranked).  NaN if any window is missing.
    """
    end_ref = date - pd.DateOffset(months=skip)
    scores  = {}

    for ticker in prices.columns:
        px       = prices[ticker].dropna()
        end_sl   = px.loc[:end_ref]
        if end_sl.empty:
            scores[ticker] = np.nan
            continue
        end_px = end_sl.iloc[-1]

        rets = []
        for lb in lookbacks:
            start_ref = date - pd.DateOffset(months=lb + skip)
            start_sl  = px.loc[:start_ref]
            if start_sl.empty:
                continue
            start_px = start_sl.iloc[-1]
            if start_px > 0:
                rets.append(end_px / start_px - 1)

        # Require all windows to be computable (strict — avoids partial signals)
        scores[ticker] = np.mean(rets) if len(rets) == len(lookbacks) else np.nan

    return pd.Series(scores)


def _spy_regime_scale(spy_prices: pd.Series, date: pd.Timestamp) -> float:
    """
    SPY 3-month momentum regime filter.
      > -5%  → full exposure  (1.0)
      < -5%  → caution        (0.6)
      < -10% → defensive      (0.3)
    """
    now_sl = spy_prices.loc[:date]
    ref_sl = spy_prices.loc[:date - pd.DateOffset(months=3)]
    if now_sl.empty or ref_sl.empty:
        return 1.0
    mom = now_sl.iloc[-1] / ref_sl.iloc[-1] - 1
    if mom < -0.10:
        return 0.3
    if mom < -0.05:
        return 0.6
    return 1.0


# ── Monthly weight computation ────────────────────────────────

def _compute_monthly_weights(
    prices: pd.DataFrame,
    garp_scores,          # pd.Series (static) or pd.DataFrame (date × ticker, point-in-time)
    spy_prices: pd.Series,
    top_n: int,
    lookback_months: list,
    skip_months: int,
    garp_weight: float,
    mom_weight: float,
    max_weight: float,
) -> tuple:
    """
    Returns:
      weights       — dict {rebal_date: pd.Series of target weights}
      regime_scales — dict {rebal_date: float exposure scale}

    garp_scores can be:
      pd.Series  — static scores applied across the whole backtest
      pd.DataFrame — date-indexed point-in-time scores; at each rebalance date
                     the most recent available row is used (forward-filled).
    """
    rebal_dates   = _month_end_dates(prices.index)
    warmup        = max(lookback_months) + skip_months
    time_varying  = isinstance(garp_scores, pd.DataFrame)

    # Precompute rank for the static case
    if not time_varying:
        g         = garp_scores.reindex(prices.columns).fillna(0.30)
        g_min, g_max = g.min(), g.max()
        _static_rank = (g - g_min) / max(g_max - g_min, 1e-9)

    weights       = {}
    regime_scales = {}

    for i, date in enumerate(rebal_dates):
        regime_scales[date] = _spy_regime_scale(spy_prices, date)

        if i < warmup:
            weights[date] = pd.Series(0.0, index=prices.columns)
            continue

        # GARP rank and effective weights for this rebalance date
        if time_varying:
            prior     = garp_scores.loc[:date]
            has_data  = not prior.empty and not prior.iloc[-1].isna().all()
            if has_data:
                g_now    = prior.iloc[-1].reindex(prices.columns).fillna(0.30)
                g_min, g_max = g_now.min(), g_now.max()
                garp_rank = (g_now - g_min) / max(g_max - g_min, 1e-9)
                garp_eff  = garp_weight
                mom_eff   = mom_weight
            else:
                # No filing data yet — pure momentum, equal-weight holdings
                garp_rank = pd.Series(0.0, index=prices.columns)
                garp_eff  = 0.0
                mom_eff   = 1.0
        else:
            garp_rank = _static_rank
            garp_eff  = garp_weight
            mom_eff   = mom_weight

        mom = _momentum_scores(prices, date, lookback_months, skip_months)

        # Rank momentum cross-sectionally (0 = worst, 1 = best)
        valid = mom.dropna()
        if valid.empty:
            weights[date] = pd.Series(0.0, index=prices.columns)
            continue

        n_valid  = len(valid)
        mom_rank = (valid.rank() - 1) / max(n_valid - 1, 1)

        # Composite score (higher = stronger GARP + stronger momentum)
        composite = (
            mom_eff   * mom_rank.reindex(prices.columns).fillna(0) +
            garp_eff  * garp_rank
        )

        # Absolute filter: remove stocks with non-positive raw momentum
        composite = composite.where(mom.reindex(prices.columns) > 0, 0)

        # Select top N with positive composite score
        candidates = composite[composite > 0].nlargest(top_n)
        if candidates.empty:
            weights[date] = pd.Series(0.0, index=prices.columns)
            continue

        # Allocate within selected stocks: GARP-quality-weighted when data
        # exists, equal-weighted otherwise
        if garp_eff > 0:
            sel_garp = garp_rank.reindex(candidates.index)
            g_sum    = sel_garp.sum()
            raw_w    = sel_garp / g_sum if g_sum > 1e-9 else pd.Series(
                1.0 / len(candidates), index=candidates.index
            )
        else:
            raw_w = pd.Series(1.0 / len(candidates), index=candidates.index)

        # Cap and renormalise
        raw_w = raw_w.clip(upper=max_weight)
        raw_w = raw_w / raw_w.sum()

        w = pd.Series(0.0, index=prices.columns)
        w.update(raw_w)
        weights[date] = w

    return weights, regime_scales


# ── Daily simulation ──────────────────────────────────────────

def run_garp_backtest(
    prices: pd.DataFrame,
    garp_scores: pd.Series,
    spy_prices: pd.Series,
    tbill_daily_rate: pd.Series,
    initial_capital: float,
    top_n: int,
    lookback_months: list,
    skip_months: int,
    garp_weight: float,
    mom_weight: float,
    max_weight: float,
    target_vol: float,
    max_leverage: float,
    vol_lookback: int,
    transaction_cost: float,
    drawdown_stop_pct: float,
) -> pd.DataFrame:

    returns = prices.pct_change()
    tbill   = tbill_daily_rate.reindex(prices.index).ffill().fillna(0)

    monthly_weights, regime_scales = _compute_monthly_weights(
        prices, garp_scores, spy_prices,
        top_n, lookback_months, skip_months,
        garp_weight, mom_weight, max_weight,
    )

    rebal_dates = _month_end_dates(prices.index)
    warmup      = max(lookback_months) + skip_months

    # First trading day after the first non-trivial rebalance
    start_day = None
    for d in rebal_dates[warmup:]:
        future = prices.index[prices.index > d]
        if not future.empty and monthly_weights.get(d, pd.Series()).sum() > 0:
            start_day = future[0]
            break
    if start_day is None:
        start_day = prices.index[warmup * 21]

    portfolio_value = initial_capital
    peak_value      = initial_capital
    prev_w          = pd.Series(0.0, index=prices.columns)
    current_target  = pd.Series(0.0, index=prices.columns)
    current_regime  = 1.0
    stop_active     = False
    stop_cooldown   = 0
    STOP_DAYS       = 21

    rebal_set = set(rebal_dates)
    records   = []

    # ── Warmup period: hold cash, earn T-bill ─────────────────
    # Included so the portfolio covers the full configured date range,
    # making Trading Days and SPY comparison consistent across strategies.
    for date in prices.index:
        if date >= start_day:
            break
        tbill_today = tbill.get(date, 0.0)
        net_pnl     = tbill_today * portfolio_value
        portfolio_value += net_pnl
        peak_value = max(peak_value, portfolio_value)
        records.append({
            "date":             date,
            "net_pnl":          net_pnl,
            "transaction_cost": 0.0,
            "portfolio_value":  portfolio_value,
            "invested_weight":  0.0,
            "cash_weight":      1.0,
            "regime_scale":     1.0,
            "stop_active":      False,
            "n_held":           0,
            "holdings":         "",
        })

    for date in prices.index:
        if date < start_day:
            continue

        day_ret = returns.loc[date]
        if day_ret.isna().all():
            continue

        # ── Drawdown stop ─────────────────────────────────────
        dd = (portfolio_value - peak_value) / peak_value
        if not stop_active and dd < -drawdown_stop_pct:
            stop_active   = True
            stop_cooldown = STOP_DAYS
        elif stop_active:
            stop_cooldown -= 1
            if stop_cooldown <= 0:
                stop_active  = False
                peak_value   = portfolio_value  # reset peak so strategy can re-enter cleanly

        # ── Effective weights ─────────────────────────────────
        if stop_active:
            w = pd.Series(0.0, index=prices.columns)
        else:
            base_w = current_target * current_regime

            # Vol targeting: scale to TARGET_VOL using last vol_lookback days
            recent = returns.loc[:date].tail(vol_lookback + 1).iloc[:-1]
            if len(recent) >= 10:
                port_hist = (base_w * recent.fillna(0)).sum(axis=1)
                hist_vol  = port_hist.std() * np.sqrt(252)
                if hist_vol > 1e-6:
                    vol_scale = min(target_vol / hist_vol, max_leverage)
                    base_w    = (base_w * vol_scale).clip(upper=max_weight)

            w = base_w

        # ── P&L ───────────────────────────────────────────────
        invested_w  = w.sum()
        cash_w      = max(0.0, 1.0 - invested_w)
        tbill_today = tbill.get(date, 0.0)

        turnover  = (w - prev_w).abs().sum()
        tc        = turnover * transaction_cost * portfolio_value
        gross_pnl = ((w * day_ret.fillna(0)).sum() + cash_w * tbill_today) * portfolio_value
        net_pnl   = gross_pnl - tc

        portfolio_value += net_pnl
        peak_value = max(peak_value, portfolio_value)

        held = [t for t in prices.columns if w.get(t, 0) > 0.01]
        records.append({
            "date":            date,
            "net_pnl":         net_pnl,
            "transaction_cost": tc,
            "portfolio_value": portfolio_value,
            "invested_weight": invested_w,
            "cash_weight":     cash_w,
            "regime_scale":    current_regime,
            "stop_active":     bool(stop_active),
            "n_held":          len(held),
            "holdings":        ",".join(held),
        })

        prev_w = w.copy()

        # ── Update targets (takes effect next trading day) ────
        if date in rebal_set and date in monthly_weights:
            current_target = monthly_weights[date].copy()
            current_regime = regime_scales[date]

    df = pd.DataFrame(records).set_index("date")
    dr = df["net_pnl"] / df["portfolio_value"].shift(1)
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df
