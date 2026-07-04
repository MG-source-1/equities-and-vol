# Strategy Backtester

A modular systematic trading backtester. All data is sourced from **Alpaca Markets** (SIP feed) and **SEC EDGAR** (XBRL Company Facts API).

Strategies run on the longest window their data sources allow:

| Strategy | Period | Binding constraint |
|---|---|---|
| Investor Portfolio (GARP + TRIAD + XAT) | 2016–2024 | Alpaca daily prices (~2016) |
| TRIAD (Tri-Timescale TMT) | 2016–2026 | Alpaca daily prices (~2016) · 2025+ is out-of-sample |
| DTQ (Dual-Timescale QQQ) | 2016–2024 | Alpaca daily prices (~2016) |
| GARP Momentum | 2016–2024 | Alpaca daily prices (~2016) · EDGAR fundamentals (~2009) |
| AFP, XAT, Tech-Tier (reference) | 2016–2024 | Alpaca daily prices (~2016) |
| SIS (reference) | 2020–2024 | Alpaca 5-min intraday bars (available from 2020 only) |

**Why SIS has a shorter window:** SIS (SPY Intraday Afternoon Short) needs 5-minute intraday bars, which Alpaca only provides from 2020 onwards. Rather than constraining the entire portfolio to 2020 to accommodate SIS, it is kept as a reference strategy only. The investor portfolio runs on the full 2016–2024 window.

---

## Portfolio

### ★ Investor Portfolio — recommended allocation
**File:** `strategies/combined_portfolio/main.py`  
**Sharpe:** 1.25 &nbsp;|&nbsp; **Return:** +428% &nbsp;|&nbsp; **Max DD:** −18.4% &nbsp;|&nbsp; **Period:** 2016–2024

| Sleeve | Weight | Strategy | Purpose |
|---|---|---|---|
| GARP | 40% | TMT quality-momentum (EDGAR fundamentals) | Alpha engine 1 — fundamental anchor |
| TRIAD | 40% | Tri-timescale TMT (momentum + panic dips) | Alpha engine 2 — pure price action |
| XAT | 20% | Cross-Asset Trend (SPY · TLT · GLD) | Regime diversifier |

**Result:** Sharpe 1.25, +428% total return, Max DD −18.4% over 2016–2024. Beats SPY (+237%) by 192 percentage points and improves the previous 80/20 GARP/XAT configuration on every metric (Sharpe 1.03 → 1.25, return +364% → +428%, drawdown −21.3% → −18.4%).

**Why 40/40 rather than replacing GARP outright:** TRIAD backtests better than GARP standalone (Sharpe 1.47 vs 1.06) and a full 80% TRIAD swap backtests better still — but TRIAD was developed on this same 2016–2024 window, so part of its measured edge is research-selection bias that GARP, anchored on point-in-time EDGAR fundamentals, carries less of. The two engines trade the same 15 TMT names with *different selection logic* (fundamental quality vs pure momentum + panic dips) and fail differently: in a momentum crash GARP's quality screen holds fundamentally sound names through the noise, while TRIAD rotates faster in trend reversals. The 40/40 split therefore diversifies **model risk** — the risk a backtest cannot measure. TRIAD's weight was granted only after it passed an 18-month out-of-sample forward test (2025-01 → 2026-06, Sharpe 1.30 — see the TRIAD section); if it continues to hold up live, shifting further weight toward it is the natural evolution.

**Why XAT includes SPY:** XAT is a cross-asset trend strategy, not a pure hedge. Including SPY lets XAT participate in equity upside when equities are trending, while rotating into TLT (bonds) or GLD (gold) in risk-off regimes. Removing SPY makes XAT entirely passive — it holds cash 35%+ of the time and generates negligible return.

