"""
Assert-based tests for the layered safety-override framework
(_apply_safety_overrides in bb_squeeze/portfolio_analyzer.py).

FOUR TIERS OF DEFENCE — re-run before touching portfolio_analyzer.py:

  Tier 1 (absolute — always wins):
    R5. Stop-loss BREACHED

  Tier 2 (multi-system consensus — escalate HOLD/ADD → SELL):
    R1. Method I sig.sell_signal fires
    R2. Triple STRONG SELL + STRONG alignment
    R3. Wyckoff CONFIRMED MARKDOWN + bearish bias
    R4. Price Action MODERATE/STRONG SELL

  Tier 4 (never touch action, only warn):
    R6. Data staleness > 5 trading days

Additional coverage:
  - Every buying strategy (M1, M2, M3, M4) escalates correctly.
  - Multiple rules firing at once still land at SELL/STRONG (idempotent).
  - Never demotes SELL.
  - Missing multi_sys keys (light-mode) → R1/R5/R6 still apply, R2/R3/R4
    silently skip without crashing.
  - safety_overrides audit trail records every rule that fired.
  - End-to-end analyze_position on real CSV returns the full contract shape.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import pandas as pd

from bb_squeeze.portfolio_analyzer import (
    _generate_recommendation,
    _apply_safety_overrides,
)


# ─────────────────────────────────────────────────────────────────────
#  Mock objects that quack like signals.SignalResult / StrategyResult
# ─────────────────────────────────────────────────────────────────────

class _FakeSig:
    def __init__(self,
                 sell_signal=False, hold_signal=False, buy_signal=False,
                 exit_sar_flip=False, exit_lower_band_tag=False, exit_double_neg=False,
                 direction_lean="NEUTRAL", confidence=50, phase="",
                 head_fake=False, summary=""):
        self.sell_signal = sell_signal
        self.hold_signal = hold_signal
        self.buy_signal = buy_signal
        self.exit_sar_flip = exit_sar_flip
        self.exit_lower_band_tag = exit_lower_band_tag
        self.exit_double_neg = exit_double_neg
        self.direction_lean = direction_lean
        self.confidence = confidence
        self.phase = phase
        self.head_fake = head_fake
        self.summary = summary


@dataclass
class _FakeStrategySignal:
    signal_type: str = "NONE"
    strength: str = "MODERATE"
    confidence: int = 20
    reason: str = ""
    details: str = ""


@dataclass
class _FakeStrategy:
    code: str = "M2"
    signal: _FakeStrategySignal = field(default_factory=_FakeStrategySignal)
    patterns: list = field(default_factory=list)
    indicators: dict = field(default_factory=dict)


def _make_df(percent_b=0.14, mfi=42.9, cmf=-0.22,
             price=1598.6, sar=1897.75, sar_bull=False,
             bb_upper=1750.0, bb_mid=1650.0, bb_lower=1550.0,
             bbw=0.18, volume=12600, vol_sma=25000) -> pd.DataFrame:
    n = 30
    rows = []
    for i in range(n):
        rows.append({
            "Close": price - (n - 1 - i) * 0.5,
            "High": price + 5, "Low": price - 5, "Open": price - 1,
            "Percent_B": percent_b, "MFI": mfi, "CMF": cmf,
            "SAR": sar, "SAR_Bull": sar_bull, "BBW": bbw,
            "BB_Upper": bb_upper, "BB_Mid": bb_mid, "BB_Lower": bb_lower,
            "Volume": volume, "Vol_SMA50": vol_sma,
        })
    return pd.DataFrame(rows)


def _strats(m2_sig="NONE", m3_sig="NONE", m4_sig="NONE") -> list:
    return [
        _FakeStrategy(code="M2", signal=_FakeStrategySignal(signal_type=m2_sig)),
        _FakeStrategy(code="M3", signal=_FakeStrategySignal(signal_type=m3_sig)),
        _FakeStrategy(code="M4", signal=_FakeStrategySignal(signal_type=m4_sig)),
    ]


def _fired_rules(rec) -> list:
    return [o["rule"] for o in rec.get("safety_overrides", [])]


def _base_rec(strategy_code="M2", m2_sig="NONE", sig_kwargs=None, buy_price=1855.0):
    """Convenience — build a base rec via _generate_recommendation, no overrides yet."""
    df = _make_df()
    sig = _FakeSig(**(sig_kwargs or {}))
    strats = _strats(m2_sig=m2_sig)
    return _generate_recommendation(strategy_code, sig, strats, df, buy_price), sig, strats


# ─────────────────────────────────────────────────────────────────────
#  Tier 2 — R1 Method I composite exit
# ─────────────────────────────────────────────────────────────────────

def test_R1_M2_bought_escalates():
    print("── R1  M2-bought + sig.sell_signal ──")
    rec, sig, strats = _base_rec(sig_kwargs=dict(sell_signal=True, exit_sar_flip=True, exit_double_neg=True))
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL" and out["strength"] == "STRONG", out
    assert "R1" in _fired_rules(out), _fired_rules(out)
    print("  [ok]")


def test_R1_M3_M4_also_escalate():
    print("── R1  M3 & M4-bought also escalate ──")
    for code in ("M3", "M4"):
        rec, sig, strats = _base_rec(strategy_code=code, sig_kwargs=dict(sell_signal=True, exit_sar_flip=True))
        out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code=code)
        assert out["action"] == "SELL", (code, out)
        assert "R1" in _fired_rules(out), (code, _fired_rules(out))
    print("  [ok]")


def test_R1_M1_bought_skipped():
    """M1 branch upstream handles sig.sell_signal — R1 must not double-fire."""
    print("── R1  M1-bought → override skipped ──")
    rec, sig, strats = _base_rec(strategy_code="M1", sig_kwargs=dict(sell_signal=True, exit_sar_flip=True))
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code="M1")
    assert "R1" not in _fired_rules(out), _fired_rules(out)
    print("  [ok]")


def test_R1_single_flag_no_escalation():
    print("── R1  single exit flag + sig.sell_signal=False → no escalation ──")
    rec, sig, strats = _base_rec(sig_kwargs=dict(sell_signal=False, exit_sar_flip=True))
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "HOLD"
    assert "R1" not in _fired_rules(out)
    print("  [ok]")


# ─────────────────────────────────────────────────────────────────────
#  Tier 2 — R2 Triple engine consensus
# ─────────────────────────────────────────────────────────────────────

def test_R2_triple_strong_sell_escalates():
    print("── R2  Triple STRONG SELL + STRONG alignment ──")
    rec, sig, strats = _base_rec()
    ms = {"triple": {"verdict": "STRONG SELL", "alignment": "STRONG", "confidence": 78}}
    out = _apply_safety_overrides(rec, sig, strats, ms, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL" and out["strength"] == "STRONG"
    assert "R2" in _fired_rules(out)
    print("  [ok]")


def test_R2_weak_alignment_skipped():
    print("── R2  STRONG SELL but WEAK alignment → skipped ──")
    rec, sig, strats = _base_rec()
    ms = {"triple": {"verdict": "STRONG SELL", "alignment": "WEAK", "confidence": 30}}
    out = _apply_safety_overrides(rec, sig, strats, ms, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "HOLD", out
    assert "R2" not in _fired_rules(out)
    print("  [ok]")


# ─────────────────────────────────────────────────────────────────────
#  Tier 2 — R3 Wyckoff CONFIRMED MARKDOWN
# ─────────────────────────────────────────────────────────────────────

def test_R3_wyckoff_markdown_escalates():
    print("── R3  Wyckoff CONFIRMED MARKDOWN + bearish bias ──")
    rec, sig, strats = _base_rec()
    ms = {"wyckoff": {"phase": "CONFIRMED MARKDOWN", "bias": "BEARISH"}}
    out = _apply_safety_overrides(rec, sig, strats, ms, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL"
    assert "R3" in _fired_rules(out)
    print("  [ok]")


def test_R3_markdown_neutral_bias_skipped():
    """Early markdown alone (bias NEUTRAL) is too noisy — must not escalate."""
    print("── R3  MARKDOWN phase but NEUTRAL bias → skipped ──")
    rec, sig, strats = _base_rec()
    ms = {"wyckoff": {"phase": "MARKDOWN", "bias": "NEUTRAL"}}
    out = _apply_safety_overrides(rec, sig, strats, ms, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "HOLD"
    assert "R3" not in _fired_rules(out)
    print("  [ok]")


# ─────────────────────────────────────────────────────────────────────
#  Tier 2 — R4 Price Action SELL
# ─────────────────────────────────────────────────────────────────────

def test_R4_pa_strong_sell_escalates():
    print("── R4  PA STRONG SELL ──")
    rec, sig, strats = _base_rec()
    ms = {"price_action": {"signal": "SELL", "strength": "STRONG", "setup": "FAILED_BREAKOUT", "context": "trapped longs exiting"}}
    out = _apply_safety_overrides(rec, sig, strats, ms, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL"
    assert "R4" in _fired_rules(out)
    print("  [ok]")


def test_R4_pa_weak_sell_skipped():
    """Weak PA sells are noise — must not escalate."""
    print("── R4  PA WEAK SELL → skipped ──")
    rec, sig, strats = _base_rec()
    ms = {"price_action": {"signal": "SELL", "strength": "WEAK", "setup": "FAILED_BREAKOUT"}}
    out = _apply_safety_overrides(rec, sig, strats, ms, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "HOLD"
    assert "R4" not in _fired_rules(out)
    print("  [ok]")


# ─────────────────────────────────────────────────────────────────────
#  Tier 1 — R5 Stop-loss breach (absolute)
# ─────────────────────────────────────────────────────────────────────

def test_R5_stop_breach_absolute():
    """Even with no other bearish signal, a stop breach IS a SELL."""
    print("── R5  Stop-loss BREACHED → SELL / STRONG (Tier 1) ──")
    rec, sig, strats = _base_rec()
    tgt = {"stop_loss": 1600.0}
    out = _apply_safety_overrides(rec, sig, strats, {}, tgt, current_price=1550.0, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL" and out["strength"] == "STRONG"
    assert "R5" in _fired_rules(out)
    print("  [ok]")


def test_R5_price_above_stop_no_escalation():
    print("── R5  price above stop → no escalation ──")
    rec, sig, strats = _base_rec()
    tgt = {"stop_loss": 1400.0}
    out = _apply_safety_overrides(rec, sig, strats, {}, tgt, current_price=1600.0, freshness={}, strategy_code="M2")
    assert out["action"] == "HOLD"
    assert "R5" not in _fired_rules(out)
    print("  [ok]")


# ─────────────────────────────────────────────────────────────────────
#  Tier 4 — R6 Data staleness (never changes action, warns + weakens)
# ─────────────────────────────────────────────────────────────────────

def test_R6_stale_data_warns_and_weakens():
    print("── R6  Stale data warns + downgrades STRONG → MODERATE ──")
    rec, sig, strats = _base_rec(sig_kwargs=dict(sell_signal=True, exit_sar_flip=True))
    # R1 will fire and set action=SELL/STRONG. Then R6 must downgrade to MODERATE.
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6,
                                  freshness={"trading_days_stale": 8}, strategy_code="M2")
    assert out["action"] == "SELL", out
    assert out["strength"] == "MODERATE", out["strength"]
    assert any("[R6]" in w for w in out["warnings"])
    print("  [ok]")


def test_R6_fresh_data_no_warning():
    print("── R6  Fresh data → no R6 warning ──")
    rec, sig, strats = _base_rec()
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6,
                                  freshness={"trading_days_stale": 1}, strategy_code="M2")
    assert not any("[R6]" in w for w in out["warnings"])
    print("  [ok]")


# ─────────────────────────────────────────────────────────────────────
#  Composite behaviour
# ─────────────────────────────────────────────────────────────────────

def test_never_demotes_sell():
    """Even with all rules quiet, an existing SELL must survive."""
    print("── Never demotes SELL ──")
    rec, sig, strats = _base_rec(m2_sig="SELL")
    assert rec["action"] == "SELL"
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL"
    print("  [ok]")


def test_multiple_rules_fire_together():
    """R1 + R2 + R3 + R4 + R5 all firing → still SELL/STRONG, all rules recorded."""
    print("── Multiple rules fire simultaneously ──")
    rec, sig, strats = _base_rec(sig_kwargs=dict(sell_signal=True, exit_sar_flip=True, exit_double_neg=True))
    ms = {
        "triple": {"verdict": "STRONG SELL", "alignment": "STRONG", "confidence": 82},
        "wyckoff": {"phase": "CONFIRMED MARKDOWN", "bias": "BEARISH"},
        "price_action": {"signal": "SELL", "strength": "STRONG", "setup": "M-TOP"},
    }
    tgt = {"stop_loss": 1650.0}
    out = _apply_safety_overrides(rec, sig, strats, ms, tgt, current_price=1500.0, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL" and out["strength"] == "STRONG"
    fired = set(_fired_rules(out))
    for r in ("R1", "R2", "R3", "R4", "R5"):
        assert r in fired, f"missing {r} in {fired}"
    print(f"  [ok] all rules fired: {sorted(fired)}")


def test_light_mode_graceful_degradation():
    """Missing multi_sys keys → R2/R3/R4 silently skip, R1/R5/R6 still apply."""
    print("── Light mode: missing multi_sys → still functional ──")
    rec, sig, strats = _base_rec(sig_kwargs=dict(sell_signal=True, exit_sar_flip=True))
    # multi_sys empty AND targets empty — should not crash
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert out["action"] == "SELL"
    assert "R1" in _fired_rules(out)
    print("  [ok]")


def test_input_rec_not_mutated():
    """The function must return a fresh dict — never mutate caller's rec."""
    print("── Input rec is not mutated (functional purity) ──")
    rec, sig, strats = _base_rec(sig_kwargs=dict(sell_signal=True, exit_sar_flip=True))
    action_before = rec["action"]
    warnings_id = id(rec.get("warnings"))
    out = _apply_safety_overrides(rec, sig, strats, {}, {}, current_price=1598.6, freshness={}, strategy_code="M2")
    assert rec["action"] == action_before, "caller's rec was mutated"
    assert id(rec.get("warnings")) == warnings_id, "warnings list identity changed on input"
    assert id(out["warnings"]) != warnings_id, "output should be a new list"
    print("  [ok]")


