# Strategy Backtester

A modular systematic trading backtester. All data is sourced exclusively from **Alpaca Markets** (SIP feed) — no Yahoo Finance.

---

## Portfolio

### ★ Investor Portfolio — recommended allocation
**File:** `strategies/combined_portfolio/main.py`  
**Sharpe:** 0.87 &nbsp;|&nbsp; **Return:** +92% &nbsp;|&nbsp; **Max DD:** −10.7% &nbsp;|&nbsp; **Period:** 2016–2024

Three strategies sharing capital, each with a different return driver and low mutual correlation:

| Sleeve | Weight | Strategy | Purpose |
|---|---|---|---|
| AFP | 50% | Adaptive Factor Portfolio | Equity alpha via factor rotation |
| XAT | 30% | Cross-Asset Trend (SPY·TLT·GLD) | Genuine diversification — bonds and gold protect in crises |
| SIS | 20% | SPY Intraday Short | Market-neutral daily alpha, uncorrelated to everything else |

**Why this beats chasing raw returns:** Sharpe 0.87 with 6.6% volatility means 1.8× leverage gives ~13.5% annualised return with only ~12% vol and ~−19% max DD — better risk-adjusted than SPY buy-and-hold at any return target.

---

## Individual Strategies

### 1. Adaptive Factor Portfolio (AFP)
**File:** `strategies/equity_factor_rotation/main.py`  
**Sharpe:** 0.97 &nbsp;|&nbsp; **Return:** +130% &nbsp;|&nbsp; **Max DD:** −13.6% &nbsp;|&nbsp; **Period:** 2016–2024

Rotates monthly between four US equity factor ETFs — QQQ (growth/tech), QUAL (quality), MTUM (momentum), USMV (min-vol) — using composite momentum with two creative additions:

- **Factor Leadership Tilt:** top-ranked qualifying factor gets 1.5× weight
- **Correlation Regime Filter:** when QQQ and USMV start moving together (correlation >0.75), a systemic event is underway — exposure cuts to 40%. Detected both the 2020 crash and 2022 rate shock without VIX data.

---

### 2. SPY Intraday Afternoon Short
**File:** `strategies/spy_intraday_short/main.py`  
**Sharpe:** 0.72 &nbsp;|&nbsp; **Return:** +21% &nbsp;|&nbsp; **Max DD:** −4.1% &nbsp;|&nbsp; **Period:** 2020–2024

Uses Alpaca 5-minute SPY bars. On high-conviction mornings — when both the overnight gap and first 30-minute return exceed minimum thresholds and agree in direction — **shorts the last 30 minutes of the session**. Up mornings reverse (61% win); down mornings continue (62% win). Active only 18% of days; earns T-bill on the rest.

---

### 3. Tech-Tier Momentum Ladder (reference)
**File:** `strategies/concentrated_momentum/main.py`  
**Return:** +305% &nbsp;|&nbsp; **Sharpe:** 0.54 &nbsp;|&nbsp; **Max DD:** −34.3% &nbsp;|&nbsp; **Period:** 2016–2024

Concentrates monthly into the highest-momentum ETF from SOXX → QQQ → SPY. Beats SPY's +237% raw return by riding SOXX's +701% semiconductor bull, with SPY as a defensive floor when all three have negative momentum. Kept as a reference — the concentration and −34% drawdown make it unsuitable as a standalone primary strategy.

---

## Project Structure

```
├── core/
│   ├── alpaca.py          Shared Alpaca API (auth, pagination, caching, dividend-adjusted prices)
│   ├── data.py            fetch_prices / fetch_spy / fetch_tbill (BIL proxy)
│   └── metrics.py         Sharpe, drawdown, win rate
│
├── strategies/
│   ├── combined_portfolio/        ★ The recommended investor portfolio
│   │   ├── main.py                Run this
│   │   └── config.py              50/30/20 weights
│   │
│   ├── equity_factor_rotation/    AFP — best standalone Sharpe (0.97)
│   │   ├── main.py
│   │   ├── backtest.py
│   │   └── config.py
│   │
│   ├── spy_intraday_short/        Intraday alpha / hedge
│   │   ├── main.py
│   │   ├── strategy.py
│   │   ├── data_intraday.py
│   │   ├── config.py
│   │   ├── STRATEGY.md
│   │   └── generate_pdf.py
│   │
│   └── concentrated_momentum/     Reference — high return, high risk
│       ├── main.py
│       ├── backtest.py
│       └── config.py
│
├── data_cache/            Cached Alpaca downloads (gitignored)
├── outputs/               Charts and CSVs (gitignored)
├── config.py              Shared: dates, capital, absolute paths
├── .env                   Alpaca API credentials (gitignored — never commit)
└── requirements.txt
```

---

## Running

All commands from the project root.

```bash
# ★ Recommended: investor portfolio (50% AFP + 30% cross-asset + 20% intraday)
python -m strategies.combined_portfolio.main

# Individual strategies
python -m strategies.equity_factor_rotation.main
python -m strategies.spy_intraday_short.main
python -m strategies.concentrated_momentum.main

# Generate PDF documentation for the intraday strategy
python strategies/spy_intraday_short/generate_pdf.py
```

---

## Setup

**Install dependencies:**
```bash
pip install pandas numpy matplotlib markdown
```

**Alpaca credentials** (required for all strategies):

1. Sign up at [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → API Keys
2. Add to `.env`:
```
ALPACA_KEY=your-key-id-here
ALPACA_SECRET=your-secret-here
```

**First run** downloads and caches all data automatically. Subsequent runs load from `data_cache/` instantly.

---

## Data Sources

| Data | Source | Notes |
|---|---|---|
| ETF daily prices | Alpaca SIP `1Day` bars, `adjustment=all` | Total return (dividends included) |
| SPY 5-min intraday | Alpaca SIP `5Min` bars | ~400k bars, 2016–2024 |
| T-bill proxy | BIL ETF daily return | SPDR 1-3 Month T-Bill ETF |

---

## Adding a New Strategy

1. Create `strategies/your_strategy/` with `__init__.py`
2. Add `config.py` importing shared params from root `config.py`
3. Add `backtest.py` and `main.py` (see existing strategies for the sys.path pattern)
4. Import from `core.data` and `core.metrics`

---

*Mark Garcera · Aspiring Trader*  
*Academic grounding: Gao et al. (2018, JF) · Lou et al. (2019, JFE) · Moskowitz et al. (2012, JF)*