**Honest caveat on XAT:** XAT returned −1.7% over the full 2016–2024 window (Sharpe −0.60), making it a mild drag on the portfolio. In the previous 80/20 configuration it reduced max drawdown from GARP standalone's −22.8% to −21.3%, but only marginally. The 2016–2024 window includes two unusually bad environments for cross-asset trend — the 2022 rate shock (bonds and equities fell simultaneously) and a long equity bull run where SPY dominated. In a 2008-style deflationary crash, XAT would be expected to earn meaningfully as TLT rallies. Whether to keep XAT in the portfolio is a forward-looking judgment call about which regime comes next.

---

## Design Decisions and What We Tested

### Why SIS was removed from the investor portfolio

SIS (SPY Intraday Short) was originally included at 10–20% of the portfolio. Removing it was motivated purely by data availability: SIS requires 5-minute intraday bars, which Alpaca only provides from 2020 onwards. Keeping SIS in the portfolio would have forced the entire backtest to start in 2020 — losing 4 years of the EDGAR-powered GARP backtest. Since the goal is a long-term performance picture, SIS was moved to reference status.

SIS's standalone edge is genuine — a 61–62% win rate on a market-neutral signal with −5.8% max drawdown — but its low reported Sharpe (0.10) is a measurement artefact: it only deploys ~18% of days, and the idle 82% suppresses the Sharpe ratio by √0.18 ≈ 0.42 mechanically.

### Why XAT includes SPY (not just TLT + GLD)

We tested XAT with TLT + GLD only (no SPY). Results over 2020–2024:

| XAT universe | XAT return | Portfolio Sharpe |
|---|---|---|
| SPY + TLT + GLD | +26% | 1.08 |
| TLT + GLD only | +2% | 0.80 |

Removing SPY made XAT almost entirely passive — it sat in cash 35% of the time and generated almost no return in normal environments. A strategy that can only defend in bad regimes but can't earn in good ones is a drag in every environment except the worst. SPY is what allows XAT to rotate meaningfully rather than defensively.

### Why sector-diversified GARP underperformed TMT-only

We tested expanding the GARP universe from 15 TMT stocks to 25 stocks across five sectors (adding LLY, UNH, ABBV, V, MA, COST, HD, NKE, CAT, HON).

| | TMT-only (15 stocks) | Expanded (25 stocks) |
|---|---|---|
| Return | +130% | +90% |
| Sharpe | 1.12 | 0.81 |
| Max DD | −25.6% | −27.9% |

*(Over 2020–2024 for comparability)*

Adding sectors with "good but not exceptional" momentum diluted exposure to the core TMT compounders (NVDA, META, AVGO) during a window where tech dominated everything. The honest caveat: if the next 5 years bring tech regulation or sustained rotation away from growth stocks, the expanded universe would likely outperform. We reverted to TMT-only because the backtest evidence is clear and the data window doesn't reward diversification.

### Portfolio weight evolution

| Configuration | Return | Sharpe | Max DD | Period | Notes |
|---|---|---|---|---|---|
| 40/40/20 GARP/XAT(TLT+GLD)/SIS | +63% | 0.84 | −15.9% | 2020–2024 | XAT without SPY too passive |
| 45/45/10 GARP/XAT(SPY+TLT+GLD)/SIS | +69% | 0.84 | −17.6% | 2020–2024 | SPY back in XAT |
| 70/20/10 GARP/XAT/SIS | +116% | 1.08 | −18.8% | 2020–2024 | With EDGAR fundamentals |
| 80/20 GARP/XAT (no SIS) | +364% | 1.03 | −21.3% | 2016–2024 | Full window, no intraday constraint |
| **40/40/20 GARP/TRIAD/XAT** | **+428%** | **1.25** | **−18.4%** | **2016–2024** | **Current — TRIAD added after passing its 2025–2026 out-of-sample test** |

---

## Individual Strategies

### 1. Adaptive Factor Portfolio (AFP)
**File:** `strategies/equity_factor_rotation/main.py`  
**Sharpe:** 0.97 &nbsp;|&nbsp; **Return:** +130% &nbsp;|&nbsp; **Max DD:** −13.6% &nbsp;|&nbsp; **Period:** 2016–2024

