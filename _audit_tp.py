"""
Audit script: Verify Top 5 Picks correctness end-to-end.
Tests that BUY picks are truly BUY, SELL picks are truly SELL,
and the scorer handles direction properly.
"""
import sys, json

from top_picks.engine import find_top_picks, _extract_candidates, _get_m1_signal_type
from top_picks.scorer import compute_composite_score, _score_signal_agreement, _to_direction
from bb_squeeze.data_loader import get_all_tickers_from_csv, load_stock_data
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict


def test_1_signal_filter_correctness():
    """Verify _extract_candidates never leaks wrong direction."""
    print("=" * 60)
    print("TEST 1: Signal direction filter correctness")
    print("=" * 60)

    tickers = get_all_tickers_from_csv()[:80]
    scan_data = []
    for t in tickers:
        try:
            df = load_stock_data(t)
            if df is None or len(df) < 100:
                continue
            df = compute_all_indicators(df)
            m1 = analyze_signals(t, df)
            strats = run_all_strategies(df)
            scan_data.append({
                "ticker": t,
                "price": float(df["Close"].iloc[-1]),
                "m1": {
                    "buy_signal": m1.buy_signal,
                    "sell_signal": m1.sell_signal,
                    "hold_signal": m1.hold_signal,
                    "wait_signal": m1.wait_signal,
                    "confidence": m1.confidence,
                },
                "strategies": [strategy_result_to_dict(s) for s in strats],
            })
        except Exception:
            continue

    print(f"  Scanned {len(scan_data)} stocks")

    # Test M1
    m1_flat = []
    for s in scan_data:
        m1_flat.append({
            "ticker": s["ticker"],
            "confidence": s["m1"]["confidence"],
            "buy_signal": s["m1"]["buy_signal"],
            "sell_signal": s["m1"]["sell_signal"],
            "hold_signal": s["m1"]["hold_signal"],
            "wait_signal": s["m1"]["wait_signal"],
            "current_price": s["price"],
        })

    for direction in ("BUY", "SELL"):
        cands = _extract_candidates(m1_flat, "M1", direction)
        bad = [c for c in cands if c["signal_type"] != direction]
        status = "PASS" if len(bad) == 0 else "FAIL"
        print(f"  M1 {direction}: {len(cands)} candidates, {len(bad)} wrong direction → {status}")

    # Test M2, M3, M4
    for method in ("M2", "M3", "M4"):
        for direction in ("BUY", "SELL"):
            cands = _extract_candidates(scan_data, method, direction)
            bad = [c for c in cands if c["signal_type"] != direction]
            status = "PASS" if len(bad) == 0 else "FAIL"
            print(f"  {method} {direction}: {len(cands)} candidates, {len(bad)} wrong direction → {status}")


def test_2_scorer_direction_awareness():
    """Verify scorer flips correctly for BUY vs SELL."""
    print("\n" + "=" * 60)
    print("TEST 2: Scorer direction-awareness")
    print("=" * 60)

    # Simulate a strongly BEARISH stock
    bearish_ta = {"score": -60, "verdict": "STRONG SELL", "categories": {}}
    bearish_hybrid = {
        "triple_verdict": {"verdict": "STRONG SELL", "score": -120},
        "target_prices": {"risk_reward_ratio": 2.5},
    }
    bearish_freshness = {"trading_days_stale": 1}

    # Score it as a SELL pick (should score HIGH)
    sell_result = compute_composite_score(
        bb_confidence=75,
        bb_signal_type="SELL",
        ta_signal=bearish_ta,
        hybrid_result=bearish_hybrid,
        data_freshness=bearish_freshness,
        method="M3",
        signal_filter="SELL",
    )

    # Score it as a BUY pick (should score LOW)
    buy_result = compute_composite_score(
        bb_confidence=75,
        bb_signal_type="SELL",
        ta_signal=bearish_ta,
        hybrid_result=bearish_hybrid,
        data_freshness=bearish_freshness,
        method="M3",
        signal_filter="BUY",
    )

    print(f"  Bearish stock scored as SELL pick: {sell_result['composite_score']} ({sell_result['grade']})")
    print(f"  Bearish stock scored as BUY pick:  {buy_result['composite_score']} ({buy_result['grade']})")
    status = "PASS" if sell_result["composite_score"] > buy_result["composite_score"] else "FAIL"
    print(f"  SELL score > BUY score? → {status}")

    # Simulate a strongly BULLISH stock
    bullish_ta = {"score": 60, "verdict": "STRONG BUY", "categories": {}}
    bullish_hybrid = {
        "triple_verdict": {"verdict": "STRONG BUY", "score": 120},
        "target_prices": {"risk_reward_ratio": 2.5},
    }

    buy_result2 = compute_composite_score(
        bb_confidence=75,
        bb_signal_type="BUY",
        ta_signal=bullish_ta,
        hybrid_result=bullish_hybrid,
        data_freshness=bearish_freshness,
        method="M3",
        signal_filter="BUY",
    )

    sell_result2 = compute_composite_score(
        bb_confidence=75,
        bb_signal_type="BUY",
        ta_signal=bullish_ta,
        hybrid_result=bullish_hybrid,
        data_freshness=bearish_freshness,
        method="M3",
        signal_filter="SELL",
    )

    print(f"\n  Bullish stock scored as BUY pick:  {buy_result2['composite_score']} ({buy_result2['grade']})")
    print(f"  Bullish stock scored as SELL pick: {sell_result2['composite_score']} ({sell_result2['grade']})")
    status = "PASS" if buy_result2["composite_score"] > sell_result2["composite_score"] else "FAIL"
    print(f"  BUY score > SELL score? → {status}")


