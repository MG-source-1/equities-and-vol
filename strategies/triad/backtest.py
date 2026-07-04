"""
TRIAD — Tri-Timescale TMT — backtest engine.

One factor (TMT), three harvesting behaviours at three timescales:

Sleeve 1 — Leaders (slow, rebalances monthly)
  Concentrates into the TOP_N strongest names in the 15-stock TMT universe
  by blended 3/6/12-month momentum (positive-momentum names only), equal
  weight, sized to a 25% annualised sleeve vol target, with a QQQ 200-day
  regime scaler (0.3x below the SMA). This is the return engine.

Sleeve 2 — Stock dips (fast, holds days)
  Buys single-name panic closes: IBS < 0.10 while the stock is above its
  200-day SMA with positive 6-month momentum. Exits when IBS > 0.75 or
  after 3 days. Each active dip gets 25% of the sleeve, gross capped at 1x.
  Single names overreact intraday far more than the index — this sleeve
  harvests idiosyncratic panic that the monthly sleeve is too slow to see.

Sleeve 3 — Index dips (fast, holds days)
  DTQ's QQQ mean-reversion sleeve verbatim: IBS < 0.10 above the 200-day
  SMA, vol-sized, exits on strength or 3 days.

Execution discipline (no lookahead): every signal is computed from data up
to and including today's close; positions are taken at that close and earn
from the next close-to-close return. Costs: 10 bps per unit of turnover,
per instrument. Uninvested capital earns the T-bill (BIL) rate; on the rare
days combined exposure exceeds 1x (max ~1.08x) the excess pays the T-bill
rate as a borrow cost.
"""

import numpy as np
import pandas as pd


def _month_end_dates(index: pd.DatetimeIndex) -> list:
    periods = index.to_period("M")
    return [index[periods == p][-1] for p in periods.unique()]


def compute_leader_weights(
    closes: pd.DataFrame,
    index_close: pd.Series,
    lookback_days: list,
    top_n: int,
    target_vol: float,
    regime_floor: float,
    sma_window: int,
    vol_lookback: int,
) -> pd.DataFrame:
    """Daily target weights for the Leaders sleeve (unshifted)."""
    rets = closes.pct_change()
    mom  = sum(closes.pct_change(lb) for lb in lookback_days) / len(lookback_days)

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    rebal   = _month_end_dates(closes.index)
    for i, date in enumerate(rebal[:-1]):
        m = mom.loc[date].dropna()
        m = m[m > 0]                       # absolute-momentum qualifier
        top = m.nlargest(top_n).index
        if len(top) == 0:
            continue                       # all momentum negative → sleeve in cash
        mask = (closes.index > date) & (closes.index <= rebal[i + 1])
        weights.loc[mask, top] = 1.0 / len(top)

    # Sleeve-level vol targeting on the unscaled sleeve return
    sleeve_ret = (weights.shift(1) * rets).sum(axis=1)
    realized   = sleeve_ret.rolling(vol_lookback).std() * np.sqrt(252)
    vol_scale  = (target_vol / realized).clip(upper=1.0).shift(1).fillna(0.0)

    # QQQ regime scaler: full risk in uptrends, regime_floor below the SMA
    in_trend = (index_close > index_close.rolling(sma_window).mean()) \
        .astype(float).shift(1).fillna(0.0)
    regime = regime_floor + (1.0 - regime_floor) * in_trend

    return weights.mul(vol_scale * regime.reindex(closes.index).fillna(0.0), axis=0)


def _dip_positions(
    bars: pd.DataFrame,
    entry_ibs: float,
    exit_ibs: float,
    max_hold: int,
    sma_window: int,
    mom_days: int,
) -> pd.Series:
    """0/1 panic-dip holding series for a single stock (unshifted)."""
    px, hi, lo = bars["close"], bars["high"], bars["low"]
    ibs  = (px - lo) / (hi - lo).replace(0, np.nan)
    sma  = px.rolling(sma_window).mean()
    mom  = px.pct_change(mom_days)

    pos, holding = pd.Series(0.0, index=px.index), 0
    for i in range(sma_window, len(px)):
        if holding > 0:
            if ibs.iloc[i] > exit_ibs or holding >= max_hold:
                holding = 0
            else:
                holding += 1
                pos.iloc[i] = 1.0
                continue
        if ibs.iloc[i] < entry_ibs and px.iloc[i] > sma.iloc[i] and mom.iloc[i] > 0:
            holding = 1
            pos.iloc[i] = 1.0
    return pos


def compute_stock_dip_weights(
    all_bars: dict,
    calendar: pd.DatetimeIndex,
    entry_ibs: float,
    exit_ibs: float,
    max_hold: int,
    sma_window: int,
    mom_days: int,
    per_name: float,
    max_gross: float,
) -> pd.DataFrame:
    """Daily target weights for the stock-dip sleeve (unshifted)."""
    pos = pd.DataFrame({
        t: _dip_positions(b, entry_ibs, exit_ibs, max_hold, sma_window, mom_days)
             .reindex(calendar).fillna(0.0)
        for t, b in all_bars.items()
    })
    w     = pos * per_name
    gross = w.sum(axis=1)
    scale = (max_gross / gross).clip(upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)


