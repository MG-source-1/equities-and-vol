"""
GARP fundamental scoring via SEC EDGAR (XBRL Company Facts API).

No API key required. EDGAR is the primary source of US public company
financial statements — every number has an exact `filed` date, making
point-in-time accuracy inherent rather than approximated.

Two modes:

  fetch_garp_scores(tickers, prices=None, cache_dir=None)
      Current GARP scores using the most recent available EDGAR filings.
      Used for the display table in main.py. Requires prices for
      market-cap-dependent metrics (FCF yield, EV/EBITDA, PEG).

  build_garp_history(tickers, prices, cache_dir=None)
      Point-in-time GARP score history for backtesting.
      Computes a score at every quarterly/annual EDGAR filing date.
      Uses the `filed` timestamp directly — no artificial lag required
      since that IS when the data became public.
      Returns DataFrame (index=prices.index, columns=tickers).
      Dates before the first EDGAR filing receive NaN; the backtest
      treats these as pure-momentum periods.

Caching
───────
  data_cache/edgar_cik_map.json      — ticker → CIK mapping (permanent)
  data_cache/edgar_facts_{cik}.json  — raw XBRL company facts (permanent)
  data_cache/garp_hist_{ticker}.pkl  — computed score history (permanent)
Delete any of these to force a refresh.

XBRL concept fallbacks
──────────────────────
Different companies tag identical line items with different XBRL concept
names. Each metric uses a priority-ordered fallback list so the first
matching concept is used, covering the large majority of S&P 500 filers.
"""

import gzip
import json
import os
import time
import urllib.request

import numpy as np
import pandas as pd

_EDGAR_FACTS   = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_EDGAR_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_HEADERS       = {"User-Agent": "GARP Backtester minimark04@gmail.com"}
_SLEEP         = 0.12   # keep well under SEC's 10 req/s guideline

METRIC_WEIGHTS = {
    "peg":      0.30,
    "roe":      0.20,
    "evebitda": 0.15,
    "fcf":      0.15,
    "margin":   0.10,
    "debt":     0.10,
}

# Priority-ordered XBRL concept fallbacks (us-gaap namespace unless noted)
_C = {
    "net_income":  ["NetIncomeLoss",
                    "NetIncomeLossAvailableToCommonStockholdersBasic",
                    "ProfitLoss"],
    "revenue":     ["Revenues",
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "SalesRevenueNet",
                    "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "equity":      ["StockholdersEquity",
                    "StockholdersEquityAttributableToParent",
                    "CommonStockholdersEquity"],
    "op_cf":       ["NetCashProvidedByUsedInOperatingActivities"],
    "capex":       ["PaymentsToAcquirePropertyPlantAndEquipment",
                    "PaymentsToAcquireProductiveAssets"],
    "lt_debt":     ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermNotesPayable"],
    "st_debt":     ["ShortTermBorrowings", "DebtCurrent", "NotesPayableCurrent"],
    "cash":        ["CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsAndShortTermInvestments", "Cash"],
    "op_income":   ["OperatingIncomeLoss"],
    "da":          ["DepreciationDepletionAndAmortization",
                    "DepreciationAndAmortization", "Depreciation"],
    "eps":         ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "shares":      ["CommonStockSharesOutstanding"],
    "shares_dei":  ["EntityCommonStockSharesOutstanding"],   # dei namespace
}

_Q_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}
_Q_FP    = {"Q1", "Q2", "Q3", "Q4"}
_A_FP    = {"FY"}


# ── Metric scorers (0–1) ──────────────────────────────────────

def _peg_score(v) -> float:
    try: v = float(v)
    except: return 0.30
    if v <= 0: return 0.10
    return max(0.0, 1.0 - min(v, 3.0) / 3.0)

def _roe_score(v) -> float:
    try: v = float(v)
    except: return 0.30
    if v < 0: return 0.10
    return min(v, 0.50) / 0.50

def _evebitda_score(v) -> float:
    try: v = float(v)
    except: return 0.30
    if v <= 0: return 0.30
    return max(0.0, 1.0 - min(v, 50.0) / 50.0)

