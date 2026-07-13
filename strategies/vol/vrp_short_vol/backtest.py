"""
VRP — Volatility Risk Premium — backtest engine.

Event-driven daily loop (options books can't be run as weight matrices —
positions have path-dependent stops and expiries):

  Each day t, in order:
    1. Mark the book at t's close (spot from Alpaca, IV = VIX/100) and
       attribute the day's P&L to greeks using YESTERDAY's greeks:
         delta P&L = Δ·dS      gamma P&L = ½Γ·dS²
         vega  P&L = ν·dIV     theta P&L = θ·(calendar days elapsed)
       plus hedge-share P&L and T-bill interest on cash; the unexplained
       remainder is reported as `residual` (higher-order/cross terms).
    2. Manage: settle at expiry; buy back if the strangle marks at
       STOP_MULT × premium received.
    3. Roll (month-end only): if VRP = VIX − EWMA realised vol exceeds the
       entry threshold, sell a new 25-delta strangle expiring next month-
       end, sized so book vega ≈ −VEGA_BUDGET × equity per vol point.
    4. Re-hedge: trade underlying shares to flatten book delta (if enabled).

  All decisions at t use data through t's close — same convention as every
  other engine in this repo. Costs: HALF_SPREAD_VOLPTS per leg per
  transaction (charged through the leg's vega — a vol-point half-spread is
  how options spreads are actually quoted), and HEDGE_COST_BPS on hedge
  notional.
"""

import numpy as np
import pandas as pd

from core.options import bs_price, bs_greeks, strike_for_delta


def _month_end_dates(index: pd.DatetimeIndex) -> list:
    periods = index.to_period("M")
    return [index[periods == p][-1] for p in periods.unique()]


def ewma_realised_vol(returns: pd.Series, lam: float) -> pd.Series:
    """RiskMetrics EWMA vol, annualised, in vol points (e.g. 16.5)."""
    var = returns.pow(2).ewm(alpha=1 - lam, adjust=False).mean()
    return np.sqrt(var * 252) * 100


def _leg_value_greeks(S, K, T, r, iv, cp, q):
    price = float(bs_price(S, K, T, r, iv, cp, q))
    g = bs_greeks(S, K, T, r, iv, cp, q)
    return price, {k: float(v) for k, v in g.items()}


class _Book:
    """One short strangle + its delta hedge."""

    def __init__(self, k_put, k_call, expiry, contracts, entry_premium):
        self.k_put, self.k_call = k_put, k_call
        self.expiry = expiry
        self.n = contracts                 # contracts per leg (short)
        self.entry_premium = entry_premium  # $ per book at entry
        self.hedge_shares = 0.0

    def value_and_greeks(self, S, T, r, iv, q, mult):
        """Book mark (liability, $) and net greeks ($ per unit)."""
        p_put, g_put = _leg_value_greeks(S, self.k_put, T, r, iv, -1, q)
        p_call, g_call = _leg_value_greeks(S, self.k_call, T, r, iv, +1, q)
        scale = self.n * mult
        value = (p_put + p_call) * scale                    # what buyback costs
        greeks = {k: -(g_put[k] + g_call[k]) * scale for k in g_put}  # short
        greeks["delta"] += self.hedge_shares                # hedge is pure delta
        return value, greeks