Rotates monthly between four US equity factor ETFs — QQQ (growth/tech), QUAL (quality), MTUM (momentum), USMV (min-vol) — using composite momentum with two creative additions:

- **Factor Leadership Tilt:** top-ranked qualifying factor gets 1.5× weight
- **Correlation Regime Filter:** when QQQ and USMV start moving together (correlation >0.75), a systemic event is underway — exposure cuts to 40%. Detected both the 2020 crash and 2022 rate shock without VIX data.

AFP's Sharpe of 0.97 reflects a regime where factor rotation added genuine value — the 2016–2019 bull market rewarded systematic tilt between growth (QQQ), quality (QUAL), momentum (MTUM), and defensive (USMV). Its defining structural strength remains capital preservation: lowest max drawdown of any strategy at −13.6%, achieved through the correlation regime filter that cut exposure in both the 2020 crash and the 2022 rate shock.

---

### 2. Cross-Asset Trend (XAT) — reference
**File:** runs as a sleeve within `strategies/combined_portfolio/main.py`  
**Sharpe:** −0.60 &nbsp;|&nbsp; **Return:** −1.7% &nbsp;|&nbsp; **Max DD:** −20.3% &nbsp;|&nbsp; **Period:** 2016–2024

Applies AFP's momentum and inverse-vol weighting to three cross-asset instruments — SPY, TLT (20+ year US Treasuries), and GLD (gold). Ranks all three monthly; the leading asset gets a 1.5× rank tilt. Holds T-bills when no asset has positive momentum.

XAT's poor 2016–2024 standalone numbers reflect two back-to-back hostile environments: a long equity bull run (2016–2021) where the trend signal was slow to rotate, followed by the 2022 rate shock where TLT and SPY fell simultaneously. In a 2008-style deflationary crash, TLT rallies strongly while equities fall — the regime XAT is built for. Retained in the portfolio at 20% for its regime-classification role despite the drag in this window.

---

### 3. SPY Intraday Afternoon Short (SIS) — reference
**File:** `strategies/spy_intraday_short/main.py`  
**Sharpe:** 0.10 &nbsp;|&nbsp; **Return:** +14% &nbsp;|&nbsp; **Max DD:** −5.8% &nbsp;|&nbsp; **Period:** 2020–2024

Uses Alpaca 5-minute SPY bars. On high-conviction mornings — when both the overnight gap and first 30-minute return exceed minimum thresholds and agree in direction — **shorts the last 30 minutes of the session**. Up mornings reverse (61% win); down mornings continue (62% win). Active only 18% of days; earns T-bill on the rest.

**On the low Sharpe:** The 0.10 figure is a measurement artefact of capital dilution. Because SIS is only active 18% of days, the other 82% contribute zero excess return while still counting in the Sharpe denominator — mechanically suppressing the ratio by roughly √0.18 ≈ 0.42. The underlying signal is sound. Excluded from the investor portfolio because its 2020 data start would shorten the backtest by 4 years.

---

### 4. GARP Momentum
**File:** `strategies/garp_momentum/main.py`  
**Sharpe:** 1.06 &nbsp;|&nbsp; **Return:** +455% &nbsp;|&nbsp; **Max DD:** −22.8% &nbsp;|&nbsp; **Period:** 2016–2024

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

**Portfolio construction:** Composite rank = 65% price momentum (3m/6m/12m with 1-month skip) + 35% GARP score. Holds top 5 qualifying stocks, weighted by GARP score (higher quality = bigger allocation, capped at 30%). Three risk overlays: 20% annualised vol targeting, SPY 3m-momentum regime filter (scales to 0.6× or 0.3× in drawdowns), and 15% drawdown stop.

**Current top GARP scores:** NVDA (0.793 — PEG 0.30, ROE 75%), MSFT (0.746), QCOM (0.736), GOOGL (0.721), AAPL (0.721). TSLA (0.203) and INTC (0.265) are correctly screened out by the fundamentals.

