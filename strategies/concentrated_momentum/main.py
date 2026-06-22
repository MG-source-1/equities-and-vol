"""
Tech-Tier Momentum Ladder — main runner.

Run from project root:
    python -m strategies.concentrated_momentum.main
"""

import os, sys
from pathlib import Path

# For absolute __file__ (e.g. when using `python -m`), Path.resolve() uses
# os.path.realpath which calls lstat() — NOT getcwd() — so it works even
# when macOS restricts cwd access.  For relative __file__ we fall back to
# string parsing (no filesystem calls at all).
try:
    _ROOT = str(Path(__file__).resolve().parent.parent.parent)
except (PermissionError, OSError):
    _raw  = __file__.replace("\\", "/")
    _ROOT = _raw.split("/strategies/")[0] if "/strategies/" in _raw else ""

if _ROOT and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Strip cwd-relative entries ('', '.') so Python never has to call getcwd()
# when scanning sys.path for imports.
sys.path[:] = [p for p in sys.path if p and p not in ('.', '')]

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

from core.data import fetch_prices, fetch_tbill, fetch_spy
from core.metrics import compute_metrics
from strategies.concentrated_momentum.backtest import run_momentum_backtest
from strategies.concentrated_momentum.config import (
    TICKERS, CASH_TICKER, START_DATE, END_DATE, INITIAL_CAPITAL,
    OUTPUT_DIR, DATA_CACHE_DIR, LOOKBACK_MONTHS, SKIP_MONTHS,
    DRAWDOWN_STOP, TRANSACTION_COST,
)

_HOLDING_COLORS = {
    "SOXX":       "#e63946",   # red — semiconductors
    "QQQ":        "#457b9d",   # blue — Nasdaq
    "SPY":        "#2a9d8f",   # teal — S&P 500
    "BIL":        "#adb5bd",   # grey — cash
    "BIL (warmup)": "#e9ecef",
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    tickers = list(TICKERS.keys())
    print(f"\n{'='*64}")
    print("  TECH-TIER MOMENTUM LADDER")
    print(f"{'='*64}")
    print(f"  Universe      : {', '.join(tickers)}  →  BIL (cash)")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Capital       : ${INITIAL_CAPITAL:,.0f}")
    print(f"  Signal        : {LOOKBACK_MONTHS}-{SKIP_MONTHS} month momentum ranking")
    print(f"  Rule          : Hold top-ranked asset if momentum > 0, else BIL")
    print(f"  Drawdown stop : {DRAWDOWN_STOP:.0%}  |  TC: {TRANSACTION_COST*10000:.0f} bps/trade")
    print(f"  Data          : Alpaca SIP  |  Academic basis: Antonacci (2014)")
    print(f"{'='*64}\n")

    print("[data] Downloading ETF prices …")
    prices = fetch_prices(tickers, START_DATE, END_DATE)

    print("[data] Downloading T-bill / BIL …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Downloading SPY benchmark …")
    spy_cumulative = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    available = list(prices.columns)
    print(f"[data] Available: {available}\n")

    print("[backtest] Running …")
    portfolio = run_momentum_backtest(
        prices,
        bil_daily_return=tbill_rate,
        initial_capital=INITIAL_CAPITAL,
        lookback_months=LOOKBACK_MONTHS,
        skip_months=SKIP_MONTHS,
        transaction_cost=TRANSACTION_COST,
        drawdown_stop_pct=DRAWDOWN_STOP,
    )

    # ── Metrics ───────────────────────────────────────────────
    metrics     = compute_metrics(portfolio, tbill_rate, INITIAL_CAPITAL)
    spy_aligned = spy_cumulative.reindex(portfolio.index).ffill()
    spy_total   = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1

    holding_counts = portfolio["holding"].value_counts()
    total_days     = len(portfolio)
    switches = (portfolio["holding"] != portfolio["holding"].shift()).sum()

    print("Portfolio Summary")
    print("-" * 52)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_total:.2%}")
    print()
    print("Holdings Breakdown")
    print("-" * 52)
    for ticker, days in holding_counts.items():
        if "warmup" in str(ticker):
            continue
        pct = days / total_days
        print(f"  {ticker:<10} {days:>5} days ({pct:.0%})")
    print(f"  Portfolio switches: {switches}")
    print()

    # Per-asset buy-and-hold reference
    print("Individual ETF Buy-and-Hold Reference (2016-2024)")
    print("-" * 52)
    for ticker in available:
        px = prices[ticker].dropna()
        total = (px.iloc[-1] / px.iloc[0]) - 1
        ann   = (1 + total) ** (252 / len(px)) - 1
        print(f"  {ticker:<6} total={total:+.1%}  annualised={ann:+.1%}")
    bil_total = (1 + tbill_rate).prod() - 1
    print(f"  {'BIL':<6} total={bil_total:+.1%}  (T-bill proxy)")
    print()

    portfolio.to_csv(os.path.join(OUTPUT_DIR, "momentum_portfolio.csv"))
    print(f"[output] CSV → {OUTPUT_DIR}/momentum_portfolio.csv")

    # ── Plot ──────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 14))
    fig.suptitle(
        "Tech-Tier Momentum Ladder  (Dual Momentum — Antonacci 2014)\n"
        "Hold top-ranked asset each month: SOXX → QQQ → SPY → BIL",
        fontsize=13, fontweight="bold",
    )

    # Panel 1: Portfolio vs SPY vs T-bill
    ax = axes[0]
    port_r  = portfolio["portfolio_value"] / INITIAL_CAPITAL * 100
    spy_r   = spy_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100
    tbill_r = tbill_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100

    ax.plot(port_r.index,  port_r,  label="Tech Momentum Ladder", color="#e63946", linewidth=2.0)
    ax.plot(spy_r.index,   spy_r,   label="SPY (buy & hold)",      color="dimgray",  linestyle="--", linewidth=1.5)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL)",          color="seagreen", linestyle=":",  linewidth=1.2)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: Asset held over time (color-coded timeline)
    ax = axes[1]
    holdings = portfolio["holding"]
    for i in range(len(holdings) - 1):
        d1   = holdings.index[i]
        d2   = holdings.index[i + 1]
        held = holdings.iloc[i]
        ax.axvspan(d1, d2, color=_HOLDING_COLORS.get(held, "white"), alpha=0.85, linewidth=0)

    legend_patches = [
        mpatches.Patch(color=_HOLDING_COLORS["SOXX"], label=f"SOXX  ({holding_counts.get('SOXX', 0)}d)"),
        mpatches.Patch(color=_HOLDING_COLORS["QQQ"],  label=f"QQQ   ({holding_counts.get('QQQ', 0)}d)"),
        mpatches.Patch(color=_HOLDING_COLORS["SPY"],  label=f"SPY   ({holding_counts.get('SPY', 0)}d)"),
        mpatches.Patch(color=_HOLDING_COLORS["BIL"],  label=f"BIL/Cash ({holding_counts.get('BIL', 0)}d)"),
    ]
    ax.set_yticks([])
    ax.set_ylabel("Asset held")
    ax.set_title("Monthly Holding — which asset the strategy owned each day")
    ax.legend(handles=legend_patches, fontsize=9, ncol=4, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: Drawdown
    ax = axes[2]
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
    ax.set_title("Portfolio Drawdown  (gold = stop active)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for a in axes:
        a.tick_params(axis="x", rotation=30)
        a.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "momentum_ladder.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
