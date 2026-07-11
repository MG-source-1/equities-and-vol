"""
Vanilla European option pricing — Black-Scholes-Merton.

Deliberately plain: closed-form BSM prices and greeks plus a robust implied
vol solver, on numpy scalars/arrays. No exotics, no trees, no scipy — the
normal CDF comes from math.erf, so the whole module needs only numpy.

Conventions (desk-standard):
  S      spot                     K      strike
  T      time to expiry in YEARS  r      cont.-comp. risk-free rate
  sigma  annualised implied vol   q      cont.-comp. dividend yield
  cp     +1 call / -1 put

Greeks are reported the way a risk report reads them:
  delta  — per 1.00 move in spot        gamma — per 1.00 move, of delta
  vega   — per 1 VOL POINT (1.00 = 1%)  theta — per CALENDAR DAY
"""

import math

import numpy as np

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x, dtype=float) / math.sqrt(2.0)))


def _norm_pdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(S, K, T, r, sigma, q):
    S, K, T, sigma = (np.asarray(v, dtype=float) for v in (S, K, T, sigma))
    T = np.maximum(T, 1e-12)
    sigma = np.maximum(sigma, 1e-12)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return d1, d1 - sigma * np.sqrt(T)


def bs_price(S, K, T, r, sigma, cp=1, q=0.0):
    """Black-Scholes-Merton price. At T=0 returns intrinsic value."""
    S, K = np.asarray(S, dtype=float), np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    intrinsic = np.maximum(cp * (S - K), 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    price = cp * (S * np.exp(-q * T) * _norm_cdf(cp * d1)
                  - K * np.exp(-r * T) * _norm_cdf(cp * d2))
    return np.where(T <= 0, intrinsic, price)


def bs_greeks(S, K, T, r, sigma, cp=1, q=0.0) -> dict:
    """Delta, gamma, vega (per vol point), theta (per calendar day), rho.

    At/after expiry all risk greeks are zero except delta, which is the
    settlement delta (0 or ±1).
    """
    S = np.asarray(S, dtype=float)
    T = np.asarray(T, dtype=float)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    sqrtT = np.sqrt(np.maximum(T, 1e-12))
    pdf = _norm_pdf(d1)

    delta = cp * np.exp(-q * T) * _norm_cdf(cp * d1)
    gamma = np.exp(-q * T) * pdf / (S * np.maximum(sigma, 1e-12) * sqrtT)
    vega = S * np.exp(-q * T) * pdf * sqrtT / 100.0          # per 1 vol pt
    theta_yr = (-S * np.exp(-q * T) * pdf * sigma / (2.0 * sqrtT)
                - cp * r * K * np.exp(-r * T) * _norm_cdf(cp * d2)
                + cp * q * S * np.exp(-q * T) * _norm_cdf(cp * d1))
    theta = theta_yr / 365.0                                  # per calendar day
    rho = cp * K * T * np.exp(-r * T) * _norm_cdf(cp * d2) / 100.0

    expired = T <= 0
    settle_delta = cp * (cp * (S - K) > 0).astype(float)
    return {
        "delta": np.where(expired, settle_delta, delta),
        "gamma": np.where(expired, 0.0, gamma),
        "vega":  np.where(expired, 0.0, vega),
        "theta": np.where(expired, 0.0, theta),
        "rho":   np.where(expired, 0.0, rho),
    }


def implied_vol(price, S, K, T, r, cp=1, q=0.0,
                lo=1e-4, hi=5.0, tol=1e-8, max_iter=100) -> float:
    """Implied vol by bisection (scalar). Monotonicity of vega makes this
    unconditionally convergent; returns nan if the price is outside
    no-arbitrage bounds."""
    price = float(price)
    if T <= 0:
        return float("nan")
    p_lo = float(bs_price(S, K, T, r, lo, cp, q))
    p_hi = float(bs_price(S, K, T, r, hi, cp, q))
    if not (p_lo <= price <= p_hi):
        return float("nan")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if float(bs_price(S, K, T, r, mid, cp, q)) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def strike_for_delta(target_delta, S, T, r, sigma, cp=1, q=0.0) -> float:
    """Strike whose BSM delta equals target_delta (desk convention: quote
    strikes by delta, e.g. the '25-delta put' has delta = -0.25)."""
    from math import sqrt, exp, log  # noqa: F401
    # invert delta = cp * exp(-qT) * N(cp*d1)  →  d1 = cp * N^-1(cp*delta*e^{qT})
    x = cp * target_delta * math.exp(q * T)
    x = min(max(x, 1e-10), 1 - 1e-10)
    d1 = cp * _norm_ppf(x)
    return float(S * math.exp(-(d1 * sigma * math.sqrt(T)
                                - (r - q + 0.5 * sigma ** 2) * T)))


def _norm_ppf(p: float) -> float:
    """Acklam's inverse normal CDF approximation (|error| < 1.15e-9)."""
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > p_high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    s = q * q
    return (((((a[0]*s+a[1])*s+a[2])*s+a[3])*s+a[4])*s+a[5])*q / \
           (((((b[0]*s+b[1])*s+b[2])*s+b[3])*s+b[4])*s+1)