> **Data source:** Fundamental data comes from the SEC EDGAR XBRL Company Facts API — no API key required. EDGAR provides the exact `filed` date for every submission, making point-in-time accuracy inherent: each rebalance only sees data publicly filed on or before that date. Coverage goes back to ~2009 for most large-cap TMT names, giving the GARP quality screen genuine historical data throughout the full 2016–2024 backtest window. `yfinance` is not used.

---

### 5. Dual-Timescale QQQ (DTQ) — lowest drawdown
**File:** `strategies/dual_timescale_qqq/main.py`  
**Sharpe:** 1.30 &nbsp;|&nbsp; **Return:** +185% &nbsp;|&nbsp; **Max DD:** −9.8% &nbsp;|&nbsp; **Period:** 2016–2024

The only strategy in this repository with a single-digit max drawdown (TRIAD later took the top Sharpe spot by reusing DTQ's mean-reversion sleeve at higher octane). The design principle: **trend-following and dip-buying profit from opposite market behaviours** — continuation vs overreaction — so running both on the *same instrument* produces two nearly uncorrelated return streams (daily sleeve P&L correlation: 0.40) without needing a second asset class. It is diversification across *timescales* rather than across assets.

| Sleeve | Weight | Timescale | Signal |
|---|---|---|---|
| Trend | 50% | Months | Long QQQ while above its 200-day SMA, sized to 15% annualised vol (20-day realised). T-bills otherwise. |
| Mean reversion | 50% | Days | Buy the close when IBS < 0.10 **and** price > 200-day SMA. Exit when IBS > 0.75 or after 3 days. Sized to 20% vol, capped at 1.5×. |

**IBS (Internal Bar Strength)** = (close − low) / (high − low): where the day closed within its own range. IBS < 0.10 means the close was pinned to the bottom decile of the day's range — a panic close. Buying that panic *inside an uptrend* captured a 76% win rate across 142 trades (avg +0.69% per trade, avg 2-day hold). The 200-day SMA filter is what separates a dip from a downtrend — the identical signal without it loses money in 2022.

**Sleeve results and combination (2016–2024, net of 10 bps turnover costs):**

| | Sharpe | Ann. return | Max DD | Notes |
|---|---|---|---|---|
| Trend sleeve alone | 1.02 | 15.3% | −16.0% | in market ~75% of days |
| MR sleeve alone | 1.19 | 11.5% | −10.1% | in market ~12% of days |
| **DTQ 50/50** | **1.30** | **13.7%** | **−9.8%** | avg total exposure 0.43× |

**Regime robustness** — Sharpe is positive in every sub-period, not carried by one lucky regime:

| Sub-period | Sharpe | Ann. return | Environment |
|---|---|---|---|
| 2016–2019 | 1.13 | +11.7% | steady bull |
| 2020–2022 | 0.84 | +7.3% | COVID crash + rate shock |
| 2023–2024 | 2.22 | +27.4% | AI-led recovery |

The 2022 bear market is handled structurally rather than predictively: QQQ below its 200-day SMA switches the trend sleeve to T-bills *and* disables the dip-buyer's entry condition, so the strategy sat almost fully in cash (earning 2022's rising T-bill yields) while QQQ fell 35%.

**Parameter honesty:** all parameters are standard literature values (200-day SMA, 3-day hold, 10/75 IBS bands), not optimised numbers. A robustness grid over SMA ∈ {150, 175, 200, 225} × IBS entry ∈ {0.08, 0.10, 0.12, 0.15} keeps the combined Sharpe between 1.09 and 1.33 — every cell beats the prior 80/20 portfolio's 1.03, so the result is not a knife-edge fit.

**What we tested and rejected:**
- **IBS mean reversion on SPY** — Sharpe ≈ 0. The signal is meaningfully stronger on QQQ/Nasdaq than the broad market; retail-heavy, higher-beta indices overreact more intraday.
- **GLD and TLT trend sleeves** — Sharpe 0.22 and −0.37 in this window (same cross-asset headwinds that hurt XAT). Adding them *lowered* the combined Sharpe.
- **A SOXX mean-reversion sleeve** — diluted the combo to 1.20.

