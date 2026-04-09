"""
wyckoff/ — Wyckoff/Weis Volume-Spread Analysis Engine
======================================================

Source: "Trades About to Happen" by David H. Weis (2013)
        Modern adaptation of Richard Wyckoff's original method.

This module implements Wyckoff's market cycle theory as codified by Weis:

  1. VOLUME-SPREAD ANALYSIS (Effort vs Result)
     - Is volume (effort) producing proportional price movement (result)?
     - High volume + narrow spread = absorption = smart money stepping in
     - Low volume + wide spread = no resistance = path of least resistance

  2. WYCKOFF MARKET PHASES
     - Accumulation → Markup → Distribution → Markdown
     - Each phase has specific volume/price signatures

  3. WYCKOFF EVENTS (Springs, Upthrusts, Tests, Climaxes)
     - Spring: false break below support that traps sellers [HIGHEST PROB BUY]
     - Upthrust: false break above resistance that traps buyers [HIGHEST PROB SELL]
     - Selling Climax (SC): panic selling, volume spike, price reversal
     - Buying Climax (BC): euphoric buying, volume spike, price reversal

  4. WEIS WAVE ANALYSIS
     - Tracks cumulative volume on up-waves vs down-waves
     - Shortening of thrust = diminishing price movement on continued volume
     - Volume dry-up = no more supply/demand at current level

Integration Strategy:
  This engine produces a WyckoffResult that feeds into the existing
  Triple Conviction Engine as cross-validation data. It does NOT replace
  any existing system — it ENHANCES them:

  - BB Squeeze + Wyckoff Accumulation = CONFIRMED squeeze breakout
  - PA Breakout + Wyckoff Spring = HIGH CONVICTION entry
  - TA Divergence + Wyckoff Distribution = CONFIRMED top
  - Volume confirms across all systems = real move, not fake
"""