def _fcf_score(v) -> float:
    try: v = float(v)
    except: return 0.30
    if v < 0: return 0.10
    return min(v, 0.10) / 0.10

def _margin_score(v) -> float:
    try: v = float(v)
    except: return 0.30
    if v < 0: return 0.10
    return min(v, 0.40) / 0.40

def _debt_score(v) -> float:
    try: v = float(v)
    except: return 0.50
    if v < 0: return 0.50
    return max(0.0, 1.0 - min(v, 3.0) / 3.0)


# ── EDGAR I/O ─────────────────────────────────────────────────

def _http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        encoding = r.info().get("Content-Encoding", "")
        raw = r.read()
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def _get_cik_map(cache_dir=None) -> dict:
    """Return {TICKER: cik_str} mapping from EDGAR. Cached permanently."""
    path = os.path.join(cache_dir, "edgar_cik_map.json") if cache_dir else None
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    data    = _http_get(_EDGAR_TICKERS)
    mapping = {v["ticker"].upper(): str(v["cik_str"]) for v in data.values()}
    if path:
        with open(path, "w") as f:
            json.dump(mapping, f)
    return mapping


def _get_facts(cik: str, cache_dir=None) -> dict:
    """Fetch and permanently cache EDGAR XBRL company facts."""
    path = os.path.join(cache_dir, f"edgar_facts_{cik}.json") if cache_dir else None
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = _EDGAR_FACTS.format(cik=int(cik))
    time.sleep(_SLEEP)
    data = _http_get(url)
    if path:
        with open(path, "w") as f:
            json.dump(data, f)
    return data


# ── Entry parsing ─────────────────────────────────────────────

def _entries(facts: dict, concepts: list, namespace: str = "us-gaap") -> list:
    """Return raw entries for the first matching XBRL concept."""
    ns = facts.get("facts", {}).get(namespace, {})
    for c in concepts:
        node = ns.get(c)
        if not node:
            continue
        for unit, rows in node.get("units", {}).items():
            if unit in ("USD", "shares", "USD/shares"):
                return rows
    return []


def _to_df(rows: list, fp_ok: set) -> pd.DataFrame:
    """
    Convert raw EDGAR entries to a clean DataFrame with columns
    [end, filed, val]. Filters to allowed fiscal periods and
    10-Q / 10-K form types. Deduplicates by period end date,
    keeping the most recently filed version (handles amendments).
    """
    out = []
    for r in rows:
        if r.get("form") not in _Q_FORMS:
            continue
        if r.get("fp") not in fp_ok:
            continue
        try:
            out.append({
                "end":   pd.Timestamp(r["end"]),
                "filed": pd.Timestamp(r["filed"]),
                "val":   float(r["val"]),
            })
        except Exception:
            continue
    if not out:
        return pd.DataFrame(columns=["end", "filed", "val"])
    df = (pd.DataFrame(out)
            .sort_values("filed")
            .groupby("end", as_index=False)
            .last()
            .sort_values("end")
            .reset_index(drop=True))
    return df


# ── Point-in-time metric retrieval ────────────────────────────

def _ttm(q_df: pd.DataFrame, a_df: pd.DataFrame, as_of: pd.Timestamp):
    """
    Trailing Twelve Months for a flow metric (income, cash flow) as of `as_of`.

    Method: use the most recent annual (10-K) as a base, then adjust for any
    quarters filed after the annual period that are now known. This matches
    how professional data providers compute TTM:
        TTM = Annual + post-annual quarters − equivalent prior-year quarters

    Falls back to summing the 4 most recent quarterly values when no annual
    filing is available yet.
    """
    q = q_df[q_df["filed"] <= as_of]
    a = a_df[a_df["filed"] <= as_of]

    if a.empty:
        return float(q.tail(4)["val"].sum()) if len(q) >= 4 else None

    fy_end = a.iloc[-1]["end"]
    fy_val = float(a.iloc[-1]["val"])

    post_q = q[q["end"] > fy_end]
    n_post = len(post_q)
    if n_post == 0:
        return fy_val

    prior_q = q[
        (q["end"] > fy_end - pd.DateOffset(years=1)) &
        (q["end"] <= fy_end)
    ].tail(n_post)

    if len(prior_q) != n_post:
        return fy_val   # can't compute clean adjustment; use annual as proxy

    return fy_val + float(post_q["val"].sum()) - float(prior_q["val"].sum())