def test_end_to_end_real_csv():
    """Full analyze_position on real CSV — no crash, full contract preserved."""
    print("── End-to-end on real CSV ──")
    from bb_squeeze.portfolio_analyzer import analyze_position
    pos = {"id": 1, "ticker": "RELIANCE.NS", "strategy_code": "M2",
           "buy_price": 1300.0, "buy_date": "2026-06-01",
           "quantity": 10, "status": "OPEN", "notes": ""}
    res = analyze_position(pos)
    rec = res.get("recommendation") or {}
    for k in ("action", "strength", "reasons", "warnings",
              "confirms", "action_triggers", "entry_quality", "momentum",
              "strategy_code", "safety_overrides"):
        assert k in rec, f"missing key: {k}"
    assert rec["action"] in ("HOLD", "SELL", "ADD", "BUY"), rec["action"]
    assert isinstance(rec["safety_overrides"], list)
    print(f"  [ok] action={rec['action']} strength={rec['strength']} "
          f"safety_overrides_fired={[o['rule'] for o in rec['safety_overrides']]}")


def main() -> int:
    # Tier 2 — R1 Method I
    test_R1_M2_bought_escalates()
    test_R1_M3_M4_also_escalate()
    test_R1_M1_bought_skipped()
    test_R1_single_flag_no_escalation()

    # Tier 2 — R2 Triple
    test_R2_triple_strong_sell_escalates()
    test_R2_weak_alignment_skipped()

    # Tier 2 — R3 Wyckoff
    test_R3_wyckoff_markdown_escalates()
    test_R3_markdown_neutral_bias_skipped()

    # Tier 2 — R4 Price Action
    test_R4_pa_strong_sell_escalates()
    test_R4_pa_weak_sell_skipped()

    # Tier 1 — R5 Stop-loss
    test_R5_stop_breach_absolute()
    test_R5_price_above_stop_no_escalation()

    # Tier 4 — R6 Staleness
    test_R6_stale_data_warns_and_weakens()
    test_R6_fresh_data_no_warning()

    # Composite behaviour
    test_never_demotes_sell()
    test_multiple_rules_fire_together()
    test_light_mode_graceful_degradation()
    test_input_rec_not_mutated()
    test_end_to_end_real_csv()

    print("\nALL SAFETY-OVERRIDE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
