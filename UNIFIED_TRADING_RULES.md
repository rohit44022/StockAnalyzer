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
#   [WEIS]        — Volume-price behavior / Wyckoff method (intent)
#   [CONFLUENCE]  — Where 2+ lenses converge (conviction)
#
# HONESTY NOTE ON [WEIS] RULES:
# ──────────────────────────────
# Weis teaches QUALITATIVE bar-by-bar reading. He gives no numeric
# thresholds, no scoring systems, and no binary rules. Every [WEIS]
# rule below captures his CONCEPT and DIRECTION accurately. The
# binary format, thresholds, and scoring are [CALIBRATION] — our
# quantification of his teaching for algorithmic use.
#
# Phase names (ACCUMULATION, MARKUP, etc.) and event labels (SOS, SOW)
# are [POST-WYCKOFF] course terminology. Weis explicitly notes these
# were "added after Wyckoff's death." We use them for convenience.
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

**Rule 1.1** [CONFLUENCE — WEIS + MURPHY] Identify Phase AND Trend
  - Step 1 [WEIS]: Name the Wyckoff phase — ACCUMULATION, MARKUP,
    DISTRIBUTION, or MARKDOWN. Source: Weis Ch. 1-11 (four-phase cycle).
    [POST-WYCKOFF] These names are post-Wyckoff course terminology.
  - Step 2 [MURPHY]: Confirm with 50-SMA — Above = BULLISH, Below = BEARISH
  - Binary: Phase + Trend agree = GREEN. Phase and trend disagree = CAUTION.
  - If ACCUMULATION or MARKUP → Only BUY setups
  - If DISTRIBUTION or MARKDOWN → Only SELL/EXIT setups
  - 📝 Hint: "First name the phase (smart money buying or selling?),
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

**Rule 1.4** [WEIS] Read the Volume Character
  - Source: Weis — Ch. 4 (bar reading), Ch. 8 (chart studies)
  - Classify current volume: CLIMAX / SPIKE / ABOVE_AVG / NORMAL / DRYUP
  - Classify volume trend (10 bars): INCREASING / DECREASING / FLAT
  - [CALIBRATION] The 5-category system is our taxonomy.
  - 📝 Hint: "Is the stock getting lots of attention or being ignored?"

**Rule 1.5** [CONFLUENCE — WEIS + MURPHY] Volume Confirms Price?
  - [WEIS] Compare wave volumes (Ch. 9-10): up-wave vol vs down-wave vol
    DEMAND_DOMINANT (ratio > 1.5×) = Bullish / SUPPLY_DOMINANT (< 0.67×) = Bearish
  - [WEIS] Compare wave durations: up-wave bars vs down-wave bars
    Patient side (longer waves) has conviction
  - [MURPHY] On the last move: did volume expand with price? YES = Confirmed
  - Binary: Volume supports the trend = GREEN / Volume diverges = WARNING
  - [CALIBRATION] The 1.5× ratio threshold is ours. Weis compares visually.
  - 📝 Hint: "Add up volume on up-days vs down-days. The side with more
    volume AND more persistent waves is winning."

**Rule 1.6** [WEIS] Check for Exhaustion Signals
  - Source: Weis — Ch. 4 ("Shortening of the Thrust"), Ch. 9-10 (waves)
  - Are the last 3 same-direction waves covering LESS distance each time? = EXHAUSTION
  - Is there a "Change in Behavior" — the LARGEST opposite-direction bar
    in 20 periods? = FIRST WARNING of trend change (Weis Ch. 4)
  - Binary: Either present = CAUTION for current direction
  - [CALIBRATION] 3-wave minimum, 65% ratio, 20-bar lookback are ours.
  - 📝 Hint: "If each push covers less ground, or the biggest bar suddenly
    appears on the OTHER side, the current move is running out of steam."

**Rule 1.7** [WEIS] Effort vs Result on Last Bar
  - Source: Weis — Ch. 4, the CENTRAL principle
  - HIGH volume + NARROW bar = ABSORPTION (smart money blocking the move)
  - LOW volume + NARROW up bar = NO DEMAND
  - LOW volume + NARROW down bar = NO SUPPLY (bullish)
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