def test_3_agreement_direction_bug():
    """
    Test signal_agreement for the known bug:
    Does a SELL scan give 100 agreement to 3 BULLISH engines?
    """
    print("\n" + "=" * 60)
    print("TEST 3: Signal agreement direction-awareness")
    print("=" * 60)

    # All 3 engines say BUY → agreement=100
    score_all_buy = _score_signal_agreement("BUY", "STRONG BUY", "STRONG BUY")
    print(f"  All 3 BULLISH → agreement score: {score_all_buy}")

    # All 3 engines say SELL → agreement=100
    score_all_sell = _score_signal_agreement("SELL", "STRONG SELL", "STRONG SELL")
    print(f"  All 3 BEARISH → agreement score: {score_all_sell}")

    # Mixed: BB=SELL, TA=BUY, Hybrid=BUY → conflict
    score_mixed = _score_signal_agreement("SELL", "STRONG BUY", "STRONG BUY")
    print(f"  BB=SELL, TA=BUY, Hybrid=BUY → agreement: {score_mixed}")

    # KEY BUG TEST: On a SELL scan, if all 3 say BUY, agreement is 100
    # but the ACTUAL agreement with the SCAN DIRECTION (SELL) is 0!
    print(f"\n  ⚠ BUG CHECK: On a SELL scan, if BB=BUY TA=BUY Hybrid=BUY:")
    print(f"    Agreement score = {score_all_buy} (they agree with EACH OTHER)")
    print(f"    But they all DISAGREE with SELL direction!")
    print(f"    However, this is already mitigated because:")
    print(f"    - The candidate would NOT pass _extract_candidates (BB=BUY != SELL)")
    print(f"    - So this scenario CANNOT happen in practice for BB direction")
    print(f"    - TA and Hybrid are not pre-filtered but their scores ARE flipped")


def test_4_live_api_m3_sell():
    """Run a mini Top-5 SELL for M3 and verify picks make sense."""
    print("\n" + "=" * 60)
    print("TEST 4: Live M3 SELL mini-run (20 stocks)")
    print("=" * 60)

    tickers = get_all_tickers_from_csv()[:100]
    scan_data = []
    for t in tickers:
        try:
            df = load_stock_data(t)
            if df is None or len(df) < 100:
                continue
            df = compute_all_indicators(df)
            m1 = analyze_signals(t, df)
            strats = run_all_strategies(df)
            scan_data.append({
                "ticker": t,
                "price": float(df["Close"].iloc[-1]),
                "m1": {
                    "buy_signal": m1.buy_signal,
                    "sell_signal": m1.sell_signal,
                    "confidence": m1.confidence,
                },
                "strategies": [strategy_result_to_dict(s) for s in strats],
            })
        except Exception:
            continue

    result = find_top_picks(scan_data, method="M3", signal_filter="SELL", capital=500000)

    print(f"  Scanned: {result['total_scanned']}")
    print(f"  Had SELL signals: {result['total_signals']}")
    print(f"  Qualified (conf >= 30): {result['total_qualified']}")
    print(f"  Deep analyzed: {result['total_analyzed']}")
    print(f"  Top picks: {len(result['picks'])}")

    for pick in result["picks"]:
        bb_type = pick.get("bb_signal_type", "?")
        ta_v = pick.get("ta_verdict", "?")
        hyb_v = pick.get("triple_verdict", "?")
        score = pick.get("composite_score", 0)
        grade = pick.get("grade", "?")

        # Check: BB signal should be SELL
        bb_ok = "✓" if "SELL" in bb_type.upper() else "✗ BUG"
        # Check: TA should be bearish for high score
        ta_ok = "✓" if "SELL" in ta_v.upper() else "~"
        # Check: Hybrid should be bearish for high score
        hyb_ok = "✓" if "SELL" in hyb_v.upper() else "~"

        print(f"  #{pick['rank']} {pick['ticker']:15s} "
              f"Score={score:5.1f} Grade={grade:3s} "
              f"BB={bb_type:10s}[{bb_ok}] "
              f"TA={ta_v:15s}[{ta_ok}] "
              f"Hybrid={hyb_v:15s}[{hyb_ok}]")

        # Hard check: BB signal MUST be SELL
        if "SELL" not in bb_type.upper():
            print(f"    ❌ CRITICAL BUG: BB signal is '{bb_type}' on a SELL scan!")


if __name__ == "__main__":
    test_1_signal_filter_correctness()
    test_2_scorer_direction_awareness()
    test_3_agreement_direction_bug()
    test_4_live_api_m3_sell()
    print("\n" + "=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)
