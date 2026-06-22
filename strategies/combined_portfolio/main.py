"""
Investor Portfolio — designed for real-world allocability, not backtest maximisation.

Why this beats the 75/20/5 Tech-Momentum portfolio:
  • Sharpe > 1 target — a high-Sharpe portfolio can be levered to any
    return target with LESS risk than chasing raw returns directly.
  • Genuine cross-asset diversification — TLT and GLD don't crash when
    semiconductors crash.  The tech-momentum portfolio had three equity-
    correlated strategies; this one has an equity sleeve, a cross-asset
    sleeve, and a market-neutral sleeve.
  • No regime-specific bets — the 75% SOXX allocation was a bet that the
    AI semiconductor bull would continue.  This portfolio is designed to
    work across multiple market regimes.
  • Drawdown < 20% target — in practice, investors exit at -30%.  A
    strategy that limits drawdowns is one investors actually stay in.

Allocation (50 / 30 / 20):
  50%  AFP   — Adaptive Factor Portfolio (equity factors, Sharpe 0.97)
               QQQ · QUAL · MTUM · USMV with correlation regime filter
  30%  XAT   — Cross-Asset Trend (SPY · TLT · GLD momentum)
               Same AFP engine, different universe, no correlation filter.
               TLT and GLD provide genuine drawdown protection.
  20%  SIS   — SPY Intraday Afternoon Short (market-neutral alpha)
               Earns on a different clock, partially negative equity correlation.

Run from project root:
    python -m strategies.combined_portfolio.investor_main
"""

import os, sys
from pathlib import Path

try:
    _ROOT = str(Path(__file__).resolve().parent.parent.parent)
except (PermissionError, OSError):
    _raw  = __file__.replace("\\", "/")
    _ROOT = _raw.split("/strategies/")[0] if "/strategies/" in _raw else ""

if _ROOT and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path[:] = [p for p in sys.path if p and p not in ('.', '')]

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates

from core.data import fetch_prices, fetch_tbill, fetch_spy
from core.metrics import compute_metrics

from strategies.equity_factor_rotation.backtest import run_factor_backtest
from strategies.equity_factor_rotation.config import (
    TICKERS as AFP_TICKERS,
    LOOKBACK_MONTHS, RANK_TILT,
    CORR_WINDOW, CORR_HIGH, CORR_MID,
    TARGET_VOL, MAX_WEIGHT, MAX_LEVERAGE, VOL_LOOKBACK,
    TRANSACTION_COST, DRAWDOWN_STOP,
)

from strategies.spy_intraday_short.data_intraday import fetch_bars as fetch_intraday
from strategies.spy_intraday_short.strategy import compute_daily_signals, run_intraday_backtest
from strategies.spy_intraday_short.config import (
    MIN_MORNING_MOVE, MIN_OVERNIGHT_GAP,
    TC as SIS_TC, DD_STOP as SIS_STOP,
)

from strategies.combined_portfolio.config import (
    START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR,
)

# ── Investor weights ──────────────────────────────────────────
WEIGHT_AFP = 0.50   # Equity factors — best Sharpe in the toolkit
WEIGHT_XAT = 0.30   # Cross-asset trend — genuine diversification
WEIGHT_SIS = 0.20   # Intraday short — uncorrelated daily alpha

