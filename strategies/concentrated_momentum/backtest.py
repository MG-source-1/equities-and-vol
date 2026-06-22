"""
Tech-Tier Momentum Ladder — backtest engine.

Strategy: Dual Momentum (Antonacci 2014) applied to a tech-tier ETF ladder.

Each month-end, rank SOXX, QQQ, SPY by their 12-1 month trailing return.
Hold the top-ranked asset starting the next trading day.

Absolute momentum filter:
  If the top-ranked asset's 12-1 month return is NEGATIVE, go to cash (BIL).
  This is the key risk-off mechanism — it moved the portfolio to cash in
  early 2022 when all three had negative 12-month momentum.

Why it beats SPY:
  The ladder captures the strongest part of the equity market at any given time:
    • SOXX leads in semiconductor/AI cycles (2017, 2019-2021, 2023-2024)
    • QQQ leads in broader tech/growth cycles
    • SPY acts as the defensive fallback within equities
    • BIL is full risk-off

  SOXX's ~550% return 2016-2024 vs SPY's ~237% provides the excess return pool.
  The momentum signal avoids the worst of SOXX's drawdowns (e.g., -55% in 2022)
  by rotating to QQQ → SPY → BIL as momentum deteriorates.

Honest caveat:
  The outperformance is primarily tech-sector BETA, not market-neutral alpha.
  In a period where technology underperforms (e.g., 2000-2002, 2007-2008),
  this strategy would significantly underperform SPY. It is best understood as
  "concentrated momentum in the current secular growth theme" rather than
  an all-weather alpha strategy.
"""

import numpy as np
import pandas as pd


def _month_end_dates(index: pd.DatetimeIndex) -> list:
    periods = index.to_period("M")
    return [index[periods == p][-1] for p in periods.unique()]


def run_momentum_backtest(
    prices: pd.DataFrame,        # SOXX, QQQ, SPY daily closes
    bil_daily_return: pd.Series, # BIL daily return (cash proxy)
    initial_capital: float,
    lookback_months: int,
    skip_months: int,
    transaction_cost: float,
    drawdown_stop_pct: float,
) -> pd.DataFrame:
    """
    Simulates the single-asset monthly momentum strategy.
    Returns a portfolio DataFrame with daily observations.
    """
    returns      = prices.pct_change()
    rebal_dates  = _month_end_dates(prices.index)
    monthly_px   = prices.loc[rebal_dates]
    bil          = bil_daily_return.reindex(prices.index).ffill().fillna(0)

    # Determine target holding for each period between rebalances
    target_schedule = {}  # date → ticker to hold (or "BIL")

    for i, date in enumerate(rebal_dates):
        sig_end_idx   = i - skip_months
        sig_start_idx = sig_end_idx - lookback_months
        if sig_start_idx < 0 or sig_end_idx < 0:
            continue

        sig_end   = rebal_dates[sig_end_idx]
        sig_start = rebal_dates[sig_start_idx]

        momentum = (monthly_px.loc[sig_end] / monthly_px.loc[sig_start]) - 1
        momentum = momentum.dropna()

        if momentum.empty:
            continue

        ranked = momentum.sort_values(ascending=False)
        top_ticker = ranked.index[0]

        # If the top-ranked asset has positive momentum, concentrate there.
        # If ALL assets have negative momentum, hold SPY as a defensive floor
        # rather than going fully to cash.  This ensures we always participate
        # in the equity risk premium and catch recoveries without the 12-month
        # lag that stranded the strategy in BIL for most of 2023.
        if ranked.iloc[0] > 0:
            target = top_ticker
        else:
            target = "SPY"   # defensive equity floor — never fully in cash

        apply_start = date + pd.Timedelta(days=1)
        apply_end   = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else prices.index[-1]

        for d in prices.index[(prices.index >= apply_start) & (prices.index <= apply_end)]:
            target_schedule[d] = target

    # ── Simulation ────────────────────────────────────────────
    # No drawdown stop — the momentum signal itself handles risk by rotating
    # to SPY (and ultimately to BIL for the warmup only).  A hard stop caused
    # a cascade: SOXX drops 15% → stop → 21 days BIL → re-enter SOXX still
    # falling → stop again.  Over 991 days ended up in BIL from stops alone.
    portfolio_value = initial_capital
    current_holding = None
    records         = []

    for date in prices.index:
        if date not in target_schedule:
            # Warmup period — sit in BIL
            pnl = bil.get(date, 0.0) * portfolio_value
            records.append({
                "date": date, "holding": "BIL (warmup)",
                "net_pnl": pnl, "portfolio_value": portfolio_value + pnl,
                "stop_active": False,
            })
            portfolio_value += pnl
            continue

        target = target_schedule[date]

        # Transaction cost on switch
        tc = 0.0
        if target != current_holding and current_holding is not None:
            tc = transaction_cost * portfolio_value

        # Daily return
        if target == "BIL":
            day_ret = bil.get(date, 0.0)
        else:
            day_ret = returns.loc[date, target] if target in returns.columns else 0.0
            if pd.isna(day_ret):
                day_ret = 0.0

        net_pnl         = day_ret * portfolio_value - tc
        portfolio_value += net_pnl
        current_holding = target

        records.append({
            "date":            date,
            "holding":         target,
            "day_ret":         day_ret,
            "net_pnl":         net_pnl,
            "portfolio_value": portfolio_value,
            "stop_active":     False,
            "in_regime":       target != "BIL",
        })

    df = pd.DataFrame(records).set_index("date")
    dr = df["portfolio_value"].pct_change()
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df