**Honest caveats:** DTQ earns less than half of QQQ's raw +362% buy-and-hold return over this window — its value proposition is the risk-adjusted number and the −9.8% drawdown, not maximum wealth. It is also 100% concentrated in Nasdaq beta at both timescales; that is why it is kept as a standalone strategy rather than blended into the investor portfolio, whose GARP sleeve already carries heavy TMT exposure (daily correlation between DTQ and GARP would compound the same underlying factor). The MR sleeve assumes execution at the closing price of the signal day (standard for daily mean-reversion backtests, achievable with a market-on-close order queued in the final minutes).

---

### 6. TRIAD — Tri-Timescale TMT — now a 40% sleeve of the investor portfolio
**File:** `strategies/triad/main.py`  
**Sharpe:** 1.44 &nbsp;|&nbsp; **Return:** +951% &nbsp;|&nbsp; **Max DD:** −19.0% &nbsp;|&nbsp; **Period:** 2016–2026 (2025+ out-of-sample)

Built as a direct challenger to the then-current 80/20 GARP/XAT portfolio — it beat it on every headline metric over the development window (2016–2024, Sharpe 1.47, +616%), and after passing its out-of-sample test it was promoted into the portfolio at 40%:

| | TRIAD | 80/20 GARP/XAT (prior portfolio) | QQQ B&H |
|---|---|---|---|
| Total return | **+616%** | +364% | +362% |
| Ann. return | **27.2%** | ~20.5% | ~20.3% |
| Sharpe | **1.47** | 1.03 | 0.80 |
| Max drawdown | **−19.0%** | −21.3% | −35.0% |

**The design idea:** the investor portfolio diversifies across *assets* (stocks + bonds + gold) — and its XAT sleeve was a drag in this window. TRIAD instead diversifies across *timescales*: one factor (TMT), harvested through three behaviours that pay off at different frequencies. Continuation pays over months; overreaction pays over days; and single-name panic is a different animal from index panic.

| Sleeve | Weight | Timescale | Signal |
|---|---|---|---|
| **Leaders** | 60% | Months | Hold the top-3 of 15 TMT names by blended 3/6/12-month momentum (positive momentum only), equal weight, monthly rebalance, 25% sleeve vol target, scaled to 0.3× when QQQ < 200-day SMA |
| **Stock dips** | 25% | Days | Buy single-name panic closes (IBS < 0.10) in names above their 200-day SMA with positive 6-month momentum; exit IBS > 0.75 or 3 days; 25% per name, gross ≤ 1× |
| **Index dips** | 15% | Days | DTQ's QQQ mean-reversion sleeve, verbatim |

Daily sleeve correlations are 0.33–0.56 — low enough that the combination's Sharpe (1.47) exceeds every sleeve alone (1.28 / 0.84 / 1.19). The Leaders sleeve supplies the return (+$463k of the +$616k total); the two dip sleeves supply the smoothing, deploying capital precisely on the days the Leaders sleeve is bleeding.

**Sub-period Sharpe** — improves in *harder* regimes, because the dip engines earn most when volatility is high:

| Sub-period | Sharpe | Ann. return |
|---|---|---|
| 2016–2019 | 1.07 | +19.0% |
| 2020–2022 | 1.48 | +25.0% |
| 2023–2024 | 2.11 | +45.4% |

**Robustness:** a grid over momentum lookbacks {12m, 6+12m, 3+6m, 3+6+12m} × top-N {2, 3, 4} keeps the combined Sharpe between 1.22 and 1.53 — every cell beats the prior 80/20 portfolio's 1.03.

#### Out-of-sample validation (2025-01 → 2026-06)

TRIAD's rules and parameters were frozen on 2016–2024 data; the following 18 months are a genuine forward test (the strategy's `config.py` extends its window to 2026-06 for exactly this purpose — all other strategies still end 2024-12):