# ── Cross-asset universe ──────────────────────────────────────
# SPY: equities (risk-on), TLT: long bonds (deflation/risk-off),
# GLD: gold (inflation/crisis hedge).  These three have near-zero
# pairwise correlation in normal markets and negative correlation in crises.
XAT_TICKERS = {
    "SPY": "SPDR S&P 500 ETF",
    "TLT": "iShares 20+ Year Treasury Bond",
    "GLD": "SPDR Gold Shares",
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    cap_afp = INITIAL_CAPITAL * WEIGHT_AFP
    cap_xat = INITIAL_CAPITAL * WEIGHT_XAT
    cap_sis = INITIAL_CAPITAL * WEIGHT_SIS

    print(f"\n{'='*66}")
    print("  INVESTOR PORTFOLIO  (50 / 30 / 20)")
    print(f"{'='*66}")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Total capital : ${INITIAL_CAPITAL:,.0f}")
    print(f"  AFP  50%  = ${cap_afp:,.0f}  Equity Factor Portfolio")
    print(f"  XAT  30%  = ${cap_xat:,.0f}  Cross-Asset Trend (SPY·TLT·GLD)")
    print(f"  SIS  20%  = ${cap_sis:,.0f}  SPY Intraday Short")
    print(f"  Design goal   : Sharpe > 1.0  |  Max DD < 20%")
    print(f"{'='*66}\n")

    # ── Fetch data ────────────────────────────────────────────
    print("[data] Downloading equity factor prices …")
    afp_prices = fetch_prices(list(AFP_TICKERS.keys()), START_DATE, END_DATE)

    print("[data] Downloading cross-asset prices …")
    xat_prices = fetch_prices(list(XAT_TICKERS.keys()), START_DATE, END_DATE)

    print("[data] Downloading T-bill / BIL …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Downloading SPY benchmark …")
    spy_cumulative = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    # ── Run AFP ───────────────────────────────────────────────
    print("\n[AFP] Running equity factor portfolio …")
    afp_portfolio = run_factor_backtest(
        afp_prices, tbill_rate, cap_afp,
        LOOKBACK_MONTHS, RANK_TILT,
        CORR_WINDOW, CORR_HIGH, CORR_MID,
        TARGET_VOL, MAX_WEIGHT, MAX_LEVERAGE, VOL_LOOKBACK,
        TRANSACTION_COST, DRAWDOWN_STOP,
    )
    afp_ret = (afp_portfolio["portfolio_value"].iloc[-1] / cap_afp) - 1
    print(f"  AFP total return: {afp_ret:+.1%}")

    # ── Run Cross-Asset Trend ─────────────────────────────────
    # Same AFP engine on SPY/TLT/GLD — no QQQ/USMV present so the
    # correlation filter returns 1.0 (disabled), giving pure cross-asset
    # momentum with inverse-vol sizing.
    print("[XAT] Running cross-asset trend (SPY · TLT · GLD) …")
    xat_portfolio = run_factor_backtest(
        xat_prices, tbill_rate, cap_xat,
        LOOKBACK_MONTHS, 1.0,             # no rank tilt for cross-asset
        CORR_WINDOW, CORR_HIGH, CORR_MID, # filter inactive (no QQQ/USMV)
        TARGET_VOL, 0.60, MAX_LEVERAGE, VOL_LOOKBACK,  # wider per-asset cap (3 assets)
        TRANSACTION_COST, DRAWDOWN_STOP,
    )
    xat_ret = (xat_portfolio["portfolio_value"].iloc[-1] / cap_xat) - 1
    print(f"  XAT total return: {xat_ret:+.1%}")

    # ── Run SIS ───────────────────────────────────────────────
    print("[SIS] Running intraday afternoon short …")
    bars        = fetch_intraday("SPY", START_DATE, END_DATE,
                                 timeframe="5Min", cache_dir=DATA_CACHE_DIR)
    sis_signals = compute_daily_signals(bars, MIN_MORNING_MOVE, MIN_OVERNIGHT_GAP)
    sis_portfolio = run_intraday_backtest(
        sis_signals, tbill_rate, cap_sis, SIS_TC, SIS_STOP,
    )
    sis_ret = (sis_portfolio["portfolio_value"].iloc[-1] / cap_sis) - 1
    print(f"  SIS total return: {sis_ret:+.1%}")

    # ── Combine ───────────────────────────────────────────────
    print("\n[portfolio] Combining …")
    date_range = (afp_portfolio.index
                  .union(xat_portfolio.index)
                  .union(sis_portfolio.index))

    afp_val = afp_portfolio["portfolio_value"].reindex(date_range).ffill().fillna(cap_afp)
    xat_val = xat_portfolio["portfolio_value"].reindex(date_range).ffill().fillna(cap_xat)
    sis_val = sis_portfolio["portfolio_value"].reindex(date_range).ffill().fillna(cap_sis)

    combined_val = afp_val + xat_val + sis_val
    combined     = pd.DataFrame(index=date_range)
    combined["portfolio_value"] = combined_val
    combined["daily_return"]    = combined_val.pct_change().fillna(0)
    combined["in_regime"]       = True

    # ── Metrics ───────────────────────────────────────────────
    metrics  = compute_metrics(combined, tbill_rate, INITIAL_CAPITAL)
    spy_t    = spy_cumulative.reindex(combined.index).ffill()
    spy_tot  = (spy_t.iloc[-1] / spy_t.iloc[0]) - 1
    combined_tot = (combined_val.iloc[-1] / INITIAL_CAPITAL) - 1

    print("\nInvestor Portfolio Summary")
    print("-" * 54)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_tot:.2%}")

    print("\nComponent Summary")
    print("-" * 54)
    rows = [
        ("AFP  50%", afp_portfolio, cap_afp),
        ("XAT  30%", xat_portfolio, cap_xat),
        ("SIS  20%", sis_portfolio, cap_sis),
    ]
    for label, pf, cap in rows:
        ret = (pf["portfolio_value"].iloc[-1] / cap) - 1
        m   = compute_metrics(pf, tbill_rate, cap)
        print(f"  {label}  return={ret:+.1%}  sharpe={m['Sharpe Ratio']}  "
              f"max_dd={m['Max Drawdown']}")

    print(f"\n  Combined total return : {combined_tot:+.1%}")
    print(f"  SPY buy-and-hold      : {spy_tot:+.1%}")
    print(f"  Excess vs SPY         : {combined_tot - spy_tot:+.1%}")

    combined.to_csv(os.path.join(OUTPUT_DIR, "investor_portfolio.csv"))
    print(f"\n[output] CSV → {OUTPUT_DIR}/investor_portfolio.csv")

    # ── Plot ──────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        "Investor Portfolio  (50% AFP  ·  30% Cross-Asset Trend  ·  20% Intraday Short)\n"
        "Designed for Sharpe > 1 and Max DD < 20%  —  not for maximum raw return",
        fontsize=12, fontweight="bold",
    )

    # Panel 1: Investor portfolio vs SPY vs previous combined
    ax = axes[0]
    inv_r  = combined_val / INITIAL_CAPITAL * 100
    spy_r  = spy_t / INITIAL_CAPITAL * 100
    tb_r   = tbill_cumulative.reindex(combined.index).ffill() / INITIAL_CAPITAL * 100
    ax.plot(inv_r.index, inv_r,  label="Investor Portfolio", color="steelblue", linewidth=2.2)
    ax.plot(spy_r.index, spy_r,  label="SPY (buy & hold)",   color="darkorange",
            linestyle="--", linewidth=1.5)
    ax.plot(tb_r.index,  tb_r,   label="T-bill (BIL)",       color="seagreen",
            linestyle=":", linewidth=1.2)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: Stacked P&L contribution
    ax = axes[1]
    a = afp_val - cap_afp
    x = xat_val - cap_xat
    s = sis_val - cap_sis
    ax.fill_between(a.index, 0, a, color="steelblue", alpha=0.75,
                    label=f"AFP 50% (equity factors)")
    ax.fill_between(x.index, a, a + x, color="#e9c46a", alpha=0.75,
                    label=f"XAT 30% (SPY·TLT·GLD trend)")
    ax.fill_between(s.index, a + x, a + x + s, color="seagreen", alpha=0.75,
                    label=f"SIS 20% (intraday short)")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title("Stacked P&L — three uncorrelated return sources")
    ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: Drawdown comparison
    ax = axes[2]
    for vals, init, label, color, lw, ls in [
        (combined_val, INITIAL_CAPITAL, "Investor Portfolio", "steelblue", 2.2, "-"),
        (spy_t, INITIAL_CAPITAL, "SPY B&H", "darkorange", 1.3, "--"),
    ]:
        rm = vals.cummax()
        dd = (vals - rm) / rm * 100
        ax.fill_between(dd.index, dd, 0, color=color, alpha=0.25)
        ax.plot(dd.index, dd, color=color, linewidth=lw, linestyle=ls, label=label)

    ax.axhline(-20, color="black", linewidth=0.8, linestyle=":",
               alpha=0.6, label="−20% institutional tolerance")
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Drawdown vs SPY  (dotted line = typical institutional limit)")
    ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for a in axes:
        a.tick_params(axis="x", rotation=30)
        a.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "investor_portfolio.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