def _latest(rows: list, as_of: pd.Timestamp):
    """Most recent balance-sheet value filed on or before as_of."""
    df = _to_df(rows, fp_ok=_Q_FP | _A_FP)
    avail = df[df["filed"] <= as_of]
    return float(avail.iloc[-1]["val"]) if not avail.empty else None


# ── Composite score computation ───────────────────────────────

def _compute(facts: dict, as_of: pd.Timestamp, price) -> dict:
    """
    Compute all GARP metrics and composite score for one ticker as of `as_of`.
    Only uses data whose `filed` date is on or before `as_of`.
    Returns a dict with individual raw metrics, sub-scores, and garp_score.
    """
    # Fetch raw entry lists
    ni_r  = _entries(facts, _C["net_income"])
    rev_r = _entries(facts, _C["revenue"])
    eq_r  = _entries(facts, _C["equity"])
    ocf_r = _entries(facts, _C["op_cf"])
    cx_r  = _entries(facts, _C["capex"])
    ltd_r = _entries(facts, _C["lt_debt"])
    std_r = _entries(facts, _C["st_debt"])
    csh_r = _entries(facts, _C["cash"])
    oi_r  = _entries(facts, _C["op_income"])
    da_r  = _entries(facts, _C["da"])
    eps_r = _entries(facts, _C["eps"])
    shr_r = (_entries(facts, _C["shares"]) or
              _entries(facts, _C["shares_dei"], namespace="dei"))

    # Build quarterly / annual DataFrames for flow metrics
    ni_q,  ni_a  = _to_df(ni_r,  _Q_FP), _to_df(ni_r,  _A_FP)
    rev_q, rev_a = _to_df(rev_r, _Q_FP), _to_df(rev_r, _A_FP)
    ocf_q, ocf_a = _to_df(ocf_r, _Q_FP), _to_df(ocf_r, _A_FP)
    cx_q,  cx_a  = _to_df(cx_r,  _Q_FP), _to_df(cx_r,  _A_FP)
    oi_q,  oi_a  = _to_df(oi_r,  _Q_FP), _to_df(oi_r,  _A_FP)
    da_q,  da_a  = _to_df(da_r,  _Q_FP), _to_df(da_r,  _A_FP)
    eps_q         = _to_df(eps_r, _Q_FP)

    # TTM flow metrics
    net_income = _ttm(ni_q,  ni_a,  as_of)
    revenue    = _ttm(rev_q, rev_a, as_of)
    op_cf      = _ttm(ocf_q, ocf_a, as_of)
    capex_raw  = _ttm(cx_q,  cx_a,  as_of)
    op_income  = _ttm(oi_q,  oi_a,  as_of)
    da         = _ttm(da_q,  da_a,  as_of)

    # FCF = operating cash flow − capital expenditure
    # CapEx is reported as a positive outflow in EDGAR, so subtract its absolute value
    fcf = (op_cf - abs(capex_raw)) if (op_cf is not None and capex_raw is not None) else None

    # Balance-sheet snapshots (most recent as of as_of)
    equity     = _latest(eq_r,  as_of)
    lt_debt    = _latest(ltd_r, as_of) or 0.0
    st_debt    = _latest(std_r, as_of) or 0.0
    cash       = _latest(csh_r, as_of) or 0.0
    shares     = _latest(shr_r, as_of)
    total_debt = lt_debt + st_debt

    # Market data
    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None
    mktcap = (price * shares) if (price and shares and price > 0 and shares > 0) else None
    ev     = (mktcap + total_debt - cash) if mktcap else None

    # Derived metrics
    roe       = (net_income / equity)   if (net_income is not None and equity and equity > 0) else None
    margin    = (net_income / revenue)  if (net_income is not None and revenue and revenue > 0) else None
    de        = (total_debt / equity)   if (equity and equity > 0) else None
    fcf_yield = (fcf / mktcap)          if (fcf is not None and mktcap and mktcap > 0) else None
    ebitda    = (op_income + da)        if (op_income is not None and da is not None) else None
    evebitda  = (ev / ebitda)           if (ev and ebitda and ebitda > 0) else None

    # Trailing PEG = (price / TTM EPS) / (YoY TTM EPS growth × 100)
    peg = None
    eps_avail = eps_q[eps_q["filed"] <= as_of]
    if len(eps_avail) >= 8 and price and price > 0:
        ttm_eps   = float(eps_avail.tail(4)["val"].sum())
        prior_eps = float(eps_avail.iloc[-8:-4]["val"].sum())
        if ttm_eps > 0 and prior_eps != 0:
            pe         = price / ttm_eps
            eps_growth = (ttm_eps - prior_eps) / abs(prior_eps)
            if eps_growth > 0:
                peg = pe / (eps_growth * 100)

    # Sub-scores and composite
    peg_s    = _peg_score(peg)
    roe_s    = _roe_score(roe)
    ev_s     = _evebitda_score(evebitda)
    fcf_s    = _fcf_score(fcf_yield)
    margin_s = _margin_score(margin)
    debt_s   = _debt_score(de)

    composite = round(
        METRIC_WEIGHTS["peg"]      * peg_s    +
        METRIC_WEIGHTS["roe"]      * roe_s    +
        METRIC_WEIGHTS["evebitda"] * ev_s     +
        METRIC_WEIGHTS["fcf"]      * fcf_s    +
        METRIC_WEIGHTS["margin"]   * margin_s +
        METRIC_WEIGHTS["debt"]     * debt_s,
        4,
    )

    def _fmt(v, scale=1.0, d=2):
        return round(float(v) * scale, d) if v is not None else None

    return {
        "peg":            _fmt(peg),
        "roe_pct":        _fmt(roe,       100, 1),
        "ev_ebitda":      _fmt(evebitda,  1,   1),
        "fcf_yield_pct":  _fmt(fcf_yield, 100, 2),
        "net_margin_pct": _fmt(margin,    100, 1),
        "debt_equity":    _fmt(de,        1,   2),
        "peg_score":      round(peg_s,    3),
        "roe_score":      round(roe_s,    3),
        "ev_score":       round(ev_s,     3),
        "fcf_score":      round(fcf_s,    3),
        "margin_score":   round(margin_s, 3),
        "debt_score":     round(debt_s,   3),
        "garp_score":     composite,
    }


