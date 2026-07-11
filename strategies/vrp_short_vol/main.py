"""
VRP — Volatility Risk Premium — standalone backtest.

Run from project root:
    python -m strategies.vrp_short_vol.main

Produces the backtest summary, greeks-attributed P&L, the three named
vol-event stress windows, a hedged-vs-unhedged comparison, charts, and the
one-page desk-style risk report (outputs/vrp_risk_report.png).
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

from core.data import fetch_prices, fetch_tbill, fetch_vix
from core.metrics import compute_metrics

from strategies.vrp_short_vol.backtest import run_vrp_backtest
from strategies.vrp_short_vol import config as cfg
from strategies.vrp_short_vol.risk_report import build_risk_report

STRESS_WINDOWS = [
    ("Volmageddon",  "2018-01-26", "2018-02-15"),
    ("COVID crash",  "2020-02-19", "2020-03-23"),
    ("GameStop",     "2021-01-15", "2021-02-05"),
]


def stress_table(pf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, a, b in STRESS_WINDOWS:
        w = pf.loc[a:b]
        if w.empty:
            continue
        ret = w["equity"].iloc[-1] / pf["equity"].loc[:a].iloc[-1] - 1
        rows.append({
            "Event": name, "Window": f"{a} → {b}",
            "P&L": f"{ret:+.2%}",
            "Worst day": f"{w['daily_return'].min():+.2%}",
            "Peak VIX": f"{w['vix'].max():.0f}",
            "Peak |vega| $": f"{w['vega'].abs().max():,.0f}",
            "Gamma P&L": f"${w['gamma_pnl'].sum():,.0f}",
            "Vega P&L": f"${w['vega_pnl'].sum():,.0f}",
            "Theta P&L": f"${w['theta_pnl'].sum():,.0f}",
            "Stopped?": "YES" if (w["action"] == "stop").any() else "no",
        })
    return pd.DataFrame(rows)


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

    print(f"\n{'='*68}")
    print("  VRP — Short SPY strangles when implied vol is rich to realised")
    print(f"{'='*68}")
    print(f"  Period  : {cfg.START_DATE} → {cfg.END_DATE}")
    print(f"  Signal  : VIX − EWMA(λ={cfg.EWMA_LAMBDA}) realised vol "
          f"> {cfg.VRP_ENTRY} vol pt at the monthly roll")
    print(f"  Position: short {cfg.DELTA_TARGET:.0%}-delta strangle, vega-budgeted "
          f"({cfg.VEGA_BUDGET:.1%} equity/vol pt), stop at {cfg.STOP_MULT}× premium")
    print(f"  Hedging : {'daily delta hedge' if cfg.DELTA_HEDGE else 'unhedged'} "
          f"| costs {cfg.HALF_SPREAD_VOLPTS} vol-pt half-spread, "
          f"{cfg.HEDGE_COST_BPS:.0f} bp hedge slippage\n")

    px = fetch_prices([cfg.UNDERLYING], cfg.START_DATE, cfg.END_DATE)[cfg.UNDERLYING]
    vix = fetch_vix(cfg.START_DATE, cfg.END_DATE)
    tbill, _ = fetch_tbill(cfg.START_DATE, cfg.END_DATE, cfg.INITIAL_CAPITAL)
    print(f"[data] SPY {len(px)} days · VIX {len(vix)} days "
          f"(CBOE official history)")

    pf = run_vrp_backtest(px, vix, tbill, cfg.INITIAL_CAPITAL, cfg)
    unhedged = run_vrp_backtest(px, vix, tbill, cfg.INITIAL_CAPITAL, cfg,
                                delta_hedge=False)

    metrics = compute_metrics(pf, tbill, cfg.INITIAL_CAPITAL)
    print("\nPortfolio Summary (delta-hedged)")
    print("─" * 56)
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")

    # ── Greeks attribution ────────────────────────────────────
    print("\nP&L Attribution (whole period, $)")
    print("─" * 56)
    total_pnl = pf["equity"].iloc[-1] - cfg.INITIAL_CAPITAL
    for label, col, sign in [("Theta (decay collected)", "theta_pnl", 1),
                             ("Gamma (paid on moves)", "gamma_pnl", 1),
                             ("Vega (IV marks)", "vega_pnl", 1),
                             ("Delta (residual directional)", "delta_pnl", 1),
                             ("Higher-order residual", "residual_pnl", 1),
                             ("T-bill interest", "interest", 1),
                             ("Transaction & hedging costs", "costs", -1)]:
        print(f"  {label:<32} ${sign * pf[col].sum():>12,.0f}")
    explained = (pf[["theta_pnl", "gamma_pnl", "vega_pnl", "delta_pnl",
                     "residual_pnl", "interest"]].sum().sum()
                 - pf["costs"].sum())
    print(f"  {'TOTAL (rows sum exactly)':<32} ${explained:>12,.0f}")
    assert abs(explained - total_pnl) < 1.0, "attribution does not reconcile"

    # ── Hedged vs unhedged ────────────────────────────────────
    um = compute_metrics(unhedged, tbill, cfg.INITIAL_CAPITAL)
    print("\nDelta hedging: what it buys and costs")
    print("─" * 56)
    print(f"  {'':<14} {'hedged':>10} {'unhedged':>10}")
    print(f"  {'Total return':<14} {metrics['Total Return']:>10} {um['Total Return']:>10}")
    print(f"  {'Sharpe':<14} {metrics['Sharpe Ratio']:>10} {um['Sharpe Ratio']:>10}")
    print(f"  {'Max DD':<14} {metrics['Max Drawdown']:>10} {um['Max Drawdown']:>10}")

    # ── Stress windows ────────────────────────────────────────
    print("\nStress Windows (named vol events)")
    print("─" * 56)
    st = stress_table(pf)
    print(st.to_string(index=False))

    pf.to_csv(os.path.join(cfg.OUTPUT_DIR, "vrp_short_vol.csv"))
    print(f"\n[output] CSV → {cfg.OUTPUT_DIR}/vrp_short_vol.csv")

    # ── Charts ────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 13))
    fig.suptitle("VRP — short SPY strangles, delta-hedged, vega-budgeted",
                 fontsize=11, fontweight="bold")

    ax = axes[0]
    ax.plot(pf.index, pf["equity"] / cfg.INITIAL_CAPITAL * 100,
            color="steelblue", linewidth=1.8, label="VRP (hedged)")
    ax.plot(unhedged.index, unhedged["equity"] / cfg.INITIAL_CAPITAL * 100,
            color="gray", linewidth=1.0, linestyle="--", label="unhedged")
    for _, a, b in STRESS_WINDOWS:
        ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="red", alpha=0.10)
    ax.set_ylabel("Equity (rebased to 100)")
    ax.set_title("Equity curve (red bands = stress windows)")
    ax.legend(fontsize=9)

    ax = axes[1]
    ax.plot(vix.index, vix, color="darkorange", linewidth=1.0, label="VIX (implied)")
    ax.plot(pf.index, pf["realised_vol"], color="steelblue", linewidth=1.0,
            label="EWMA realised")
    ax.fill_between(pf.index, 0, pf["in_position"].astype(int) * pf["vix"].max(),
                    color="seagreen", alpha=0.07, label="short vol on")
    ax.set_ylabel("Vol points")
    ax.set_title("The premium being sold: implied vs realised vol")
    ax.legend(fontsize=9)

    ax = axes[2]
    cum = pf[["theta_pnl", "gamma_pnl", "vega_pnl", "delta_pnl"]].cumsum()
    ax.plot(cum.index, cum["theta_pnl"], color="seagreen", label="theta (collected)")
    ax.plot(cum.index, cum["gamma_pnl"], color="firebrick", label="gamma (paid)")
    ax.plot(cum.index, cum["vega_pnl"], color="darkorange", label="vega")
    ax.plot(cum.index, cum["delta_pnl"], color="gray", label="delta")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Cumulative P&L ($)")
    ax.set_title("Greeks-attributed P&L — the short-vol business model: "
                 "collect theta, pay gamma")
    ax.legend(fontsize=9)

    for a in axes:
        a.grid(True, alpha=0.3)
        a.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    path = os.path.join(cfg.OUTPUT_DIR, "vrp_short_vol.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot] Saved → {path}")

    # ── One-page desk-style risk report ───────────────────────
    report_path = build_risk_report(pf, stress_table(pf), cfg)
    print(f"[report] One-page risk report → {report_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