def run_vrp_backtest(
    spot: pd.Series,            # underlying daily closes
    vix: pd.Series,             # VIX closes, vol points
    tbill_daily_rate: pd.Series,
    initial_capital: float,
    cfg,
    delta_hedge: bool = None,
) -> pd.DataFrame:
    if delta_hedge is None:
        delta_hedge = cfg.DELTA_HEDGE

    idx = spot.index.intersection(vix.index)
    spot = spot.reindex(idx)
    vix = vix.reindex(idx)
    tbill = tbill_daily_rate.reindex(idx).ffill().fillna(0.0)
    rets = spot.pct_change()
    rv = ewma_realised_vol(rets, cfg.EWMA_LAMBDA)
    vrp = vix - rv
    # short-rate proxy for pricing (annualised from BIL)
    r_ann = (tbill.rolling(21).mean() * 252).fillna(0.02).clip(lower=0.0)

    month_ends = _month_end_dates(idx)
    me_set = set(month_ends)
    next_me = {d: month_ends[i + 1] for i, d in enumerate(month_ends[:-1])}

    equity = initial_capital
    book = None
    prev = None      # yesterday's snapshot for attribution
    records = []
    q, mult = cfg.DIV_YIELD, cfg.CONTRACT_MULT

    warmup = idx[60]     # let the EWMA vol estimate season
    for t in idx:
        S, ivp = float(spot[t]), float(vix[t])
        iv = ivp / 100.0
        r = float(r_ann[t])

        # ── 1. Mark & attribute ───────────────────────────────
        d_delta = d_gamma = d_vega = d_theta = d_resid = 0.0
        interest = equity * float(tbill[t])
        pnl = interest
        if book is not None and prev is not None:
            T_rem = max((book.expiry - t).days, 0) / 365.0
            value_now, greeks_now = book.value_and_greeks(S, T_rem, r, iv, q, mult)
            dS = S - prev["S"]
            dIV = ivp - prev["ivp"]
            d_days = (t - prev["t"]).days
            opt_pnl = prev["value"] - value_now              # short: value falling = gain
            hedge_pnl = book.hedge_shares * dS
            d_delta = (prev["greeks"]["delta"]) * dS         # includes hedge delta
            d_gamma = 0.5 * prev["greeks"]["gamma"] * dS ** 2
            d_vega = prev["greeks"]["vega"] * dIV
            d_theta = prev["greeks"]["theta"] * d_days
            total_explained = d_delta + d_gamma + d_vega + d_theta
            d_resid = (opt_pnl + hedge_pnl) - total_explained
            pnl += opt_pnl + hedge_pnl
        equity += pnl

        # ── 2. Manage ─────────────────────────────────────────
        action = ""
        day_costs = 0.0
        if book is not None:
            T_rem = max((book.expiry - t).days, 0) / 365.0
            value_now, _ = book.value_and_greeks(S, T_rem, r, iv, q, mult)
            if t >= book.expiry:
                # settle at intrinsic (bs_price returns intrinsic at T=0);
                # unwind hedge
                day_costs += abs(book.hedge_shares) * S * cfg.HEDGE_COST_BPS / 1e4
                action = "expire"
                book = None
            elif value_now >= cfg.STOP_MULT * book.entry_premium:
                # stop: buy back both legs, crossing the spread
                _, g = _leg_value_greeks(S, book.k_put, T_rem, r, iv, -1, q)
                _, gc = _leg_value_greeks(S, book.k_call, T_rem, r, iv, +1, q)
                day_costs += (g["vega"] + gc["vega"]) * cfg.HALF_SPREAD_VOLPTS \
                    * book.n * mult
                day_costs += abs(book.hedge_shares) * S * cfg.HEDGE_COST_BPS / 1e4
                action = "stop"
                book = None

        # ── 3. Roll (month-end, signal-gated) ─────────────────
        if t in me_set and t in next_me and t >= warmup and book is None:
            if float(vrp[t]) > cfg.VRP_ENTRY:
                expiry = next_me[t]
                T_new = max((expiry - t).days, 1) / 365.0
                k_put = strike_for_delta(-cfg.DELTA_TARGET, S, T_new, r, iv, -1, q)
                k_call = strike_for_delta(+cfg.DELTA_TARGET, S, T_new, r, iv, +1, q)
                p_put, g_put = _leg_value_greeks(S, k_put, T_new, r, iv, -1, q)
                p_call, g_call = _leg_value_greeks(S, k_call, T_new, r, iv, +1, q)
                vega_per_contract = (g_put["vega"] + g_call["vega"]) * mult
                n = max(int((cfg.VEGA_BUDGET * equity) / max(vega_per_contract, 1e-9)), 0)
                if n > 0:
                    premium = (p_put + p_call) * n * mult
                    day_costs += (g_put["vega"] + g_call["vega"]) \
                        * cfg.HALF_SPREAD_VOLPTS * n * mult
                    book = _Book(k_put, k_call, expiry, n, premium)
                    action = (action + "+" if action else "") + "sell"

        # ── 4. Re-hedge ───────────────────────────────────────
        if book is not None and delta_hedge:
            T_rem = max((book.expiry - t).days, 0) / 365.0
            _, greeks_nohedge = book.value_and_greeks(S, T_rem, r, iv, q, mult)
            option_delta = greeks_nohedge["delta"] - book.hedge_shares
            target = -option_delta
            trade = target - book.hedge_shares
            if abs(trade) * S > 1.0:
                day_costs += abs(trade) * S * cfg.HEDGE_COST_BPS / 1e4
                book.hedge_shares = target

        equity -= day_costs

        # ── snapshot for tomorrow's attribution ───────────────
        if book is not None:
            T_rem = max((book.expiry - t).days, 0) / 365.0
            value, greeks = book.value_and_greeks(S, T_rem, r, iv, q, mult)
        else:
            value, greeks = 0.0, {k: 0.0 for k in
                                  ("delta", "gamma", "vega", "theta", "rho")}
        prev = {"t": t, "S": S, "ivp": ivp, "value": value, "greeks": greeks}

        records.append({
            "date": t, "equity": equity, "spot": S, "vix": ivp,
            "realised_vol": float(rv[t]) if np.isfinite(rv[t]) else np.nan,
            "vrp": float(vrp[t]) if np.isfinite(vrp[t]) else np.nan,
            "in_position": book is not None,
            "book_value": value,
            "delta": greeks["delta"], "gamma": greeks["gamma"],
            "vega": greeks["vega"], "theta": greeks["theta"],
            "hedge_shares": book.hedge_shares if book else 0.0,
            "delta_pnl": d_delta, "gamma_pnl": d_gamma,
            "vega_pnl": d_vega, "theta_pnl": d_theta,
            "residual_pnl": d_resid, "interest": interest,
            "costs": day_costs,
            "action": action,
        })

    df = pd.DataFrame(records).set_index("date")
    df["portfolio_value"] = df["equity"]
    df["daily_return"] = df["equity"].pct_change().fillna(0.0)
    df["in_regime"] = df["in_position"]
    return df
