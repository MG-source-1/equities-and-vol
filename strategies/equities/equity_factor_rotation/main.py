"""
Adaptive Factor Portfolio (AFP) — main runner.

Run from project root:
    python -m strategies.equities.equity_factor_rotation.main
"""

import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates

from core.data import fetch_prices, fetch_tbill, fetch_spy
from core.metrics import compute_metrics, per_ticker_metrics
from strategies.equities.equity_factor_rotation.backtest import run_factor_backtest, per_factor_contribution
from strategies.equities.equity_factor_rotation.config import (
    TICKERS, START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR,
    LOOKBACK_MONTHS, RANK_TILT,
    CORR_WINDOW, CORR_HIGH, CORR_MID,
    TARGET_VOL, MAX_WEIGHT, MAX_LEVERAGE, VOL_LOOKBACK,
    DRAWDOWN_STOP, TRANSACTION_COST,
)

_REGIME_COLORS = {"Crisis": "#f8d7da", "Caution": "#fff3cd", "Normal": "#ffffff"}


def _shade_regimes(ax, portfolio):
    if "regime" not in portfolio.columns:
        return
    df    = portfolio[["regime"]].copy()
    df["change"] = df["regime"].ne(df["regime"].shift())
    bounds = df.index[df["change"]].tolist() + [df.index[-1]]
    prev = cur = None
    for i, b in enumerate(bounds):
        if prev is None:
            prev, cur = b, df.at[b, "regime"]
            continue
        color = _REGIME_COLORS.get(cur)
        if color and cur != "Normal":
            ax.axvspan(prev, b, color=color, alpha=0.45, linewidth=0)
        prev = b
        if i < len(bounds) - 1:
            cur = df.at[b, "regime"]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    tickers = list(TICKERS.keys())
    print(f"\n{'='*64}")
    print("  ADAPTIVE FACTOR PORTFOLIO (AFP)")
    print(f"{'='*64}")
    print(f"  Universe      : {', '.join(tickers)}")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Capital       : ${INITIAL_CAPITAL:,.0f}")
    print(f"  Signal        : 3-of-4 composite momentum + {RANK_TILT}× leader tilt")
    print(f"  Corr filter   : QQQ vs USMV  >{CORR_HIGH:.0%}→0.4× crisis  "
          f"{CORR_MID:.0%}-{CORR_HIGH:.0%}→0.7× caution  <{CORR_MID:.0%}→1.0× normal")
    print(f"  Target vol    : {TARGET_VOL:.0%}  |  Max leverage: {MAX_LEVERAGE:.1f}×")
    print(f"  Drawdown stop : {DRAWDOWN_STOP:.0%}  |  TC: {TRANSACTION_COST*10000:.0f} bps")
    print(f"  Benchmark     : SPY  |  Data: Alpaca SIP")
    print(f"{'='*64}\n")

    print("[data] Downloading factor ETF prices …")
    prices = fetch_prices(tickers, START_DATE, END_DATE)

    print("[data] Downloading SPY benchmark …")
    spy_cumulative = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Downloading T-bill (BIL) …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)

    available = list(prices.columns)
    print(f"[data] Available: {available}\n")

    print("[backtest] Running …")
    portfolio = run_factor_backtest(
        prices, tbill_rate, INITIAL_CAPITAL,
        LOOKBACK_MONTHS, RANK_TILT,
        CORR_WINDOW, CORR_HIGH, CORR_MID,
        TARGET_VOL, MAX_WEIGHT, MAX_LEVERAGE, VOL_LOOKBACK,
        TRANSACTION_COST, DRAWDOWN_STOP,
    )

    per_factor = per_factor_contribution(
        prices, INITIAL_CAPITAL,
        LOOKBACK_MONTHS, RANK_TILT,
        CORR_WINDOW, CORR_HIGH, CORR_MID,
        TARGET_VOL, MAX_WEIGHT, MAX_LEVERAGE, VOL_LOOKBACK,
    )

    # ── Metrics ───────────────────────────────────────────────
    metrics     = compute_metrics(portfolio, tbill_rate, INITIAL_CAPITAL)
    spy_aligned = spy_cumulative.reindex(portfolio.index).ffill()
    spy_total   = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1

    regime_counts = portfolio["regime"].value_counts()
    crisis_pct    = regime_counts.get("Crisis", 0) / len(portfolio)
    caution_pct   = regime_counts.get("Caution", 0) / len(portfolio)
    leader_counts = portfolio.loc[portfolio["leader"] != "", "leader"].value_counts()

    print("Portfolio Summary")
    print("-" * 50)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_total:.2%}")
    print(f"  {'Avg factors held':<36} {portfolio['n_long'].mean():.1f} of {len(available)}")
    print()
    print("Regime Distribution")
    print("-" * 50)
    print(f"  Normal (full exposure)         {1-crisis_pct-caution_pct:.0%} of days")
    print(f"  Caution (0.7× exposure)        {caution_pct:.0%} of days")
    print(f"  Crisis  (0.4× exposure)        {crisis_pct:.0%} of days")
    print()
    print("Factor Leadership (days as top-weighted)")
    print("-" * 50)
    for factor, count in leader_counts.items():
        pct = count / len(portfolio.loc[portfolio["leader"] != ""])
        print(f"  {factor:<6}  {count:>4} days  ({pct:.0%})")
    print()

    ticker_df = per_ticker_metrics(prices, borrow_rate=0.0, initial_capital=INITIAL_CAPITAL)
    print("Per-Factor Buy-and-Hold Reference")
    print("-" * 50)
    print(ticker_df.to_string())
    print()

    portfolio.to_csv(os.path.join(OUTPUT_DIR, "factor_portfolio.csv"))
    ticker_df.to_csv(os.path.join(OUTPUT_DIR, "factor_per_ticker.csv"))
    print(f"[output] CSVs → {OUTPUT_DIR}/")

    # ── Plot ──────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        "Adaptive Factor Portfolio (AFP)\n"
        "QQQ · QUAL · MTUM · USMV  ·  Factor Leadership Tilt  ·  Correlation Regime Filter",
        fontsize=13, fontweight="bold",
    )
    colors = plt.cm.tab10.colors

    # Panel 1: Portfolio vs SPY vs T-bill (regime shading)
    ax = axes[0]
    _shade_regimes(ax, portfolio)
    port_r  = portfolio["portfolio_value"] / INITIAL_CAPITAL * 100
    spy_r   = spy_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100
    tbill_r = tbill_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100
    ax.plot(port_r.index,  port_r,  label="AFP", color="steelblue", linewidth=2.0)
    ax.plot(spy_r.index,   spy_r,   label="SPY (buy & hold)", color="darkorange",
            linestyle="--", linewidth=1.5)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL)", color="seagreen",
            linestyle=":", linewidth=1.3)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    legend_extra = [
        mpatches.Patch(color=_REGIME_COLORS["Caution"], alpha=0.6, label="Caution (0.7×)"),
        mpatches.Patch(color=_REGIME_COLORS["Crisis"],  alpha=0.6, label="Crisis (0.4×)"),
    ]
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles + legend_extra, fontsize=8, ncol=3)
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio vs Benchmarks  (shading = correlation regime)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: Per-factor cumulative P&L
    ax = axes[1]
    _shade_regimes(ax, portfolio)
    for i, col in enumerate(per_factor.columns):
        label = f"{col} – {TICKERS.get(col, col).split('(')[0].strip()}"
        ax.plot(per_factor.index, per_factor[col], label=label,
                color=colors[i % len(colors)], linewidth=1.4)
    ax.axhline(0, color="black", linewidth=0.5, linestyle=":")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title("Per-Factor Cumulative P&L Attribution")
    ax.legend(fontsize=8, ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: QQQ-USMV correlation + drawdown
    ax = axes[2]
    returns  = prices.pct_change()
    corr_ser = returns["QQQ"].rolling(CORR_WINDOW).corr(returns["USMV"])
    corr_ser = corr_ser.reindex(portfolio.index).ffill()

    ax.fill_between(corr_ser.index, corr_ser, 0, color="steelblue", alpha=0.25)
    ax.plot(corr_ser.index, corr_ser, color="steelblue", linewidth=0.8)
    ax.axhline(CORR_HIGH, color="firebrick", linewidth=1.2, linestyle="--",
               label=f"Crisis threshold ({CORR_HIGH:.0%})")
    ax.axhline(CORR_MID,  color="darkorange", linewidth=1.2, linestyle="--",
               label=f"Caution threshold ({CORR_MID:.0%})")
    ax.set_ylabel("QQQ vs USMV 20d Correlation", color="steelblue")
    ax.set_ylim(-0.2, 1.1)

    ax2 = ax.twinx()
    rolling_max = portfolio["portfolio_value"].cummax()
    drawdown    = (portfolio["portfolio_value"] - rolling_max) / rolling_max * 100
    ax2.fill_between(drawdown.index, drawdown, 0, color="tomato", alpha=0.35)
    ax2.set_ylabel("Drawdown (%)", color="tomato")
    ax2.tick_params(axis="y", labelcolor="tomato")
    ax.set_title("QQQ–USMV Correlation (regime signal) + Portfolio Drawdown")
    ax.legend(fontsize=8, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for a in axes:
        a.tick_params(axis="x", rotation=30)
        a.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "factor_portfolio.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
