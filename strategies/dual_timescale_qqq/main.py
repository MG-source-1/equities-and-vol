"""
Dual-Timescale QQQ (DTQ) — main runner.

Run from project root:
    python -m strategies.dual_timescale_qqq.main
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
from strategies.dual_timescale_qqq.backtest import run_dtq_backtest
from strategies.dual_timescale_qqq.config import (
    TICKER, START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR,
    TREND_WEIGHT, MR_WEIGHT,
    SMA_WINDOW, TREND_TARGET_VOL, TREND_MAX_SIZE,
    MR_ENTRY_IBS, MR_EXIT_IBS, MR_MAX_HOLD, MR_TARGET_VOL, MR_MAX_SIZE,
    VOL_LOOKBACK, TRANSACTION_COST,
)


def _sub_period_sharpes(portfolio: pd.DataFrame, tbill_rate: pd.Series) -> list:
    """Sharpe per sub-period — the honesty check against single-regime luck."""
    out = []
    for a, b in [("2016-10", "2019-12"), ("2020-01", "2022-12"), ("2023-01", "2024-12")]:
        r = portfolio["daily_return"].dropna().loc[a:b]
        if len(r) < 50:
            continue
        total   = (1 + r).prod() - 1
        ann_ret = (1 + total) ** (252 / len(r)) - 1
        ann_vol = r.std() * np.sqrt(252)
        rf      = tbill_rate.reindex(r.index).ffill().dropna()
        rf_ann  = (1 + rf.mean()) ** 252 - 1
        sharpe  = (ann_ret - rf_ann) / ann_vol if ann_vol > 0 else np.nan
        out.append((a, b, sharpe, ann_ret))
    return out


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\n{'='*64}")
    print("  DUAL-TIMESCALE QQQ (DTQ)")
    print(f"{'='*64}")
    print(f"  Instrument    : {TICKER} (single instrument, two timescales)")
    print(f"  Period        : {START_DATE}  →  {END_DATE}")
    print(f"  Capital       : ${INITIAL_CAPITAL:,.0f}")
    print(f"  Trend sleeve  : {TREND_WEIGHT:.0%} — long > {SMA_WINDOW}d SMA, "
          f"{TREND_TARGET_VOL:.0%} vol target")
    print(f"  MR sleeve     : {MR_WEIGHT:.0%} — buy IBS<{MR_ENTRY_IBS:.2f} dips in uptrends, "
          f"exit IBS>{MR_EXIT_IBS:.2f} or {MR_MAX_HOLD}d")
    print(f"  Costs         : {TRANSACTION_COST*10000:.0f} bps per unit turnover")
    print(f"  Benchmark     : {TICKER} & SPY buy-and-hold  |  Data: Alpaca SIP")
    print(f"{'='*64}\n")

    print(f"[data] Fetching {TICKER} OHLC bars …")
    bars = fetch_bars(TICKER, START_DATE, END_DATE, "1Day",
                      cache_dir=DATA_CACHE_DIR, verbose=False)

    print("[data] Fetching SPY benchmark …")
    spy_cumulative = fetch_spy(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[data] Fetching T-bill (BIL) …")
    tbill_rate, tbill_cumulative = fetch_tbill(START_DATE, END_DATE, INITIAL_CAPITAL)

    print("[backtest] Running …\n")
    portfolio, trades = run_dtq_backtest(
        bars, tbill_rate, INITIAL_CAPITAL,
        trend_weight     = TREND_WEIGHT,
        mr_weight        = MR_WEIGHT,
        sma_window       = SMA_WINDOW,
        trend_target_vol = TREND_TARGET_VOL,
        trend_max_size   = TREND_MAX_SIZE,
        mr_entry_ibs     = MR_ENTRY_IBS,
        mr_exit_ibs      = MR_EXIT_IBS,
        mr_max_hold      = MR_MAX_HOLD,
        mr_target_vol    = MR_TARGET_VOL,
        mr_max_size      = MR_MAX_SIZE,
        vol_lookback     = VOL_LOOKBACK,
        transaction_cost = TRANSACTION_COST,
    )

    # ── Metrics ───────────────────────────────────────────────
    metrics = compute_metrics(portfolio, tbill_rate, INITIAL_CAPITAL)

    qqq_ret = bars["close"].pct_change().reindex(portfolio.index).fillna(0)
    qqq_tot = (1 + qqq_ret).prod() - 1
    spy_aligned = spy_cumulative.reindex(portfolio.index).ffill()
    spy_tot = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]) - 1

    print("Portfolio Summary")
    print("-" * 52)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    print(f"  {'QQQ Buy-and-Hold (same window)':<36} {qqq_tot:.2%}")
    print(f"  {'SPY Buy-and-Hold (same window)':<36} {spy_tot:.2%}")

    print("\nSub-Period Sharpe (regime robustness)")
    print("-" * 52)
    for a, b, sharpe, ann in _sub_period_sharpes(portfolio, tbill_rate):
        print(f"  {a} → {b}    Sharpe {sharpe:5.2f}   Ann. return {ann:6.1%}")

    print("\nSleeve Attribution")
    print("-" * 52)
    trend_total = portfolio["trend_pnl"].sum()
    mr_total    = portfolio["mr_pnl"].sum()
    print(f"  Trend sleeve P&L        ${trend_total:>12,.0f}")
    print(f"  MR sleeve P&L           ${mr_total:>12,.0f}")
    corr = portfolio["trend_pnl"].corr(portfolio["mr_pnl"])
    print(f"  Daily sleeve P&L corr   {corr:>13.2f}")
    print(f"  Avg invested weight     {portfolio['invested_weight'].mean():>13.2f}")

    print("\nMean-Reversion Trade Log")
    print("-" * 52)
    n = len(trades)
    wins = (trades["return"] > 0).sum()
    print(f"  Trades                  {n:>13}")
    print(f"  Win rate                {wins / n:>13.1%}")
    print(f"  Avg trade return        {trades['return'].mean():>13.2%}")
    print(f"  Avg days held           {trades['days_held'].mean():>13.1f}")
    print(f"  Worst trade             {trades['return'].min():>13.2%}")
    print(f"  Best trade              {trades['return'].max():>13.2%}")

    portfolio.to_csv(os.path.join(OUTPUT_DIR, "dtq_portfolio.csv"))
    trades.to_csv(os.path.join(OUTPUT_DIR, "dtq_trades.csv"), index=False)
    print(f"\n[output] CSVs → {OUTPUT_DIR}/dtq_portfolio.csv, dtq_trades.csv")

    # ── Charts ────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 15))
    fig.suptitle(
        "Dual-Timescale QQQ (DTQ)\n"
        f"{TREND_WEIGHT:.0%} slow trend (200d SMA, vol-targeted)  ·  "
        f"{MR_WEIGHT:.0%} fast mean reversion (IBS dip-buying in uptrends)",
        fontsize=12, fontweight="bold",
    )

    # Panel 1: equity curve vs QQQ / SPY / T-bill
    ax = axes[0]
    port_r  = portfolio["portfolio_value"] / INITIAL_CAPITAL * 100
    qqq_r   = (1 + qqq_ret).cumprod() * 100
    spy_r   = spy_aligned / spy_aligned.iloc[0] * 100
    tbill_r = tbill_cumulative.reindex(portfolio.index).ffill()
    tbill_r = tbill_r / tbill_r.iloc[0] * 100
    ax.plot(port_r.index,  port_r,  label="DTQ", color="steelblue", linewidth=2.2)
    ax.plot(qqq_r.index,   qqq_r,   label="QQQ (buy & hold)", color="mediumpurple",
            linestyle="--", linewidth=1.5)
    ax.plot(spy_r.index,   spy_r,   label="SPY (buy & hold)", color="darkorange",
            linestyle="--", linewidth=1.3)
    ax.plot(tbill_r.index, tbill_r, label="T-bill (BIL)", color="seagreen",
            linestyle=":", linewidth=1.2)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio Value vs Benchmarks")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 2: cumulative sleeve P&L attribution
    ax = axes[1]
    ax.plot(portfolio.index, portfolio["trend_pnl"].cumsum(),
            label="Trend sleeve (slow)", color="#2c7bb6", linewidth=1.6)
    ax.plot(portfolio.index, portfolio["mr_pnl"].cumsum(),
            label="Mean-reversion sleeve (fast)", color="#d7761b", linewidth=1.6)
    ax.axhline(0, color="black", linewidth=0.5, linestyle=":")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title(f"Sleeve P&L Attribution  (daily P&L correlation: {corr:.2f})")
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Panel 3: exposure + drawdown
    ax = axes[2]
    ax.fill_between(portfolio.index, 0, portfolio["weight_trend"],
                    color="#2c7bb6", alpha=0.55, label="Trend exposure")
    ax.fill_between(portfolio.index, portfolio["weight_trend"],
                    portfolio["weight_trend"] + portfolio["weight_mr"],
                    color="#d7761b", alpha=0.65, label="MR exposure")
    ax.set_ylabel("QQQ weight")
    ax.set_ylim(0, 1.45)
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
    path = os.path.join(OUTPUT_DIR, "dtq_portfolio.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
