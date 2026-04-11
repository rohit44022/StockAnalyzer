"""
wyckoff/ — Wyckoff/Villahermosa Volume-Spread Analysis Engine
==============================================================

Source: "The Wyckoff Methodology in Depth" by Rubén Villahermosa (2019)
        Comprehensive modern treatment of Richard Wyckoff's original method.

This module implements Wyckoff's market cycle theory as taught by Villahermosa:

  1. VOLUME-SPREAD ANALYSIS (Effort vs Result — Law 3)
     - Is volume (effort) producing proportional price movement (result)?
     - High volume + narrow spread = absorption = Composite Man stepping in
     - Low volume + wide spread = no resistance = Lack of Interest

  2. WYCKOFF MARKET PHASES (5 Phases A-E, 4 Schematics)
     - Accumulation → Markup → Distribution → Markdown
     - Each phase has specific volume/price signatures
     - Phase A: Stopping, Phase B: Building, Phase C: Test, Phase D: Trend, Phase E: Extension

  3. WYCKOFF EVENTS (7 Events: PS, Climax, Reaction, Test, Shaking, Breakout, Confirmation)
     - Spring: false break below support (Ice) that traps sellers [HIGHEST PROB BUY]
     - Upthrust: false break above resistance (Creek) that traps buyers [HIGHEST PROB SELL]
     - Selling Climax (SC): panic selling, volume spike, price reversal
     - Buying Climax (BC): euphoric buying, volume spike, price reversal

  4. WYCKOFF WAVE ANALYSIS
     - Tracks cumulative volume on up-waves vs down-waves
     - Shortening of thrust = diminishing price movement on continued volume
     - Volume dry-up = Lack of Interest at current level

Integration Strategy:
  This engine produces a WyckoffResult that feeds into the existing
  Triple Conviction Engine as cross-validation data. It does NOT replace
  any existing system — it ENHANCES them:

  - BB Squeeze + Wyckoff Accumulation = CONFIRMED squeeze breakout
  - PA Breakout + Wyckoff Spring = HIGH CONVICTION entry
  - TA Divergence + Wyckoff Distribution = CONFIRMED top
  - Volume confirms across all systems = real move, not fake
"""