# ── Public API ────────────────────────────────────────────────

def fetch_garp_scores(
    tickers: list,
    prices: pd.DataFrame = None,
    cache_dir: str = None,
) -> pd.DataFrame:
    """
    Current GARP scores from the most recent available EDGAR filings.
    For display only — not used in backtesting.

    prices: daily price DataFrame (tickers as columns). When provided,
            the most recent price is used for market-cap-dependent metrics
            (FCF yield, EV/EBITDA, PEG). Without prices, those metrics
            fall back to their neutral scores.
    """
    cik_map = _get_cik_map(cache_dir)
    as_of   = pd.Timestamp.now().normalize()
    rows    = []

    for tkr in tickers:
        cik = cik_map.get(tkr.upper())
        if not cik:
            print(f"[fundamentals] {tkr}: CIK not found in EDGAR — neutral score")
            rows.append({"ticker": tkr, "garp_score": 0.30})
            continue
        try:
            facts = _get_facts(cik, cache_dir)
            price = None
            if prices is not None and tkr in prices.columns:
                px = prices[tkr].dropna()
                if not px.empty:
                    price = float(px.iloc[-1])
            metrics        = _compute(facts, as_of, price)
            metrics["ticker"] = tkr
            rows.append(metrics)
        except Exception as e:
            print(f"[fundamentals] {tkr}: {e} — neutral score")
            rows.append({"ticker": tkr, "garp_score": 0.30})

    return pd.DataFrame(rows).set_index("ticker")


