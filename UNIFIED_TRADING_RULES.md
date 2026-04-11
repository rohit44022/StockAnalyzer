# UNIFIED TRADING RULES — One System, Four Lenses
# ══════════════════════════════════════════════════
#
# This is ONE integrated trading system built from four complementary
# perspectives. Each perspective adds a unique lens — together they
# form a single decision framework, not four separate systems.
#
# The Four Lenses:
#   [BOLLINGER]   — Volatility & mean-reversion (timing)
#   [MURPHY]      — Trend structure & confirmation (direction)
#   [BROOKS]      — Bar-by-bar price action (precision)
#   [VILLAHERMOSA] — Volume-price behavior / Wyckoff method (intent)
#   [CONFLUENCE]  — Where 2+ lenses converge (conviction)
#
# HONESTY NOTE ON [VILLAHERMOSA] RULES:
# ──────────────────────────────────────
# Villahermosa teaches a systematic Wyckoff methodology with qualitative
# principles. He provides a complete framework: 3 Laws, 7 Events,
# 5 Phases (A-E), 4 Schematics, and 3 Trading Zones. Every [VILLAHERMOSA]
# rule below captures his CONCEPT and DIRECTION accurately. The
# binary format, numeric thresholds, and scoring are [CALIBRATION] — our
# quantification of his teaching for algorithmic use.
#
# Phase names (A-E) and event labels (PS, SC, AR, ST, Spring, SOS, LPS)
# follow Villahermosa's explicit framework from "The Wyckoff Methodology
# in Depth." Schematics #1/#2 and Trading Zones are Villahermosa's own
# pedagogical contributions to the Wyckoff canon.
#
# Every rule below is:
#   1. Specific and binary (YES/NO)
#   2. Labeled with its source lens
#   3. Part of a checklist executable in under 60 seconds
#   4. Accompanied by a plain-English hint
#
# ══════════════════════════════════════════════════


## 1. PRE-TRADE CHECKLIST (< 60 seconds)
## ═══════════════════════════════════════════════

Check every item. If more than 2 fail → NO TRADE.

### A. What Is the Market Doing? (Structure + Phase)

