"""
ai_ml — Standalone AI/ML Intelligence Layer
============================================

This module is a READ-ONLY consumer of existing system data.
It NEVER modifies any existing module, signal, or pipeline.

Architecture:
  - Top 5 pipeline runs exactly as before → produces picks
  - ai_ml.engine.enrich_picks(picks) adds ML confidence,
    correlation risk, position sizing — purely additive fields
  - If ai_ml fails or is unavailable, Top 5 works unchanged

Integration contract:
  - Input:  list of pick dicts from find_top_picks()
  - Output: same list with new keys added (ml_*, corr_*, size_*)
  - Existing keys are NEVER modified or removed
"""
