"""
BTREND — Broad Cross-Asset Trend — standalone backtest.

Run from project root:
    python -m strategies.broad_trend.main
"""

import os, sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from core.data import fetch_prices, fetch_tbill, fetch_spy
from core.metrics import compute_metrics

from strategies.broad_trend.backtest import run_trend_backtest
from strategies.broad_trend import config as cfg


def _sub_sharpe(df: pd.DataFrame, tbill: pd.Series, a: str, b: str) -> tuple:
    r  = df.loc[a:b, "daily_return"].dropna()
    rf = tbill.reindex(r.index).ffill().fillna(0)
    if len(r) < 60 or r.std() == 0:
        return np.nan, np.nan
    ann = (1 + r).prod() ** (252 / len(r)) - 1
    sh  = ((r - rf).mean() * 252) / (r.std() * np.sqrt(252))
    return sh, ann


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

    mode = "long/short" if cfg.LONG_SHORT else "long-only"
    print(f"\n{'='*68}")
    print(f"  BTREND — Broad Cross-Asset Trend  ({len(cfg.TICKERS)} ETFs, 5 asset classes, {mode})")
    print(f"{'='*68}")
    print(f"  Period : {cfg.START_DATE} → {cfg.END_DATE}  (2025+ is forward validation)")
    print(f"  Signal : per-asset 3/6/12m TSMOM, monthly · inverse-vol · "
          f"{cfg.TARGET_VOL:.0%} vol target\n")

    prices = fetch_prices(list(cfg.TICKERS), cfg.START_DATE, cfg.END_DATE)
    tbill_rate, _ = fetch_tbill(cfg.START_DATE, cfg.END_DATE, cfg.INITIAL_CAPITAL)
    spy_cum = fetch_spy(cfg.START_DATE, cfg.END_DATE, cfg.INITIAL_CAPITAL)
    print(f"[data] {len(prices.columns)} of {len(cfg.TICKERS)} tickers available: "
          f"{', '.join(prices.columns)}")

    pf = run_trend_backtest(prices, tbill_rate, cfg.INITIAL_CAPITAL, cfg)

    metrics = compute_metrics(pf, tbill_rate, cfg.INITIAL_CAPITAL)
    print("\nPortfolio Summary")
    print("─" * 56)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")
    spy_aligned = spy_cum.reindex(pf.index).ffill()
    print(f"  {'SPY Buy-and-Hold (same window)':<36} "
          f"{spy_aligned.iloc[-1] / spy_aligned.iloc[0] - 1:.2%}")

    print("\nSub-Period Sharpe (regime robustness)")
    print("─" * 56)
    for a, b, label in [("2017-01", "2019-12", "2017 → 2019  (bull)"),
                        ("2020-01", "2020-12", "2020         (COVID)"),
                        ("2021-01", "2022-12", "2021 → 2022  (rate shock)"),
                        ("2023-01", "2024-12", "2023 → 2024  (AI bull)"),
                        ("2025-01", "2026-06", "2025 → 26H1  (forward test)")]:
        sh, ann = _sub_sharpe(pf, tbill_rate, a, b)
        print(f"  {label:<28} Sharpe {sh:5.2f}   Ann. return {ann:+6.1%}")

    # Diagnostics: exposure and what it actually held
    active = pf[pf["in_regime"]]
    print("\nDiagnostics")
    print("─" * 56)
    print(f"  Avg gross exposure         {pf['invested_weight'].mean():.2f}")
    print(f"  Avg net exposure           {pf['net_weight'].mean():.2f}")
    print(f"  Avg longs / shorts held    {active['n_long'].mean():.1f} / {active['n_short'].mean():.1f}")
    freq = pd.Series(
        [t for h in active["holdings"] if h for t in h.split(",")]
    ).value_counts(normalize=True).head(6)
    print("  Most-held longs            "
          + ", ".join(f"{t} {p:.0%}" for t, p in freq.items()))
    sfreq = pd.Series(
        [t for h in active["shorts"] if isinstance(h, str) and h for t in h.split(",")]
    ).value_counts(normalize=True).head(6)
    if not sfreq.empty:
        print("  Most-shorted               "
              + ", ".join(f"{t} {p:.0%}" for t, p in sfreq.items()))

    pf.to_csv(os.path.join(cfg.OUTPUT_DIR, "broad_trend.csv"))
    print(f"\n[output] CSV → {cfg.OUTPUT_DIR}/broad_trend.csv")

    # ── Chart ─────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 13))
    fig.suptitle("BTREND — Broad Cross-Asset Trend (17 ETFs · long/short TSMOM)",
                 fontsize=11, fontweight="bold")

    ax = axes[0]
    ax.plot(pf.index, pf["portfolio_value"] / cfg.INITIAL_CAPITAL * 100,
            label="BTREND", color="steelblue", linewidth=2)
    ax.plot(spy_aligned.index, spy_aligned / cfg.INITIAL_CAPITAL * 100,
            label="SPY B&H", color="darkorange", linestyle="--", linewidth=1.3)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_ylabel("Value (rebased to 100)")
    ax.set_title("Portfolio value vs SPY")
    ax.legend(fontsize=9)

    ax = axes[1]
    ax.fill_between(pf.index, pf["invested_weight"], color="seagreen", alpha=0.4,
                    label="Gross")
    ax.plot(pf.index, pf["net_weight"], color="darkgreen", linewidth=1.0,
            label="Net")
    ax.axhline(0, color="black", linewidth=0.4)
    ax.set_ylabel("Exposure")
    ax.set_title("Gross and net exposure")
    ax.legend(fontsize=8)

    ax = axes[2]
    v  = pf["portfolio_value"]
    dd = (v - v.cummax()) / v.cummax() * 100
    sv = spy_aligned
    sdd = (sv - sv.cummax()) / sv.cummax() * 100
    ax.fill_between(dd.index, dd, 0, color="steelblue", alpha=0.25)
    ax.plot(dd.index, dd, color="steelblue", linewidth=1.8, label="BTREND")
    ax.plot(sdd.index, sdd, color="darkorange", linewidth=1.1, linestyle="--", label="SPY B&H")
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Drawdown vs SPY")
    ax.legend(fontsize=8)

    for a in axes:
        a.grid(True, alpha=0.3)
        a.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        a.tick_params(axis="x", rotation=30)

    plt.tight_layout()
    path = os.path.join(cfg.OUTPUT_DIR, "broad_trend.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
