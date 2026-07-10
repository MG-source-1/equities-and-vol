# Strategy Backtester

A modular systematic trading backtester with a live paper-trading arm. All data comes from **Alpaca Markets** (SIP feed) and **SEC EDGAR** (XBRL Company Facts API).

Every strategy runs on the longest window its data sources allow:

| Strategy | Period | Binding constraint |
|---|---|---|
| Investor Portfolio (GARP + TRIAD + T-bills) | 2016–2024 | Alpaca daily prices (~2016) |
| TRIAD (Tri-Timescale TMT) | 2016–2026 | 2025+ held out-of-sample |
| GARP Momentum | 2016–2024 | EDGAR fundamentals reach back to ~2009 |
| DTQ (Dual-Timescale QQQ) | 2016–2024 | Alpaca daily prices (~2016) |
| BTREND (Broad Cross-Asset Trend) | 2016–2026 | 2025+ is forward validation |
| AFP, XAT, Tech-Tier (reference) | 2016–2024 | Alpaca daily prices (~2016) |
| SIS (reference) | 2020–2024 | Alpaca 5-min intraday bars start in 2020 |

**Timing convention, uniform across every engine:** signals are computed from data through today's close; positions are entered at that close (live: a market order at ~15:25 ET, ~30 minutes before the close) and earn from the next close-to-close return. Costs are 10 bps per unit of turnover; uninvested capital earns the T-bill (BIL) rate.

---

## ★ Investor Portfolio

**File:** `strategies/combined_portfolio/main.py`
**Sharpe:** 1.33 &nbsp;|&nbsp; **Return:** +478% &nbsp;|&nbsp; **Max DD:** −16.9% &nbsp;|&nbsp; **Period:** 2016–2024 &nbsp;|&nbsp; SPY same window: +237%

| Sleeve | Weight | Strategy | Purpose |
|---|---|---|---|
| GARP | 45% | TMT quality-momentum (EDGAR fundamentals) | Alpha engine 1 — fundamental anchor |
| TRIAD | 45% | Tri-timescale TMT (momentum + panic dips) | Alpha engine 2 — pure price action |
| T-bills | 10% | BIL (1–3 month T-bill ETF), held as a position | Dry powder — regime-risk buffer |

The sleeves are rebalanced back to 45/45/10 **daily** — the same constant-mix discipline the live system trades, so the backtest measures the portfolio that actually runs.

**Why 45/45 rather than replacing GARP with TRIAD outright:** TRIAD backtests better than GARP standalone (Sharpe 1.49 vs 1.14) — but TRIAD was developed on this same 2016–2024 window, so part of its measured edge is research-selection bias that GARP, anchored on point-in-time EDGAR fundamentals, carries less of. The two engines trade the same 15 TMT names with *different selection logic* (fundamental quality vs pure momentum + panic dips) and fail differently: in a momentum crash GARP's quality screen holds fundamentally sound names through the noise, while TRIAD rotates faster in trend reversals. The even split diversifies **model risk** — the risk a backtest cannot measure. Their daily return correlation is 0.83 and GARP wins 44% of months, so keeping both costs little in expectation (~1.2%/yr return gap) while insuring against the scenario where TRIAD's edge was partly curve-fit. TRIAD's weight was granted only after it passed an 18-month out-of-sample forward test (2025-01 → 2026-06, Sharpe 1.38); if it keeps holding up live, shifting weight toward it gradually is the natural evolution.

**Why 10% T-bills:** GARP and TRIAD are two expressions of *one market bet* — long US mega-cap TMT momentum — so the 45/45 split diversifies model risk but not regime risk. Nothing inside the engines protects against a multi-year tech unwind the 2016–2024 window never contained. The 10% BIL sleeve is the acknowledgment of that concentration: dry powder that earns the risk-free rate in every regime, and easier to defend to an investor than a sleeve that loses money waiting for the right kind of crash. It replaced a 20% cross-asset trend sleeve (XAT) that T-bills strictly dominated at every weight tested — see the research log. Live, BIL is implemented as a **cash sweep**: it absorbs not just the structural 10% but *all* capital the engines' risk overlays leave uninvested (when the vol targets and regime scalers cut exposure to 40%, ~58% of the account sits in BIL) — matching the backtests, which credit the T-bill rate on every uninvested dollar.

---

## Portfolio Sleeves

### GARP Momentum — 45% sleeve
**File:** `strategies/garp_momentum/main.py`
**Sharpe:** 1.14 &nbsp;|&nbsp; **Return:** +529% &nbsp;|&nbsp; **Max DD:** −20.5% &nbsp;|&nbsp; **Period:** 2016–2024

