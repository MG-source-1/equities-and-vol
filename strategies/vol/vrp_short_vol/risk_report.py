"""
One-page desk-style risk report for the VRP book.

Reads like something a junior trader hands the desk head at the close:
current position and greeks, what drove recent P&L, and how the book
behaves in stress — one PNG, no scrolling.
"""

import os

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd


def _fmt_greek(v, unit=""):
    return f"{v:+,.0f}{unit}"


def build_risk_report(pf: pd.DataFrame, stress: pd.DataFrame, cfg) -> str:
    last = pf.iloc[-1]
    asof = pf.index[-1].date()
    recent = pf.tail(21)

    fig = plt.figure(figsize=(11.7, 8.3))          # A4 landscape
    fig.suptitle(f"VRP SHORT-VOL BOOK — DAILY RISK REPORT   |   as of {asof}",
                 fontsize=13, fontweight="bold", y=0.985)

    # ── Header: position & greeks strip ──────────────────────
    ax = fig.add_axes([0.04, 0.80, 0.92, 0.13])
    ax.axis("off")
    pos = ("SHORT 25Δ SPY STRANGLE (hedged)"
           if last["in_position"] else "FLAT (signal off / stopped)")
    cells = [
        ("Position", pos, 0.00),
        ("Equity", f"${last['equity']:,.0f}", 0.26),
        ("Book Δ (sh)", _fmt_greek(last["delta"]), 0.38),
        ("Γ ($/1²)", _fmt_greek(last["gamma"]), 0.48),
        ("Vega ($/volpt)", _fmt_greek(last["vega"]), 0.58),
        ("Theta ($/day)", _fmt_greek(last["theta"]), 0.70),
        ("VIX / RV", f"{last['vix']:.1f} / {last['realised_vol']:.1f}", 0.81),
        ("VRP", f"{last['vrp']:+.1f} pts", 0.93),
    ]
    for k, v, x in cells:
        ax.text(x, 0.72, k, fontsize=8, color="gray", transform=ax.transAxes)
        ax.text(x, 0.22, v, fontsize=10.5, fontweight="bold", transform=ax.transAxes)

    # ── Left: equity (63d) + drawdown context ─────────────────
    ax1 = fig.add_axes([0.06, 0.44, 0.42, 0.30])
    win = pf.tail(63)
    ax1.plot(win.index, win["equity"], color="steelblue", linewidth=1.6)
    ax1.set_title("Equity — last quarter", fontsize=9)
    ax1.grid(alpha=0.3)
    ax1.xaxis.set_major_locator(mdates.MonthLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax1.tick_params(labelsize=7)

    # ── Right: 21-day P&L attribution bars ────────────────────
    ax2 = fig.add_axes([0.56, 0.44, 0.40, 0.30])
    attr = {
        "theta": recent["theta_pnl"].sum(),
        "gamma": recent["gamma_pnl"].sum(),
        "vega": recent["vega_pnl"].sum(),
        "delta": recent["delta_pnl"].sum(),
        "resid": recent["residual_pnl"].sum(),
        "carry": recent["interest"].sum(),
        "costs": -recent["costs"].sum(),
    }
    colors = ["seagreen" if v >= 0 else "firebrick" for v in attr.values()]
    ax2.bar(list(attr), list(attr.values()), color=colors, alpha=0.85)
    ax2.axhline(0, color="black", linewidth=0.6)
    total21 = recent["equity"].iloc[-1] - pf["equity"].iloc[-22]
    ax2.set_title(f"P&L attribution — last 21 sessions (total ${total21:+,.0f})",
                  fontsize=9)
    ax2.grid(alpha=0.3, axis="y")
    ax2.tick_params(labelsize=8)

    # ── Bottom: stress-scenario table ─────────────────────────
    ax3 = fig.add_axes([0.04, 0.06, 0.92, 0.30])
    ax3.axis("off")
    ax3.set_title("Historical stress replay — what this book did in named vol events",
                  fontsize=9, loc="left")
    if not stress.empty:
        tbl = ax3.table(cellText=stress.values, colLabels=stress.columns,
                        cellLoc="center", bbox=[0.0, 0.45, 1.0, 0.50])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        tbl.auto_set_column_width(range(len(stress.columns)))
        for j in range(len(stress.columns)):
            tbl[0, j].set_facecolor("#2c3e50")
            tbl[0, j].set_text_props(color="white", fontweight="bold")

    fig.text(0.04, 0.015,
             f"Sizing: vega budget {cfg.VEGA_BUDGET:.1%} equity/vol pt · "
             f"stop {cfg.STOP_MULT}× premium · costs {cfg.HALF_SPREAD_VOLPTS} "
             f"vol-pt half-spread + {cfg.HEDGE_COST_BPS:.0f} bp hedge slippage · "
             "pricing: BSM, VIX as IV (flat skew — conservative for short vol)",
             fontsize=7, color="gray")

    path = os.path.join(cfg.OUTPUT_DIR, "vrp_risk_report.png")
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path