**Rule 1.1** [CONFLUENCE — VILLAHERMOSA + MURPHY] Identify Phase AND Trend
  - Step 1 [VILLAHERMOSA]: Name the Wyckoff phase (A-E) and structure —
    ACCUMULATION, MARKUP, DISTRIBUTION, or MARKDOWN.
    Identify which Schematic (#1 with Spring/UTAD or #2 without).
    Source: Villahermosa Parts 4-6 (phases, events, structures).
  - Step 2 [MURPHY]: Confirm with 50-SMA — Above = BULLISH, Below = BEARISH
  - Binary: Phase + Trend agree = GREEN. Phase and trend disagree = CAUTION.
  - If ACCUMULATION or MARKUP → Only BUY setups
  - If DISTRIBUTION or MARKDOWN → Only SELL/EXIT setups
  - 📝 Hint: "First name the phase (what is the Composite Man doing?),
    then check the trend direction. If both agree, you have a green light."

**Rule 1.2** [BROOKS] Determine Always-In Direction
  - Would a trader who MUST always hold a position be LONG or SHORT?
  - Binary: LONG / SHORT / FLAT
  - If this CONFLICTS with Rule 1.1 → treat as CAUTION
  - 📝 Hint: "If forced to bet right now, which way? That's always-in."

**Rule 1.3** [BOLLINGER] Check Volatility State
  - Is Bollinger Band Width < 25th percentile of last 120 bars?
  - YES = SQUEEZE (big move imminent, direction unknown from this lens alone)
  - NO = Normal volatility
  - 📝 Hint: "Are the bands very tight? A coiled spring is about to release."

### B. Who Is Winning? (Volume Truth)

**Rule 1.4** [VILLAHERMOSA] Read the Volume Character
  - Source: Villahermosa — Part 3, Law of Effort vs Result
  - Classify current volume: CLIMAX / SPIKE / ABOVE_AVG / NORMAL / DRYUP
  - Classify volume trend (10 bars): INCREASING / DECREASING / FLAT
  - [CALIBRATION] The 5-category system is our taxonomy.
  - 📝 Hint: "Is the stock getting lots of attention or being ignored?"

**Rule 1.5** [CONFLUENCE — VILLAHERMOSA + MURPHY] Volume Confirms Price?
  - [VILLAHERMOSA] Compare wave volumes (Part 3, Effort vs Result on Waves):
    up-wave vol vs down-wave vol.
    DEMAND_DOMINANT (ratio > 1.5×) = Bullish / SUPPLY_DOMINANT (< 0.67×) = Bearish
  - [VILLAHERMOSA] Compare wave durations: up-wave bars vs down-wave bars
    Patient side (longer waves) has conviction
  - [MURPHY] On the last move: did volume expand with price? YES = Confirmed
  - Binary: Volume supports the trend = GREEN / Volume diverges = WARNING
  - [CALIBRATION] The 1.5× ratio threshold is ours. Villahermosa compares qualitatively.
  - 📝 Hint: "Add up volume on up-days vs down-days. The side with more
    volume AND more persistent waves is winning."

**Rule 1.6** [VILLAHERMOSA] Check for Exhaustion Signals
  - Source: Villahermosa — Part 3, Effort vs Result on Movements
  - Are the last 3 same-direction waves covering LESS distance each time? = EXHAUSTION
    (Shortening of Thrust — Villahermosa Part 3, Law 3 applied to waves)
  - Is there a "Change in Behavior" — the LARGEST opposite-direction bar
    in 20 periods? = FIRST WARNING of trend change
  - Binary: Either present = CAUTION for current direction
  - [CALIBRATION] 3-wave minimum, 65% ratio, 20-bar lookback are ours.
  - 📝 Hint: "If each push covers less ground, or the biggest bar suddenly
    appears on the OTHER side, the current move is running out of steam."

**Rule 1.7** [VILLAHERMOSA] Effort vs Result on Last Bar
  - Source: Villahermosa — Part 3, Law 3 (Effort vs Result on candles)
  - HIGH volume + NARROW bar = ABSORPTION (Composite Man blocking the move)
  - LOW volume + NARROW up bar = NO DEMAND (Lack of Interest)
  - LOW volume + NARROW down bar = NO SUPPLY (bullish — Lack of Interest)
  - HIGH volume + WIDE bar + close in direction = GENUINE move
  - [CALIBRATION] Percentile thresholds for HIGH/LOW/NARROW are ours.
  - 📝 Hint: "Lots of trading but price didn't move? Someone big is
    absorbing all the orders."

### C. Do the Lenses Agree? (Conviction Check)

**Rule 1.8** [CONFLUENCE] System Alignment
  - Do BB, TA, PA, and Wyckoff phase agree on direction?
  - ALL 4 agree → FULL CONVICTION — proceed with full size
  - 3 of 4 agree → HIGH CONVICTION — 75% size
  - 2 of 4 agree → MODERATE — 50% size with tight stops
  - Split or conflicting → NO TRADE or minimum size
  - 📝 Hint: "When every lens says the same thing, the odds are
    heavily in your favor. When they fight, stay small or stay out."


## 2. ENTRY RULES
## ═══════════════════════════════════════════════

### A. BUY Entries

**Rule 2.1** [CONFLUENCE — VILLAHERMOSA + BROOKS] Spring BUY (Highest Confluence)
  - Source: Villahermosa — Part 5, Event #5 (Shaking / Spring)
  - [VILLAHERMOSA] Price briefly breaks BELOW support → reverses above → LOW volume
    on the penetration = shakeout of weak holders (Composite Man buying the liquidity)
  - [VILLAHERMOSA] Spring Type Classification:
    Spring #3 (low vol, small penetration) = BEST, enter directly
    Spring #2 (moderate vol) = wait for test
    Spring #1 / Terminal Shakeout (high vol, large penetration) = must retest
  - [BROOKS] Same event = "failed breakout below range" — reversal bar
  - [VILLAHERMOSA] Trend context: Spring in Phase C of confirmed accumulation
    has highest success rate. Spring in isolation = riskier.
  - [VILLAHERMOSA] Follow-through: Check next 1-3 bars for continuation UP with
    expanding volume. After confirmed Spring, expect SOS bar (wide bullish bar,
    high volume, close near high). NO follow-through = signal disqualified.
  - Conviction: Maximum when Villahermosa (low-vol Spring #3) + Brooks (failed BO)
    fire together AND follow-through confirms.
  - 📝 Hint: "Stock dipped below its floor on light volume, bounced back,
    and the next bars confirmed by going higher. The dip was a trap."

**Rule 2.2** [BOLLINGER] Squeeze Breakout BUY
  - Conditions: Squeeze ON (BBW < threshold) + price breaks above upper BB
    + volume above SMA50
  - [CONFLUENCE with VILLAHERMOSA]: If Wyckoff phase = ACCUMULATION → Maximum
    conviction. Composite Man finished loading + volatility explodes upward.
  - 📝 Hint: "Bands were tight, now price explodes up with volume."

**Rule 2.3** [MURPHY] Moving Average Confirmation BUY
  - Conditions: Price crosses above 20 SMA + 20 SMA above 50 SMA + RSI > 50
  - [CONFLUENCE with VILLAHERMOSA]: Stronger if wave balance = DEMAND_DOMINANT
  - 📝 Hint: "All averages pointing up, price is above them. Trend is your friend."

**Rule 2.4** [VILLAHERMOSA] Absorption BUY — Composite Man Accumulating
  - Source: Villahermosa — Part 3, Effort vs Result at Key Levels;
    Part 5, Event identification within trading ranges
  - Conditions (need 2 of 3 clues):
    1. Rising supports within the trading range (higher lows forming)
    2. Heavy volume near resistance being absorbed (price doesn't fall)
    3. Bag-holding at support (heavy selling fails to break it)
  - Context: Occurs INSIDE a trading range during Phase B/C. Bullish absorption =
    demand quietly overcoming supply. Composite Man taking the other side.
  - [CALIBRATION] The 3-clue framework and specific detection logic are ours.
  - 📝 Hint: "Inside a range, the lows keep creeping higher while heavy
    selling at resistance gets absorbed. Buyers are winning quietly."

**Rule 2.5** [VILLAHERMOSA] Successful Test BUY
  - Source: Villahermosa — Part 5, Event #4 (Secondary Test)
  - Conditions: After a Spring or SC, price returns to the same zone with
    LESS volume (<75% of the reference event's volume)
  - This confirms supply has dried up — sellers are gone (No Supply condition)
  - [CALIBRATION] The 75% threshold is ours.
  - 📝 Hint: "Stock came back to its lows, but this time almost nobody
    was selling. The selling is done — time to buy."

**Rule 2.6** [VILLAHERMOSA] Sign of Strength (SOS) BUY / Jump Across the Creek
  - Source: Villahermosa — Part 5, Event #6 (Breakout / SOS / JAC)
  - Conditions: Wide spread up bar + above-average volume + close near high
    + price breaks above the Creek (AR high / range resistance)
  - Context: After Phase C Spring confirmed → Phase D begins → SOS breaks Creek
  - This is Change of Character #2 (CHoCH #2) confirming the bullish imbalance
  - [CALIBRATION] Spread/volume thresholds are ours.
  - 📝 Hint: "A big strong green bar with heavy volume jumping above
    resistance. Buyers showed their hand — the move up is REAL."

**Rule 2.7** [CONFLUENCE — ALL] Maximum Conviction BUY
  - ALL of these are simultaneously true:
    1. [BOLLINGER] Squeeze active or just broke out upward
    2. [MURPHY] TA Score > +45, momentum positive, volume confirming
    3. [BROOKS] Always-in LONG, recent pattern bullish
    4. [VILLAHERMOSA] Phase = C (Spring confirmed) or D (LPS/BUEC) or early E
    5. [VILLAHERMOSA] Wave balance = DEMAND_DOMINANT, no shortening of upward thrust
    6. [VILLAHERMOSA] No Change-in-Behavior warning (no bearish CIB)
    7. [VILLAHERMOSA] If spring present: follow-through = YES + Spring type #2/#3
  - Action: Full position size. This is the rarest, highest-probability signal.
  - 📝 Hint: "EVERY lens says BUY. This is as good as it gets."

### B. SELL / SHORT Entries

**Rule 2.8** [CONFLUENCE — VILLAHERMOSA + BROOKS] Upthrust/UTAD SELL (Highest Confluence)
  - Source: Villahermosa — Part 5, Event #5 (Shaking / UTAD)
  - [VILLAHERMOSA] Price briefly breaks ABOVE resistance → reverses below → LOW volume
    on the penetration = failed breakout, buyers trapped (Composite Man distributing)
  - [BROOKS] Same event = "failed breakout above range"
  - [VILLAHERMOSA] Trend context: UTAD in Phase C of confirmed distribution
    has highest success rate. UTAD in uptrend = riskier.
  - [VILLAHERMOSA] Follow-through: Check next 1-3 bars for continuation DOWN.
    NO follow-through = signal disqualified.
  - 📝 Hint: "Stock poked above its ceiling on light volume, fell back,
    and the next bars confirmed by heading lower. The breakout was fake."

**Rule 2.9** [BOLLINGER] Squeeze Breakout SELL
  - Conditions: Squeeze ON + price breaks below lower BB + volume above SMA50
  - [CONFLUENCE with VILLAHERMOSA]: If Wyckoff phase = DISTRIBUTION → Maximum conviction
  - 📝 Hint: "Bands were tight, now price crashes through the bottom with volume."

**Rule 2.10** [VILLAHERMOSA] Sign of Weakness (SOW) SELL / Fall Through the Ice
  - Source: Villahermosa — Part 5, Event #6 (Breakout / SOW / Major SOW)
  - Conditions: Wide spread down bar + above-average volume + close near low
    + price breaks below the Ice (AR low / range support)
  - Context: After Phase C UTAD confirmed → Phase D develops → SOW breaks Ice
  - 📝 Hint: "A big strong red bar with heavy volume falling through support.
    Sellers showed their hand."

**Rule 2.11** [VILLAHERMOSA] Absorption SELL — Composite Man Distributing
  - Mirror of Rule 2.4 (bearish version):
    1. Falling highs within the trading range (lower highs forming)
    2. Heavy volume near support being absorbed (price doesn't rise)
    3. Bag-holding at resistance (heavy buying fails to break it)
  - Context: Bearish absorption = supply quietly overcoming demand.
    The Composite Man is distributing during Phase B of distribution.
  - 📝 Hint: "Inside a range, the highs keep creeping lower while heavy
    buying at support gets absorbed. Sellers are winning quietly."


## 3. EXIT RULES
## ═══════════════════════════════════════════════

### A. Exit LONG Positions

**Rule 3.1** [CONFLUENCE — VILLAHERMOSA + BOLLINGER + BROOKS] Climax + Exhaustion Exit
  - [VILLAHERMOSA] Buying Climax: Extreme volume + wide up bar + close near LOW
    (Source: Villahermosa Part 5, Event #2). Composite Man selling into euphoria.
  - [VILLAHERMOSA] Shortening of upward thrust: Last 3 up-waves cover less distance
    (Source: Villahermosa Part 3, Law 3 on waves). Especially dangerous with INCREASING volume.
  - [VILLAHERMOSA] Change in Behavior: Largest down-bar in 20 periods appears.
    First warning the other side is waking up.
  - [BOLLINGER] SAR flips from below to above price
  - [BROOKS] Two-leg move target reached
  - Binary: ANY of these fires = Begin exit. TWO or more = EXIT NOW.
  - [CALIBRATION] "Extreme" = 3× avg volume, "wide" = top 20% spread.
  - 📝 Hint: "The rally is showing fatigue — buyer climax, shrinking
    pushes, or a monster red bar. One warning = tighten stops.
    Two warnings = get out."

**Rule 3.2** [VILLAHERMOSA] Distribution Phase Transition Exit
  - Source: Villahermosa — Part 4 (Distribution Process), Part 6 (Phase transitions)
  - Condition: Phase shifts from MARKUP to DISTRIBUTION (Phase A events appearing)
  - [VILLAHERMOSA] If absorption detected (Rule 2.11 — bearish version) within the
    range, Composite Man is distributing. Exit urgency increases.
  - [VILLAHERMOSA] Look for PSY + BC + AR + ST sequence = Phase A of distribution.
  - Action: Tighten stops, scale out. No new longs.
  - 📝 Hint: "Composite Man stopped pushing up and started selling. Protect profits."

**Rule 3.3** [BOLLINGER] Lower Band Tag After Uptrend
  - Condition: Price was riding upper band, now touches lower band
  - 📝 Hint: "Price dropped from the top band to the bottom. Uptrend is broken."

**Rule 3.4** [MURPHY] Triple System Flip Exit
  - Condition: Triple Engine verdict changes from BUY to HOLD or SELL
  - 📝 Hint: "The combined system changed its mind. Listen."

### B. Exit SHORT Positions

**Rule 3.5** [VILLAHERMOSA] Selling Climax Exit (Cover Short)
  - Source: Villahermosa — Part 5, Event #2 (Selling Climax)
  - Condition: Extreme volume + wide down bar + close near HIGH
  - Composite Man buying the panic — Phase A of new accumulation beginning
  - 📝 Hint: "Panicked selling but price closed at the top. The Composite Man bought the fear."

**Rule 3.6** [VILLAHERMOSA] Shortening of Downward Thrust + Accumulation Transition
  - Condition: Last 3 down-waves cover less distance each time
    OR phase shifts from MARKDOWN to ACCUMULATION (Phase A events appearing)
  - [VILLAHERMOSA] If bullish absorption detected (Rule 2.4) within the new range,
    Composite Man is accumulating. Cover urgency increases.
  - Action: Cover shorts. No new short positions.
  - 📝 Hint: "Each drop is smaller, or the Composite Man started buying. The decline is ending."


## 4. WYCKOFF PHASE IDENTIFICATION
## ═══════════════════════════════════════════════

How to identify which phase the stock is in.
[VILLAHERMOSA] Phase names (A-E) follow Villahermosa's explicit framework.

**Rule 4.1** [VILLAHERMOSA] ACCUMULATION — Composite Man Buying
  - Source: Villahermosa — Part 4 (Accumulation Process), Part 6 (Phases A-E)
  - Prior context: Significant decline before entering a trading range
  - Phase A: PS → SC → AR → ST (stopping the trend)
  - Phase B: Multiple tests at range extremes, volume decreasing (building cause)
  - Phase C: Spring / Shakeout (the test — trapping weak holders)
  - Phase D: SOS / JAC (breakout above Creek) → LPS / BUEC (confirmation)
  - Phase E: Uptrend begins (SOS impulses + LPS corrections)
  - Volume evidence:
    - [VILLAHERMOSA] Down-wave volume DECREASING (sellers exhausted — No Supply)
    - [VILLAHERMOSA] Up-wave volume INCREASING (buyers appearing — Initiative Buying)
    - [VILLAHERMOSA] Overall range volume PROGRESSIVELY DECREASING (absorption)
  - Schematic #1: With Spring (breaks below SC low) = textbook
  - Schematic #2: Without Spring (higher low in Phase C) = background strength
  - [CALIBRATION] Our range detection (40-bar windows, 5% prior-trend)
    quantifies Villahermosa's visual judgment.
  - 📝 Hint: "After a big drop, stock goes sideways. Volume quiets on drops,
    grows on rallies. The Composite Man is loading up."

**Rule 4.2** [VILLAHERMOSA] MARKUP — The Uptrend (Phase E of Accumulation)
  - Source: Villahermosa — Part 6, Phase E; Part 3, Law 3 on movements
  - Structure: Higher highs AND higher lows (staircase up)
  - Volume: Expands on impulses (SOS), contracts on corrections (LPS)
  - [MURPHY] Price above 20 and 50 SMA
  - Sub-phases:

  **EARLY:** Phase D just confirmed, LPS/BUEC held, first SOS impulse.
  → Watch for expanding volume on impulse. High volume = real. Flat = cautious.

  **CONFIRMED:** Clear uptrend with successive SOS + LPS pattern.
  → LPS on LOW volume = buying opportunities. LPS on HIGH volume = warning.

  **LATE:** Watch for exhaustion (Villahermosa Part 3):
  1. Shortening of thrust (each SOS impulse covers less distance)
  2. Buying Climax (extreme volume, wide bar, close near low)
  3. Change in Behavior (largest down-bar in 20 periods)
  4. Phase A events of a new structure beginning to appear (PSY + BC)
  → DO NOT add new buys. Tighten stops.

  📝 Hint: "During a healthy uptrend, PULLBACKS tell the truth. Quiet
  pullbacks (LPS) = healthy. Loud pullbacks = trouble ahead."

**Rule 4.3** [VILLAHERMOSA] DISTRIBUTION — Composite Man Selling
  - Source: Villahermosa — Part 4 (Distribution Process), Part 6 (Phases A-E)
  - Prior context: Significant advance before entering a trading range
  - Phase A: PSY → BC → AR → ST (stopping the trend)
  - Phase B: Multiple tests, volume remains HIGH and VOLATILE (urgency)
  - Phase C: UTAD (the test — trapping breakout buyers)
  - Phase D: SOW (breakdown below Ice) → LPSY / FTI (confirmation)
  - Phase E: Downtrend begins (SOW impulses + LPSY corrections)
  - Volume evidence:
    - [VILLAHERMOSA] Up-wave volume DECREASING (buyers exhausted)
    - [VILLAHERMOSA] Down-wave volume INCREASING (sellers appearing)
    - [VILLAHERMOSA] Overall range volume PERSISTENTLY HIGH (urgency to distribute)
  - Schematic #1: With UTAD (breaks above BC high) = textbook
  - Schematic #2: Without UTAD (lower high in Phase C) = background weakness
  - 📝 Hint: "After a big rally, stock goes sideways. Volume stays high and
    volatile. The Composite Man is unloading positions."

**Rule 4.4** [VILLAHERMOSA] MARKDOWN — The Downtrend (Phase E of Distribution)
  - Source: Villahermosa — Part 6, Phase E; Part 3, Law 3
  - Lower highs AND lower lows
  - Volume expands on declines (SOW impulses), contracts on rallies (LPSY corrections)
  - [VILLAHERMOSA] Rallies on low volume = LPSY (selling opportunities)
  - [VILLAHERMOSA] Look for minor redistribution structures within the trend
  - [MURPHY] Price below moving averages
  - 📝 Hint: "Stock is falling steadily. Each bounce is weaker (LPSY). Avoid or sell."


## 5. VOLUME READING RULES
## ═══════════════════════════════════════════════

How to read volume — the INTENT behind price moves.

**Rule 5.1** [VILLAHERMOSA] The Master Principle: Effort vs Result (Law 3)
  - Source: Villahermosa — Part 3, Law of Effort vs Result
  - Volume = EFFORT. Price movement = RESULT. Read them TOGETHER:
  - HIGH effort + HIGH result = GENUINE move (Harmony) [MURPHY confirms: volume with trend]
  - HIGH effort + LOW result = ABSORPTION — Composite Man blocking the move
    [BOLLINGER: often occurs at band edges]
  - LOW effort + HIGH result = EASE OF MOVEMENT — no opposition, path clear
  - LOW effort + LOW result = NO INTEREST — skip this bar
  - 📝 Hint: "Volume = how hard. Price = how far. If it worked hard but
    went nowhere, the Composite Man is blocking the move."

**Rule 5.2** [VILLAHERMOSA] Demand/Supply Bars
  - Source: Villahermosa — Part 3, Law 1 (Supply and Demand); Part 5, Event #4
  - NO DEMAND: Up bar + LOW volume + NARROW spread → nobody wants to buy
    In uptrend: warning the rally may fail (Lack of Interest — bullish side)
  - NO SUPPLY: Down bar + LOW volume + NARROW spread → nobody wants to sell
    In downtrend: hint the decline may end (Lack of Interest — bearish side)
  - [BROOKS also teaches]: Narrow range bars after a move = loss of momentum
  - 📝 Hint: "Tiny bar, no volume? Nobody cares about this direction."

**Rule 5.3** [VILLAHERMOSA] Absorption — Effort vs Result at Key Levels
  - Source: Villahermosa — Part 3, Law 3 at key levels; Part 5, absorption within ranges
  - HIGH volume but NARROW spread (price blocked despite heavy effort)
  - In a decline: Composite Man BUYING all the selling → Bullish
  - In an advance: Composite Man SELLING all the buying → Bearish
  - [VILLAHERMOSA] Three clues for pattern-level absorption (within a range):
    1. Rising supports (higher lows) or falling highs (lower highs)
    2. Heavy volume at a boundary being absorbed (price doesn't break)
    3. Bag-holding: heavy selling/buying at a level that fails to move price
  - Needs 2 of 3 clues to confirm
  - 📝 Hint: "Massive trading but price didn't budge. A giant sponge is
    soaking up all the supply (or demand)."

**Rule 5.4** [VILLAHERMOSA] Climax Volume — The Turning Point
  - Source: Villahermosa — Part 5, Event #2 (Climax)
  - BUYING CLIMAX: Extreme vol + wide up bar + close near LOW
    → Composite Man selling into euphoria → EXIT longs
  - SELLING CLIMAX: Extreme vol + wide down bar + close near HIGH
    → Composite Man buying into panic → Cover shorts
  - [VILLAHERMOSA] The CLOSE within the bar reveals initiative vs responsive:
    Close in top = buyers initiated / Close in bottom = sellers initiated
  - [CALIBRATION] "Extreme" = 3× avg volume, "wide" = top 20% spread.
  - 📝 Hint: "Dramatic bar, highest volume in weeks. The CLOSE tells you
    who really won the fight."

**Rule 5.5** [CONFLUENCE — VILLAHERMOSA + BOLLINGER] Volume Dry-Up = Imminent Move
  - [VILLAHERMOSA] Volume drops to < 50% of average, tiny range.
    Source: Part 3, Lack of Interest condition — no initiative from either side.
  - [BOLLINGER] If BBW also near minimum → maximum compression
  - A big move is coming. Direction from Phase (Rule 1.1) + Trend (Rule 1.1).
  - 📝 Hint: "Zero volume + tight bands = calm before the storm.
    Use Wyckoff phase to guess which way the storm blows."

**Rule 5.6** [VILLAHERMOSA] Wave Volume + Duration — The Complete Picture
  - Source: Villahermosa — Part 3, Effort vs Result on Waves
  - Compare recent waves in three dimensions:
    1. VOLUME: Sum up-wave vol vs down-wave vol (who has more effort?)
    2. DISTANCE: Is distance per wave shrinking? = Shortening of Thrust
    3. DURATION: Which side's waves last longer? (patient side has conviction)
  - [VILLAHERMOSA] Impulsive vs Corrective: impulsive movements have wider ranges
    + expanding volume. Corrective movements have narrower ranges + contracting volume.
    If corrective movement shows wide ranges + high volume = Change of Character.
  - [CALIBRATION] 1.5× ratio, 1.3× duration ratio thresholds are ours.
  - 📝 Hint: "Volume shows effort, distance shows progress, duration shows
    patience. The side with more of all three is winning."


## 6. CONFLICT RESOLUTION
## ═══════════════════════════════════════════════

When lenses disagree, these rules break the tie.

**Rule 6.1** [CONFLUENCE] Phase + Volume > Short-Term Indicators
  - If [VILLAHERMOSA] phase = DISTRIBUTION but [MURPHY] RSI says BUY → Trust phase
  - If [VILLAHERMOSA] wave balance = SUPPLY_DOMINANT but [BOLLINGER] says squeeze up
    → Trust wave balance for direction, Bollinger for timing
  - Reason: Phase and volume reflect weeks of behavior. Oscillators reflect hours.
  - [INFERRED] This priority hierarchy is our design decision.
  - 📝 Hint: "Big-picture volume story beats short-term indicators."

**Rule 6.2** [CONFLUENCE] Bar Reading > Moving Averages
  - If [BROOKS] strong reversal bar at key level but MAs point the other way
    → Trust PA for entry, use MA for position sizing
  - If [VILLAHERMOSA] effort vs result shows absorption at a level but MAs say trend
    continues → Absorption is the leading indicator
  - 📝 Hint: "What's happening NOW (bars, volume) beats what HAPPENED (averages)."

**Rule 6.3** [CONFLUENCE] Bollinger Squeeze + Villahermosa Phase = Timing System
  - Squeeze tells you WHEN (imminent breakout)
  - Phase tells you WHICH WAY (accumulation Phase C/D = up, distribution Phase C/D = down)
  - [BROOKS] Always-in direction confirms or denies
  - All three agree → Maximum timing conviction
  - 📝 Hint: "Squeeze says 'soon.' Phase says 'which way.' PA confirms."

**Rule 6.4** [CONFLUENCE] Spring/Upthrust WITH Follow-Through > All
  - [VILLAHERMOSA] A Spring or UTAD is a high-probability Phase C event.
    The Composite Man is capturing liquidity before the trend move.
  - BUT only if follow-through confirms in the next 1-3 bars
  - If follow-through = YES → Act on the Spring/UTAD even if other
    lenses are neutral. This is the single strongest event signal.
  - If follow-through = NO → Signal disqualified regardless of other lenses
  - [VILLAHERMOSA] Spring #3 (low volume) has best immediate follow-through.
    Spring #1 (terminal shakeout) requires patience and retesting.
  - [INFERRED] "Takes priority" is our hierarchy.
  - 📝 Hint: "A confirmed spring or upthrust is the strongest single signal.
    But confirmation (follow-through) is non-negotiable."

**Rule 6.5** [CONFLUENCE] Change-in-Behavior as Early Warning Override
  - [VILLAHERMOSA] If a Change-in-Behavior bar appears (largest opposite-direction
    bar in 20 periods), treat it as an override on momentum signals.
    This is the first Change of Character (CHoCH) — Villahermosa Part 5.
  - A bullish CIB in a downtrend overrides bearish momentum (early reversal)
  - A bearish CIB in an uptrend overrides bullish momentum (early warning)
  - Action: Don't EXIT on CIB alone, but do REDUCE size and tighten stops
  - 📝 Hint: "When the biggest bar of the month suddenly appears on the
    OTHER side, the current trend is about to change. Don't ignore it."

**Rule 6.6** [CONFLUENCE] Conflicting Lenses = Reduce or Skip
  - 2 lenses BUY, 2 lenses SELL → NO TRADE
  - 3 lenses agree, 1 disagrees → 75% size, normal stops
  - All 4 agree → Full size, widest stops
  - 📝 Hint: "Don't bet big on a confused market."

**Rule 6.7** [CONFLUENCE] Volume Is the Lie Detector
  - When in doubt about ANY signal from any lens, check volume:
  - Signal + high volume = REAL (Initiative activity)
  - Signal + low volume = SUSPICIOUS (Lack of Interest)
  - [VILLAHERMOSA] This is the through-line of the entire Villahermosa/Wyckoff method:
    volume reveals intent. Law 3 (Effort vs Result) is the universal validation.
  - 📝 Hint: "Volume is the closest thing to truth in the market."


## SCORING INTEGRATION
## ═══════════════════════════════════════════════
##
## BB Score:    -100 to +100  (4 Bollinger Methods)     [BOLLINGER]
## TA Score:    -100 to +100  (6 Murphy Categories)     [MURPHY]
## PA Score:    -100 to +100  (8 Brooks Components)     [BROOKS]
## Cross-Val:    -90 to  +90  (Agreement + Wyckoff)     [CONFLUENCE]
##   └─ Base agreement:  -60 to +60
##   └─ Wyckoff context: -30 to +30                     [VILLAHERMOSA]
##     └─ Phase bias:        ±8
##     └─ Events (SP/UT/SC/BC/SOS/SOW): ±6 each
##     └─ Absorption:        ±5
##     └─ Change-in-Behavior: ±4
##     └─ Wave balance:      ±3
##     └─ Shortening/SOT:    ±2
##     └─ Follow-through:    quality modifier on events
##     └─ Creek/Ice position: ±2
##     └─ Failed structure:   ∓6 (penalty when detected)
##
## TOTAL:      -390 to +390
##
## The 3 core scores (BB, TA, PA) are NEVER modified by Wyckoff.
## Wyckoff operates ONLY in the cross-validation layer, adding
## context that strengthens or weakens the combined signal.
##
## Source: Rubén Villahermosa, "The Wyckoff Methodology in Depth"
##   - 3 Laws (Supply/Demand, Cause/Effect, Effort/Result)
##   - 7 Events (PS, Climax, Reaction, Test, Shaking, Breakout, Confirmation)
##   - 5 Phases (A-E) with explicit functions
##   - 4 Schematics (Acc #1/#2, Dist #1/#2)
##   - 3 Trading Zones (Phase C, Phase D, Phase E)
##   - Creek/Ice/BUEC concepts for confirmation levels
##   - Spring type classification (#1/#2/#3) by volume
##   - Re-accumulation vs Distribution distinction
##   - Failed structure detection and handling
