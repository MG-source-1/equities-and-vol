"""
Investor Portfolio — GARP Momentum + TRIAD + T-bills.

  45%  GARP  — TMT Growth-at-Reasonable-Price + Momentum.
               Individual stock alpha: selects top 5 from a 15-stock TMT
               universe using price momentum + fundamental quality (PEG,
               ROE, EV/EBITDA, FCF yield, net margin, D/E) from SEC EDGAR.
               Three internal risk overlays:
                 • 20% vol target   — scales exposure when volatility spikes
                 • SPY regime filter — cuts to 0.6× / 0.3× in market downtrends
                 • 15% drawdown stop — moves to cash for 21 days after large loss

  45%  TRIAD — Tri-Timescale TMT (same 15-stock universe + QQQ).
               Top-3 momentum concentration (months) + single-name panic
               dips (days) + QQQ index dips (days). Forward-validated
               out-of-sample on 2025-01 → 2026-06 (Sharpe 1.38).

  10%  T-bills (BIL) — dry powder. GARP and TRIAD are two expressions of
               one market bet (long US mega-cap TMT momentum); the cash
               sleeve is the acknowledgment that no overlay inside them
               diversifies that regime risk. Replaced the former 20% XAT
               sleeve, which T-bills strictly dominated at every weight
               tested (more return, equal-or-better Sharpe, smaller
               drawdown — including in the COVID and 2022 episodes).

GARP and TRIAD trade the same TMT names but select differently (fundamental
quality vs pure price action) — the 45/45 split diversifies model risk.

SIS (SPY Intraday Short) is excluded because it requires 5-minute intraday
bars only available from 2020, which would shorten the backtest by 4 years.
It is retained as a reference strategy, as is XAT (cross-asset trend).

Run from project root:
    python -m strategies.equities.combined_portfolio.main
"""

import os, sys
from pathlib import Path

try:
    _ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
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

from strategies.equities.garp_momentum.fundamentals import build_garp_history
from strategies.equities.garp_momentum.backtest import run_garp_backtest
from strategies.equities.garp_momentum.config import (
    TICKERS as GARP_TICKERS,
    TOP_N, MAX_WEIGHT as GARP_MAX_WEIGHT,
    MOM_WEIGHT, GARP_WEIGHT as GARP_SCORE_WEIGHT,
    LOOKBACK_MONTHS, SKIP_MONTHS,
    TARGET_VOL, MAX_LEVERAGE, VOL_LOOKBACK,
    DRAWDOWN_STOP, TRANSACTION_COST,
)

from core.alpaca import fetch_bars
from strategies.equities.triad.backtest import run_triad_backtest
from strategies.equities.triad import config as triad_cfg

