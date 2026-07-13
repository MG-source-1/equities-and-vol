"""
SPY Intraday Afternoon Short — main runner.

Run from the project root:
    python -m strategies.equities.spy_intraday_short.main
Or directly:
    python strategies/spy_intraday_short/main.py
"""

import os, sys
# Ensure project root is importable regardless of how this script is invoked
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates

from core.data import fetch_tbill, fetch_spy
from core.metrics import compute_metrics
from strategies.equities.spy_intraday_short.data_intraday import fetch_bars
from strategies.equities.spy_intraday_short.strategy import compute_daily_signals, run_intraday_backtest
from strategies.equities.spy_intraday_short.config import (
    SYMBOL, START_DATE, END_DATE, INITIAL_CAPITAL,
    MIN_MORNING_MOVE, MIN_OVERNIGHT_GAP, TC, DD_STOP,
    OUTPUT_DIR, DATA_CACHE_DIR,
)


def run_multi_instrument(symbols, tbill_rate, initial_capital,
                         min_morning_move, min_overnight_gap,
                         transaction_cost, drawdown_stop_pct):
    all_signals = {}
    for sym in symbols:
        bars = fetch_bars(sym, START_DATE, END_DATE, timeframe="5Min",
                          cache_dir=DATA_CACHE_DIR)
        sigs = compute_daily_signals(bars, min_morning_move, min_overnight_gap)
        all_signals[sym] = sigs
        n   = sigs["trade"].sum()
        win = (sigs["trade"] & (sigs["signal"] * sigs["afternoon_ret"] > 0)).sum()
        print(f"  {sym}: {n} trade days, win rate {win/n:.1%} when active")

    all_dates  = sorted(set.union(*[set(s.index) for s in all_signals.values()]))
    date_index = pd.DatetimeIndex(all_dates)

    tbill = tbill_rate.reindex(
        pd.date_range(date_index[0], date_index[-1], freq="B")
    ).ffill().fillna(0)

    portfolio_value = initial_capital
    peak_value      = initial_capital
    stop_active     = False
    stop_cooldown   = 0
    STOP_DAYS       = 21
    records         = []

    for date in date_index:
        tbill_today = tbill.get(date, 0.0)

        dd = (portfolio_value - peak_value) / peak_value
        if not stop_active and dd < -drawdown_stop_pct:
            stop_active   = True
            stop_cooldown = STOP_DAYS
        elif stop_active:
            stop_cooldown -= 1
            if stop_cooldown <= 0:
                stop_active = False

        active_syms = [
            sym for sym, sigs in all_signals.items()
            if date in sigs.index and sigs.loc[date, "trade"] and not stop_active
        ]

        if not active_syms:
            net_pnl   = tbill_today * portfolio_value
            trade_ret = 0.0
            traded    = False
        else:
            weight    = 1.0 / len(active_syms)
            trade_ret = sum(
                weight * all_signals[sym].loc[date, "signal"]
                       * all_signals[sym].loc[date, "afternoon_ret"]
                for sym in active_syms
            )
            tc      = len(active_syms) * 2 * transaction_cost * weight
            net_pnl = (trade_ret - tc + tbill_today) * portfolio_value
            traded  = True

        portfolio_value += net_pnl
        peak_value = max(peak_value, portfolio_value)

        records.append({
            "date":            date,
            "trade_ret":       trade_ret,
            "net_pnl":         net_pnl,
            "portfolio_value": portfolio_value,
            "n_active":        len(active_syms),
            "symbols_traded":  ",".join(active_syms),
            "stop_active":     bool(stop_active),
            "in_regime":       traded,
        })

    df = pd.DataFrame(records).set_index("date")
    dr = df["net_pnl"] / df["portfolio_value"].shift(1)
    dr.iloc[0] = df["net_pnl"].iloc[0] / initial_capital
    df["daily_return"] = dr
    return df


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\n{'='*64}")
    print("  INTRADAY AFTERNOON SHORT — DUAL-SIGNAL FILTER")
    print(f"{'='*64}")
    print(f"  Asset         : {SYMBOL}  (Alpaca SIP 5-min)")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Capital       : ${INITIAL_CAPITAL:,.0f}")
    print(f"  Filter        : |morning ret| ≥ {MIN_MORNING_MOVE:.2%}  AND")
    print(f"                  |overnight gap| ≥ {MIN_OVERNIGHT_GAP:.2%}  AND same direction")
    print(f"  Trade         : SHORT 15:30 → 15:55  (last 30 min)")
    print(f"  TC            : {TC*10000:.0f} bp/side  |  Drawdown stop: {DD_STOP:.0%}")
    print(f"  Data          : 100% Alpaca SIP (BIL ETF as T-bill proxy)")
    print(f"{'='*64}\n")

    print("[data] Fetching benchmarks …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)
    spy_cumulative               = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Fetching intraday bars and computing signals …")
    portfolio = run_multi_instrument(
        [SYMBOL], tbill_rate, INITIAL_CAPITAL,
        MIN_MORNING_MOVE, MIN_OVERNIGHT_GAP,
        TC, DD_STOP,
    )

    metrics     = compute_metrics(portfolio, tbill_rate, INITIAL_CAPITAL)
    spy_aligned = spy_cumulative.reindex(portfolio.index).ffill()
    spy_total   = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1

    total_days  = len(portfolio)
    trade_days  = (portfolio["n_active"] > 0).sum()
    win_on_trade = (portfolio.loc[portfolio["n_active"] > 0, "trade_ret"] > 0).mean()

    print("\nPortfolio Summary")
    print("-" * 52)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_total:.2%}")
    print(f"  {'Trade days / total days':<36} {trade_days}/{total_days} ({trade_days/total_days:.0%})")
    print(f"  {'Win rate (active days)':<36} {win_on_trade:.2%}")
    print()

    portfolio.to_csv(os.path.join(OUTPUT_DIR, "intraday_portfolio.csv"))
    print(f"[output] CSV → {OUTPUT_DIR}/intraday_portfolio.csv")

    # ── Plot ──────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(13, 10))
    fig.suptitle(
        "Intraday Afternoon Short — SPY  (Alpaca SIP data)\n"
        "SHORT last 30 min when dual-signal fires  ·  BIL T-bill proxy  ·  1 bp/side TC",
        fontsize=12, fontweight="bold",
    )

    ax = axes[0]
    port_r  = portfolio["portfolio_value"] / INITIAL_CAPITAL * 100
    spy_r   = spy_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100
    tbill_r = tbill_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100
    ax.plot(port_r.index,  port_r,  label="Intraday Afternoon Short", color="steelblue",  linewidth=2.0)
    ax.plot(spy_r.index,   spy_r,   label="SPY (buy & hold)",         color="darkorange",  linestyle="--", linewidth=1.5)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL ETF proxy)",   color="seagreen",    linestyle=":",  linewidth=1.3)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax = axes[1]
    rolling_max = portfolio["portfolio_value"].cummax()
    drawdown    = (portfolio["portfolio_value"] - rolling_max) / rolling_max * 100
    ax.fill_between(drawdown.index, drawdown, 0, color="tomato", alpha=0.5)
    if "stop_active" in portfolio.columns:
        stop = portfolio["stop_active"].astype(bool)
        s    = None
        for date, active in stop.items():
            if active and s is None: s = date
            elif not active and s is not None:
                ax.axvspan(s, date, color="gold", alpha=0.35, linewidth=0)
                s = None
        if s:
            ax.axvspan(s, portfolio.index[-1], color="gold", alpha=0.35, linewidth=0)
    ax.legend(handles=[
        mpatches.Patch(color="tomato", alpha=0.6, label="Drawdown"),
        mpatches.Patch(color="gold",   alpha=0.5, label="Stop active"),
    ], fontsize=8)
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Portfolio Drawdown")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for a in axes:
        a.tick_params(axis="x", rotation=30)
        a.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "intraday_afternoon_short.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