def compute_index_dip_weights(
    bars: pd.DataFrame,
    entry_ibs: float,
    exit_ibs: float,
    max_hold: int,
    sma_window: int,
    target_vol: float,
    vol_lookback: int,
    max_size: float,
) -> pd.Series:
    """Daily target QQQ weight for the index-dip sleeve (unshifted) — DTQ's MR sleeve."""
    px, hi, lo = bars["close"], bars["high"], bars["low"]
    ret  = px.pct_change()
    ibs  = (px - lo) / (hi - lo).replace(0, np.nan)
    sma  = px.rolling(sma_window).mean()
    size = (target_vol / (ret.rolling(vol_lookback).std() * np.sqrt(252))).clip(upper=max_size)

    pos, holding = pd.Series(0.0, index=px.index), 0
    for i in range(sma_window, len(px)):
        if holding > 0:
            if ibs.iloc[i] > exit_ibs or holding >= max_hold:
                holding = 0
            else:
                holding += 1
                pos.iloc[i] = pos.iloc[i - 1]
                continue
        if ibs.iloc[i] < entry_ibs and px.iloc[i] > sma.iloc[i]:
            holding = 1
            pos.iloc[i] = size.iloc[i] if np.isfinite(size.iloc[i]) else 0.0
    return pos


def run_triad_backtest(
    all_bars: dict,              # {ticker: OHLC DataFrame} for the 15 stocks
    index_bars: pd.DataFrame,    # QQQ OHLC
    tbill_daily_rate: pd.Series,
    initial_capital: float,
    cfg,                         # the strategies.triad.config module
) -> pd.DataFrame:
    calendar = index_bars.index
    closes   = pd.DataFrame({t: b["close"].reindex(calendar)
                             for t, b in all_bars.items()}).ffill()
    rets     = closes.pct_change()
    idx_ret  = index_bars["close"].pct_change()
    tbill    = tbill_daily_rate.reindex(calendar).ffill().fillna(0.0)

    w_lead = compute_leader_weights(
        closes, index_bars["close"],
        cfg.LOOKBACK_DAYS, cfg.TOP_N, cfg.LEADERS_TARGET_VOL,
        cfg.REGIME_FLOOR, cfg.SMA_WINDOW, cfg.VOL_LOOKBACK)
    w_sdip = compute_stock_dip_weights(
        all_bars, calendar,
        cfg.DIP_ENTRY_IBS, cfg.DIP_EXIT_IBS, cfg.DIP_MAX_HOLD,
        cfg.SMA_WINDOW, cfg.DIP_MOM_DAYS, cfg.DIP_PER_NAME, cfg.DIP_MAX_GROSS)
    w_idip = compute_index_dip_weights(
        index_bars,
        cfg.IDX_ENTRY_IBS, cfg.IDX_EXIT_IBS, cfg.IDX_MAX_HOLD,
        cfg.SMA_WINDOW, cfg.IDX_TARGET_VOL, cfg.VOL_LOOKBACK, cfg.IDX_MAX_SIZE)

    # Scale sleeves to their capital split; weight held over t → t+1
    stock_w = (cfg.LEADERS_WEIGHT * w_lead + cfg.STOCK_DIP_WEIGHT * w_sdip) \
        .shift(1).fillna(0.0)
    index_w = (cfg.INDEX_DIP_WEIGHT * w_idip).reindex(calendar).shift(1).fillna(0.0)

    # Sleeve components kept for attribution
    lead_w_held = (cfg.LEADERS_WEIGHT * w_lead).shift(1).fillna(0.0)
    sdip_w_held = (cfg.STOCK_DIP_WEIGHT * w_sdip).shift(1).fillna(0.0)

    start_day = calendar[cfg.SMA_WINDOW + 1]

    portfolio_value = initial_capital
    prev_stock_w    = pd.Series(0.0, index=closes.columns)
    prev_index_w    = 0.0
    records         = []

    for date in calendar:
        if date < start_day:
            continue
        day_ret = rets.loc[date]
        iday    = idx_ret.get(date, 0.0)
        if day_ret.isna().all() and pd.isna(iday):
            continue

        sw = stock_w.loc[date].fillna(0.0)
        iw = index_w.get(date, 0.0)
        total_w = sw.sum() + iw
        cash_w  = 1.0 - total_w   # negative on rare >1x days → pays T-bill rate

        turnover = (sw - prev_stock_w).abs().sum() + abs(iw - prev_index_w)
        tc       = turnover * cfg.TRANSACTION_COST * portfolio_value

        lead_pnl = (lead_w_held.loc[date].fillna(0.0) * day_ret.fillna(0.0)).sum() * portfolio_value
        sdip_pnl = (sdip_w_held.loc[date].fillna(0.0) * day_ret.fillna(0.0)).sum() * portfolio_value
        idip_pnl = iw * (0.0 if pd.isna(iday) else iday) * portfolio_value

        gross_pnl = lead_pnl + sdip_pnl + idip_pnl \
            + cash_w * tbill.get(date, 0.0) * portfolio_value
        net_pnl = gross_pnl - tc
        portfolio_value += net_pnl

        records.append({
            "date":             date,
            "net_pnl":          net_pnl,
            "transaction_cost": tc,
            "portfolio_value":  portfolio_value,
            "leaders_pnl":      lead_pnl,
            "stock_dip_pnl":    sdip_pnl,
            "index_dip_pnl":    idip_pnl,
            "weight_leaders":   lead_w_held.loc[date].sum(),
            "weight_stock_dip": sdip_w_held.loc[date].sum(),
            "weight_index_dip": iw,
            "invested_weight":  total_w,
            "cash_weight":      cash_w,
            "n_leaders":        int((lead_w_held.loc[date] > 0.001).sum()),
            "n_dips":           int((sdip_w_held.loc[date] > 0.001).sum()),
            "top_holding":      sw.idxmax() if sw.max() > 0.001 else "",
            "in_regime":        bool(total_w > 0.01),
        })
        prev_stock_w = sw
        prev_index_w = iw

    df = pd.DataFrame(records).set_index("date")
    dr = df["net_pnl"] / df["portfolio_value"].shift(1)
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df