from strategies.equities.combined_portfolio.config import (
    START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR,
    WEIGHT_GARP, WEIGHT_TRIAD, WEIGHT_TBILL,
)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    cap_garp  = INITIAL_CAPITAL * WEIGHT_GARP
    cap_triad = INITIAL_CAPITAL * WEIGHT_TRIAD
    cap_bil   = INITIAL_CAPITAL * WEIGHT_TBILL

    print(f"\n{'='*68}")
    print(f"  INVESTOR PORTFOLIO  ({WEIGHT_GARP:.0%} GARP  ·  {WEIGHT_TRIAD:.0%} TRIAD  ·  {WEIGHT_TBILL:.0%} T-bills)")
    print(f"{'='*68}")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Total capital : ${INITIAL_CAPITAL:,.0f}")
    print(f"  GARP   {WEIGHT_GARP:.0%}  = ${cap_garp:,.0f}  TMT quality-momentum (EDGAR fundamentals)")
    print(f"  TRIAD  {WEIGHT_TRIAD:.0%}  = ${cap_triad:,.0f}  Tri-timescale TMT (momentum + panic dips)")
    print(f"  T-bill {WEIGHT_TBILL:.0%}  = ${cap_bil:,.0f}  BIL — dry powder / regime-risk buffer")
    print(f"  Design goal   : Sharpe > 1.0  |  Max DD < 25%")
    print(f"{'='*68}\n")

    # ── Fetch data ────────────────────────────────────────────
    print("[data] Fetching stock prices for GARP universe …")
    garp_all_px = fetch_prices(GARP_TICKERS + ["SPY"], START_DATE, END_DATE)
    spy_prices  = garp_all_px["SPY"] if "SPY" in garp_all_px.columns else None
    garp_prices = garp_all_px[[t for t in GARP_TICKERS if t in garp_all_px.columns]]

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

    # ── Combine ───────────────────────────────────────────────
    # Constant-mix: sleeves are rebalanced back to their target weights
    # daily, matching live/rebalance.py, which sizes every sleeve as a fixed
    # fraction of TOTAL account equity each day. (Summing sleeve equity
    # curves instead would let the mix drift for years — e.g. GARP's share
    # ballooning as it compounds — an allocation live never holds.)
    # Cross-sleeve rebalancing flows are small daily; each sleeve already
    # charges its own transaction costs. The T-bill sleeve earns the BIL
    # daily return — live it is held as an actual BIL position.
    print("\n[portfolio] Combining (daily-rebalanced constant mix) …")
    date_range   = garp_portfolio.index.union(triad_portfolio.index)
    garp_ret_d   = garp_portfolio["daily_return"].reindex(date_range).fillna(0.0)
    triad_ret_d  = triad_portfolio["daily_return"].reindex(date_range).fillna(0.0)
    bil_ret_d    = tbill_rate.reindex(date_range).ffill().fillna(0.0)
    combined_ret = (WEIGHT_GARP * garp_ret_d + WEIGHT_TRIAD * triad_ret_d
                    + WEIGHT_TBILL * bil_ret_d)
    combined_val = INITIAL_CAPITAL * (1 + combined_ret).cumprod()

    combined = pd.DataFrame(index=date_range)
    combined["portfolio_value"] = combined_val
    combined["daily_return"]    = combined_ret

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
    ]:
        ret = (pf["portfolio_value"].iloc[-1] / cap) - 1
        m   = compute_metrics(pf, tbill_rate, cap)
        print(f"  {label}  return={ret:+.1%}  sharpe={m['Sharpe Ratio']}  max_dd={m['Max Drawdown']}")
    bil_tot = (1 + bil_ret_d).prod() - 1
    print(f"  T-bill {WEIGHT_TBILL:.0%}  return={bil_tot:+.1%}  (BIL, held as an ETF position live)")

    print(f"\n  Combined total return : {combined_tot:+.1%}")
    print(f"  SPY buy-and-hold      : {spy_tot:+.1%}")
    print(f"  Excess vs SPY         : {combined_tot - spy_tot:+.1%}")

    combined.to_csv(os.path.join(OUTPUT_DIR, "investor_portfolio.csv"))
    print(f"\n[output] CSV → {OUTPUT_DIR}/investor_portfolio.csv")

    # ── Charts ────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        f"Investor Portfolio  ({WEIGHT_GARP:.0%} GARP  ·  {WEIGHT_TRIAD:.0%} TRIAD  ·  {WEIGHT_TBILL:.0%} T-bills)\n"
        "TMT quality-momentum  +  tri-timescale TMT  +  T-bill dry powder (BIL)",
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

    # Panel 2: Stacked P&L by sleeve — daily dollar contribution under the
    # constant mix (sleeve weight × sleeve return × prior portfolio value),
    # so the three bands sum exactly to combined P&L.
    ax = axes[1]
    prior_val = combined_val.shift(1).fillna(INITIAL_CAPITAL)
    g = (WEIGHT_GARP  * garp_ret_d  * prior_val).cumsum()
    t = (WEIGHT_TRIAD * triad_ret_d * prior_val).cumsum()
    x = (WEIGHT_TBILL * bil_ret_d   * prior_val).cumsum()
    ax.fill_between(g.index, 0, g,             color="#2c7bb6", alpha=0.75,
                    label=f"GARP {WEIGHT_GARP:.0%} (EDGAR quality-momentum)")
    ax.fill_between(t.index, g, g + t,         color="#d7761b", alpha=0.75,
                    label=f"TRIAD {WEIGHT_TRIAD:.0%} (tri-timescale TMT)")
    ax.fill_between(x.index, g + t, g + t + x, color="#e9c46a", alpha=0.75,
                    label=f"T-bills {WEIGHT_TBILL:.0%} (BIL)")
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