**Rule 2.1** [CONFLUENCE — WEIS + BROOKS] Spring BUY (Highest Confluence)
  - Source: Weis — Ch. 5 ("The Spring" / "Shakeout")
  - [WEIS] Price briefly breaks BELOW support → reverses above → LOW volume
    on the penetration = shakeout of weak holders
  - [BROOKS] Same event = "failed breakout below range" — reversal bar
  - [WEIS] Trend context: Spring in an UPTREND has highest success rate
    (Ch. 5). Spring in downtrend = riskier, needs stronger follow-through.
  - [WEIS] Follow-through: Check next 1-3 bars for continuation UP with
    expanding volume. "Follow-through is the deciding factor" (Ch. 1).
    NO follow-through = signal disqualified, do NOT enter.
  - Conviction: Maximum when both Weis (low-vol spring) + Brooks (failed BO)
    fire together AND follow-through confirms.
  - 📝 Hint: "Stock dipped below its floor on light volume, bounced back,
    and the next bars confirmed by going higher. The dip was a trap."

**Rule 2.2** [BOLLINGER] Squeeze Breakout BUY
  - Conditions: Squeeze ON (BBW < threshold) + price breaks above upper BB
    + volume above SMA50
  - [CONFLUENCE with WEIS]: If Wyckoff phase = ACCUMULATION → Maximum
    conviction. Smart money finished loading + volatility explodes upward.
  - 📝 Hint: "Bands were tight, now price explodes up with volume."

**Rule 2.3** [MURPHY] Moving Average Confirmation BUY
  - Conditions: Price crosses above 20 SMA + 20 SMA above 50 SMA + RSI > 50
  - [CONFLUENCE with WEIS]: Stronger if wave balance = DEMAND_DOMINANT
  - 📝 Hint: "All averages pointing up, price is above them. Trend is your friend."

