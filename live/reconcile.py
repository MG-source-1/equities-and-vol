"""
Morning reconcile job — run any time after the close (e.g. next morning SGT).

    python -m live.reconcile

Appends today's account equity to the live equity curve, then checks the
most recent decision log's orders against actual fills and reports any
mismatch or slippage vs the official close. The equity curve CSV is what
live/tearsheet.py measures.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alpaca import fetch_bars
from live import broker
from live.config import LIVE_DIR, DECISIONS_DIR, EQUITY_CSV, DATA_CACHE_DIR


def append_equity_curve() -> None:
    account = broker.get_account()
    row = {
        "date":   pd.Timestamp.now().normalize(),
        "equity": float(account["equity"]),
        "cash":   float(account["cash"]),
    }
    os.makedirs(LIVE_DIR, exist_ok=True)
    if os.path.exists(EQUITY_CSV):
        curve = pd.read_csv(EQUITY_CSV, index_col=0, parse_dates=True)
        curve.loc[row["date"]] = [row["equity"], row["cash"]]   # idempotent per day
    else:
        curve = pd.DataFrame([row]).set_index("date")
    curve.sort_index().to_csv(EQUITY_CSV)
    print(f"[reconcile] Equity ${row['equity']:,.2f} (cash ${row['cash']:,.2f}) "
          f"→ {EQUITY_CSV}")


def latest_decision() -> dict:
    if not os.path.isdir(DECISIONS_DIR):
        return {}
    files = sorted(f for f in os.listdir(DECISIONS_DIR)
                   if f.endswith(".json") and not f.endswith(".dryrun.json"))
    if not files:
        return {}
    with open(os.path.join(DECISIONS_DIR, files[-1])) as f:
        return json.load(f)


def check_fills() -> None:
    decision = latest_decision()
    if not decision or not decision.get("executed"):
        print("[reconcile] No executed decision to reconcile.")
        return

    # Match each intended order to ITS OWN fill via order_id (recorded in
    # the decision log at submission). Matching by (symbol, side) over a
    # multi-day window aggregates unrelated orders and can mark a missed
    # fill "OK" because an earlier day's order filled.
    after  = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    closed = broker.list_orders(status="closed", after=after)
    by_id  = {o["id"]: o for o in closed if o.get("id")}

    print(f"[reconcile] Checking {len(decision['orders'])} intended orders "
          f"from {decision['utc_time'][:10]} …")
    problems = 0
    for o in decision["orders"]:
        rec = by_id.get(o.get("order_id"))
        if rec is None:
            filled = {"qty": 0.0, "avg_px": 0.0}
            status = "NO ORDER FOUND" if o.get("order_id") else "SUBMIT FAILED"
        else:
            filled = {"qty":    float(rec.get("filled_qty") or 0),
                      "avg_px": float(rec.get("filled_avg_price") or 0)}
            status = "OK" if filled["qty"] >= o["qty"] else "PARTIAL/MISSING"
        if status != "OK":
            problems += 1
        slip = ""
        if filled["avg_px"] > 0 and o.get("ref_price"):
            bps  = (filled["avg_px"] / o["ref_price"] - 1) * 1e4
            slip = f"fill ${filled['avg_px']:,.2f} ({bps:+.0f} bps vs signal price)"
        print(f"  {o['side']:<4} {o['symbol']:<5} intended {o['qty']:>5} "
              f"filled {filled['qty']:>7.0f}  {status}  {slip}")
    if problems == 0:
        print("[reconcile] All orders filled as intended.")
    else:
        print(f"[reconcile] WARNING: {problems} order(s) need attention.")


def main():
    append_equity_curve()
    check_fills()


if __name__ == "__main__":
    main()