| 2025-01 → 2026-06 | TRIAD | QQQ B&H | SPY B&H |
|---|---|---|---|
| Total return | **+47.1%** | +45.1% | +29.6% |
| Sharpe | **1.30** | 1.08 | 0.85 |
| Max drawdown | **−12.6%** | −22.8% | −18.8% |

The in-sample Sharpe of 1.47 degraded to 1.30 out-of-sample — a ~12% haircut, which is the normal signature of a real (non-overfit) edge rather than the collapse-toward-zero of a curve-fit one. Three findings from the forward window:

- **Every structural mechanism fired as designed.** In the spring 2025 correction the regime scaler held TRIAD's drawdown to −12.6% while QQQ fell −22.8%; the momentum sleeve then rotated into the new leaders and delivered +33.6% vs QQQ's +20.2% in H1 2026. All three sleeves were independently profitable out-of-sample.
- **The NVDA-dependence caveat did not materialise.** Out-of-sample top holdings were AVGO (25% of days), GOOGL (22%) and AMD (16%) — NVDA only 9%. The rule found the new leaders on its own.
- **The outperformance is lumpy by construction.** TRIAD lagged QQQ in two of the three half-years (+1.6% vs +8.2%, then +8.3% vs +11.6%) and earned its edge from drawdown protection plus one strong concentration run. Expect to be behind the index most calm quarters.

**Statistical honesty:** 18 months is one regime (a tech bull with one sharp correction), and a Sharpe measured over 1.5 years carries a standard error of roughly ±0.8. The forward test validates the mechanisms; it does not yet prove the magnitude.

**What we tested and rejected:**
- **An EDGAR GARP quality gate on both stock sleeves** (only trade names above the median point-in-time GARP score). It *reduced* the Leaders sleeve's Sharpe from 1.28 to 1.19 — the gate screens out exactly the momentum runs (AMD, TSLA) that momentum is supposed to ride. Quality and momentum are separate factors; forcing every position to satisfy both shrinks the opportunity set without cutting tail risk. Kept GARP fundamentals where they belong — in the GARP strategy.
- **Vol-scaled dip sizing and a cross-sectional correlation brake** — each safety layer cut return faster than it cut risk (dip-sleeve Sharpe fell 0.84 → 0.75 as layers were added).

