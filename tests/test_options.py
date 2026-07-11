"""
Black-Scholes engine tests — the options/VRP layer is built on this module,
so it gets the strictest checks in the suite: closed-form identities,
greeks vs finite differences, and solver roundtrips.
"""

import numpy as np
import pytest

from core.options import (
    bs_price, bs_greeks, implied_vol, strike_for_delta, _norm_ppf,
)

S, K, T, R, SIG, Q = 100.0, 105.0, 0.25, 0.04, 0.22, 0.012


def test_put_call_parity():
    c = bs_price(S, K, T, R, SIG, cp=+1, q=Q)
    p = bs_price(S, K, T, R, SIG, cp=-1, q=Q)
    lhs = c - p
    rhs = S * np.exp(-Q * T) - K * np.exp(-R * T)
    assert lhs == pytest.approx(rhs, abs=1e-10)


def test_known_value():
    # Textbook check: S=100, K=100, T=1, r=5%, sigma=20%, q=0 → call ≈ 10.4506
    assert float(bs_price(100, 100, 1.0, 0.05, 0.20)) == pytest.approx(10.4506, abs=1e-3)


def test_expiry_is_intrinsic():
    assert float(bs_price(110, 100, 0.0, R, SIG, cp=+1)) == pytest.approx(10.0)
    assert float(bs_price(110, 100, 0.0, R, SIG, cp=-1)) == pytest.approx(0.0)


@pytest.mark.parametrize("cp", [+1, -1])
def test_greeks_match_finite_differences(cp):
    g = bs_greeks(S, K, T, R, SIG, cp=cp, q=Q)
    h = 1e-4
    fd_delta = (bs_price(S + h, K, T, R, SIG, cp, Q)
                - bs_price(S - h, K, T, R, SIG, cp, Q)) / (2 * h)
    fd_gamma = (bs_price(S + h, K, T, R, SIG, cp, Q)
                - 2 * bs_price(S, K, T, R, SIG, cp, Q)
                + bs_price(S - h, K, T, R, SIG, cp, Q)) / h ** 2
    fd_vega = (bs_price(S, K, T, R, SIG + 1e-4, cp, Q)
               - bs_price(S, K, T, R, SIG - 1e-4, cp, Q)) / (2 * 1e-4) / 100
    dt = 1e-5
    fd_theta = (bs_price(S, K, T - dt, R, SIG, cp, Q)
                - bs_price(S, K, T, R, SIG, cp, Q)) / dt / 365

    assert float(g["delta"]) == pytest.approx(float(fd_delta), abs=1e-6)
    assert float(g["gamma"]) == pytest.approx(float(fd_gamma), abs=1e-4)
    assert float(g["vega"]) == pytest.approx(float(fd_vega), abs=1e-6)
    assert float(g["theta"]) == pytest.approx(float(fd_theta), rel=1e-4)


@pytest.mark.parametrize("cp,sigma", [(+1, 0.15), (-1, 0.15), (+1, 0.55), (-1, 0.55)])
def test_implied_vol_roundtrip(cp, sigma):
    price = float(bs_price(S, K, T, R, sigma, cp, Q))
    assert implied_vol(price, S, K, T, R, cp, Q) == pytest.approx(sigma, abs=1e-6)


def test_implied_vol_rejects_arbitrage():
    assert np.isnan(implied_vol(-1.0, S, K, T, R, +1, Q))       # negative price
    assert np.isnan(implied_vol(S * 2, S, K, T, R, +1, Q))      # above bound


@pytest.mark.parametrize("cp,target", [(+1, 0.25), (-1, -0.25), (+1, 0.50), (-1, -0.10)])
def test_strike_for_delta_roundtrip(cp, target):
    k = strike_for_delta(target, S, T, R, SIG, cp, Q)
    d = float(bs_greeks(S, k, T, R, SIG, cp, Q)["delta"])
    assert d == pytest.approx(target, abs=1e-6)
    # sanity: 25d put strikes below spot, 25d call above
    assert (k > S) if cp == +1 else (k < S)


def test_norm_ppf_inverts_cdf():
    from core.options import _norm_cdf
    for p in (0.001, 0.01, 0.25, 0.5, 0.75, 0.99, 0.999):
        assert float(_norm_cdf(_norm_ppf(p))) == pytest.approx(p, abs=1e-8)