Applies **Growth at a Reasonable Price** screening to a 15-stock TMT universe (AAPL, MSFT, GOOGL, META, NVDA, AMD, AVGO, QCOM, ORCL, CRM, ADBE, NFLX, AMZN, TSLA, INTC), then selects and sizes with **Jegadeesh-Titman price momentum**.

Six ratios combine into a composite GARP quality rank:

| Ratio | Weight | Signal |
|---|---|---|
| PEG ratio | 30% | P/E ÷ EPS growth — core GARP metric; <1 = paying less than 1× per % of growth |
| Return on Equity | 20% | Profitability quality; great companies sustain ROE >30% |
| EV/EBITDA | 15% | Enterprise value efficiency; lower = cheaper relative to earnings power |
| FCF Yield | 15% | Free cash flow / market cap — cash generation strength |
| Net Margin | 10% | Pricing power and earnings quality |
| Debt/Equity | 10% | Financial health; lower leverage = more resilience in downturns |

**Construction:** composite rank = 65% price momentum (3m/6m/12m with 1-month skip) + 35% GARP score. Holds the top 5 qualifying stocks monthly, weighted by GARP score (capped at 30% per name). Three risk overlays: 20% annualised vol targeting, SPY 3-month-momentum regime filter (0.6× / 0.3× in drawdowns), and a 15% drawdown stop (cash for 21 days). Turnover ≈ 8×/yr, ~0.8%/yr in costs.

**Current top GARP scores** (latest 2026 filings): ADBE (0.792), MSFT (0.744), CRM (0.734), QCOM (0.729), NVDA (0.714). TSLA (0.203) and INTC (0.265) are correctly screened out. One coverage gap: AVGO's XBRL concept tagging stops matching after its 2024 10-K, so its score carries forward its last known value.

> **Data source:** SEC EDGAR XBRL Company Facts API — no API key required. EDGAR provides the exact `filed` date for every submission, making point-in-time accuracy inherent: each rebalance only sees data publicly filed on or before that date. Coverage reaches back to ~2009 for most large-cap TMT names. `yfinance` is not used.

### TRIAD — Tri-Timescale TMT — 45% sleeve
**File:** `strategies/triad/main.py`
**Sharpe:** 1.47 &nbsp;|&nbsp; **Return:** +975% &nbsp;|&nbsp; **Max DD:** −18.6% &nbsp;|&nbsp; **Period:** 2016–2026 (2025+ out-of-sample)

Built as a direct challenger to the then-current 80/20 GARP/XAT portfolio — it beat it on every headline metric over the development window, and was promoted into the portfolio after passing its out-of-sample test. Over 2016–2024 (the shared window):

| | TRIAD | 80/20 GARP/XAT (prior portfolio) | QQQ B&H |
|---|---|---|---|
| Total return | **+619%** | +364% | +362% |
| Ann. return | **27.2%** | ~20.5% | ~20.3% |
| Sharpe | **1.49** | 1.03 | 0.80 |
| Max drawdown | **−18.6%** | −21.3% | −35.0% |

**The design idea:** instead of diversifying across assets, TRIAD diversifies across *timescales* — one factor (TMT), harvested through three behaviours that pay off at different frequencies. Continuation pays over months; overreaction pays over days; and single-name panic is a different animal from index panic.

| Sleeve | Weight | Timescale | Signal |
|---|---|---|---|
| **Leaders** | 60% | Months | Top-3 of 15 TMT names by blended 3/6/12-month momentum (positive only), equal weight, monthly rebalance, 25% sleeve vol target, 0.3× when QQQ < 200-day SMA |
| **Stock dips** | 25% | Days | Buy single-name panic closes (IBS < 0.10) in names above their 200-day SMA with positive 6-month momentum; exit IBS > 0.75 or 3 days; 25% per name, gross ≤ 1× |
| **Index dips** | 15% | Days | DTQ's QQQ mean-reversion sleeve, verbatim |

Daily sleeve correlations are 0.33–0.56 — low enough that the combination's Sharpe exceeds every sleeve alone (1.28 / 0.84 / 1.19). The Leaders sleeve supplies the return (+$464k of the +$619k total); the dip sleeves supply the smoothing, deploying capital precisely on the days the Leaders sleeve is bleeding. The dip sleeves make TRIAD trade a lot — turnover ≈ 33×/yr, ~3.3%/yr in costs (already netted from all results) — which makes it the strategy most sensitive to the 10 bps cost assumption.

**Sub-period Sharpe** — improves in *harder* regimes, because the dip engines earn most when volatility is high:

