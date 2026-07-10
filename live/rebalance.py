"""
Daily rebalance job — run between ~15:20 and 15:40 ET on trading days.

    python -m live.rebalance              # dry run: print orders, submit nothing
    python -m live.rebalance --execute    # submit market orders (~15:25 ET)
    python -m live.rebalance --force      # compute even if market is closed (testing)

Flow: check market clock → compute target weights (live/signals.py) →
apply the portfolio-level drawdown guard → diff targets against current
positions → submit whole-share market orders → write a decision log.
(Immediate market orders, not MOC — the paper simulator lets MOC orders
expire unfilled; see live/broker.py.)

Safe to schedule generously (e.g. hourly): it exits immediately unless the
market is open, so a Singapore-time cron doesn't need to track US DST.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live import broker
from live.config import (
    LIVE_DIR, DECISIONS_DIR, STATE_PATH,
    MIN_TRADE_VALUE, DD_STOP, DD_COOLDOWN_DAYS,
)
from live.signals import compute_targets


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"peak_equity": 0.0, "dd_stop_active": False,
            "dd_cooldown_left": 0, "last_rebalance": None}


def save_state(state: dict) -> None:
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def apply_drawdown_guard(state: dict, equity: float) -> bool:
    """Update peak/stop state. Returns True when the portfolio must be flat."""
    state["peak_equity"] = max(state.get("peak_equity", 0.0), equity)
    if state.get("dd_stop_active"):
        state["dd_cooldown_left"] = max(0, state.get("dd_cooldown_left", 0) - 1)
        if state["dd_cooldown_left"] == 0:
            state["dd_stop_active"] = False
            state["peak_equity"]    = equity   # clean re-entry, like the backtest
            print("[guard] Drawdown cooldown finished — re-entering.")
        else:
            print(f"[guard] Drawdown stop active — {state['dd_cooldown_left']} days left.")
            return True
    drawdown = (equity - state["peak_equity"]) / state["peak_equity"] \
        if state["peak_equity"] > 0 else 0.0
    if drawdown < -DD_STOP:
        state["dd_stop_active"]   = True
        state["dd_cooldown_left"] = DD_COOLDOWN_DAYS
        print(f"[guard] Live drawdown {drawdown:.1%} breached −{DD_STOP:.0%} → flattening "
              f"for {DD_COOLDOWN_DAYS} trading days.")
        return True
    return False


def build_orders(target_weights: dict, prices: dict,
                 positions: dict, equity: float) -> list:
    """Whole-share order list to move current positions to target weights."""
    symbols = sorted(set(target_weights) | set(positions))
    orders  = []
    for sym in symbols:
        price = prices.get(sym)
        if not price or price <= 0:
            print(f"[orders] WARNING: no price for {sym}, skipping.")
            continue
        target_qty  = int(target_weights.get(sym, 0.0) * equity / price)
        current_qty = int(positions.get(sym, 0))
        delta       = target_qty - current_qty
        if delta == 0 or abs(delta) * price < MIN_TRADE_VALUE:
            continue
        orders.append({
            "symbol": sym,
            "side":   "buy" if delta > 0 else "sell",
            "qty":    abs(delta),
            "ref_price":  round(price, 2),
            "est_value":  round(abs(delta) * price, 2),
            "target_qty": target_qty,
        })
    # Sells first so their proceeds cover the buys
    return sorted(orders, key=lambda o: 0 if o["side"] == "sell" else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="submit orders (default is dry run)")
    ap.add_argument("--force", action="store_true",
                    help="compute targets even if the market is closed")
    args = ap.parse_args()

    clock = broker.get_clock()
    if not clock["is_open"] and not args.force:
        print(f"[rebalance] Market closed (next open {clock['next_open']}) — exiting.")
        return

    account = broker.get_account()
    equity  = float(account["equity"])
    print(f"[rebalance] Paper account equity: ${equity:,.2f}")

    print("[rebalance] Computing target weights …")
    targets = compute_targets()
    print(f"[rebalance] Signals as of {targets['as_of']}  "
          f"(gross exposure {targets['diag']['gross']:.2f})")

    state   = load_state()
    flatten = apply_drawdown_guard(state, equity)
    weights = {} if flatten else targets["weights"]

    positions = broker.get_positions()
    orders    = build_orders(weights, targets["prices"], positions, equity)

    if not orders:
        print("[rebalance] Portfolio already within tolerance — no trades.")
    for o in orders:
        print(f"  {o['side'].upper():<4} {o['qty']:>5} {o['symbol']:<5} "
              f"@~${o['ref_price']:<9,.2f} (${o['est_value']:,.0f})")

    submitted = []
    if args.execute and orders:
        broker.cancel_open_orders()
        for o in orders:
            try:
                resp = broker.submit_order(o["symbol"], o["qty"], o["side"])
                submitted.append({**o, "order_id": resp.get("id")})
                print(f"  → submitted {o['side']} {o['qty']} {o['symbol']}")
            except Exception as e:
                submitted.append({**o, "error": str(e)})
                print(f"  → FAILED {o['symbol']}: {e}")
    elif orders:
        print("[rebalance] DRY RUN — nothing submitted (use --execute to trade).")

    # ── Decision log: every input to today's decision, replayable later ─
    os.makedirs(DECISIONS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = {
        "utc_time":      datetime.now(timezone.utc).isoformat(),
        "equity":        equity,
        "dd_guard":      {"flattened": flatten,
                          "peak_equity": state["peak_equity"],
                          "stop_active": state["dd_stop_active"]},
        "targets":       targets,
        "positions_before": positions,
        "orders":        submitted if args.execute else orders,
        "executed":      bool(args.execute),
    }
    path = os.path.join(DECISIONS_DIR, f"{stamp}.json")
    with open(path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"[rebalance] Decision log → {path}")

    state["last_rebalance"] = stamp
    save_state(state)


if __name__ == "__main__":
    main()
