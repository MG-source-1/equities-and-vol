"""
Investor Portfolio — GARP Momentum + TRIAD + Cross-Asset Trend.

  40%  GARP  — TMT Growth-at-Reasonable-Price + Momentum.
               Individual stock alpha: selects top 5 from a 15-stock TMT
               universe using price momentum + fundamental quality (PEG,
               ROE, EV/EBITDA, FCF yield, net margin, D/E) from SEC EDGAR.
               Three internal risk overlays:
                 • 20% vol target   — scales exposure when volatility spikes
                 • SPY regime filter — cuts to 0.6× / 0.3× in market downtrends
                 • 15% drawdown stop — moves to cash for 21 days after large loss

  40%  TRIAD — Tri-Timescale TMT (same 15-stock universe + QQQ).
               Top-3 momentum concentration (months) + single-name panic
               dips (days) + QQQ index dips (days). Forward-validated
               out-of-sample on 2025-01 → 2026-06 (Sharpe 1.30).

  20%  XAT   — Cross-Asset Trend (SPY · TLT · GLD).
               Ranks SPY, TLT (bonds), and GLD (gold) by momentum each month.
               Participates in equity upside when SPY leads; rotates to bonds
               or gold in risk-off regimes. SPY is included so XAT can earn
               in good environments, not just protect in bad ones.

GARP and TRIAD trade the same TMT names but select differently (fundamental
quality vs pure price action) — the 40/40 split diversifies model risk.

SIS (SPY Intraday Short) is excluded because it requires 5-minute intraday
bars only available from 2020, which would shorten the backtest by 4 years.
It is retained as a reference strategy.

Run from project root:
    python -m strategies.combined_portfolio.main
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
import matplotlib.dates as mdates

from core.data import fetch_prices, fetch_tbill, fetch_spy
from core.metrics import compute_metrics

from strategies.garp_momentum.fundamentals import build_garp_history
from strategies.garp_momentum.backtest import run_garp_backtest
from strategies.garp_momentum.config import (
    TICKERS as GARP_TICKERS,
    TOP_N, MAX_WEIGHT as GARP_MAX_WEIGHT,
    MOM_WEIGHT, GARP_WEIGHT as GARP_SCORE_WEIGHT,
    LOOKBACK_MONTHS, SKIP_MONTHS,
    TARGET_VOL, MAX_LEVERAGE, VOL_LOOKBACK,
    DRAWDOWN_STOP, TRANSACTION_COST,
)

from core.alpaca import fetch_bars
from strategies.triad.backtest import run_triad_backtest
from strategies.triad import config as triad_cfg

from strategies.equity_factor_rotation.backtest import run_factor_backtest
from strategies.equity_factor_rotation.config import (
    LOOKBACK_MONTHS as AFP_LB, RANK_TILT,
    CORR_WINDOW, CORR_HIGH, CORR_MID,
    TARGET_VOL as AFP_VOL, MAX_WEIGHT as AFP_MAX_W,
    MAX_LEVERAGE as AFP_LEV, VOL_LOOKBACK as AFP_VOLLB,
    TRANSACTION_COST as AFP_TC, DRAWDOWN_STOP as AFP_DD,
)

from strategies.combined_portfolio.config import (
    START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR,
    WEIGHT_GARP, WEIGHT_TRIAD, WEIGHT_XAT,
    XAT_TICKERS,
)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    cap_garp  = INITIAL_CAPITAL * WEIGHT_GARP
    cap_triad = INITIAL_CAPITAL * WEIGHT_TRIAD
    cap_xat   = INITIAL_CAPITAL * WEIGHT_XAT

    print(f"\n{'='*68}")
    print(f"  INVESTOR PORTFOLIO  ({WEIGHT_GARP:.0%} GARP  ·  {WEIGHT_TRIAD:.0%} TRIAD  ·  {WEIGHT_XAT:.0%} XAT)")
    print(f"{'='*68}")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Total capital : ${INITIAL_CAPITAL:,.0f}")
    print(f"  GARP  {WEIGHT_GARP:.0%}  = ${cap_garp:,.0f}  TMT quality-momentum (EDGAR fundamentals)")
    print(f"  TRIAD {WEIGHT_TRIAD:.0%}  = ${cap_triad:,.0f}  Tri-timescale TMT (momentum + panic dips)")
    print(f"  XAT   {WEIGHT_XAT:.0%}  = ${cap_xat:,.0f}  Cross-Asset Trend (SPY · TLT · GLD)")
    print(f"  Design goal   : Sharpe > 1.0  |  Max DD < 25%")
    print(f"{'='*68}\n")

    # ── Fetch data ────────────────────────────────────────────
    print("[data] Fetching stock prices for GARP universe …")
    garp_all_px = fetch_prices(GARP_TICKERS + ["SPY"], START_DATE, END_DATE)
    spy_prices  = garp_all_px["SPY"] if "SPY" in garp_all_px.columns else None
    garp_prices = garp_all_px[[t for t in GARP_TICKERS if t in garp_all_px.columns]]

    print("[data] Fetching cross-asset prices (SPY · TLT · GLD) …")
    xat_prices = fetch_prices(list(XAT_TICKERS.keys()), START_DATE, END_DATE)

    print("[data] Fetching T-bill / BIL …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Fetching SPY benchmark …")
    spy_cumulative = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[fundamentals] Building point-in-time GARP score history …")
    garp_history = build_garp_history(
        list(garp_prices.columns), garp_prices, cache_dir=DATA_CACHE_DIR
    )

    # ── Run GARP ──────────────────────────────────────────────
    print("\n[GARP] Running TMT quality-momentum …")
    garp_portfolio = run_garp_backtest(
        prices            = garp_prices,
        garp_scores       = garp_history,
        spy_prices        = spy_prices,
        tbill_daily_rate  = tbill_rate,
        initial_capital   = cap_garp,
        top_n             = TOP_N,
        lookback_months   = LOOKBACK_MONTHS,
        skip_months       = SKIP_MONTHS,
        garp_weight       = GARP_SCORE_WEIGHT,
        mom_weight        = MOM_WEIGHT,
        max_weight        = GARP_MAX_WEIGHT,
        target_vol        = TARGET_VOL,
        max_leverage      = MAX_LEVERAGE,
        vol_lookback      = VOL_LOOKBACK,
        transaction_cost  = TRANSACTION_COST,
        drawdown_stop_pct = DRAWDOWN_STOP,
    )
    garp_ret = (garp_portfolio["portfolio_value"].iloc[-1] / cap_garp) - 1
    garp_m   = compute_metrics(garp_portfolio, tbill_rate, cap_garp)
    print(f"  GARP return: {garp_ret:+.1%}  |  Sharpe: {garp_m['Sharpe Ratio']}  |  Max DD: {garp_m['Max Drawdown']}")

    # ── Run TRIAD ─────────────────────────────────────────────
    print("[TRIAD] Running tri-timescale TMT …")
    triad_bars = {t: fetch_bars(t, START_DATE, END_DATE, "1Day",
                                cache_dir=DATA_CACHE_DIR, verbose=False)
                  for t in triad_cfg.TICKERS}
    qqq_bars = fetch_bars(triad_cfg.INDEX_TICKER, START_DATE, END_DATE, "1Day",
                          cache_dir=DATA_CACHE_DIR, verbose=False)
    triad_portfolio = run_triad_backtest(triad_bars, qqq_bars, tbill_rate,
                                         cap_triad, triad_cfg)
    triad_ret = (triad_portfolio["portfolio_value"].iloc[-1] / cap_triad) - 1
    triad_m   = compute_metrics(triad_portfolio, tbill_rate, cap_triad)
    print(f"  TRIAD return: {triad_ret:+.1%}  |  Sharpe: {triad_m['Sharpe Ratio']}  |  Max DD: {triad_m['Max Drawdown']}")

    # ── Run XAT ───────────────────────────────────────────────
    print("[XAT] Running cross-asset trend (SPY · TLT · GLD) …")
    xat_portfolio = run_factor_backtest(
        xat_prices, tbill_rate, cap_xat,
        AFP_LB, RANK_TILT,
        CORR_WINDOW, CORR_HIGH, CORR_MID,
        AFP_VOL, AFP_MAX_W, AFP_LEV, AFP_VOLLB,
        AFP_TC, AFP_DD,
    )
    xat_ret = (xat_portfolio["portfolio_value"].iloc[-1] / cap_xat) - 1
    xat_m   = compute_metrics(xat_portfolio, tbill_rate, cap_xat)
    print(f"  XAT return:  {xat_ret:+.1%}  |  Sharpe: {xat_m['Sharpe Ratio']}  |  Max DD: {xat_m['Max Drawdown']}")

    # ── Combine ───────────────────────────────────────────────
    print("\n[portfolio] Combining …")
    date_range   = garp_portfolio.index.union(xat_portfolio.index) \
                                       .union(triad_portfolio.index)
    garp_val     = garp_portfolio["portfolio_value"].reindex(date_range).ffill().fillna(cap_garp)
    triad_val    = triad_portfolio["portfolio_value"].reindex(date_range).ffill().fillna(cap_triad)
    xat_val      = xat_portfolio["portfolio_value"].reindex(date_range).ffill().fillna(cap_xat)
    combined_val = garp_val + triad_val + xat_val

    combined = pd.DataFrame(index=date_range)
    combined["portfolio_value"] = combined_val
    combined["daily_return"]    = combined_val.pct_change().fillna(0)

    # ── Metrics ───────────────────────────────────────────────
    metrics      = compute_metrics(combined, tbill_rate, INITIAL_CAPITAL)
    spy_aligned  = spy_cumulative.reindex(combined.index).ffill()
    spy_tot      = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1
    combined_tot = (combined_val.iloc[-1] / INITIAL_CAPITAL) - 1

    print("\nInvestor Portfolio Summary")
    print("─" * 56)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_tot:.2%}")

    print("\nComponent Breakdown")
    print("─" * 56)
    for label, pf, cap in [
        (f"GARP  {WEIGHT_GARP:.0%}",  garp_portfolio,  cap_garp),
        (f"TRIAD {WEIGHT_TRIAD:.0%}", triad_portfolio, cap_triad),
        (f"XAT   {WEIGHT_XAT:.0%}",   xat_portfolio,   cap_xat),
    ]:
        ret = (pf["portfolio_value"].iloc[-1] / cap) - 1
        m   = compute_metrics(pf, tbill_rate, cap)
        print(f"  {label}  return={ret:+.1%}  sharpe={m['Sharpe Ratio']}  max_dd={m['Max Drawdown']}")

    print(f"\n  Combined total return : {combined_tot:+.1%}")
    print(f"  SPY buy-and-hold      : {spy_tot:+.1%}")
    print(f"  Excess vs SPY         : {combined_tot - spy_tot:+.1%}")

    combined.to_csv(os.path.join(OUTPUT_DIR, "investor_portfolio.csv"))
    print(f"\n[output] CSV → {OUTPUT_DIR}/investor_portfolio.csv")

    # ── Charts ────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        f"Investor Portfolio  ({WEIGHT_GARP:.0%} GARP  ·  {WEIGHT_TRIAD:.0%} TRIAD  ·  {WEIGHT_XAT:.0%} XAT)\n"
        "TMT quality-momentum  +  tri-timescale TMT  +  cross-asset rotation (SPY · TLT · GLD)",
        fontsize=11, fontweight="bold",
    )

    # Panel 1: Portfolio vs SPY vs T-bill
    ax = axes[0]
    port_r  = combined_val / INITIAL_CAPITAL * 100
    spy_r   = spy_aligned / INITIAL_CAPITAL * 100
    tbill_r = tbill_cumulative.reindex(combined.index).ffill() / INITIAL_CAPITAL * 100
    ax.plot(port_r.index,  port_r,  label="Investor Portfolio", color="steelblue", linewidth=2.2)
    ax.plot(spy_r.index,   spy_r,   label="SPY (buy & hold)",   color="darkorange",
            linestyle="--", linewidth=1.5)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL)",       color="seagreen",
            linestyle=":", linewidth=1.2)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: Stacked P&L by sleeve
    ax = axes[1]
    g = garp_val  - cap_garp
    t = triad_val - cap_triad
    x = xat_val   - cap_xat
    ax.fill_between(g.index, 0, g,             color="#2c7bb6", alpha=0.75,
                    label=f"GARP {WEIGHT_GARP:.0%} (EDGAR quality-momentum)")
    ax.fill_between(t.index, g, g + t,         color="#d7761b", alpha=0.75,
                    label=f"TRIAD {WEIGHT_TRIAD:.0%} (tri-timescale TMT)")
    ax.fill_between(x.index, g + t, g + t + x, color="#e9c46a", alpha=0.75,
                    label=f"XAT {WEIGHT_XAT:.0%} (SPY · TLT · GLD)")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title("Stacked P&L by sleeve")
    ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: Drawdown vs SPY
    ax = axes[2]
    for vals, label, color, lw, ls in [
        (combined_val, "Investor Portfolio", "steelblue",  2.2, "-"),
        (spy_aligned,  "SPY B&H",            "darkorange", 1.3, "--"),
    ]:
        rm = vals.cummax()
        dd = (vals - rm) / rm * 100
        ax.fill_between(dd.index, dd, 0, color=color, alpha=0.20)
        ax.plot(dd.index, dd, color=color, linewidth=lw, linestyle=ls, label=label)
    ax.axhline(-25, color="black", linewidth=0.8, linestyle=":", alpha=0.6,
               label="−25% reference line")
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Drawdown vs SPY")
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