**Rule 2.4** [WEIS] Absorption BUY — Smart Money Accumulating
  - Source: Weis — Ch. 5 (one of three core patterns: spring, upthrust, absorption)
  - Conditions (need 2 of 3 clues):
    1. Rising supports within the trading range (higher lows forming)
    2. Heavy volume near resistance being absorbed (price doesn't fall)
    3. Bag-holding at support (heavy selling fails to break it)
  - Context: Occurs INSIDE a trading range. Bullish absorption = demand
    quietly overcoming supply. Smart money taking the other side.
  - [CALIBRATION] The 3-clue framework and specific detection logic are ours.
  - 📝 Hint: "Inside a range, the lows keep creeping higher while heavy
    selling at resistance gets absorbed. Buyers are winning quietly."

**Rule 2.5** [WEIS] Successful Test BUY
  - Source: Weis — Ch. 5 ("The Test" / "Secondary Test")
  - Conditions: After a Spring or SC, price returns to the same zone with
    LESS volume (<75% of the reference event's volume)
  - This confirms supply has dried up — sellers are gone
  - [CALIBRATION] The 75% threshold is ours.
  - 📝 Hint: "Stock came back to its lows, but this time almost nobody
    was selling. The selling is done — time to buy."

**Rule 2.6** [POST-WYCKOFF] Sign of Strength (SOS) BUY
  - Source: Post-Wyckoff course terminology. Weis describes the behavior
    (wide up bar, heavy volume, close near high) but uses different language.
  - Conditions: Wide spread up bar + above-average volume + close near high
  - Context: After Accumulation → Signals start of Markup
  - [CALIBRATION] Spread/volume thresholds are ours.
  - 📝 Hint: "A big strong green bar with heavy volume. Buyers showed
    their hand — the move up is REAL."

**Rule 2.7** [CONFLUENCE — ALL] Maximum Conviction BUY
  - ALL of these are simultaneously true:
    1. [BOLLINGER] Squeeze active or just broke out upward
    2. [MURPHY] TA Score > +45, momentum positive, volume confirming
    3. [BROOKS] Always-in LONG, recent pattern bullish
    4. [WEIS] Phase = ACCUMULATION (late) or early MARKUP
    5. [WEIS] Wave balance = DEMAND_DOMINANT, no shortening of upward thrust
    6. [WEIS] No Change-in-Behavior warning (no bearish CIB)
    7. [WEIS] If spring/upthrust present: follow-through = YES
  - Action: Full position size. This is the rarest, highest-probability signal.
  - 📝 Hint: "EVERY lens says BUY. This is as good as it gets."

### B. SELL / SHORT Entries

**Rule 2.8** [CONFLUENCE — WEIS + BROOKS] Upthrust SELL (Highest Confluence)
  - Source: Weis — Ch. 6 ("The Upthrust")
  - [WEIS] Price briefly breaks ABOVE resistance → reverses below → LOW volume
    on the penetration = failed breakout, buyers trapped
  - [BROOKS] Same event = "failed breakout above range"
  - [WEIS] Trend context: Upthrust in a DOWNTREND has highest success rate
    (Ch. 6). Upthrust in uptrend = riskier.
  - [WEIS] Follow-through: Check next 1-3 bars for continuation DOWN.
    NO follow-through = signal disqualified.
  - 📝 Hint: "Stock poked above its ceiling on light volume, fell back,
    and the next bars confirmed by heading lower. The breakout was fake."

**Rule 2.9** [BOLLINGER] Squeeze Breakout SELL
  - Conditions: Squeeze ON + price breaks below lower BB + volume above SMA50
  - [CONFLUENCE with WEIS]: If Wyckoff phase = DISTRIBUTION → Maximum conviction
  - 📝 Hint: "Bands were tight, now price crashes through the bottom with volume."

**Rule 2.10** [POST-WYCKOFF] Sign of Weakness (SOW) SELL
  - Source: Post-Wyckoff course terminology. Weis describes the behavior
    (wide down bar, heavy volume, close near low) but uses different language.
  - Conditions: Wide spread down bar + above-average volume + close near low
  - Context: After Distribution → Signals start of Markdown
  - 📝 Hint: "A big strong red bar with heavy volume. Sellers showed their hand."

**Rule 2.11** [WEIS] Absorption SELL — Smart Money Distributing
  - Mirror of Rule 2.4 (bearish version):
    1. Falling highs within the trading range (lower highs forming)
    2. Heavy volume near support being absorbed (price doesn't rise)
    3. Bag-holding at resistance (heavy buying fails to break it)
  - Context: Bearish absorption = supply quietly overcoming demand.
  - 📝 Hint: "Inside a range, the highs keep creeping lower while heavy
    buying at support gets absorbed. Sellers are winning quietly."


## 3. EXIT RULES
## ═══════════════════════════════════════════════

### A. Exit LONG Positions

**Rule 3.1** [CONFLUENCE — WEIS + BOLLINGER + BROOKS] Climax + Exhaustion Exit
  - [WEIS] Buying Climax: Extreme volume + wide up bar + close near LOW
    (Source: Weis Ch. 4, Ch. 8). Smart money selling into euphoria.
  - [WEIS] Shortening of upward thrust: Last 3 up-waves cover less distance
    (Source: Weis Ch. 4). Especially dangerous with INCREASING volume.
  - [WEIS] Change in Behavior: Largest down-bar in 20 periods appears.
    First warning the other side is waking up (Weis Ch. 4).
  - [BOLLINGER] SAR flips from below to above price
  - [BROOKS] Two-leg move target reached
  - Binary: ANY of these fires = Begin exit. TWO or more = EXIT NOW.
  - [CALIBRATION] "Extreme" = 3× avg volume, "wide" = top 20% spread.
  - 📝 Hint: "The rally is showing fatigue — buyer climax, shrinking
    pushes, or a monster red bar. One warning = tighten stops.
    Two warnings = get out."

**Rule 3.2** [WEIS] Distribution Phase Transition Exit
  - Source: Weis Ch. 7-8 (transition from Markup to Distribution)
  - Condition: Phase shifts from MARKUP to DISTRIBUTION
  - [WEIS] If absorption detected (Rule 2.11 — bearish version) within the
    range, suppliers are gaining control. Exit urgency increases.
  - Action: Tighten stops, scale out. No new longs.
  - 📝 Hint: "Smart money stopped pushing up and started selling. Protect profits."

**Rule 3.3** [BOLLINGER] Lower Band Tag After Uptrend
  - Condition: Price was riding upper band, now touches lower band
  - 📝 Hint: "Price dropped from the top band to the bottom. Uptrend is broken."

**Rule 3.4** [MURPHY] Triple System Flip Exit
  - Condition: Triple Engine verdict changes from BUY to HOLD or SELL
  - 📝 Hint: "The combined system changed its mind. Listen."

### B. Exit SHORT Positions

**Rule 3.5** [WEIS] Selling Climax Exit (Cover Short)
  - Source: Weis Ch. 4 (bar reading), Ch. 8 (chart studies)
  - Condition: Extreme volume + wide down bar + close near HIGH
  - Smart money buying the panic
  - 📝 Hint: "Panicked selling but price closed at the top. Someone big bought the fear."

**Rule 3.6** [WEIS] Shortening of Downward Thrust + Accumulation Transition
  - Condition: Last 3 down-waves cover less distance each time
    OR phase shifts from MARKDOWN to ACCUMULATION
  - [WEIS] If bullish absorption detected (Rule 2.4) within the new range,
    demand is accumulating. Cover urgency increases.
  - Action: Cover shorts. No new short positions.
  - 📝 Hint: "Each drop is smaller, or smart money started buying. The decline is ending."


## 4. WYCKOFF PHASE IDENTIFICATION
## ═══════════════════════════════════════════════

How to identify which phase the stock is in.
[POST-WYCKOFF] Phase names are course terminology, not Weis/Wyckoff originals.

**Rule 4.1** [WEIS] ACCUMULATION — Smart Money Buying
  - Source: Weis Ch. 5 (springs), Ch. 8 (chart studies)
  - Prior context: Significant decline before entering a trading range
  - Volume evidence:
    - [WEIS] Down-wave volume DECREASING (sellers exhausted)
    - [WEIS] Up-wave volume INCREASING (buyers appearing)
    - [WEIS] Down-wave duration SHORTENING (selling pressure fading)
  - Key events: Selling Climax (SC) → Spring → Test → Absorption → SOS
  - [WEIS] "Dynamics not geometry" (Ch. 1) — don't look for cookie-cutter
    patterns. Read the behavior: is supply drying up? Is demand growing?
  - [CALIBRATION] Our range detection (40-bar windows, 5% prior-trend)
    quantifies Weis's visual judgment.
  - 📝 Hint: "After a big drop, stock goes sideways. Volume quiets on drops,
    grows on rallies. Smart money is loading up."

**Rule 4.2** [WEIS] MARKUP — The Uptrend
  - Source: Weis Ch. 5-8, markup characteristics
  - Structure: Higher highs AND higher lows (staircase up)
  - Volume: Expands on rallies, contracts on pullbacks
  - [MURPHY] Price above 20 and 50 SMA
  - [INFERRED] Sub-phases (EARLY/MIDDLE/CONFIRMED/LATE) are our formalization:

  **EARLY:** Staircase forming, volume not yet confirming.
  → Watch next rally's volume. High volume = real. Flat = cautious.

  **CONFIRMED:** Clear uptrend with volume confirmation.
  → Dips on LOW volume = LPS (buying opportunities). Dips on HIGH volume = warning.

  **LATE:** Watch for exhaustion:
  1. Shortening of thrust (each rally shorter)
  2. Buying Climax (extreme volume, wide bar, close near low)
  3. Change in Behavior (largest down-bar in 20 periods)
  4. Declining volume on rallies
  → DO NOT add new buys. Tighten stops.

  📝 Hint: "During a healthy uptrend, PULLBACKS tell the truth. Quiet
  pullbacks = healthy. Loud pullbacks = trouble ahead."

**Rule 4.3** [WEIS] DISTRIBUTION — Smart Money Selling
  - Source: Weis Ch. 6 (upthrusts), Ch. 8 (chart studies)
  - Prior context: Significant advance before entering a trading range
  - Volume evidence:
    - [WEIS] Up-wave volume DECREASING (buyers exhausted)
    - [WEIS] Down-wave volume INCREASING (sellers appearing)
    - [WEIS] Up-wave duration SHORTENING (buying pressure fading)
  - Key events: Buying Climax (BC) → Upthrust → Absorption (bearish) → SOW
  - 📝 Hint: "After a big rally, stock goes sideways. Volume quiets on
    rallies, grows on drops. Smart money is unloading."

**Rule 4.4** [WEIS] MARKDOWN — The Downtrend
  - Source: Weis Ch. 8-9, markdown characteristics
  - Lower highs AND lower lows
  - Volume expands on declines, contracts on rallies
  - [WEIS] Rallies on low volume = LPSY (selling opportunities)
  - [MURPHY] Price below moving averages
  - 📝 Hint: "Stock is falling steadily. Each bounce is weaker. Avoid or sell."


## 5. VOLUME READING RULES
## ═══════════════════════════════════════════════

How to read volume — the INTENT behind price moves.

**Rule 5.1** [WEIS] The Master Principle: Effort vs Result
  - Source: Weis Ch. 4 — this is the CENTRAL teaching of the entire book
  - Volume = EFFORT. Price movement = RESULT. Read them TOGETHER:
  - HIGH effort + HIGH result = GENUINE move [MURPHY confirms: volume with trend]
  - HIGH effort + LOW result = ABSORPTION — smart money blocking the move
    [BOLLINGER: often occurs at band edges]
  - LOW effort + HIGH result = NO OPPOSITION — path of least resistance
  - LOW effort + LOW result = NO INTEREST — skip this bar
  - 📝 Hint: "Volume = how hard. Price = how far. If it worked hard but
    went nowhere, someone big is blocking the move."

**Rule 5.2** [WEIS] Demand/Supply Bars
  - Source: Weis Ch. 4
  - NO DEMAND: Up bar + LOW volume + NARROW spread → nobody wants to buy
    In uptrend: warning the rally may fail
  - NO SUPPLY: Down bar + LOW volume + NARROW spread → nobody wants to sell
    In downtrend: hint the decline may end
  - [BROOKS also teaches]: Narrow range bars after a move = loss of momentum
  - 📝 Hint: "Tiny bar, no volume? Nobody cares about this direction."

**Rule 5.3** [WEIS] Absorption — One of the Three Core Patterns
  - Source: Weis Ch. 5 — alongside springs and upthrusts
  - HIGH volume but NARROW spread (price blocked despite heavy effort)
  - In a decline: Smart money BUYING all the selling → Bullish
  - In an advance: Smart money SELLING all the buying → Bearish
  - [WEIS] Three clues for pattern-level absorption (within a range):
    1. Rising supports (higher lows) or falling highs (lower highs)
    2. Heavy volume at a boundary being absorbed (price doesn't break)
    3. Bag-holding: heavy selling/buying at a level that fails to move price
  - Needs 2 of 3 clues to confirm
  - 📝 Hint: "Massive trading but price didn't budge. A giant sponge is
    soaking up all the supply (or demand)."

**Rule 5.4** [WEIS] Climax Volume — The Turning Point
  - Source: Weis Ch. 4, Ch. 8
  - BUYING CLIMAX: Extreme vol + wide up bar + close near LOW
    → Smart money selling into euphoria → EXIT longs
  - SELLING CLIMAX: Extreme vol + wide down bar + close near HIGH
    → Smart money buying into panic → Cover shorts
  - [WEIS] The CLOSE within the bar tells you who won:
    "Consider the meaning of the close within the range" (Core Principle #3)
  - [CALIBRATION] "Extreme" = 3× avg volume, "wide" = top 20% spread.
  - 📝 Hint: "Dramatic bar, highest volume in weeks. The CLOSE tells you
    who really won the fight."

**Rule 5.5** [CONFLUENCE — WEIS + BOLLINGER] Volume Dry-Up = Imminent Move
  - [WEIS] Volume drops to < 50% of average, tiny range. Source: Ch. 4
  - [BOLLINGER] If BBW also near minimum → maximum compression
  - A big move is coming. Direction from Phase (Rule 1.1) + Trend (Rule 1.1).
  - 📝 Hint: "Zero volume + tight bands = calm before the storm.
    Use Wyckoff phase to guess which way the storm blows."

**Rule 5.6** [WEIS] Wave Volume + Duration — The Complete Picture
  - Source: Weis Ch. 9-10 (Weis Wave)
  - Compare recent waves in three dimensions:
    1. VOLUME: Sum up-wave vol vs down-wave vol (who has more effort?)
    2. DISTANCE: Is distance per wave shrinking? = Shortening of Thrust
    3. DURATION: Which side's waves last longer? (patient side has conviction)
  - [WEIS] "A flat wave accompanied by heavy volume is the personification
    of weakness" — high effort, zero price progress, extended duration.
  - [CALIBRATION] 1.5× ratio, 1.3× duration ratio thresholds are ours.
  - 📝 Hint: "Volume shows effort, distance shows progress, duration shows
    patience. The side with more of all three is winning."


## 6. CONFLICT RESOLUTION
## ═══════════════════════════════════════════════

When lenses disagree, these rules break the tie.

**Rule 6.1** [CONFLUENCE] Phase + Volume > Short-Term Indicators
  - If [WEIS] phase = DISTRIBUTION but [MURPHY] RSI says BUY → Trust phase
  - If [WEIS] wave balance = SUPPLY_DOMINANT but [BOLLINGER] says squeeze up
    → Trust wave balance for direction, Bollinger for timing
  - Reason: Phase and volume reflect weeks of behavior. Oscillators reflect hours.
  - [INFERRED] This priority hierarchy is our design decision.
  - 📝 Hint: "Big-picture volume story beats short-term indicators."

**Rule 6.2** [CONFLUENCE] Bar Reading > Moving Averages
  - If [BROOKS] strong reversal bar at key level but MAs point the other way
    → Trust PA for entry, use MA for position sizing
  - If [WEIS] effort vs result shows absorption at a level but MAs say trend
    continues → Absorption is the leading indicator
  - 📝 Hint: "What's happening NOW (bars, volume) beats what HAPPENED (averages)."

**Rule 6.3** [CONFLUENCE] Bollinger Squeeze + Weis Phase = Timing System
  - Squeeze tells you WHEN (imminent breakout)
  - Phase tells you WHICH WAY (accumulation = up, distribution = down)
  - [BROOKS] Always-in direction confirms or denies
  - All three agree → Maximum timing conviction
  - 📝 Hint: "Squeeze says 'soon.' Phase says 'which way.' PA confirms."

**Rule 6.4** [CONFLUENCE] Spring/Upthrust WITH Follow-Through > All
  - [WEIS] A spring or upthrust is a high-probability Wyckoff setup
  - BUT only if follow-through confirms in the next 1-3 bars (Ch. 1)
  - If follow-through = YES → Act on the spring/upthrust even if other
    lenses are neutral. This is the single strongest event signal.
  - If follow-through = NO → Signal disqualified regardless of other lenses
  - [INFERRED] "Takes priority" is our hierarchy. Weis treats these as
    high-probability but does not claim they override all other analysis.
  - 📝 Hint: "A confirmed spring or upthrust is the strongest single signal.
    But confirmation (follow-through) is non-negotiable."

**Rule 6.5** [CONFLUENCE] Change-in-Behavior as Early Warning Override
  - [WEIS] If a Change-in-Behavior bar appears (largest opposite-direction
    bar in 20 periods), treat it as an override on momentum signals
  - A bullish CIB in a downtrend overrides bearish momentum (early reversal)
  - A bearish CIB in an uptrend overrides bullish momentum (early warning)
  - Action: Don't EXIT on CIB alone, but do REDUCE size and tighten stops
  - Source: Weis Ch. 4 — "first" event in the opposite direction matters
  - 📝 Hint: "When the biggest bar of the month suddenly appears on the
    OTHER side, the current trend is about to change. Don't ignore it."

**Rule 6.6** [CONFLUENCE] Conflicting Lenses = Reduce or Skip
  - 2 lenses BUY, 2 lenses SELL → NO TRADE
  - 3 lenses agree, 1 disagrees → 75% size, normal stops
  - All 4 agree → Full size, widest stops
  - 📝 Hint: "Don't bet big on a confused market."

**Rule 6.7** [CONFLUENCE] Volume Is the Lie Detector
  - When in doubt about ANY signal from any lens, check volume:
  - Signal + high volume = REAL
  - Signal + low volume = SUSPICIOUS
  - [WEIS] This is the through-line of the entire Weis/Wyckoff method:
    volume reveals intent. Every rule above ultimately relies on it.
  - 📝 Hint: "Volume is the closest thing to truth in the market."


## SCORING INTEGRATION
## ═══════════════════════════════════════════════
##
## BB Score:    -100 to +100  (4 Bollinger Methods)     [BOLLINGER]
## TA Score:    -100 to +100  (6 Murphy Categories)     [MURPHY]
## PA Score:    -100 to +100  (8 Brooks Components)     [BROOKS]
## Cross-Val:    -90 to  +90  (Agreement + Wyckoff)     [CONFLUENCE]
##   └─ Base agreement:  -60 to +60
##   └─ Wyckoff context: -30 to +30                     [WEIS]
##     └─ Phase bias:        ±8
##     └─ Events (SP/UT/SC/BC): ±6 each
##     └─ Absorption:        ±5
##     └─ Change-in-Behavior: ±4
##     └─ Wave balance:      ±3
##     └─ Shortening/SOT:    ±2
##     └─ Follow-through:    quality modifier on events
##
## TOTAL:      -390 to +390
##
## The 3 core scores (BB, TA, PA) are NEVER modified by Wyckoff.
## Wyckoff operates ONLY in the cross-validation layer, adding
## context that strengthens or weakens the combined signal.
##
## New in this version:
##   - Absorption detection (±5) — one of Weis's 3 core patterns
##   - Change-in-Behavior (±4) — first warning of trend change
##   - Follow-through assessment — validates spring/upthrust events
##   - Wave duration comparison — time as the third element
##   - Trend context on springs/upthrusts — ±10 confidence adjustment