| Sub-period | Sharpe | Ann. return |
|---|---|---|
| 2016–2019 | 1.10 | +19.4% |
| 2020–2022 | 1.44 | +23.8% |
| 2023–2024 | 2.18 | +46.9% |
| 2025–2026 H1 (out-of-sample) | 1.38 | +31.2% |

**Robustness:** a grid over momentum lookbacks {12m, 6+12m, 3+6m, 3+6+12m} × top-N {2, 3, 4} keeps the combined Sharpe between 1.22 and 1.53.

#### Out-of-sample validation (2025-01 → 2026-06)

Rules and parameters were frozen on 2016–2024 data; the following 18 months are a genuine forward test (`config.py` extends TRIAD's window to 2026-06 for exactly this purpose — all other strategies end 2024-12):

| 2025-01 → 2026-06 | TRIAD | QQQ B&H | SPY B&H |
|---|---|---|---|
| Total return | **+49.6%** | +45.1% | +29.6% |
| Sharpe | **1.38** | 1.08 | 0.85 |
| Max drawdown | **−13.9%** | −22.8% | −18.8% |

The in-sample Sharpe of 1.49 degraded to 1.38 out-of-sample — a modest haircut, the signature of a real edge rather than the collapse-toward-zero of a curve-fit one. Findings from the forward window:

- **Every structural mechanism fired as designed.** In the spring 2025 correction the regime scaler held TRIAD's drawdown to −13.9% while QQQ fell −22.8%; the momentum sleeve then rotated into the new leaders and delivered +32.8% vs QQQ's +20.2% in H1 2026. All three sleeves were independently profitable out-of-sample.
- **The NVDA-dependence caveat did not materialise.** Out-of-sample top holdings were AVGO (25% of days), GOOGL (22%) and AMD (16%) — NVDA only 9%. The rule found the new leaders on its own.
- **The outperformance is lumpy by construction.** TRIAD lagged QQQ in two of the three half-years (+2.2% vs +8.2%, then +10.2% vs +11.6%) and earned its edge from drawdown protection plus one strong concentration run. Expect to trail the index in most calm quarters.

**Statistical honesty:** 18 months is one regime (a tech bull with one sharp correction), and a Sharpe measured over 1.5 years carries a standard error of roughly ±0.8. The forward test validates the mechanisms; it does not yet prove the magnitude.

**Tested and rejected:**
- **An EDGAR GARP quality gate on the stock sleeves** — *reduced* the Leaders sleeve's Sharpe from 1.28 to 1.19 by screening out exactly the momentum runs (AMD, TSLA) momentum is supposed to ride. Quality and momentum are separate factors; forcing every position to satisfy both shrinks the opportunity set without cutting tail risk.
- **Vol-scaled dip sizing and a cross-sectional correlation brake** — each safety layer cut return faster than it cut risk (dip-sleeve Sharpe 0.84 → 0.75 as layers were added).

**Honest caveats:**
- **This is one factor, three ways.** Daily correlation with GARP is 0.83 — TRIAD diversifies *model* risk, not *market* risk, which is exactly how the portfolio uses it. In a multi-year tech bear, all three sleeves degrade together; the 200-day regime scaler is the only structural defence.
- **NVDA was the top holding 31% of in-sample days.** The rule is fully systematic, but the regime was exceptionally kind to TMT momentum; forward expectations should be haircut accordingly.
- **Monthly top-3 concentration means single-name risk** — one overnight gap in a 20%+ position is unhedged; the dip sleeves offset this statistically, not structurally.

---

## Standalone & Reference Strategies

### Dual-Timescale QQQ (DTQ) — lowest drawdown
**File:** `strategies/dual_timescale_qqq/main.py`
**Sharpe:** 1.30 &nbsp;|&nbsp; **Return:** +185% &nbsp;|&nbsp; **Max DD:** −9.8% &nbsp;|&nbsp; **Period:** 2016–2024

The only strategy in the repo with a single-digit max drawdown, and the origin of TRIAD's mean-reversion sleeve. Trend-following and dip-buying profit from opposite market behaviours — continuation vs overreaction — so running both on the *same instrument* produces two nearly uncorrelated return streams (daily sleeve P&L correlation 0.40) without a second asset class.

| Sleeve | Weight | Timescale | Signal |
|---|---|---|---|
| Trend | 50% | Months | Long QQQ above its 200-day SMA, sized to 15% annualised vol; T-bills otherwise |
| Mean reversion | 50% | Days | Buy the close when IBS < 0.10 **and** price > 200-day SMA; exit IBS > 0.75 or 3 days; sized to 20% vol, capped 1.5× |

**IBS (Internal Bar Strength)** = (close − low) / (high − low): where the day closed within its own range. IBS < 0.10 is a panic close; buying it *inside an uptrend* captured a 76% win rate across 142 trades (avg +0.69%, 2-day hold). The 200-day SMA filter is what separates a dip from a downtrend — the identical signal without it loses money in 2022.

| 2016–2024, net of costs | Sharpe | Ann. return | Max DD | Notes |
|---|---|---|---|---|
| Trend sleeve alone | 1.02 | 15.3% | −16.0% | in market ~75% of days |
| MR sleeve alone | 1.19 | 11.5% | −10.1% | in market ~12% of days |
| **DTQ 50/50** | **1.30** | **13.7%** | **−9.8%** | avg total exposure 0.43× |

Sharpe is positive in every sub-period (1.13 / 0.84 / 2.22 across 2016–19, 2020–22, 2023–24). The 2022 bear was handled structurally: QQQ below its 200-day SMA parks the trend sleeve in T-bills *and* disables dip entries, so DTQ sat in cash earning rising yields while QQQ fell 35%. All parameters are standard literature values, not optimised; a robustness grid over SMA {150–225} × IBS entry {0.08–0.15} keeps Sharpe between 1.09 and 1.33.

**Tested and rejected:** IBS mean-reversion on SPY (Sharpe ≈ 0 — the signal is much stronger on high-beta Nasdaq), GLD/TLT trend sleeves (Sharpe 0.22 / −0.37), a SOXX MR sleeve (diluted the combo to 1.20).

**Caveats:** DTQ earns less than half of QQQ's raw +362% — its value is the risk-adjusted number, not maximum wealth. It is kept standalone rather than blended into the portfolio because it would compound the same Nasdaq beta the TMT sleeves already carry.

### BTREND — Broad Cross-Asset Trend — candidate diversifier
**File:** `strategies/broad_trend/main.py`
**Sharpe:** 0.33 &nbsp;|&nbsp; **Return:** +46% &nbsp;|&nbsp; **Max DD:** −7.8% &nbsp;|&nbsp; **Period:** 2016–2026 (2025+ forward validation)

Per-asset **long/short time-series momentum** (Moskowitz-Ooi-Pedersen 2012) on 17 ETFs across five asset classes (US/intl equity, rates/credit, commodities, currencies, REITs). Each asset is judged on its own 3/6/12-month trend — long if positive, **short if negative** — sized by inverse vol with gross = 1, ±20% per-asset cap, and a 10% portfolio vol target. All parameters are untuned literature values shared with the rest of the repo; the strategy was built to answer a research question, not to maximise a backtest (see research log).

Its job is not standalone return — it is to be the portfolio's first genuinely uncorrelated sleeve (correlation with the GARP/TRIAD alpha book: **+0.22**, vs +0.83 between GARP and TRIAD themselves). The crisis behaviour comes from the shorts:

| Sub-period | Sharpe | Ann. return | Context |
|---|---|---|---|
| 2017–2019 | 0.09 | +1.7% | bull — nothing to do |
| 2020 | 0.67 | +4.5% | COVID |
| 2021–2022 | **0.95** | **+7.3%** | rate shock — short bonds/yen while stocks *and* bonds fell |
| 2023–2024 | −0.77 | +1.5% | AI bull — whipsawed, roughly cash-like |
| 2025–26H1 (forward) | **0.82** | +7.9% | untouched data; long credit/TIPS, short yen |

Runs at 0.88 average gross / 0.34 net exposure, ~11 longs and ~6 shorts. **Status: validated candidate for the portfolio's 10% diversifier slot, not yet allocated** — the in-window portfolio improvement over plain T-bills is modest (equal Sharpe, better worst-year and 2022 drawdown) and shorting adds live mechanics (margin, borrow fees ~25–50 bps/yr on the short book, not yet modelled). Promotion follows the TRIAD process: prove it live first.

### Adaptive Factor Portfolio (AFP) — reference
**File:** `strategies/equity_factor_rotation/main.py`
**Sharpe:** 0.72 &nbsp;|&nbsp; **Return:** +102% &nbsp;|&nbsp; **Max DD:** −13.6% &nbsp;|&nbsp; **Period:** 2016–2024

Rotates monthly between four US factor ETFs — QQQ (growth), QUAL (quality), MTUM (momentum), USMV (min-vol) — with two additions: a **leadership tilt** (top-ranked qualifying factor gets 1.5× weight) and a **correlation regime filter** — when the QQQ–USMV 20-day correlation spikes above 0.75, diversification has collapsed and exposure cuts to 40%. The filter detected both the 2020 crash and the 2022 rate shock without VIX data, and is why AFP has the second-lowest drawdown in the repo. Its backtest engine also powers XAT.

### Cross-Asset Trend (XAT) — reference, removed from the portfolio
**Engine:** `strategies/equity_factor_rotation/backtest.py` on SPY / TLT / GLD
**Sharpe:** −0.60 &nbsp;|&nbsp; **Return:** −1.7% &nbsp;|&nbsp; **Max DD:** −20.3% &nbsp;|&nbsp; **Period:** 2016–2024

AFP's engine applied to SPY, TLT and GLD as a monthly cross-asset regime rotator. It was the portfolio's 20% diversifier sleeve until July 2026, when the corrected constant-mix backtest showed **T-bills strictly dominated it at every weight tested** — including in the crisis episodes it was meant to defend (see research log). Its defence (TLT rallies in a deflationary crash) remains theoretically true, but 2022 demonstrated the failure mode: a 3-asset monthly trend signal is too slow and too narrow to be reliable insurance, and bonds fell with equities.

### SPY Intraday Afternoon Short (SIS) — reference
**File:** `strategies/spy_intraday_short/main.py`
**Sharpe:** 0.10 &nbsp;|&nbsp; **Return:** +14% &nbsp;|&nbsp; **Max DD:** −5.8% &nbsp;|&nbsp; **Period:** 2020–2024

On high-conviction mornings — overnight gap and first-30-minute return both above threshold and agreeing in direction — **shorts the last 30 minutes of the session**. Up mornings reverse (61% win); down mornings continue (62% win). Active only 18% of days. The 0.10 Sharpe is a capital-dilution artefact: the idle 82% of days suppress the ratio by √0.18 ≈ 0.42 mechanically; the underlying signal is sound. Excluded from the portfolio because its 5-minute data only exists from 2020, which would have cut 4 years off the combined backtest.

### Tech-Tier Momentum Ladder — reference
**File:** `strategies/concentrated_momentum/main.py`
**Sharpe:** 0.54 &nbsp;|&nbsp; **Return:** +305% &nbsp;|&nbsp; **Max DD:** −34.3% &nbsp;|&nbsp; **Period:** 2016–2024

Concentrates monthly into the highest-momentum of SOXX → QQQ → SPY, with SPY as the defensive floor. The −34% drawdown makes it unsuitable as a primary strategy.

---

## Research Log — how the portfolio got here

### Portfolio weight evolution

| Configuration | Return | Sharpe | Max DD | Period | Notes |
|---|---|---|---|---|---|
| 40/40/20 GARP/XAT(TLT+GLD)/SIS | +63% | 0.84 | −15.9% | 2020–2024 | XAT without SPY too passive |
| 45/45/10 GARP/XAT(SPY+TLT+GLD)/SIS | +69% | 0.84 | −17.6% | 2020–2024 | SPY added to XAT |
| 70/20/10 GARP/XAT/SIS | +116% | 1.08 | −18.8% | 2020–2024 | EDGAR fundamentals added |
| 80/20 GARP/XAT (no SIS) | +364% | 1.03 | −21.3% | 2016–2024 | Full window, no intraday constraint |
| 40/40/20 GARP/TRIAD/XAT | +371% | 1.27 | −17.0% | 2016–2024 | TRIAD promoted after its out-of-sample test |
| **45/45/10 GARP/TRIAD/T-bills** | **+478%** | **1.33** | **−16.9%** | **2016–2024** | **Current — XAT replaced by BIL** |

*(Rows before the 40/40/20 GARP/TRIAD/XAT entry were measured under the pre-July-2026 methodology and overstate slightly; kept for decision history, not magnitude comparison.)*

### July 2026 methodology fixes

A timing audit found three gaps between what the backtests measured and what the live system trades. All are fixed; every number in this README uses the corrected methodology.

1. **Constant-mix combination.** The combined backtest previously summed buy-and-hold sleeve curves, letting the mix drift for years, while live re-targets the sleeve weights daily. Now daily-rebalanced, matching live. (This is what exposed XAT: continually rebalancing winners into a flat sleeve is expensive — the old drift method hid it.)
2. **TRIAD's Leaders sleeve entered one day late** — a double lag between the month-end mask and the engine's shift. Removed; the backtest now trades the decision-day close like live does (Sharpe 1.47 → 1.49; the extra day was pure lag).
3. **XAT/AFP had a one-day lookahead in position sizing** — inverse-vol weights and the vol-target scale used returns through the entry day. Now lagged one day. AFP: Sharpe 0.97 → 0.72; XAT barely moved.

### Why XAT was replaced with T-bills

With the constant-mix fix in place, every weight configuration was re-tested on identical sleeve returns (2016–2024, daily-rebalanced):

| Config | Return | Sharpe* | Max DD | COVID | 2022 DD |
|---|---|---|---|---|---|
| 40/40/20 with XAT | +371% | 1.22 | −17.0% | −8.3% | −13.0% |
| 45/45/10 with XAT | +467% | 1.25 | −17.8% | −9.3% | −14.4% |
| 50/50 no diversifier | +581% | 1.27 | −18.6% | −10.3% | −15.8% |
| **45/45/10 with T-bills (chosen)** | **+478%** | **1.27** | **−16.8%** | −9.3% | −14.3% |
| 40/40/20 with T-bills | +389% | 1.27 | −15.0% | −8.3% | −12.7% |

*\*Simplified excess-return convention for cross-row comparability; the headline 1.33 uses the standard `core/metrics.py` calculation.*

T-bills beat XAT at every weight on every metric — including the two crisis episodes XAT existed to defend. 50/50 with no diversifier backtests highest, but both engines are one bet (long mega-cap TMT) evaluated on the most tech-friendly window in history; the 10% cash sleeve is the price of acknowledging that.

Earlier XAT research, preserved for the record: SPY had to be *in* the XAT universe (TLT+GLD-only left it in cash 35% of the time, portfolio Sharpe 1.08 → 0.80 over 2020–2024), which foreshadowed the problem — the sleeve only earned when it held the asset the alpha engines already owned.

### The diversifier search, continued: BTREND (July 2026)

XAT's replacement by T-bills left an open question: did cross-asset trend fail because trend-following doesn't work here, or because XAT's implementation (3 assets, long-only, winner-take-most rotation) couldn't express it? BTREND was built to answer that — per-asset TSMOM on 17 ETFs, all literature parameters, zero tuning — and tested in two variants:

1. **Long-only, broad universe** (long up-trends, flat otherwise): standalone Sharpe 0.09, correlation +0.46 with the alpha book, and **dominated by T-bills in the diversifier slot** — same return, lower Sharpe, worse drawdown, worse in both crises. Verdict: breadth alone was *not* XAT's problem. A long-flat trend book holding SPY/QQQ/HYG most of the time is still equity beta, and in crises it's just slow cash.
2. **Long/short** (short down-trends): standalone Sharpe 0.33 with max DD −7.8%, correlation with the alpha book **+0.22**, and — decisively — **positive in both crisis episodes**, including Sharpe 0.95 through 2021–2022 by being short bonds and yen while stocks and bonds fell together. This is the first diversifier tested that plain T-bills do *not* dominate:

| Config (2016–2024) | Return | Sharpe | Max DD | 2022 DD | Worst year |
|---|---|---|---|---|---|
| 45/45/10 BIL (current) | +478% | 1.27 | −16.8% | −14.3% | −10.5% |
| 45/45/10 BTREND L/S | +484% | 1.27 | −17.1% | **−13.0%** | **−9.6%** |
| 40/40/10/10 BTREND+BIL | +394% | 1.27 | **−15.3%** | **−11.4%** | **−8.3%** |

Results are unchanged at 20 bps costs (double the standard assumption). A quasi-forward test on 2025-01 → 2026-06 (fair because nothing was tuned on any window) delivered Sharpe 0.82.

**Decision: BTREND is a validated candidate, not yet allocated.** The lesson of the whole diversifier search is that the crash protection of trend-following lives in the *shorts*, which no long-only implementation can capture — but the in-window gain over T-bills is modest, and shorting brings live mechanics (margin, ETF borrow costs) the paper system hasn't exercised. It gets promoted the way TRIAD did: run it, watch it, then allocate.

### Why SIS was removed

Purely data availability: SIS needs 5-minute bars, which Alpaca provides only from 2020. Keeping it would have forced the whole backtest to start in 2020, losing 4 years of the EDGAR-powered GARP history. Its edge is genuine (61–62% win rate, −5.8% max DD); it lives on as a reference strategy.

### Why GARP stays TMT-only

Expanding from 15 TMT names to 25 across five sectors (adding LLY, UNH, ABBV, V, MA, COST, HD, NKE, CAT, HON) was tested over 2020–2024: return +130% → +90%, Sharpe 1.12 → 0.81, DD −25.6% → −27.9%. Diversifying into "good but not exceptional" momentum diluted the core TMT compounders during a window where tech dominated. Honest caveat: under sustained rotation away from growth, the expanded universe would likely win — the backtest window simply doesn't reward diversification.

---

## Project Structure

```
├── core/
│   ├── alpaca.py          Shared Alpaca API (auth, pagination, caching, dividend-adjusted prices)
│   ├── data.py            fetch_prices / fetch_spy / fetch_tbill (BIL proxy)
│   └── metrics.py         Sharpe, drawdown, win rate
│
├── strategies/
│   ├── combined_portfolio/        ★ The investor portfolio (45% GARP + 45% TRIAD + 10% T-bills)
│   ├── garp_momentum/             GARP — TMT quality-momentum; fundamentals.py = EDGAR scoring
│   ├── triad/                     TRIAD — tri-timescale TMT (best Sharpe & return in repo)
│   ├── dual_timescale_qqq/        DTQ — trend + dip-buying on QQQ (lowest drawdown)
│   ├── broad_trend/               BTREND — long/short cross-asset TSMOM (candidate diversifier)
│   ├── equity_factor_rotation/    AFP — factor rotation; engine also powers XAT
│   ├── spy_intraday_short/        SIS — reference (2020–2024, intraday data constraint)
│   └── concentrated_momentum/     Tech-Tier — reference (high return, high risk)
│
├── live/                  Live paper trading of the investor portfolio (Alpaca paper API)
│   ├── rebalance.py       Daily: compute targets → submit market orders (~15:25 ET)
│   ├── reconcile.py       Morning: record equity, verify fills vs intentions
│   ├── tearsheet.py       Monthly: live metrics vs backtest expectation
│   ├── signals.py         Live targets via the same weight functions the backtests use
│   ├── broker.py          Paper trading API wrapper (urllib, no SDK)
│   └── config.py          Paper endpoint, drawdown guard, execution settings
│
├── tests/                 No-lookahead property tests, golden numbers, timing checks
├── data_cache/            Cached downloads (gitignored) — Alpaca CSVs + EDGAR JSON
├── outputs/               Charts and CSVs
│   └── live/              Live track record: equity curve, daily decision logs, state
├── config.py              Shared: START_DATE=2016, capital, absolute paths
├── .env                   Alpaca API credentials (gitignored — never commit)
└── requirements.txt
```

Each strategy folder contains `main.py` (run this), `backtest.py` (engine), and `config.py` (parameters).

---

## Running

All commands from the project root.

```bash
# ★ The investor portfolio (45% GARP + 45% TRIAD + 10% T-bills), 2016–2024
python -m strategies.combined_portfolio.main

# Individual strategies
python -m strategies.garp_momentum.main
python -m strategies.triad.main                   # runs to 2026-06 (out-of-sample window)
python -m strategies.dual_timescale_qqq.main
python -m strategies.broad_trend.main             # runs to 2026-06 (forward-validation window)
python -m strategies.equity_factor_rotation.main
python -m strategies.spy_intraday_short.main      # reference, 2020–2024
python -m strategies.concentrated_momentum.main

# PDF documentation for the intraday strategy
python strategies/spy_intraday_short/generate_pdf.py
```

---

## Live Paper Trading

The investor portfolio runs live on the **Alpaca paper account** — the point is to build a track record that can't be curve-fit. Backtests prove the research; the live record proves the system.

### The three jobs

```bash
# 1. Daily rebalance — only trades in the final 45 minutes of the session.
#    Computes today's targets with the SAME functions the backtests use,
#    diffs against current positions, submits immediate market orders.
#    Dry runs never touch live state and log to a separate .dryrun.json.
python -m live.rebalance              # dry run (prints orders, submits nothing)
python -m live.rebalance --execute    # submit market orders to the paper account
python -m live.rebalance --force      # compute signals even when market closed (testing)

# 2. Morning reconcile — run any time after the close.
#    Appends equity to outputs/live/equity_curve.csv and checks each of
#    yesterday's orders against its own fill by order_id (slippage in bps).
python -m live.reconcile

# 3. Tearsheet — run monthly (needs ≥5 live days).
#    Live Sharpe/vol/drawdown vs the backtest's expectation, and where the
#    live window sits in the distribution of same-length backtest windows.
python -m live.tearsheet
```

### Scheduling from Singapore

The rebalance job exits instantly unless the market is open **and within 45 minutes of the close**, so the cron doesn't need to track US daylight saving — schedule **both** possible SGT times and let the wrong one no-op (the market-open check alone isn't enough: in EST the early entry lands mid-session at 14:25 ET):

