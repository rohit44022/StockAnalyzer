# 📈 Bollinger Band Squeeze Strategy Analyser

> **Based on:** *Bollinger on Bollinger Bands* — John Bollinger CFA CMT  
> **Method I:** Volatility Breakout — Chapters 15 & 16  
> **Market:** NSE India (1,983 stocks)  
> **Timeframe:** Positional (daily candles) — short to medium term

---

## 📋 Table of Contents

1. [Quick Start](#1-quick-start)
2. [Project Structure — Every File Explained](#2-project-structure--every-file-explained)
3. [How to Run the Software](#3-how-to-run-the-software)
4. [Menu Options — Deep Dive](#4-menu-options--deep-dive)
5. [Terminal Output Guide — Every Panel Decoded](#5-terminal-output-guide--every-panel-decoded)
6. [The 7 Indicators — What They Measure](#6-the-7-indicators--what-they-measure)
7. [The 5 Buy Conditions — All Must Be ✅](#7-the-5-buy-conditions--all-must-be-)
8. [The 3 Exit Signals — One Is Enough](#8-the-3-exit-signals--one-is-enough)
9. [Signal Types — Explained](#9-signal-types--explained)
10. [Confidence Score — How It's Calculated](#10-confidence-score--how-its-calculated)
11. [Head Fake Detection](#11-head-fake-detection)
12. [Phase Analysis (3 Phases)](#12-phase-analysis-3-phases)
13. [Fundamental Analysis Panel](#13-fundamental-analysis-panel)
14. [Scan Results Table — Every Column](#14-scan-results-table--every-column)
15. [Historical Data System](#15-historical-data-system)
16. [Configuration Reference](#16-configuration-reference)
17. [Data Flow Diagram](#17-data-flow-diagram)
18. [Common Questions & Answers](#18-common-questions--answers)

---

## 1. Quick Start

```bash
# Step 1: Navigate to the project folder
cd '/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data'

# Step 2: Run the application
python3 main.py
```

On first launch, the software automatically checks if historical data exists and is current.  
If data is missing or stale, it downloads all 1,983 NSE stocks before opening the menu.

---

## 2. Project Structure — Every File Explained

```
historical_data/
│
├── main.py                     ← ENTRY POINT — Run this file
├── historical_data.py          ← Downloads OHLCV data from Yahoo Finance
├── get-pip.py                  ← pip installer (not used at runtime)
├── README.md                   ← This file
│
├── stock_csv/                  ← 1,983 CSV files (one per NSE stock)
│   ├── RELIANCE.NS.csv         ← Format: Date,Open,High,Low,Close,Adj Close,Volume
│   ├── TCS.NS.csv
│   ├── INFY.NS.csv
│   └── ... (1,983 total)
│
└── bb_squeeze/                 ← Core analysis package
    ├── __init__.py             ← Package marker
    ├── config.py               ← All parameters & thresholds (edit here to tune)
    ├── data_loader.py          ← CSV reader + live yfinance fallback
    ├── indicators.py           ← All 7 indicator calculations (pure math)
    ├── signals.py              ← Signal engine (buy/sell/hold/wait logic)
    ├── scanner.py              ← Batch scanner (parallel, 8 threads)
    ├── display.py              ← Terminal UI (rich library — all formatting)
    ├── fundamentals.py         ← Fundamental data fetcher (yfinance)
    └── cache/                  ← Cached fundamental data (auto-created)
```

### File-by-File Role

| File | What It Does | Output on Terminal |
|------|--------------|--------------------|
| `main.py` | Entry point. Menu loop. Calls everything else. Startup freshness check. | Header banner, menu, data-freshness message |
| `historical_data.py` | Downloads 1,983 NSE tickers via yfinance. Skips fresh CSVs. Retries once. | Progress bar: `Saving RELIANCE.NS … ✓ 1538 rows` |
| `bb_squeeze/config.py` | All tunable parameters (BB period, SAR AF, BBW trigger, CMF/MFI thresholds) | *(no terminal output — pure config)* |
| `bb_squeeze/data_loader.py` | Reads `.NS.csv` from `stock_csv/`. Falls back to live yfinance if CSV missing. Lists all 1,983 tickers. | `⚠ No local data — fetching live` |
| `bb_squeeze/indicators.py` | Calculates all 7 indicators. Returns enriched DataFrame with new columns. | *(no direct output — feeds signals.py)* |
| `bb_squeeze/signals.py` | Evaluates 5 buy conditions, 3 exit signals, head-fake check. Produces `SignalResult`. | *(no direct output — feeds display.py)* |
| `bb_squeeze/scanner.py` | Runs `analyze_single_ticker()` on ALL 1,983 stocks in parallel (8 threads). Categorises into buy/sell/hold/squeeze/head_fake buckets. | Progress bar `Scanning stocks... 1983/1983`, scan time |
| `bb_squeeze/display.py` | Renders all terminal panels using `rich`. Single stock dashboard + scan tables. | **All the coloured panels you see** |
| `bb_squeeze/fundamentals.py` | Fetches P/E, ROE, debt ratios etc. from yfinance. Computes conviction score. | Valuation / Profitability / Health tables |

---

## 3. How to Run the Software

```bash
python3 main.py
```

### What Happens on Startup (Step-by-Step)

```
1. print_header()               → Prints the golden banner
2. check_and_update_data()      → Checks stock_csv/ for data freshness
   ├── If no data found         → Auto-downloads all 1,983 stocks (no prompt)
   ├── If data > 4 days old     → Asks: "Update historical data now? [Y/n]"
   └── If data ≤ 4 days old     → Prints: "✓ Historical data is up-to-date (last date: 2026-03-16)"
3. Main menu loop begins
```

### Data Freshness Logic (`STALENESS_DAYS = 4`)

Why 4 days? Because:
- **Monday** — last trade was Friday (2 days ago)
- **Tuesday after a long weekend** — last trade was Thursday (4 days ago)
- 4 days covers all weekend + public holiday gaps without false alerts

---

## 4. Menu Options — Deep Dive

```
📊 MAIN MENU

  1  →  Analyze a specific stock
  2  →  Scan ALL stocks — BUY signals
  3  →  Scan ALL stocks — SELL / EXIT signals
  4  →  Scan ALL stocks — SQUEEZE stocks (Phase 1 & 2)
  5  →  Scan ALL stocks — COMPLETE report
  6  →  Download / Update historical data
  7  →  Help
  0  →  Exit
```

### Option 1 — Single Stock Analysis

**What it does:**
- Asks for a ticker: `RELIANCE` or `RELIANCE.NS` or `TCS` — all formats accepted
- Loads CSV from `stock_csv/`, falls back to live yfinance if not found
- Computes all 7 indicators on the full history
- Runs signal engine
- Fetches fundamental data from Yahoo Finance
- Renders the full 5-panel dashboard

**Time taken:** ~3–5 seconds (mostly fundamental fetch from internet)

### Option 2 — BUY Signals Scan

**What it does:**
- Loads all 1,983 CSVs from `stock_csv/`
- Processes each in parallel (8 threads)
- Shows ONLY stocks where all 5 buy conditions are simultaneously ✅
- Sorted by confidence score (highest first)

**Time taken:** ~30–90 seconds depending on hardware

### Option 3 — SELL Signals Scan

**What it does:**
- Same parallel scan as Option 2
- Shows stocks where ANY ONE of the 3 exit signals has triggered
- These are stocks you might already own that need attention

### Option 4 — SQUEEZE Scan

**What it does:**
- Shows stocks currently in Phase 1 (Compression) or Phase 2 (Direction)
- Sorted by `squeeze_days` descending (longest squeeze first = highest energy stored)
- These are "watch list" stocks — spring is coiling, breakout coming

### Option 5 — Complete Report

**What it does:**
- Runs the full scan once
- Prints BUY signals first (highest priority)
- Then SELL signals
- Then top 30 squeeze stocks by days in squeeze
- Then head-fake warnings
- Then summary statistics

### Option 6 — Download / Update Data

**What it does:**
- Calls `download_all_historical_data()` from `data_loader.py`
- Asks: "Skip already-downloaded tickers?" (recommended = Yes)
- Downloads 2020-01-01 to today for all tickers
- Shows progress every 50 tickers

### Option 7 — Help

Shows the condensed version of this README as a panel in the terminal.

---

## 5. Terminal Output Guide — Every Panel Decoded

When you run **Option 1 (Single Stock Analysis)**, you get 5 panels in this order:

---

### Panel 1 — ACTION SIGNAL

```
╭─────────────────────── ACTION SIGNAL — Confidence: 85/100 ────────────────────────╮
│                                                                                      │
│  🚀 BUY SIGNAL                                                                       │
│                                                                                      │
│  ✅ BUY SIGNAL — Enter at tomorrow's market open.                                    │
│     MFI shows maximum fuel. Enter FULL position.                                     │
│     Stop Loss: ₹2,450.50 (Parabolic SAR). Exit if price closes below this.          │
│                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────╯
```

**What each element means:**

| Element | Meaning |
|---------|---------|
| `Confidence: 85/100` | How many of the 7 conditions are strongly met. See [Section 10](#10-confidence-score--how-its-calculated) |
| `🚀 BUY SIGNAL` | All 5 buy conditions are ✅ AND no head fake detected |
| `Enter at tomorrow's market open` | Execute the trade at NSE open (9:15 AM IST) next day |
| `Stop Loss: ₹2,450.50` | Current Parabolic SAR value — if price closes below this, EXIT immediately |
| `Enter FULL position` | MFI > 80 — maximum fuel — go in with full planned capital |
| `Enter half position` | MFI 50–80 — moderate fuel — risk half your normal position |

**Action Signal Color Codes:**

| Color | Signal | Meaning |
|-------|--------|---------|
| 🟩 Green background | BUY | Enter the trade |
| 🟦 Blue background | HOLD | Stay in the trade |
| 🟥 Red background | SELL / EXIT | Exit the trade |
| 🟨 Yellow background | WAIT | Squeeze set, no breakout yet |
| 🟧 Orange background | HEAD FAKE | Suspicious breakout — DO NOT enter |
| ⬜ Grey background | MONITOR | No setup present — just watching |

---

### Panel 2 — Indicator Readings (7 Indicators, 3 Groups)

```
────────────────── INDICATOR READINGS  (7 Indicators — 3 Groups) ──────────────────

 Group  Indicator           Value          Status
 ─────  ──────────────────  ─────────────  ────────────────────────────────────
   A    Bollinger Bands     ₹2,580.00      Upper:₹2,640.00  Mid:₹2,520.00  Lower:₹2,400.00
                                           Price ABOVE upper band → BREAKOUT ↑
   A    Parabolic SAR       ₹2,450.50      Dots BELOW candles = UPTREND → HOLD
   A    Volume + 50 SMA     1,23,45,678    2.3x above avg — STRONG CONVICTION
   B    BandWidth (BBW)     0.0791         Trigger: 0.0800  6M-Min: 0.0742
                                           🔴 SQUEEZE SET — Spring is coiled!
   B    %b (Percent B)      1.042          Levels: 0.20 / 0.50 / 0.80
                                           Above 0.80 — Bullish zone
   C    CMF (Chaikin MF)    +0.1340        Zones: -0.10 / 0 / +0.10
                                           Strong ACCUMULATION → Big players buying
   C    MFI (Money Flow)    83.4           Levels: 20 / 50 / 80
                                           MFI > 80 — MAXIMUM FUEL → Full position
```

**Group A — Main Chart Indicators (what you see on the candle chart)**

| Indicator | What the Value Means | Key Levels to Know |
|-----------|---------------------|--------------------|
| **Bollinger Bands** | Shows price (₹) and the three band levels. The "Status" tells you WHERE price is relative to bands. | Above Upper = Breakout ↑ / Below Lower = Breakdown ↓ / Middle = neutral |
| **Parabolic SAR** | The trailing stop loss dot value in ₹. "Bull" = dots below candles. "Bear" = dots above candles. | Dots BELOW = uptrend (hold). Dots ABOVE = downtrend (don't buy / exit) |
| **Volume + 50 SMA** | Today's volume vs. the 50-day average volume (the "yellow line"). `2.3x above avg` means today's volume is 2.3× the average. | ≥ 1.0x = confirms breakout. ≥ 1.5x = strong conviction. < 1.0x = weak / potential head fake |

**Group B — Squeeze Indicators (the "squeeze sensor")**

| Indicator | What the Value Means | Key Levels to Know |
|-----------|---------------------|--------------------|
| **BandWidth (BBW)** | `(Upper Band − Lower Band) ÷ Middle Band`. Measures how tight/wide the bands are. Lower = tighter = more compressed. | `Trigger: 0.0800` = the absolute squeeze threshold. `6M-Min: 0.0742` = the rolling 6-month minimum BBW. Squeeze is ON when current BBW ≤ either threshold. |
| **%b (Percent B)** | Where is price within the bands? 0 = at lower band. 0.5 = at middle. 1.0 = at upper band. Values > 1.0 = ABOVE upper band (breakout). | < 0.20 = bearish zone. 0.20–0.50 = lean bearish. 0.50–0.80 = lean bullish. > 0.80 = bullish zone. > 1.0 = breakout confirmed. |

**Group C — Direction Indicators (the "fuel gauge")**

| Indicator | What the Value Means | Key Levels to Know |
|-----------|---------------------|--------------------|
| **CMF (Chaikin Money Flow)** | Range: −1.0 to +1.0. Measures whether BIG institutional money is flowing INTO (+) or OUT OF (−) the stock. Calculated over 20 days. | > +0.10 = strong accumulation (big players buying). 0 to +0.10 = mild buying. −0.10 to 0 = mild selling. < −0.10 = strong distribution (big players selling). |
| **MFI (Money Flow Index)** | Range: 0 to 100. Like RSI but includes volume — measures breakout "fuel". Calculated over 10 days. | > 80 = maximum fuel → FULL position. 50–80 = moderate fuel → enter. < 50 on breakout = weak fuel → skip or half position. < 20 = heavily oversold. |

---

### Panel 3 — 5-Condition Buy Checklist

```
───────────────── 5-CONDITION BUY CHECKLIST  (ALL must be ✅ to BUY) ──────────────────

 #   Condition                                 Required                          Status
 ──  ───────────────────────────────────────   ───────────────────────────────   ──────────
 1   BBW at squeeze trigger (0.08)             BBW ≤ 0.08 or 6M low | 0.0791   ✅ GREEN
 2   Price closes ABOVE upper Bollinger Band   Close > Upper | ₹2580 > ₹2480   ✅ GREEN
 3   Volume GREEN and above 50-period SMA      Vol 1,23,45,678 > SMA 53,45,123  ✅ GREEN
 4   CMF above zero (ideally > +0.10)          CMF: +0.1340 | Need: > 0.00      ✅ GREEN
 5   MFI above 50 and rising                   MFI: 83.4 | Need: > 50 rising ✓  ✅ GREEN
 ──────────────────────────────────────────────────────────────────────────────────────────
     VERDICT                                   ALL 5 ✅ — BUY SIGNAL ACTIVE
```

**Reading this panel:**

| Condition | What it Checks | Why It Matters |
|-----------|---------------|----------------|
| **#1 — BBW Squeeze** | Is the spring coiled? BBW must be at or below the 6-month lowest value (indicating minimum volatility). | The "Squeeze" is the setup — it only works when the bands are maximally compressed. Without this, there is no strategy. |
| **#2 — Price Breakout** | Did price close ABOVE the upper Bollinger Band on today's candle? The entire candle close must be above, not just a wick. | This is the TRIGGER — the spring being released. Price breaking the band = the volatility burst starting. |
| **#3 — Volume + Green Candle** | Is today's candle green (close ≥ previous close) AND is volume above the 50-day average volume? | Volume above average = institutions are participating. Without volume, the breakout is not confirmed — it's just noise. |
| **#4 — CMF > 0** | Is institutional money flowing INTO the stock? CMF must be positive (>0). Ideally >+0.10. | CMF reveals what big money is doing QUIETLY during the squeeze. Positive CMF during squeeze = accumulation phase (they were buying BEFORE the breakout). |
| **#5 — MFI > 50 and Rising** | Is the MFI above 50 AND higher than yesterday's MFI? | MFI is the fuel gauge. Rising MFI > 50 means buying pressure is building. A breakout without rising MFI is likely to fail immediately. |

**What happens if 4/5 conditions are met?**

The signal stays as `WAIT`. ALL five must be simultaneously ✅. This is strict by design — false signals are extremely costly.

---

### Panel 4 — Squeeze Phase Analysis

```
─────────────────────────── SQUEEZE PHASE ANALYSIS ────────────────────────────────

 Phase 2 — DIRECTION CLUES
 Big players are positioning. CMF and MFI giving directional hints.

 Direction Lean  : 🟢 BULLISH
 Squeeze Active  : YES — 12 consecutive days
 SAR Direction   : Uptrend (hold)
```

**The 3 Phases (from John Bollinger's book):**

| Phase | Name | What's Happening | What You Do |
|-------|------|-----------------|-------------|
| **Phase 1** | COMPRESSION | BBW at 6-month low. No clear direction. Both CMF and MFI are neutral (near zero/50). This is pure waiting. | Add to your watchlist. Set a price alert above the upper band. |
| **Phase 2** | DIRECTION CLUES | Still in squeeze but CMF is showing clear buying (+ve) or selling (−ve). MFI diverging from 50. %b moving. | Prepare your order. Direction lean tells you WHICH way the breakout will likely go. |
| **Phase 3** | EXPLOSION | Price breaks the upper (bullish) or lower (bearish) band. BBW starts expanding. This is the entry candle. | If all 5 conditions met → ENTER. If head fake detected → WAIT. |

**Direction Lean Explanation:**

The software scores 5 indicators (CMF, MFI, %b, volume) to determine lean:
- `🟢 BULLISH` — bull_score > bear_score + 1 → upside breakout more likely
- `🔴 BEARISH` — bear_score > bull_score + 1 → downside breakout more likely
- `⚪ NEUTRAL` — scores tied → no clear lean, wait

**Squeeze Days:**
- How many consecutive days the stock has been in squeeze (Squeeze_ON = True)
- **Longer squeeze = more energy stored = potentially bigger breakout**
- 10+ days in squeeze is very significant
- 20+ days in squeeze → spring is extremely coiled

---

### Panel 5 — Fundamental Analysis

```
─────────────────── FUNDAMENTAL ANALYSIS — Reliance Industries Ltd ─────────────────

 Company    Reliance Industries Ltd       Market Cap   ₹17,23,456 Cr (Large Cap)
 Sector     Energy                        Industry     Oil & Gas Refining
 52W High   ₹2,960.00                    52W Low      ₹2,208.00
 vs 52W High   -12.84%                   Beta         0.87

 ┌─ VALUATION ─────────────────┐  ┌─ PROFITABILITY ───────────────┐  ┌─ FINANCIAL HEALTH ────────────┐
 │ P/E Ratio (TTM)   22.4      │  │ ROE %           16.8          │  │ Debt/Equity      0.45         │
 │ Forward P/E       19.1      │  │ ROA %            8.2          │  │ Current Ratio    1.82         │
 │ Price/Book         2.1      │  │ Profit Margin %  9.4          │  │ Quick Ratio      1.41         │
 │ Price/Sales        1.8      │  │ Operating Margin 14.7         │  │ Dividend Yield % 0.42         │
 │ EV/EBITDA         11.2      │  │ Revenue Growth % 8.3          │  │ Dividend/Share   ₹9.50        │
 │ PEG Ratio          1.4      │  │ EPS Growth %    12.1          │  │ Payout Ratio %  18.2          │
 └─────────────────────────────┘  └───────────────────────────────┘  └───────────────────────────────┘

╭──────────────────── FUNDAMENTAL CONVICTION BUILDER ────────────────────────────────╮
│ Fundamental Score: 72/100  —  STRONG FUNDAMENTALS                                  │
│                                                                                     │
│ Conviction Points:                                                                  │
│    ROE 16.8% (strong >15%), Revenue growth 8.3% (healthy),                         │
│    Debt/Equity 0.45 (conservative), P/E 22.4 (reasonable for large-cap)            │
╰─────────────────────────────────────────────────────────────────────────────────────╯
```

**Reading the Fundamental Tables:**

**VALUATION (Is it cheap or expensive?)**

| Metric | What It Is | Good Range | Why It Matters |
|--------|-----------|------------|----------------|
| P/E Ratio (TTM) | Price ÷ Earnings per share (last 12 months) | < 25 for large-cap, < 20 for mid-cap | Lower = cheaper. But very low P/E with low growth = value trap. |
| Forward P/E | Price ÷ Expected future earnings | < 20 = good | If Forward P/E < TTM P/E → earnings expected to grow |
| Price/Book | Price ÷ Book value per share | < 3 = reasonable | How much premium market pays over accounting value |
| Price/Sales | Market cap ÷ Revenue | < 3 = good | Useful for low-margin businesses |
| EV/EBITDA | Enterprise value ÷ Earnings before interest, tax, depreciation | < 15 = fair | Best cross-company valuation metric |
| PEG Ratio | P/E ÷ Earnings growth % | < 1.5 = good | PEG < 1 = growing faster than its valuation suggests |

**PROFITABILITY (Is the business making real money?)**

| Metric | What It Is | Good Range | Why It Matters |
|--------|-----------|------------|----------------|
| ROE % | Net profit ÷ Shareholders' equity × 100 | > 15% = strong | Measures how efficiently management uses your money |
| ROA % | Net profit ÷ Total assets × 100 | > 5% = good | Asset efficiency |
| Profit Margin % | Net profit ÷ Revenue × 100 | > 10% = good | How much of each ₹ of revenue becomes profit |
| Operating Margin % | Operating profit ÷ Revenue × 100 | > 15% = strong | Core business profitability before tax/interest |
| Revenue Growth % | YoY revenue increase | > 10% = growing | Is the business actually expanding? |
| EPS Growth % | YoY earnings per share increase | > 10% = growing | Is profit growing? Key for P/E ratio context |

**FINANCIAL HEALTH (Will it survive hard times?)**

| Metric | What It Is | Good Range | Why It Matters |
|--------|-----------|------------|----------------|
| Debt/Equity | Total debt ÷ Shareholders' equity | < 1.0 = safe | High debt = risky in bear markets |
| Current Ratio | Current assets ÷ Current liabilities | > 1.5 = liquid | Can it pay short-term bills? |
| Quick Ratio | (Current assets − Inventory) ÷ Current liabilities | > 1.0 = healthy | Like current ratio but excludes hard-to-sell inventory |
| Dividend Yield % | Annual dividend ÷ Price × 100 | > 1% = income | Passive income from holding the stock |
| Payout Ratio % | Dividends paid ÷ Net profit × 100 | < 60% = sustainable | Low ratio = company retaining profits to reinvest |

**Fundamental Score (0–100):**

| Score | Verdict | Meaning |
|-------|---------|---------|
| 65–100 | STRONG FUNDAMENTALS | Business is healthy. Technical signal has fundamental backing. High conviction. |
| 40–64 | MODERATE FUNDAMENTALS | Average business. Signal may still work but reduce position size. |
| 0–39 | WEAK FUNDAMENTALS | Business is struggling. Technical signal may be short-lived. Caution. |

---

## 6. The 7 Indicators — What They Measure

### Group A — Main Chart (overlay on candles)

#### 1. Bollinger Bands (BB)
```
Parameters: Period = 20 days, Std Dev = 2.0, Type = SMA
```
- **Middle Band** = 20-day Simple Moving Average of Close price
- **Upper Band** = Middle + (2 × 20-day standard deviation)
- **Lower Band** = Middle − (2 × 20-day standard deviation)
- **Why 20 and 2.0?** — John Bollinger's own specification. 20 = intermediate trend. 2.0 std dev = covers 88–89% of all price data. These are NOT arbitrary.

#### 2. Parabolic SAR (Stop And Reverse)
```
Parameters: Init AF = 0.02, Step AF = 0.02, Max AF = 0.20
```
- Dots that appear BELOW candles in an uptrend, ABOVE candles in a downtrend
- As price makes new highs, the SAR value "accelerates" upward (AF increases by 0.02 each new high, up to 0.20 max)
- When price closes below the SAR dot → **IMMEDIATE EXIT** (primary exit signal)
- The ₹ value shown IS your stop loss — if you own the stock, it's where you get out

#### 3. Volume + 50-period SMA
```
Parameters: Volume SMA Period = 50 days
```
- Yellow line = 50-day average daily volume (e.g., 50 lakh shares/day average)
- Today's bar = green (up day) or red (down day) relative to yesterday's close
- Condition 3 requires: Today is a GREEN candle AND today's volume > 50-day SMA

### Group B — Squeeze Panel (below the main chart)

#### 4. BandWidth (BBW)
```
Formula: BBW = (Upper Band − Lower Band) ÷ Middle Band
```
- Measures the WIDTH of the bands as a fraction of price
- **Low BBW (e.g., 0.06)** = bands are very tight = very low volatility = squeeze
- **High BBW (e.g., 0.25)** = bands are wide = high volatility = post-breakout
- The strategy looks for BBW at its **6-month rolling minimum** (lowest in 126 trading days)
- The absolute threshold `0.08` is used as backup if rolling min data is insufficient

#### 5. %b (Percent B)
```
Formula: %b = (Close − Lower Band) ÷ (Upper Band − Lower Band)
```
- A normalised position indicator: where is the current close within the band range?
- `%b = 0.0` → at the lower band
- `%b = 0.5` → at the midline (20-day SMA)
- `%b = 1.0` → at the upper band
- `%b = 1.2` → 20% ABOVE the upper band (full breakout)
- Used to determine Phase 2 direction lean and post-breakout momentum

### Group C — Direction Oscillators (separate chart panels)

#### 6. CMF — Chaikin Money Flow
```
Parameters: Period = 20 days
Formula: CMF = Sum(MFV, 20) ÷ Sum(Volume, 20)
         where MFV = ((Close−Low) − (High−Close)) ÷ (High−Low) × Volume
```
- Ranges from −1.0 to +1.0 (shown as +0.1340 format)
- Captures the **LOCATION of the close within the day's range**, multiplied by volume
- **Positive** = price closing near HIGH of day (bulls in control) × volume = smart money buying
- **Negative** = price closing near LOW of day (bears in control) × volume = smart money selling
- The KEY insight: CMF can be positive DURING a squeeze when price isn't moving — this is smart money quietly accumulating BEFORE the breakout

#### 7. MFI — Money Flow Index
```
Parameters: Period = 10 days (half of Bollinger Band period)
Formula: Typical Price = (High + Low + Close) ÷ 3
         Raw MF = Typical Price × Volume
         MFI = 100 − (100 ÷ (1 + (Positive MF Sum ÷ Negative MF Sum)))
```
- Ranges from 0 to 100
- Like RSI but volume-weighted — measures both PRICE direction and VOLUME
- Above 80 = maximum buying fuel (overbought but in a GOOD way at breakout)
- Above 50 = buying fuel present → condition 5 requires MFI > 50 AND rising
- Below 50 = selling pressure starting → exit warning
- Below 20 = extremely oversold (good for bottom-fishing, not this strategy)

---

## 7. The 5 Buy Conditions — All Must Be ✅

These are the EXACT conditions from John Bollinger's book, Method I, Chapters 15–16:

| # | Condition | Technical Check | Default Value | Meaning |
|---|-----------|----------------|---------------|---------|
| 1 | **Squeeze SET** | `Squeeze_ON = True` | BBW ≤ 0.08 OR BBW ≤ 6M rolling min × 1.05 | The spring is coiled. Low volatility setup. |
| 2 | **Price above upper band** | `Close > BB_Upper` | Real-time | The spring is being released. Upside breakout candle. |
| 3 | **Volume confirmed** | `Volume > Vol_SMA50` AND `Close ≥ Previous Close` | 50-period SMA | Institutions are participating. Not a retail-only spike. |
| 4 | **CMF positive** | `CMF > 0` | Ideally > +0.10 | Smart money flowed IN before/during breakout. |
| 5 | **MFI rising above 50** | `MFI > 50` AND `MFI > Previous MFI` | Period = 10 | Breakout has buying fuel. Not running on empty. |

**ALL five must be true at the same time. If even one is ❌, the signal is NOT generated.**

---

## 8. The 3 Exit Signals — One Is Enough

| # | Exit Signal | Condition | Urgency | Why |
|---|------------|-----------|---------|-----|
| 1 | **SAR Flip** (Primary) | `SAR_Bull = False` AND `Close < SAR` | 🔴 IMMEDIATE | Parabolic SAR has flipped. Trend has officially reversed. This is the book's primary exit. Exit NEXT morning open, no arguments. |
| 2 | **Lower Band Tag** (Max Profit) | `Close ≤ BB_Lower` | 🔴 IMMEDIATE | Price has traveled from upper band to lower band. The full move is complete. This is the textbook "take profit" exit. |
| 3 | **Double Negative** (Early Warning) | `CMF < 0` AND `MFI < 50` | 🟡 EARLY WARNING | Smart money exiting (CMF negative) AND fuel exhausted (MFI below 50). Breakout is losing steam. Exit before SAR flips to protect profits. |

**Exit signals override HOLD signals.** If you see SELL, act on it.

---

## 9. Signal Types — Explained

| Signal | When | Action | Notes |
|--------|------|--------|-------|
| 🚀 **BUY** | All 5 conditions ✅, no head fake | Enter at tomorrow's open | Confidence score tells you position size |
| 🟢 **HOLD** | In a trend: SAR below, price > mid band, CMF positive, MFI > 40 | Stay in the trade | Trail your stop loss to the SAR value daily |
| 🔴 **SELL / EXIT** | Any 1 of 3 exit conditions triggered | Exit at tomorrow's open | No exceptions — discipline over emotion |
| ⏳ **WAIT** | Squeeze is ON but price hasn't broken above upper band yet | Watch daily | The spring is coiled but not yet released |
| ⚠️ **HEAD FAKE** | Price broke upper band BUT confirming indicators disagree | DO NOT enter | Wait 2–3 days. Real move will come opposite direction. |
| ⚪ **MONITOR** | No squeeze, no signal | No action | Keep it on a general watchlist |

---

## 10. Confidence Score — How It's Calculated

The confidence score (0–100) reflects how strongly the 5 conditions are met, plus bonus points:

| Condition Met | Points |
|---------------|--------|
| Condition 1: Squeeze ON | +25 |
| Condition 2: Price above upper band | +25 |
| Condition 3: Volume confirmed | +20 |
| Condition 4: CMF positive | +15 |
| Condition 5: MFI above 50 | +15 |
| **Bonus:** CMF > +0.10 (strong accumulation) | +5 |
| **Bonus:** MFI > 80 (maximum fuel) | +5 |
| **Maximum** | **100** |

**Using confidence score for position sizing:**

| Confidence | Position Size Suggestion |
|------------|--------------------------|
| 85–100 | Full position (100% of planned capital) |
| 70–84 | 75% position |
| 60–69 | 50% position (MFI likely 50–65 range) |
| < 60 | Consider skipping (rare to trigger buy with this score) |

---

## 11. Head Fake Detection

A head fake is a **false breakout** — price punches above the upper band but then immediately reverses back down. The software uses 5 checks:

| Check | Condition | Eliminates |
|-------|-----------|------------|
| **Volume below average** | `Volume < Vol_SMA50` | ~80% of false breakouts — the single most powerful filter |
| **CMF negative on breakout** | `Close > BB_Upper` AND `CMF < 0` | Smart money not participating — they're actually selling into the spike |
| **MFI below 50 on breakout** | `Close > BB_Upper` AND `MFI < 50` | No buying fuel — breakout has no momentum behind it |
| **BBW not expanding** | `BBW < 6M_Min × 1.02` | Bands not widening = no real volatility explosion occurring |
| **Long upper wick rejection** | Upper wick > 60% of candle range | Price was rejected strongly — buyers couldn't hold the gains |

**Threshold:** 2 or more of the above = HEAD FAKE warning.

**What to do:** Wait 2–3 days. Often the REAL move will come in the **opposite direction** (downside) after a head fake up, once trapped buyers capitulate.

---

## 12. Phase Analysis (3 Phases)

Based on John Bollinger's 3-phase squeeze model:

```
Phase 1: COMPRESSION
    ┌──────────────────────────────────────┐
    │   BBW low (spring coiling)           │
    │   CMF ≈ 0  (no clear flow)           │
    │   MFI ≈ 50 (balanced)                │
    │   %b ≈ 0.5 (at midline)              │
    │   ACTION: Add to watchlist           │
    └──────────────────────────────────────┘
              ↓  (days or weeks later)
Phase 2: DIRECTION CLUES
    ┌──────────────────────────────────────┐
    │   BBW still low (still coiling)      │
    │   CMF starts going + or −            │
    │   MFI moves away from 50             │
    │   %b drifts towards 0.8 or 0.2       │
    │   ACTION: Prepare your order         │
    └──────────────────────────────────────┘
              ↓  (the breakout candle)
Phase 3: EXPLOSION
    ┌──────────────────────────────────────┐
    │   Price closes above upper band      │
    │   BBW starts expanding rapidly       │
    │   All 5 conditions ✅                │
    │   ACTION: ENTER (if no head fake)    │
    └──────────────────────────────────────┘
```

---

## 13. Fundamental Analysis Panel

The fundamental analysis is **optional conviction-building data** — it does NOT affect the buy/sell signals. The 5 conditions and 3 exits are purely technical.

**Purpose:** If two stocks both show BUY signal with 85/100 confidence, fundamentals help you decide WHICH ONE to enter. Strong fundamentals = higher conviction = larger position size.

**How to use:**
- Technical signal = WHEN to enter
- Fundamental score = HOW MUCH to put in
- High fundamental score (> 65) + BUY signal = high conviction → full position
- Low fundamental score (< 40) + BUY signal = low conviction → half position or skip

**Fundamental Score is calculated from:**
- P/E ratio vs sector
- ROE > 15% → strong
- Debt/Equity < 1.0 → safe
- Revenue growth > 10% → growing
- Current ratio > 1.5 → liquid
- Profit margin > 10% → profitable

---

## 14. Scan Results Table — Every Column

When you run Options 2–5, you get a table like this:

```
 Ticker       Company              Price ₹  Signal       Confidence  Phase        BBW     CMF     MFI   %b    Sqz Days  Lean    Fund.Score
 ───────────  ───────────────────  ───────  ───────────  ──────────  ───────────  ──────  ──────  ────  ────  ────────  ──────  ──────────
 RELIANCE.NS  Reliance Industries  ₹2,580   🚀 BUY       85/100      3-Explode    0.0791  +0.134  83.4  1.04  12        ▲ Bull  72/100
 TCS.NS       TCS                  ₹3,420   🚀 BUY       80/100      3-Explode    0.0623  +0.089  71.2  1.02  8         ▲ Bull  88/100
 INFY.NS      Infosys              ₹1,620   ⏳ WAIT      50/100      1-Compress   0.0751  +0.041  52.1  0.72  15        ▲ Bull  N/A
```

**Column-by-column breakdown:**

| Column | What It Shows | How to Read It |
|--------|--------------|----------------|
| **Ticker** | NSE ticker symbol (always ends in `.NS`) | Standard NSE code + `.NS` = Yahoo Finance format |
| **Company** | Company name (first 20 characters) | Full name visible in single stock analysis |
| **Price ₹** | Last closing price | Current market price from the latest CSV row |
| **Signal** | Current signal type | 🚀 BUY / 🔴 SELL / 🟢 HOLD / ⏳ WAIT / ⚠️ HEAD FAKE / ⚪ MONITOR |
| **Confidence** | Score out of 100 | Green ≥ 80 / Yellow ≥ 50 / Red < 50 |
| **Phase** | Current squeeze phase | `1-Compress` = Phase 1 / `2-Direct` = Phase 2 / `3-Explode` = Phase 3 / `Running` = post-breakout trend |
| **BBW** | Current BandWidth value | Lower = tighter = more compressed. < 0.08 = in squeeze zone |
| **CMF** | Chaikin Money Flow value | Green = positive (accumulation) / Red = negative (distribution) |
| **MFI** | Money Flow Index value | Green > 50 / Red < 50 |
| **%b** | Percent B position | > 1.0 = above upper band (breakout). 0.5 = at midline. |
| **Sqz Days** | Consecutive days in squeeze | Higher = more energy stored. `—` = not in squeeze |
| **Lean** | Direction lean during squeeze | `▲ Bull` / `▼ Bear` / `◆ Neut` |
| **Fund. Score** | Fundamental score | Only populated if "Fetch fundamentals?" was answered Yes. `N/A` if not fetched. |

---

### Scan Summary Statistics

At the bottom of every scan:

```
 Total Stocks Scanned:   1,983    Buy Signals:          14
 Stocks in Squeeze:        287    Sell/Exit Signals:    52
 Hold Signals:             340    Head Fake Warnings:    8
```

| Stat | What It Means | Typical Range |
|------|--------------|---------------|
| **Total Stocks Scanned** | How many CSVs were successfully loaded and analyzed | 1,900–1,983 (some may fail min data check) |
| **Buy Signals** | Stocks where all 5 conditions simultaneously ✅ | 5–30 in a normal market. >50 = market euphoria. 0 = bear market |
| **Sell/Exit Signals** | Stocks where any exit condition triggered | 20–100+ normal. Spikes during market corrections |
| **Stocks in Squeeze** | Total in Phase 1 or Phase 2 | 100–400 typical. Higher in range-bound markets |
| **Hold Signals** | Stocks in active uptrend (not at exit) | 100–500 in bull market |
| **Head Fake Warnings** | Suspicious breakouts to avoid | 3–15 normal |

---

## 15. Historical Data System

### How Data is Downloaded

```
historical_data.py
    ↓
get_historical_data(tickers, start_date, end_date, save_path, skip_existing)
    ↓
For each ticker (ThreadPoolExecutor, 8 workers):
    ↓
    1. Check if CSV exists in stock_csv/
    2. If exists: Read last date. Check staleness.
       - If last_date is within 4 days of today → SKIP (already fresh)
       - If last_date > 4 days ago → RE-DOWNLOAD (stale)
    3. Download via yfinance: ticker.history(start, end, auto_adjust=False)
    4. Clean the data (_clean_df):
       - Convert timezone: UTC → Asia/Kolkata
       - Normalize time to midnight → strip to pure YYYY-MM-DD date
       - Remove time component (avoids "2026-03-16 18:30:00" problem)
    5. Save to stock_csv/TICKER.NS.csv
```

### CSV File Format

```
Date,Open,High,Low,Close,Adj Close,Volume
2020-01-02,1313.250000,1320.199951,1299.099976,1314.800049,1314.800049,8345678
2020-01-03,1310.000000,1325.000000,1302.150024,1319.449951,1319.449951,7234567
...
2026-03-16,1380.000000,1397.300049,1363.500000,1395.099976,1395.099976,22837802
```

| Column | Type | Description |
|--------|------|-------------|
| `Date` | YYYY-MM-DD | Trading date (NSE market days only — no weekends/holidays) |
| `Open` | Float | Opening price at 9:15 AM IST |
| `High` | Float | Highest price during the day |
| `Low` | Float | Lowest price during the day |
| `Close` | Float | Closing price at 3:30 PM IST |
| `Adj Close` | Float | Dividend/split adjusted close (same as Close for analysis) |
| `Volume` | Integer | Total shares traded that day |

### Why is the last date always yesterday?

**This is not a bug.** Yahoo Finance has a 4–6 hour delay after NSE closes (15:30 IST).  
Data for today typically appears at 20:00–22:00 IST.  
If you run the software at 10:00 AM, the latest available data will be the previous trading day.  
Run after 10 PM IST for same-day data.

### Staleness Threshold (4 days)

The system considers data "stale" if the last date in the CSVs is more than 4 calendar days ago.  
This avoids unnecessary re-downloads on weekends and public holidays:
- If today is Monday → last data was Friday (2 days) → FRESH ✅
- If today is Tuesday after a 3-day weekend → last data was Thursday (4 days) → borderline FRESH ✅
- If today is Wednesday after data hasn't been updated → last data was Friday (4 days) → STALE ⚠️

---

## 16. Configuration Reference

All parameters live in `bb_squeeze/config.py`. You can tune them here:

```python
# ── Bollinger Bands ──
BB_PERIOD   = 20       # Standard. Do NOT change unless you're an expert.
BB_STD_DEV  = 2.0      # Standard. Do NOT change.

# ── Squeeze Trigger ──
BBW_TRIGGER  = 0.08    # Absolute threshold. Lower = stricter (fewer signals).
BBW_LOOKBACK = 126     # 6-month rolling window (~126 trading days in India)

# ── Parabolic SAR ──
SAR_INIT_AF  = 0.02    # Starting acceleration factor
SAR_STEP_AF  = 0.02    # How fast SAR accelerates on new highs
SAR_MAX_AF   = 0.20    # Maximum acceleration (SAR can't accelerate past this)

# ── Volume ──
VOLUME_SMA_PERIOD = 50  # 50-day average volume line

# ── CMF ──
CMF_PERIOD        = 20   # 20-day window
CMF_UPPER_LINE    = +0.10 # Strong accumulation threshold
CMF_LOWER_LINE    = -0.10 # Strong distribution threshold

# ── MFI ──
MFI_PERIOD      = 10    # 10-day (half of BB period — book specification)
MFI_OVERBOUGHT  = 80    # Full position above this
MFI_OVERSOLD    = 20    # Heavily oversold
MFI_MID         = 50    # Buy condition threshold
```

**Parameters you might reasonably tune:**
- `BBW_TRIGGER`: Increase to `0.10` to get MORE signals (looser squeeze definition). Decrease to `0.06` for FEWER, higher-quality signals.
- `CMF_PERIOD`: Book says 20–21. Try `21` if you want book-exact.
- `VOLUME_SMA_PERIOD`: Some traders use `20` instead of `50`. `50` is more reliable.

**Parameters you should NOT change:**
- `BB_PERIOD = 20` — John Bollinger specifically chose this. Changing it breaks the system.
- `BB_STD_DEV = 2.0` — Same — book specification.
- `MFI_PERIOD = 10` — Half of BB period — book specification.
- `MFI_OVERBOUGHT = 80` / `MFI_OVERSOLD = 20` — Book says 80/20, NOT 70/30.

---

## 17. Data Flow Diagram

```
main.py
  │
  ├── check_and_update_data()
  │     └── historical_data.py → stock_csv/*.NS.csv
  │
  ├── Option 1: run_single_stock()
  │     ├── data_loader.load_stock_data(ticker)
  │     │     ├── load_from_csv()   ← stock_csv/TICKER.NS.csv
  │     │     └── fetch_live_data() ← yfinance (fallback)
  │     ├── indicators.compute_all_indicators(df)
  │     │     ├── bollinger_bands()  → BB_Mid, BB_Upper, BB_Lower
  │     │     ├── bandwidth()        → BBW
  │     │     ├── percent_b()        → Percent_B
  │     │     ├── is_squeeze()       → Squeeze_ON (bool)
  │     │     ├── parabolic_sar()    → SAR, SAR_Bull
  │     │     ├── volume_sma()       → Vol_SMA50
  │     │     ├── chaikin_money_flow() → CMF
  │     │     └── money_flow_index() → MFI
  │     ├── signals.analyze_signals(ticker, df)
  │     │     ├── _phase_detection()  → phase (COMPRESSION/DIRECTION/EXPLOSION)
  │     │     ├── _direction_lean()   → BULLISH/BEARISH/NEUTRAL
  │     │     ├── _count_squeeze_days()
  │     │     ├── 5 buy conditions evaluated
  │     │     ├── confidence score calculated
  │     │     ├── _head_fake_check()
  │     │     ├── 3 exit conditions evaluated
  │     │     └── _build_action() → human text
  │     ├── fundamentals.fetch_fundamentals(ticker)
  │     │     └── yfinance.info → P/E, ROE, Debt/Equity, etc.
  │     └── display.print_signal_dashboard(sig, fd)
  │           ├── Panel 1: Action Signal
  │           ├── Panel 2: 7 Indicator Readings
  │           ├── Panel 3: 5 Conditions Checklist
  │           ├── Panel 4: Phase Analysis
  │           └── Panel 5: Fundamentals (if fetched)
  │
  └── Options 2–5: run_scan(mode)
        ├── get_all_tickers_from_csv() ← reads ALL *.csv from stock_csv/
        │     → ~1,983 tickers
        ├── SqueezeScanner.scan(tickers)
        │     └── ThreadPoolExecutor (8 workers)
        │           └── analyze_single_ticker() × 1,983
        │                 (same pipeline as Option 1, no fundamentals)
        ├── _categorise() → buy/sell/hold/wait/head_fake/squeeze buckets
        └── print_report(mode)
              ├── print_scan_results(buy_signals, "BUY")
              ├── print_scan_results(sell_signals, "SELL")
              ├── print_scan_results(squeeze_only, "SQUEEZE")
              └── print_summary_stats()
```

---

## 18. Common Questions & Answers

**Q: How often should I run the scanner?**  
A: Once per day, after the market closes (after 4:00 PM IST). Run it the evening before to prepare your orders for the next morning's open.

**Q: I see a BUY signal. Do I enter the same day?**  
A: No. The signal is generated AFTER the day's close. You enter at the NEXT day's market open (9:15 AM IST). This is because the signal is based on the closing candle confirming all 5 conditions.

**Q: What position size should I use?**  
A: Use the Confidence Score:
- 85–100 → Full planned position
- 70–84 → 75% position
- 60–69 → 50% position
- < 60 → Skip (buy signal unlikely with this score)

**Q: The SELL signal appeared. Should I exit immediately?**  
A: Exit at TOMORROW's market open (9:15 AM IST). Do not try to pick intraday exits. The signal is based on the daily closing candle.

**Q: Why do I see stocks with 0 BUY signals after running Options 2–5?**  
A: A BUY signal requires ALL 5 conditions simultaneously. In a bear market or sideways market, this can be rare. A result of 0 buy signals is itself useful information — it means the market is not in a healthy breakout phase.

**Q: The scan takes 2–3 minutes. Is this normal?**  
A: Yes. With 1,983 stocks processed in 8 parallel threads, it typically takes 60–120 seconds on modern hardware. Each stock requires loading a CSV, running 7 indicator calculations, and evaluating 8 signal conditions.

**Q: Why is BBW_TRIGGER = 0.08? Is this accurate?**  
A: The book specifies the CONCEPT (6-month rolling minimum BBW) not a fixed number. `0.08` is a typical absolute value that works well for most NSE large/mid-cap stocks. The code uses BOTH: dynamic rolling minimum AND the 0.08 absolute threshold — whichever is triggered. This makes it robust across different stocks.

**Q: The fundamentals show N/A for most columns. Why?**  
A: Fundamental data is fetched live from Yahoo Finance at scan time, which is slow. During bulk scans (Options 2–5), you are asked "Fetch fundamental scores?" — say NO for speed and fundamentals will show N/A. Use Option 1 (single stock) where fundamentals are always fetched.

**Q: Can I use this for intraday trading?**  
A: No. This strategy uses daily (EOD) candles. It is designed for positional trades: enter next day's open, hold for days to weeks, exit when SAR flips or lower band is tagged. It is NOT designed for intraday.

**Q: What does "Direction Lean: BULLISH" mean during a squeeze?**  
A: While the stock is in squeeze (spring coiling), the CMF and MFI are already showing which direction the eventual breakout will likely be. BULLISH lean = institutions buying quietly = upside breakout more likely. This is NOT a buy signal yet — it's a direction hint to help you prepare mentally.

**Q: How do I know which SELL signal is most important?**  
A: Priority order:
1. **SAR Flip** = MOST urgent. Exit immediately no matter what.
2. **Lower Band Tag** = Take your profits. The full move is done.
3. **Double Negative** = EARLY warning. You can choose to exit now or tighten stop.

If SAR Flip and Double Negative both fire on the same day — do not debate. Exit at next open.

---

*Software built by Rohit | Strategy from John Bollinger's "Bollinger on Bollinger Bands" (2001), McGraw-Hill*  
*Data source: Yahoo Finance via yfinance library | Universe: NSE India (~1,983 stocks)*
