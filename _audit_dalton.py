"""Dalton Market Profile Audit Script — Truthfulness & Book Accuracy Check"""
import pandas as pd
from collections import Counter
from market_profile.engine import (
    run_market_profile_analysis, market_profile_to_dict,
    _compute_profiles, _compute_day_profile,
    _classify_day_type, _classify_activity,
    _detect_poor_extremes, _detect_one_timeframing,
    _detect_3_to_i, _compute_rotation_factor,
)

TICKERS = [
    'RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'SBIN.NS',
    'TATAMOTORS.NS', 'WIPRO.NS', 'BHARTIARTL.NS', 'ICICIBANK.NS', 'LT.NS',
    'HCLTECH.NS', 'BAJFINANCE.NS', 'MARUTI.NS', 'SUNPHARMA.NS', 'TITAN.NS',
    'KOTAKBANK.NS', 'ADANIENT.NS', 'ONGC.NS', 'COALINDIA.NS', 'NTPC.NS',
]


def _sanitize(df):
    """Drop corrupt rows where H==L or Close outside [Low, High]."""
    valid = (df["High"] > df["Low"]) & (df["Close"] >= df["Low"]) & (df["Close"] <= df["High"])
    return df[valid].copy()


def run_full_audit():
    results = {}
    errors = []

    for ticker in TICKERS:
        try:
            df = pd.read_csv(f'stock_csv/{ticker}.csv')
            mp = run_market_profile_analysis(df)
            d = market_profile_to_dict(mp)
            results[ticker] = d
            print(f"OK {ticker}: day={d['day_type']['type']}, struct={d['market_structure']['type']}, "
                  f"otf={d['one_timeframing']['direction']}({d['one_timeframing']['days']}), "
                  f"dp={d['directional_performance']['rating']}, cv={d['scoring']['cv_bonus']}")
        except Exception as e:
            errors.append((ticker, str(e)))
            print(f"FAIL {ticker}: {e}")

    print(f"\n=== RESULTS: {len(results)} OK, {len(errors)} FAIL ===")
    if errors:
        for t, e in errors:
            print(f"  ERROR {t}: {e}")

    # ---- Distribution Analysis ----
    print("\n=== DISTRIBUTION ANALYSIS ===")
    day_types = [r['day_type']['type'] for r in results.values()]
    structures = [r['market_structure']['type'] for r in results.values()]
    activities = [r['activity'] for r in results.values()]
    one_tfs = [r['one_timeframing']['direction'] for r in results.values()]
    cv_bonuses = [r['scoring']['cv_bonus'] for r in results.values()]

    print(f"Day Types: {dict(Counter(day_types))}")
    print(f"Structures: {dict(Counter(structures))}")
    print(f"Activities: {dict(Counter(activities))}")
    print(f"One-TF: {dict(Counter(one_tfs))}")
    if cv_bonuses:
        print(f"CV Bonus: min={min(cv_bonuses)}, max={max(cv_bonuses)}, mean={sum(cv_bonuses)/len(cv_bonuses):.1f}")

    t3i = sum(1 for r in results.values() if r['high_probability']['three_to_i']['active'])
    ne = sum(1 for r in results.values() if r['high_probability']['neutral_extreme']['active'])
    bb = sum(1 for r in results.values() if r['high_probability']['balance_breakout']['active'])
    ph = sum(1 for r in results.values() if r['poor_extremes']['poor_high'])
    pl = sum(1 for r in results.values() if r['poor_extremes']['poor_low'])
    print(f"High-prob: 3-to-I={t3i}, Neutral-Extreme={ne}, Balance-Breakout={bb}")
    print(f"Poor Extremes: poor_high={ph}, poor_low={pl}")

    # ---- VA Width Truthfulness (D8: should be ~70%) ----
    print("\n=== VA WIDTH AUDIT (D8: should approximate 70% of range) ===")
    for ticker, d in results.items():
        df = _sanitize(pd.read_csv(f'stock_csv/{ticker}.csv'))
        row = df.iloc[-1]
        rng = row['High'] - row['Low']
        if rng > 0:
            va_width = d['value_area']['va_high'] - d['value_area']['va_low']
            va_pct = va_width / rng * 100
            body = abs(row['Open'] - row['Close'])
            body_pct = body / rng * 100
            flag = " *** TOO NARROW" if va_pct < 50 else ""
            print(f"  {ticker}: VA={va_pct:.1f}% of range, body={body_pct:.1f}%{flag}")

    # ---- Initiative/Responsive Audit (D67 bug check) ----
    print("\n=== INITIATIVE/RESPONSIVE AUDIT (D67) ===")
    for ticker, d in results.items():
        df = _sanitize(pd.read_csv(f'stock_csv/{ticker}.csv'))
        profiles = _compute_profiles(df, lookback=10)
        if len(profiles) >= 2:
            today = profiles[-1]
            prev = profiles[-2]
            is_up = today.close > today.open
            is_down = today.close < today.open
            within_va = prev.va_low <= today.close <= prev.va_high
            activity = d['activity']
            # D67: Buying WITHIN or ABOVE prev VA = Initiative Buying
            # Current code: close > prev.va_high → Initiative, else Responsive
            if is_up and within_va and activity == "RESPONSIVE_BUYING":
                print(f"  BUG {ticker}: close={today.close:.2f} WITHIN prev VA [{prev.va_low:.2f}-{prev.va_high:.2f}] "
                      f"but classified as RESPONSIVE_BUYING (should be INITIATIVE_BUYING per D67)")
            elif is_down and within_va and activity == "RESPONSIVE_SELLING":
                print(f"  BUG {ticker}: close={today.close:.2f} WITHIN prev VA [{prev.va_low:.2f}-{prev.va_high:.2f}] "
                      f"but classified as RESPONSIVE_SELLING (should be INITIATIVE_SELLING per D67)")
            else:
                print(f"  OK  {ticker}: activity={activity}, close={today.close:.2f}, "
                      f"prev_VA=[{prev.va_low:.2f}-{prev.va_high:.2f}]")

    # ---- One-Timeframing Verification ----
    print("\n=== ONE-TIMEFRAMING VERIFICATION (D28) ===")
    for ticker in list(results.keys())[:5]:
        df = _sanitize(pd.read_csv(f'stock_csv/{ticker}.csv'))
        profiles = _compute_profiles(df, lookback=10)
        otf = results[ticker]['one_timeframing']
        if otf['direction'] != 'NONE':
            print(f"  {ticker}: OTF {otf['direction']} for {otf['days']} days")
            # Verify by checking actual lows/highs
            for i in range(len(profiles)-1, max(0, len(profiles)-1-otf['days']), -1):
                if i > 0:
                    curr, prev = profiles[i], profiles[i-1]
                    if otf['direction'] == 'UP':
                        ok = curr.low >= prev.low - 0.001
                        print(f"    Day {i}: low={curr.low:.2f} >= prev_low={prev.low:.2f} -> {'OK' if ok else 'FAIL'}")
                    else:
                        ok = curr.high <= prev.high + 0.001
                        print(f"    Day {i}: high={curr.high:.2f} <= prev_high={prev.high:.2f} -> {'OK' if ok else 'FAIL'}")

    # ---- Rotation Factor Verification (D32) ----
    print("\n=== ROTATION FACTOR VERIFICATION (D32) ===")
    for ticker in list(results.keys())[:5]:
        df = _sanitize(pd.read_csv(f'stock_csv/{ticker}.csv'))
        profiles = _compute_profiles(df, lookback=10)
        rf = results[ticker]['rotation_factor']
        # Manual calculation
        manual_rf = 0
        n = min(5, len(profiles) - 1)
        for i in range(-n, 0):
            curr, prev = profiles[i], profiles[i - 1]
            if curr.high > prev.high: manual_rf += 1
            elif curr.high < prev.high: manual_rf -= 1
            if curr.low > prev.low: manual_rf += 1
            elif curr.low < prev.low: manual_rf -= 1
        match = "OK" if rf == manual_rf else f"MISMATCH (got {rf}, expected {manual_rf})"
        print(f"  {ticker}: RF={rf}, manual={manual_rf} -> {match}")

    print("\n=== AUDIT COMPLETE ===")


if __name__ == "__main__":
    run_full_audit()
