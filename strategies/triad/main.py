"""
TRIAD — Tri-Timescale TMT — main runner.

Run from project root:
    python -m strategies.triad.main
"""

import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from core.alpaca import fetch_bars
from core.data import fetch_spy, fetch_tbill
from core.metrics import compute_metrics
from strategies.triad.backtest import run_triad_backtest
from strategies.triad import config as cfg


def _sub_period_sharpes(portfolio, tbill_rate):
    out = []
    for a, b in [("2016-10", "2019-12"), ("2020-01", "2022-12"),
                 ("2023-01", "2024-12"), ("2025-01", "2026-06")]:
        r = portfolio["daily_return"].dropna().loc[a:b]
        if len(r) < 50:
            continue
        total   = (1 + r).prod() - 1
        ann_ret = (1 + total) ** (252 / len(r)) - 1
        ann_vol = r.std() * np.sqrt(252)
        rf      = tbill_rate.reindex(r.index).ffill().dropna()
        rf_ann  = (1 + rf.mean()) ** 252 - 1
        out.append((a, b, (ann_ret - rf_ann) / ann_vol if ann_vol > 0 else np.nan, ann_ret))
    return out


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

    print(f"\n{'='*68}")
    print("  TRIAD — TRI-TIMESCALE TMT")
    print(f"{'='*68}")
    print(f"  Universe      : {len(cfg.TICKERS)} TMT stocks + {cfg.INDEX_TICKER}")
    print(f"  Period        : {cfg.START_DATE}  →  {cfg.END_DATE}")
    print(f"  Capital       : ${cfg.INITIAL_CAPITAL:,.0f}")
    print(f"  Leaders   {cfg.LEADERS_WEIGHT:.0%} : top-{cfg.TOP_N} momentum (3/6/12m blend), "
          f"{cfg.LEADERS_TARGET_VOL:.0%} vol target, QQQ regime scaler")
    print(f"  Stock dip {cfg.STOCK_DIP_WEIGHT:.0%} : IBS<{cfg.DIP_ENTRY_IBS:.2f} panic closes in "
          f"uptrending names, {cfg.DIP_PER_NAME:.0%}/name")
    print(f"  Index dip {cfg.INDEX_DIP_WEIGHT:.0%} : DTQ mean-reversion sleeve on {cfg.INDEX_TICKER}")
    print(f"  Costs         : {cfg.TRANSACTION_COST*10000:.0f} bps per unit turnover")
    print(f"{'='*68}\n")

    print("[data] Fetching TMT stock OHLC bars …")
    all_bars = {t: fetch_bars(t, cfg.START_DATE, cfg.END_DATE, "1Day",
                              cache_dir=cfg.DATA_CACHE_DIR, verbose=False)
                for t in cfg.TICKERS}

    print(f"[data] Fetching {cfg.INDEX_TICKER} OHLC bars …")
    index_bars = fetch_bars(cfg.INDEX_TICKER, cfg.START_DATE, cfg.END_DATE, "1Day",
                            cache_dir=cfg.DATA_CACHE_DIR, verbose=False)

    print("[data] Fetching SPY benchmark …")
    spy_cumulative = fetch_spy(cfg.START_DATE, cfg.END_DATE, cfg.INITIAL_CAPITAL)

    print("[data] Fetching T-bill (BIL) …")
    tbill_rate, tbill_cumulative = fetch_tbill(cfg.START_DATE, cfg.END_DATE, cfg.INITIAL_CAPITAL)

    print("[backtest] Running …\n")
    portfolio = run_triad_backtest(all_bars, index_bars, tbill_rate,
                                   cfg.INITIAL_CAPITAL, cfg)

    # ── Metrics ───────────────────────────────────────────────
    metrics = compute_metrics(portfolio, tbill_rate, cfg.INITIAL_CAPITAL)

    qqq_ret = index_bars["close"].pct_change().reindex(portfolio.index).fillna(0)
    qqq_tot = (1 + qqq_ret).prod() - 1
    spy_aligned = spy_cumulative.reindex(portfolio.index).ffill()
    spy_tot = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1

    print("Portfolio Summary")
    print("-" * 54)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'QQQ Buy-and-Hold (same window)':<36} {qqq_tot:.2%}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_tot:.2%}")

    # Investor portfolio comparison, if its CSV exists
    inv_path = os.path.join(cfg.OUTPUT_DIR, "investor_portfolio.csv")
    inv_val = None
    if os.path.exists(inv_path):
        inv = pd.read_csv(inv_path, index_col=0, parse_dates=True)
        # The investor portfolio CSV ends at the shared END_DATE (2024-12) —
        # compare over the overlapping window only, don't ffill past its end.
        inv_val  = inv["portfolio_value"].reindex(portfolio.index)
        overlap  = inv_val.dropna()
        inv_tot  = (overlap.iloc[-1] / overlap.iloc[0]) - 1
        inv_span = f"{overlap.index[0].year}–{overlap.index[-1].year}"
        corr = portfolio["daily_return"].corr(inv["daily_return"]
                                              .reindex(portfolio.index))
        print(f"  {f'Investor Portfolio ({inv_span})':<36} {inv_tot:.2%}")
        print(f"  {'Daily corr vs Investor Portfolio':<36} {corr:.2f}")

    print("\nSub-Period Sharpe (regime robustness)")
    print("-" * 54)
    for a, b, sharpe, ann in _sub_period_sharpes(portfolio, tbill_rate):
        print(f"  {a} → {b}    Sharpe {sharpe:5.2f}   Ann. return {ann:6.1%}")

    print("\nSleeve Attribution")
    print("-" * 54)
    for col, label in [("leaders_pnl", "Leaders (slow)"),
                       ("stock_dip_pnl", "Stock dips (fast)"),
                       ("index_dip_pnl", "Index dips (fast)")]:
        print(f"  {label:<26} ${portfolio[col].sum():>12,.0f}")
    print(f"  {'Avg invested weight':<26} {portfolio['invested_weight'].mean():>13.2f}")
    print(f"  {'Avg leaders held':<26} {portfolio['n_leaders'].mean():>13.1f}")
    print(f"  {'Days with active dips':<26} {(portfolio['n_dips'] > 0).mean():>13.1%}")
    top_counts = portfolio.loc[portfolio["top_holding"] != "", "top_holding"].value_counts()
    top_str = ", ".join(f"{t} {c/len(portfolio):.0%}" for t, c in top_counts.head(5).items())
    print(f"  Top holding (days)         {top_str}")

    portfolio.to_csv(os.path.join(cfg.OUTPUT_DIR, "triad_portfolio.csv"))
    print(f"\n[output] CSV → {cfg.OUTPUT_DIR}/triad_portfolio.csv")

    # ── Charts ────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        "TRIAD — Tri-Timescale TMT\n"
        f"{cfg.LEADERS_WEIGHT:.0%} momentum leaders (months)  ·  "
        f"{cfg.STOCK_DIP_WEIGHT:.0%} stock panic dips (days)  ·  "
        f"{cfg.INDEX_DIP_WEIGHT:.0%} index dips (days)",
        fontsize=12, fontweight="bold",
    )

    # Panel 1: equity curve vs benchmarks (and investor portfolio)
    ax = axes[0]
    port_r  = portfolio["portfolio_value"] / cfg.INITIAL_CAPITAL * 100
    qqq_r   = (1 + qqq_ret).cumprod() * 100
    spy_r   = spy_aligned / spy_aligned.iloc[0] * 100
    tbill_r = tbill_cumulative.reindex(portfolio.index).ffill()
    tbill_r = tbill_r / tbill_r.iloc[0] * 100
    ax.plot(port_r.index, port_r, label="TRIAD", color="steelblue", linewidth=2.2)
    if inv_val is not None:
        inv_r = inv_val / inv_val.dropna().iloc[0] * 100
        ax.plot(inv_r.index, inv_r,
                label=f"Investor Portfolio ({inv_span}; holds TRIAD at 40%)",
                color="firebrick", linestyle="-.", linewidth=1.6)
    ax.plot(qqq_r.index, qqq_r, label="QQQ (buy & hold)", color="mediumpurple",
            linestyle="--", linewidth=1.4)
    ax.plot(spy_r.index, spy_r, label="SPY (buy & hold)", color="darkorange",
            linestyle="--", linewidth=1.2)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL)", color="seagreen",
            linestyle=":", linewidth=1.1)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks")
    ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: cumulative sleeve P&L
    ax = axes[1]
    for col, label, color in [
        ("leaders_pnl",   "Leaders (slow — months)",     "#2c7bb6"),
        ("stock_dip_pnl", "Stock dips (fast — days)",    "#d7761b"),
        ("index_dip_pnl", "Index dips (fast — days)",    "#5e9e56"),
    ]:
        ax.plot(portfolio.index, portfolio[col].cumsum(), label=label,
                color=color, linewidth=1.6)
    ax.axhline(0, color="black", linewidth=0.5, linestyle=":")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title("Sleeve P&L Attribution")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: exposure + drawdown
    ax = axes[2]
    base = portfolio["weight_leaders"]
    mid  = base + portfolio["weight_stock_dip"]
    top  = mid + portfolio["weight_index_dip"]
    ax.fill_between(portfolio.index, 0, base, color="#2c7bb6", alpha=0.55,
                    label="Leaders exposure")
    ax.fill_between(portfolio.index, base, mid, color="#d7761b", alpha=0.65,
                    label="Stock-dip exposure")
    ax.fill_between(portfolio.index, mid, top, color="#5e9e56", alpha=0.65,
                    label="Index-dip exposure")
    ax.set_ylabel("Total weight")
    ax.set_ylim(0, 1.25)
    ax.legend(fontsize=8, loc="upper left")

    ax2 = ax.twinx()
    rolling_max = portfolio["portfolio_value"].cummax()
    drawdown    = (portfolio["portfolio_value"] - rolling_max) / rolling_max * 100
    ax2.fill_between(drawdown.index, drawdown, 0, color="tomato", alpha=0.30)
    ax2.set_ylabel("Drawdown (%)", color="tomato")
    ax2.tick_params(axis="y", labelcolor="tomato")
    ax.set_title("Exposure by Sleeve + Portfolio Drawdown")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for a in axes:
        a.tick_params(axis="x", rotation=30)
        a.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(cfg.OUTPUT_DIR, "triad_portfolio.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