**Honest caveats:**
- **This is one factor, three ways.** Daily correlation with GARP is 0.81 — TRIAD diversifies *model* risk (how names are selected), not *market* risk. That is exactly how it is used in the investor portfolio: a 40% sleeve alongside GARP's 40%, not a replacement for TMT exposure. In a multi-year tech bear market or a momentum crash, all three of TRIAD's sleeves degrade together; the 200-day regime scaler (which cut exposure through 2022 — the strategy lost far less than QQQ's −35%) is the only structural defence.
- **NVDA was the top holding 31% of days.** Any TMT momentum strategy in 2016–2024 rides the great semiconductor run. The rule is fully systematic (no hindsight in the picks), but the *regime* was exceptionally kind to it; forward expectations should be haircut accordingly, exactly as with GARP.
- Monthly top-3 concentration means single-name risk: one overnight gap in a 20%+ position is unhedged. The dip sleeves partially offset this only statistically, not structurally.

---

### 7. Tech-Tier Momentum Ladder (reference)
**File:** `strategies/concentrated_momentum/main.py`  
**Return:** +305% &nbsp;|&nbsp; **Sharpe:** 0.54 &nbsp;|&nbsp; **Max DD:** −34.3% &nbsp;|&nbsp; **Period:** 2016–2024

Concentrates monthly into the highest-momentum ETF from SOXX → QQQ → SPY. Uses SPY as a defensive floor when all three have negative momentum. Kept as a reference — the concentration and −34% drawdown make it unsuitable as a standalone primary strategy.

---

## Project Structure

```
├── core/
│   ├── alpaca.py          Shared Alpaca API (auth, pagination, caching, dividend-adjusted prices)
│   ├── data.py            fetch_prices / fetch_spy / fetch_tbill (BIL proxy)
│   └── metrics.py         Sharpe, drawdown, win rate
│
├── strategies/
│   ├── combined_portfolio/        ★ The recommended investor portfolio (40% GARP + 40% TRIAD + 20% XAT)
│   │   ├── main.py                Run this
│   │   └── config.py              40/40/20 weights; 2016–2024
│   │
│   ├── equity_factor_rotation/    AFP — lowest drawdown; backtest engine also used by XAT
│   │   ├── main.py
│   │   ├── backtest.py
│   │   └── config.py
│   │
│   ├── spy_intraday_short/        SIS — reference only (2020–2024, intraday data constraint)
│   │   ├── main.py
│   │   ├── strategy.py
│   │   ├── data_intraday.py
│   │   ├── config.py
│   │   ├── STRATEGY.md
│   │   └── generate_pdf.py
│   │
│   ├── garp_momentum/             GARP — TMT quality-momentum (Sharpe 1.06 over 2016–2024)
│   │   ├── main.py
│   │   ├── backtest.py
│   │   ├── fundamentals.py        SEC EDGAR GARP scoring (PEG, ROE, EV/EBITDA, FCF, margin, D/E)
│   │   └── config.py
│   │
│   ├── dual_timescale_qqq/        DTQ — trend + dip-buying on QQQ (Sharpe 1.30)
│   │   ├── main.py
│   │   ├── backtest.py
│   │   └── config.py
│   │
│   ├── triad/                     TRIAD — tri-timescale TMT (Sharpe 1.44, +951% over 2016–2026 — best in repo)
│   │   ├── main.py
│   │   ├── backtest.py
│   │   └── config.py
│   │
│   └── concentrated_momentum/     Reference — high return, high risk
│       ├── main.py
│       ├── backtest.py
│       └── config.py
│
├── data_cache/            Cached downloads (gitignored)
│                          Includes Alpaca price CSVs and EDGAR JSON facts files
├── outputs/               Charts and CSVs (gitignored)
├── config.py              Shared: START_DATE=2016, capital, absolute paths
├── .env                   Alpaca API credentials (gitignored — never commit)
└── requirements.txt
```

---

## Running

All commands from the project root.

```bash
# ★ Recommended: investor portfolio (40% GARP + 40% TRIAD + 20% XAT), 2016–2024
python -m strategies.combined_portfolio.main

# Individual strategies
python -m strategies.triad.main                   # TRIAD — best Sharpe & return (1.44, +951%, runs to 2026-06)
python -m strategies.dual_timescale_qqq.main      # DTQ — lowest drawdown per unit Sharpe (1.30)
python -m strategies.equity_factor_rotation.main
python -m strategies.spy_intraday_short.main      # reference only, 2020–2024
python -m strategies.concentrated_momentum.main
python -m strategies.garp_momentum.main

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
| ETF / stock daily prices | Alpaca SIP `1Day` bars, `adjustment=all` | Total return (splits + dividends included) · ~2016 onwards |
| SPY 5-min intraday | Alpaca SIP `5Min` bars | ~230k bars · 2020–2024 · SIS only |
| T-bill proxy | BIL ETF daily return | SPDR 1-3 Month T-Bill ETF |
| Fundamental data | SEC EDGAR XBRL Company Facts API | No API key required · exact filing dates · ~2009 onwards |

---

## Adding a New Strategy

1. Create `strategies/your_strategy/` with `__init__.py`
2. Add `config.py` importing shared params from root `config.py`
3. Add `backtest.py` and `main.py` (see existing strategies for the sys.path pattern)
4. Import from `core.data` and `core.metrics`

---

*Mark Garcera · Aspiring Trader*  
*Academic grounding: Gao et al. (2018, JF) · Lou et al. (2019, JFE) · Moskowitz et al. (2012, JF)*
