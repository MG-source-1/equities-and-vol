"""
GARP Momentum — main runner.

Run from project root:
    python -m strategies.equities.garp_momentum.main
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
import matplotlib.patches as mpatches
import matplotlib.dates as mdates

from core.data import fetch_prices, fetch_tbill, fetch_spy
from core.metrics import compute_metrics
from strategies.equities.garp_momentum.fundamentals import fetch_garp_scores, build_garp_history, METRIC_WEIGHTS
from strategies.equities.garp_momentum.backtest import run_garp_backtest
from strategies.equities.garp_momentum.config import (
    TICKERS, START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR,
    TOP_N, MAX_WEIGHT,
    MOM_WEIGHT, GARP_WEIGHT,
    LOOKBACK_MONTHS, SKIP_MONTHS,
    TARGET_VOL, MAX_LEVERAGE, VOL_LOOKBACK,
    DRAWDOWN_STOP, TRANSACTION_COST,
)

_REGIME_LABELS = {1.0: "Normal", 0.6: "Caution", 0.3: "Defensive"}
_REGIME_COLORS = {"Caution": "#fff3cd", "Defensive": "#f8d7da"}

# Consistent colours for each ticker in charts
_TICKER_COLORS = {
    "AAPL": "#4c72b0", "MSFT": "#dd8452", "GOOGL": "#55a868",
    "META": "#c44e52", "NVDA": "#8172b3", "AMD":   "#937860",
    "AVGO": "#da8bc3", "QCOM": "#8c8c8c", "ORCL":  "#ccb974",
    "CRM":  "#64b5cd", "ADBE": "#e67e22", "NFLX":  "#e74c3c",
    "AMZN": "#ff9900", "TSLA": "#cc0000", "INTC":  "#0071c5",
}


# ── Helpers ───────────────────────────────────────────────────

def _fmt(v, kind="pct"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "  —"
    if kind == "pct":
        return f"{v:>6.1f}%"
    if kind == "x":
        return f"{v:>6.1f}x"
    if kind == "ratio":
        return f"{v:>6.2f}"
    return str(v)


def _shade_regime(ax, portfolio):
    if "regime_scale" not in portfolio.columns:
        return
    prev_date  = None
    prev_regime = None
    for date, scale in portfolio["regime_scale"].items():
        label = _REGIME_LABELS.get(round(scale, 1), "Normal")
        if prev_date is None:
            prev_date, prev_regime = date, label
            continue
        if label != prev_regime:
            color = _REGIME_COLORS.get(prev_regime)
            if color:
                ax.axvspan(prev_date, date, color=color, alpha=0.45, linewidth=0)
            prev_date, prev_regime = date, label
    if prev_regime and prev_date:
        color = _REGIME_COLORS.get(prev_regime)
        if color:
            ax.axvspan(prev_date, portfolio.index[-1], color=color, alpha=0.45, linewidth=0)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\n{'='*68}")
    print("  GARP MOMENTUM  (Growth at a Reasonable Price + Price Momentum)")
    print(f"{'='*68}")
    print(f"  Universe      : {', '.join(TICKERS)}")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Capital       : ${INITIAL_CAPITAL:,.0f}")
    print(f"  Holdings      : Top-{TOP_N} by composite rank  (max {MAX_WEIGHT:.0%}/stock)")
    print(f"  Signal        : {MOM_WEIGHT:.0%} price momentum ({LOOKBACK_MONTHS} mo, skip {SKIP_MONTHS})")
    print(f"                  {GARP_WEIGHT:.0%} GARP score (PEG·ROE·EV/EBITDA·FCF·Margin·D/E)")
    print(f"  Risk          : {TARGET_VOL:.0%} vol target  |  {DRAWDOWN_STOP:.0%} drawdown stop")
    print(f"  TC            : {TRANSACTION_COST*10000:.0f} bps/trade")
    print(f"{'='*68}\n")

    # ── Data ──────────────────────────────────────────────────
    print("[data] Fetching stock prices …")
    all_px = fetch_prices(TICKERS + ["SPY"], START_DATE, END_DATE)
    spy_prices = all_px["SPY"] if "SPY" in all_px.columns else None
    prices = all_px[[t for t in TICKERS if t in all_px.columns]]
    available = list(prices.columns)
    missing   = [t for t in TICKERS if t not in all_px.columns]
    if missing:
        print(f"[data] WARNING: missing tickers dropped: {missing}")

    print("[data] Fetching T-bill (BIL) …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Fetching SPY benchmark …")
    spy_cumulative = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[fundamentals] Building point-in-time GARP score history …")
    garp_history = build_garp_history(available, prices, cache_dir=DATA_CACHE_DIR)

    print("[fundamentals] Fetching current GARP scores for display …")
    garp_df = fetch_garp_scores(available, prices=prices, cache_dir=DATA_CACHE_DIR)

    # ── Print GARP table ──────────────────────────────────────
    sorted_garp = garp_df.sort_values("garp_score", ascending=False)
    print("\nGARP Fundamental Scores  (current snapshot — display only, backtest uses point-in-time)")
    print("─" * 74)
    print(f"  {'Ticker':<6}  {'PEG':>5}  {'ROE':>7}  {'EV/EBITDA':>9}  "
          f"{'FCF%':>6}  {'Margin':>7}  {'D/E':>6}  {'Score':>7}")
    print("─" * 74)
    for i, (tkr, row) in enumerate(sorted_garp.iterrows()):
        star = " ★" if i < TOP_N else "  "
        print(
            f"  {tkr:<6}{star}"
            f"  {_fmt(row.get('peg'),           'ratio')}"
            f"  {_fmt(row.get('roe_pct'),        'pct')}"
            f"  {_fmt(row.get('ev_ebitda'),      'x'):>9}"
            f"  {_fmt(row.get('fcf_yield_pct'),  'pct'):>6}"
            f"  {_fmt(row.get('net_margin_pct'), 'pct'):>7}"
            f"  {_fmt(row.get('debt_equity'),    'ratio'):>6}"
            f"  {row['garp_score']:.3f}"
        )
    print("─" * 74)
    print(f"  ★ = top-{TOP_N} GARP candidates (momentum determines final selection)\n")

    garp_df.to_csv(os.path.join(OUTPUT_DIR, "garp_scores.csv"))

    # ── Backtest ──────────────────────────────────────────────
    print("[backtest] Running …")
    portfolio = run_garp_backtest(
        prices         = prices,
        garp_scores    = garp_history,
        spy_prices     = spy_prices,
        tbill_daily_rate = tbill_rate,
        initial_capital  = INITIAL_CAPITAL,
        top_n            = TOP_N,
        lookback_months  = LOOKBACK_MONTHS,
        skip_months      = SKIP_MONTHS,
        garp_weight      = GARP_WEIGHT,
        mom_weight       = MOM_WEIGHT,
        max_weight       = MAX_WEIGHT,
        target_vol       = TARGET_VOL,
        max_leverage     = MAX_LEVERAGE,
        vol_lookback     = VOL_LOOKBACK,
        transaction_cost = TRANSACTION_COST,
        drawdown_stop_pct = DRAWDOWN_STOP,
    )

    # ── Metrics ───────────────────────────────────────────────
    metrics     = compute_metrics(portfolio, tbill_rate, INITIAL_CAPITAL)
    spy_aligned = spy_cumulative.reindex(portfolio.index).ffill()
    spy_total   = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1

    holding_freq = {}
    for held_str in portfolio["holdings"].dropna():
        for t in held_str.split(","):
            if t:
                holding_freq[t] = holding_freq.get(t, 0) + 1

    regime_counts = portfolio["regime_scale"].round(1).value_counts()
    caution_pct   = regime_counts.get(0.6, 0) / len(portfolio)
    defensive_pct = regime_counts.get(0.3, 0) / len(portfolio)
    switches      = (portfolio["holdings"] != portfolio["holdings"].shift()).sum()

    print("\nPortfolio Summary")
    print("─" * 52)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_total:.2%}")
    print()
    print("Regime Distribution (SPY momentum filter)")
    print("─" * 52)
    print(f"  Normal   (full exposure)          {1-caution_pct-defensive_pct:.0%} of days")
    print(f"  Caution  (0.6× exposure)          {caution_pct:.0%} of days")
    print(f"  Defensive (0.3× exposure)         {defensive_pct:.0%} of days")
    print()
    print("Stock Holding Frequency (days held)")
    print("─" * 52)
    for tkr, days in sorted(holding_freq.items(), key=lambda x: -x[1]):
        pct = days / len(portfolio)
        print(f"  {tkr:<6}  {days:>5} days  ({pct:.0%})")
    print(f"  Portfolio switches: {switches}")
    print()

    portfolio.to_csv(os.path.join(OUTPUT_DIR, "garp_portfolio.csv"))
    print(f"[output] CSVs → {OUTPUT_DIR}/")

    # ── Charts ────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        "GARP Momentum Strategy\n"
        "Growth at a Reasonable Price + Jegadeesh-Titman Momentum  ·  TMT/Large-Cap Universe",
        fontsize=13, fontweight="bold",
    )

    # Panel 1: Portfolio vs SPY vs T-bill (with regime shading)
    ax = axes[0]
    _shade_regime(ax, portfolio)
    port_r  = portfolio["portfolio_value"] / INITIAL_CAPITAL * 100
    spy_r   = spy_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100
    tbill_r = tbill_cumulative.reindex(portfolio.index).ffill() / INITIAL_CAPITAL * 100

    ax.plot(port_r.index,  port_r,  label="GARP Momentum", color="#2c7bb6", linewidth=2.2)
    ax.plot(spy_r.index,   spy_r,   label="SPY (buy & hold)", color="darkorange",
            linestyle="--", linewidth=1.5)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL)", color="seagreen",
            linestyle=":", linewidth=1.3)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    legend_extra = [
        mpatches.Patch(color=_REGIME_COLORS["Caution"],   alpha=0.55, label="Caution (0.6×)"),
        mpatches.Patch(color=_REGIME_COLORS["Defensive"], alpha=0.55, label="Defensive (0.3×)"),
    ]
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles + legend_extra, fontsize=8, ncol=3)
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks  (shading = SPY momentum regime)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: Holdings composition over time (stacked weight bars)
    ax = axes[1]
    # Resample to monthly for readability
    monthly_port = portfolio.resample("ME").last()
    held_matrix  = pd.DataFrame(0.0, index=monthly_port.index, columns=available)

    for date, row in monthly_port.iterrows():
        held_str = row.get("holdings", "")
        n = row.get("n_held", 0)
        if not held_str or n == 0:
            continue
        held = [t for t in held_str.split(",") if t]
        w_each = row.get("invested_weight", len(held) / TOP_N) / max(len(held), 1)
        for t in held:
            if t in held_matrix.columns:
                held_matrix.loc[date, t] = w_each

    bottom = np.zeros(len(held_matrix))
    for tkr in available:
        vals = held_matrix[tkr].values
        if vals.sum() == 0:
            continue
        color = _TICKER_COLORS.get(tkr, "#999999")
        ax.bar(held_matrix.index, vals, bottom=bottom, width=25,
               color=color, label=tkr, alpha=0.85)
        bottom += vals

    ax.set_ylabel("Approx. allocated weight")
    ax.set_ylim(0, 1.05)
    ax.set_title("Monthly Holdings Composition  (stacked weight by stock)")
    ax.legend(fontsize=7, ncol=5, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: Drawdown + stop periods
    ax = axes[2]
    rolling_max = portfolio["portfolio_value"].cummax()
    drawdown    = (portfolio["portfolio_value"] - rolling_max) / rolling_max * 100
    ax.fill_between(drawdown.index, drawdown, 0, color="tomato", alpha=0.5)

    if "stop_active" in portfolio.columns:
        stop = portfolio["stop_active"].astype(bool)
        s    = None
        for date, active in stop.items():
            if active and s is None:
                s = date
            elif not active and s is not None:
                ax.axvspan(s, date, color="gold", alpha=0.35, linewidth=0)
                s = None
        if s:
            ax.axvspan(s, portfolio.index[-1], color="gold", alpha=0.35, linewidth=0)

    ax.legend(handles=[
        mpatches.Patch(color="tomato", alpha=0.6, label="Drawdown"),
        mpatches.Patch(color="gold",   alpha=0.5, label="Stop active (cash)"),
    ], fontsize=8)
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Portfolio Drawdown  (gold = drawdown stop active)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for a in axes:
        a.tick_params(axis="x", rotation=30)
        a.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "garp_portfolio.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
