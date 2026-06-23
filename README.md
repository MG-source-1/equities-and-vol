# Strategy Backtester

A modular systematic trading backtester. All data is sourced from **Alpaca Markets** (SIP feed) and yahoo finance.

---

## Portfolio

### ★ Investor Portfolio — recommended allocation
**File:** `strategies/combined_portfolio/main.py`  
**Sharpe:** 1.11 &nbsp;|&nbsp; **Return:** +247% &nbsp;|&nbsp; **Max DD:** −16.4% &nbsp;|&nbsp; **Period:** 2016–2024

Three uncorrelated return engines sharing capital:

| Sleeve | Weight | Strategy | Purpose |
|---|---|---|---|
| GARP | 40% | GARP Momentum (individual stocks) | Equity alpha — individual stock selection via PEG, ROE, FCF, momentum |
| XAT | 40% | Cross-Asset Trend (SPY·TLT·GLD) | Genuine diversification — bonds and gold protect in equity drawdowns |
| SIS | 20% | SPY Intraday Short | Market-neutral daily alpha, uncorrelated to everything else |

**Why GARP replaced AFP:** AFP (factor ETFs) and GARP (individual stocks) are both long-equity — running both just doubles equity exposure without diversification benefit. GARP is strictly better as the equity engine (Sharpe 1.23 vs 0.97; +531% vs +130% standalone). XAT gets equal weight to AFP's old 50% because individual stocks need more bond/gold ballast than factor ETFs did.

**Result:** Sharpe 1.11, +247% total return, beats SPY (+237%) with half the max drawdown (−16% vs SPY's −34%).

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

### 3. GARP Momentum
**File:** `strategies/garp_momentum/main.py`  
**Sharpe:** 1.23 &nbsp;|&nbsp; **Return:** +531% &nbsp;|&nbsp; **Max DD:** −21.2% &nbsp;|&nbsp; **Period:** 2016–2024

Applies **Growth at a Reasonable Price (GARP)** fundamental screening to a 15-stock TMT universe (AAPL, MSFT, GOOGL, META, NVDA, AMD, AVGO, QCOM, ORCL, CRM, ADBE, NFLX, AMZN, TSLA, INTC), then selects and sizes positions using **Jegadeesh-Titman price momentum**.

Six ratios are scored and combined into a composite GARP quality rank:

| Ratio | Weight | Signal |
|---|---|---|
| PEG ratio | 30% | P/E ÷ EPS growth — core GARP metric; <1 = paying less than 1× per % of growth |
| Return on Equity | 20% | Profitability quality; great companies sustain ROE >30% |
| EV/EBITDA | 15% | Enterprise value efficiency; lower = cheaper relative to earnings power |
| FCF Yield | 15% | Free cash flow / market cap — cash generation strength |
| Net Margin | 10% | Pricing power and earnings quality |
| Debt/Equity | 10% | Financial health; lower leverage = more resilience in downturns |

**Portfolio construction:** Composite rank = 65% price momentum (3m/6m/12m with 1-month skip) + 35% GARP score. Holds top 5 qualifying stocks, weighted by GARP score (higher quality = bigger allocation, capped at 30%). Three risk overlays: 20% annualised volatility targeting, SPY 3m-momentum regime filter (scales to 0.6× or 0.3× in drawdowns), and 15% drawdown stop.

**Current top GARP scores:** ADBE (0.874 — PEG 0.53, ROE 63%), NVDA (0.706 — PEG 0.65, ROE 114%), NFLX (0.707), CRM (0.665), META (0.656). TSLA (0.128) and INTC (0.297) are correctly screened out by the fundamentals.

> **Note:** Fundamental scores are fetched live from yfinance at runtime and used as a static quality screen. The actual entry/exit signals are pure price momentum (no look-ahead). Requires `yfinance` in addition to the base dependencies.

---

### 4. Tech-Tier Momentum Ladder (reference)
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
│   ├── garp_momentum/             GARP + momentum — best standalone Sharpe (1.23)
│   │   ├── main.py
│   │   ├── backtest.py
│   │   ├── fundamentals.py        yfinance GARP scoring (PEG, ROE, EV/EBITDA, FCF, margin, D/E)
│   │   └── config.py
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
python -m strategies.garp_momentum.main

# Generate PDF documentation for the intraday strategy
python strategies/spy_intraday_short/generate_pdf.py
```

---

## Setup

**Install dependencies:**
```bash
pip install pandas numpy matplotlib markdown yfinance
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
| ETF / stock daily prices | Alpaca SIP `1Day` bars, `adjustment=all` | Total return (splits + dividends included) |
| SPY 5-min intraday | Alpaca SIP `5Min` bars | ~400k bars, 2016–2024 |
| T-bill proxy | BIL ETF daily return | SPDR 1-3 Month T-Bill ETF |
| Fundamental data | yfinance (live snapshot) | PEG, ROE, EV/EBITDA, FCF yield — GARP strategy only |

---

## Adding a New Strategy

1. Create `strategies/your_strategy/` with `__init__.py`
2. Add `config.py` importing shared params from root `config.py`
3. Add `backtest.py` and `main.py` (see existing strategies for the sys.path pattern)
4. Import from `core.data` and `core.metrics`

---

*Mark Garcera · Aspiring Trader*  
*Academic grounding: Gao et al. (2018, JF) · Lou et al. (2019, JFE) · Moskowitz et al. (2012, JF)*