def build_garp_history(
    tickers: list,
    prices: pd.DataFrame,
    cache_dir: str = None,
) -> pd.DataFrame:
    """
    Build point-in-time GARP score history from SEC EDGAR filings.

    For each ticker, computes a GARP score at every date a quarterly (10-Q)
    or annual (10-K) filing was submitted to the SEC. The `filed` timestamp
    from EDGAR is used directly as the known date — no artificial lag needed.

    Returns DataFrame (index=prices.index, columns=tickers).
    Dates before the first available EDGAR filing receive NaN; the backtest
    detects these and runs as pure momentum with equal GARP weight.

    Cache files:
      edgar_cik_map.json       — refreshed by deleting
      edgar_facts_{cik}.json   — one per ticker; delete to re-fetch
      garp_hist_{ticker}.pkl   — computed history; delete to recompute
    """
    cik_map     = _get_cik_map(cache_dir)
    all_series: dict = {}

    for tkr in tickers:
        pkl_path = os.path.join(cache_dir, f"garp_hist_{tkr}.pkl") if cache_dir else None
        if pkl_path and os.path.exists(pkl_path):
            try:
                all_series[tkr] = pd.read_pickle(pkl_path)
                print(f"[fundamentals] {tkr}: loaded from cache")
                continue
            except Exception:
                pass

        cik = cik_map.get(tkr.upper())
        if not cik:
            print(f"[fundamentals] {tkr}: CIK not found — neutral scores")
            all_series[tkr] = pd.Series(dtype=float)
            continue

        try:
            facts = _get_facts(cik, cache_dir)
        except Exception as e:
            print(f"[fundamentals] {tkr}: EDGAR fetch failed ({e}) — neutral scores")
            all_series[tkr] = pd.Series(dtype=float)
            continue

        # Use net income filing dates as event triggers (quarterly + annual)
        ni_rows = _entries(facts, _C["net_income"])
        ni_q    = _to_df(ni_rows, _Q_FP)
        ni_a    = _to_df(ni_rows, _A_FP)
        filing_dates = sorted(set(ni_q["filed"].tolist() + ni_a["filed"].tolist()))

        if not filing_dates:
            print(f"[fundamentals] {tkr}: no filing dates found — neutral scores")
            all_series[tkr] = pd.Series(dtype=float)
            continue

        price_s = prices[tkr] if tkr in prices.columns else None
        scores: dict = {}

        for filed_date in filing_dates:
            price = None
            if price_s is not None:
                avail_px = price_s[price_s.index <= filed_date]
                if not avail_px.empty:
                    price = float(avail_px.iloc[-1])
            try:
                result = _compute(facts, filed_date, price)
                scores[filed_date] = result["garp_score"]
            except Exception:
                pass

        if not scores:
            all_series[tkr] = pd.Series(dtype=float)
            continue

        s = pd.Series(scores).sort_index()
        # Trim to dates that fall within the prices window (with a 1-year forward buffer)
        s = s[s.index <= prices.index[-1] + pd.Timedelta(days=365)]

        n = len(s)
        if n:
            print(
                f"[fundamentals] {tkr}: {n} filing dates "
                f"({s.index[0].strftime('%Y-%m-%d')} → {s.index[-1].strftime('%Y-%m-%d')})"
            )
        else:
            print(f"[fundamentals] {tkr}: no filings in price window — neutral scores")

        all_series[tkr] = s

        if pkl_path:
            try:
                s.to_pickle(pkl_path)
            except Exception:
                pass

    # Forward-fill sparse filing events into the daily prices index
    score_df = pd.DataFrame(all_series)
    full_idx  = prices.index
    if score_df.empty:
        return pd.DataFrame(np.nan, index=full_idx, columns=tickers)

    merged = (
        score_df
        .reindex(score_df.index.union(full_idx))
        .sort_index()
        .ffill()
        .reindex(full_idx)
    )
    return merged