```cron
# US market close is 04:00 SGT (EDT) or 05:00 SGT (EST).
25 3 * * 2-6  cd ~/trading/backtester && python3 -m live.rebalance --execute >> outputs/live/cron.log 2>&1
25 4 * * 2-6  cd ~/trading/backtester && python3 -m live.rebalance --execute >> outputs/live/cron.log 2>&1
0  7 * * 2-6  cd ~/trading/backtester && python3 -m live.reconcile          >> outputs/live/cron.log 2>&1
```

Every daily decision is logged to `outputs/live/decisions/YYYY-MM-DD.json` with its full inputs — equity, sleeve diagnostics, target weights, orders — so any divergence from the backtest can be replayed and explained later.

### Known deviations from the backtest

| Deviation | Why | Expected impact |
|---|---|---|
| Signal prices are the ~15:19 ET snapshot, not the official close | Free Alpaca data plan rejects the most recent 15 minutes | Tiny signal noise |
| Fills at ~15:25 ET market orders, not the closing auction | True MOC ("cls") orders mostly EXPIRE UNFILLED in Alpaca's paper simulator — observed July 2026, 15 of 18 expired; switched to immediate market orders | Execution ~30 min before the close the backtest assumes; a few bps of noise vs the auction price, but orders actually fill |
| Whole-share orders, trades under $200 skipped | Fractional shares complicate qty-diff rebalancing | Weight rounding of a few basis points on a $100k account |
| Drawdown stop applied at portfolio level (−15% / 21 days), not per sleeve | Sleeve-level stops require tracking virtual per-sleeve equity | Triggers on the same magnitude of loss, slightly different timing |
| ~2% cash buffer earns 0 | ALL uninvested capital is swept into BIL (matching the backtests' T-bill credit), minus a small buffer so buys never bounce on same-day BIL sales | Negligible (~8 bps/yr); before the July 2026 sweep, the engines' defensive cash idled at 0% — up to ~2%/yr of drag vs the backtest |

EDGAR fundamentals refresh automatically when caches are older than 7 days, so new 10-Q/10-K filings flow into the GARP score — backtests keep their caches permanent.

---

## Testing

```bash
python -m pytest tests/ -q        # ~6 seconds, runs entirely from data_cache/
```

Three layers, built after a July 2026 timing audit found bugs that had survived for months untested:

- **`test_no_lookahead.py`** — two causality properties per engine. *Truncation*: removing the last 40 days must not change any surviving weight (catches dependence on the future). *Last-day perturbation*: bumping only the final day's prices must not move weights that were already decided (catches the subtler off-by-one where a position entered at yesterday's close is sized with today's data — the exact class of the XAT/AFP bug, which a truncation test provably cannot see).
- **`test_golden_numbers.py`** — each engine must reproduce its documented results on the cached window. Price-only engines get tight tolerances; GARP gets a band, since its EDGAR inputs legitimately shift as new filings arrive.
- **`test_execution_timing.py`** — synthetic-data check that a month-end decision enters at the decision close and earns from the next day: a crash engineered on day D+1 must hit the portfolio (no lag), while data after day D must never leak into P&L through D (no lookahead).

The suite was validated by mutation: re-introducing each fixed July 2026 bug makes the corresponding test fail. Tests skip gracefully when `data_cache/` is absent (fresh clone); run any strategy once to populate it.

---

## Setup

```bash
pip install pandas numpy matplotlib markdown pytest
```

**Alpaca credentials** (required for all strategies):

1. Sign up at [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → API Keys
2. Add to `.env`:
```
ALPACA_KEY=your-key-id-here
ALPACA_SECRET=your-secret-here
```

First run downloads and caches all data; subsequent runs load from `data_cache/` instantly.

---

## Data Sources

| Data | Source | Notes |
|---|---|---|
| ETF / stock daily prices | Alpaca SIP `1Day` bars, `adjustment=all` | Total return (splits + dividends) · ~2016 onwards |
| SPY 5-min intraday | Alpaca SIP `5Min` bars | ~230k bars · 2020–2024 · SIS only |
| T-bill proxy | BIL ETF daily return | SPDR 1–3 Month T-Bill ETF |
| Fundamentals | SEC EDGAR XBRL Company Facts API | No API key · exact filing dates · ~2009 onwards |

---

## Adding a New Strategy

1. Create `strategies/your_strategy/` with `__init__.py`
2. Add `config.py` importing shared params from root `config.py`
3. Add `backtest.py` and `main.py` (see existing strategies for the sys.path pattern)
4. Import from `core.data` and `core.metrics`

---

*Mark Garcera · NUS CS · CFA Level 1 Passed (and going further)· Aspiring Junior Trader*