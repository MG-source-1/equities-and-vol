"""
Live tearsheet — compare the live paper track record to the backtest.

    python -m live.tearsheet

Reads outputs/live/equity_curve.csv (built daily by live/reconcile.py),
computes live metrics, and puts them next to what the backtest would lead
you to expect over a window of the same length. The honest question it
answers monthly: "is live behaving like the simulation said it would?"
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alpaca import fetch_bars
from live.config import LIVE_DIR, EQUITY_CSV, DATA_CACHE_DIR
from config import OUTPUT_DIR


def metrics(returns: pd.Series, rf: pd.Series) -> dict:
    r = returns.dropna()
    total = (1 + r).prod() - 1
    ann   = (1 + total) ** (252 / len(r)) - 1
    vol   = r.std() * np.sqrt(252)
    rfa   = rf.reindex(r.index).ffill().dropna()
    rfann = (1 + rfa.mean()) ** 252 - 1 if len(rfa) else 0.0
    curve = (1 + r).cumprod()
    return {
        "days":   len(r),
        "total":  total,
        "ann":    ann,
        "vol":    vol,
        "sharpe": (ann - rfann) / vol if vol > 0 else np.nan,
        "max_dd": (curve / curve.cummax() - 1).min(),
    }


def main():
    if not os.path.exists(EQUITY_CSV):
        print("[tearsheet] No live equity curve yet — run live/reconcile.py daily first.")
        return
    curve = pd.read_csv(EQUITY_CSV, index_col=0, parse_dates=True)["equity"]
    if len(curve) < 5:
        print(f"[tearsheet] Only {len(curve)} live days — need at least 5.")
        return
    live_ret = curve.pct_change().dropna()
    n = len(live_ret)

    start = curve.index[0].strftime("%Y-%m-%d")
    # Cap end at now − 16 min: the free data plan 403s on the recent window
    end_ts = min(curve.index[-1].tz_localize("UTC") + pd.Timedelta(days=1),
                 pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=16))
    end = end_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    bil   = fetch_bars("BIL", start, end, "1Day", cache_dir=DATA_CACHE_DIR,
                       verbose=False, use_cache=False)
    spy   = fetch_bars("SPY", start, end, "1Day", cache_dir=DATA_CACHE_DIR,
                       verbose=False, use_cache=False)
    rf = bil["close"].pct_change().fillna(0)

    live_m = metrics(live_ret, rf)

    # Backtest expectation: distribution of same-length windows from the
    # backtested investor portfolio, so "is live normal?" has a base rate.
    bt_path = os.path.join(OUTPUT_DIR, "investor_portfolio.csv")
    bt_line, pct_line = "", ""
    if os.path.exists(bt_path):
        bt = pd.read_csv(bt_path, index_col=0, parse_dates=True)["daily_return"].dropna()
        window_rets = np.array([
            (1 + bt.iloc[i:i + n]).prod() - 1
            for i in range(0, len(bt) - n, max(1, n // 4))
        ])
        pctile = (window_rets < live_m["total"]).mean() * 100
        bt_m = metrics(bt, rf=pd.Series(0, index=bt.index))
        bt_line  = (f"  Backtest full-period ann return {bt_m['ann']:.1%}, "
                    f"vol {bt_m['vol']:.1%}, max DD {bt_m['max_dd']:.1%}")
        pct_line = (f"  Live {n}-day return sits at the {pctile:.0f}th percentile of "
                    f"all {n}-day backtest windows")

    print(f"\nLIVE TEARSHEET  ({start} → {curve.index[-1].date()}, {n} trading days)")
    print("─" * 58)
    print(f"  Equity                ${curve.iloc[-1]:,.2f}")
    print(f"  Total return          {live_m['total']:+.2%}")
    print(f"  Ann. return           {live_m['ann']:+.1%}")
    print(f"  Ann. vol              {live_m['vol']:.1%}")
    print(f"  Sharpe                {live_m['sharpe']:.2f}")
    print(f"  Max drawdown          {live_m['max_dd']:.1%}")
    if bt_line:
        print("\nVs backtest expectation")
        print("─" * 58)
        print(bt_line)
        print(pct_line)

    # Chart: live equity vs SPY over the same window
    fig, ax = plt.subplots(figsize=(11, 6))
    live_r = curve / curve.iloc[0] * 100
    spy_r  = spy["close"].reindex(curve.index).ffill()
    spy_r  = spy_r / spy_r.iloc[0] * 100
    ax.plot(live_r.index, live_r, label="Live portfolio (paper)",
            color="steelblue", linewidth=2.2)
    ax.plot(spy_r.index, spy_r, label="SPY (same window)",
            color="darkorange", linestyle="--", linewidth=1.5)
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":")
    ax.set_title(f"Live Paper Track Record — {n} trading days")
    ax.set_ylabel("Value (rebased to 100)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.tight_layout()
    path = os.path.join(LIVE_DIR, "tearsheet.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n[tearsheet] Chart → {path}")


if __name__ == "__main__":
    main()
