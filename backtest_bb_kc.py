"""
Backtest: BB + Keltner Channel Squeeze with Volume & CMF Confirmation
=====================================================================
Tests 4 strategy tiers on all available NSE data (15 years):
  T1: BB-only squeeze breakout (current M1 baseline)
  T2: BB + KC squeeze gate
  T3: BB + KC + volume confirmation
  T4: BB + KC + volume + CMF confirmation (full conviction)

Entry rules (T4 — full):
  1. Squeeze ON for ≥3 bars (BB inside KC)
  2. Squeeze FIRES: BB expands outside KC
  3. Directional: Close > BB_Mid (bullish)
  4. Volume: Volume > 1.5× Vol_SMA50
  5. CMF > 0 (institutional money flowing in)

Exit rules (same across all tiers):
  Stop-loss:  Entry − 2×ATR(14)
  Target:     Entry + 3×ATR(14)
  Timeout:    30 bars max hold
"""

import os, sys, time, json
import numpy as np
import pandas as pd
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from bb_squeeze.config import CSV_DIR
from bb_squeeze.data_loader import get_all_tickers_from_csv

# ── Fast numpy indicators ──────────────────────────────────────

def _sma(arr, p):
    out = np.full_like(arr, np.nan)
    cs = np.nancumsum(arr)
    out[p-1:] = (cs[p-1:] - np.concatenate([[0], cs[:-p]])) / p
    return out

def _ema(arr, p):
    out = np.full_like(arr, np.nan)
    k = 2.0 / (p + 1)
    first_valid = np.argmax(~np.isnan(arr))
    out[first_valid] = arr[first_valid]
    for i in range(first_valid + 1, len(arr)):
        if np.isnan(arr[i]):
            out[i] = out[i-1]
        else:
            out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out

def _rolling_std(arr, p):
    out = np.full_like(arr, np.nan)
    for i in range(p - 1, len(arr)):
        window = arr[i - p + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) >= p:
            out[i] = np.std(valid, ddof=0)
    return out

def _atr(high, low, close, p=14):
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    out = np.full(n, np.nan)
    out[p-1] = np.mean(tr[:p])
    for i in range(p, n):
        out[i] = (out[i-1] * (p - 1) + tr[i]) / p
    return out

def _cmf(high, low, close, volume, p=20):
    denom = high - low
    denom[denom == 0] = 1e-10
    mfm = ((close - low) - (high - close)) / denom
    mfv = mfm * volume
    num = np.convolve(mfv, np.ones(p), 'full')[:len(close)]
    den = np.convolve(volume, np.ones(p), 'full')[:len(close)]
    den[den == 0] = 1e-10
    out = num / den
    out[:p-1] = np.nan
    return out


# ── Compute all needed indicators ──────────────────────────────

def compute_indicators(df):
    close = df["Close"].values.astype(float)
    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    volume = df["Volume"].values.astype(float)
    n = len(close)

    # Bollinger Bands
    sma20 = _sma(close, 20)
    std20 = _rolling_std(close, 20)
    bb_upper = sma20 + 2.0 * std20
    bb_lower = sma20 - 2.0 * std20
    bb_mid = sma20
    denom = np.where(sma20 == 0, 1e-10, sma20)
    bbw = (bb_upper - bb_lower) / denom

    # Keltner Channels
    ema20 = _ema(close, 20)
    atr14 = _atr(high, low, close, 14)
    kc_upper = ema20 + 1.5 * atr14
    kc_lower = ema20 - 1.5 * atr14

    # BB inside KC = squeeze ON
    squeeze_on = np.zeros(n, dtype=bool)
    for i in range(n):
        if not (np.isnan(bb_upper[i]) or np.isnan(kc_upper[i])):
            squeeze_on[i] = (bb_upper[i] < kc_upper[i]) and (bb_lower[i] > kc_lower[i])

    # Squeeze duration (consecutive bars inside KC)
    squeeze_dur = np.zeros(n, dtype=int)
    for i in range(n):
        if squeeze_on[i]:
            squeeze_dur[i] = (squeeze_dur[i-1] + 1) if i > 0 else 1

    # Squeeze fire: was in squeeze, now BB expands outside KC
    squeeze_fire = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if squeeze_on[i-1] and not squeeze_on[i]:
            squeeze_fire[i] = True

    # Volume SMA
    vol_sma50 = _sma(volume, 50)

    # CMF
    cmf = _cmf(high, low, close, volume, 20)

    # BBW squeeze (current M1 baseline)
    bbw_min126 = np.full(n, np.nan)
    for i in range(125, n):
        bbw_min126[i] = np.nanmin(bbw[i-125:i+1])

    bbw_squeeze = np.zeros(n, dtype=bool)
    for i in range(n):
        if not np.isnan(bbw[i]) and not np.isnan(bbw_min126[i]):
            bbw_squeeze[i] = (bbw[i] <= bbw_min126[i] * 1.05) or (bbw[i] <= 0.08)

    return {
        "close": close, "high": high, "low": low, "volume": volume,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_mid": bb_mid,
        "bbw": bbw, "atr14": atr14,
        "kc_upper": kc_upper, "kc_lower": kc_lower,
        "squeeze_on": squeeze_on, "squeeze_dur": squeeze_dur,
        "squeeze_fire": squeeze_fire,
        "vol_sma50": vol_sma50, "cmf": cmf,
        "bbw_squeeze": bbw_squeeze,
    }


# ── Signal functions for each tier ─────────────────────────────

def _had_kc_squeeze(ind, i, lookback=10, min_dur=3):
    """Check if there was a KC squeeze (BB inside KC) of ≥ min_dur bars
    within the last `lookback` bars ending at bar i."""
    start = max(0, i - lookback)
    for j in range(start, i + 1):
        if ind["squeeze_dur"][j] >= min_dur:
            return True
    return False

def signal_t1(ind, i):
    """T1: BB-only squeeze breakout (current M1 baseline).
    BBW at 6-month low + close > upper BB + volume surge."""
    if i < 1: return False
    if np.isnan(ind["bbw"][i]) or np.isnan(ind["bb_upper"][i]): return False
    if np.isnan(ind["vol_sma50"][i]): return False
    return (ind["bbw_squeeze"][i]
            and ind["close"][i] > ind["bb_upper"][i]
            and ind["volume"][i] > 1.5 * ind["vol_sma50"][i])

def signal_t2(ind, i):
    """T2: T1 + KC squeeze gate.
    Same M1 breakout conditions BUT also require that BB was inside KC
    for ≥3 bars within the last 10 bars (genuine compression, not just low BBW)."""
    if not signal_t1(ind, i): return False
    return _had_kc_squeeze(ind, i, lookback=10, min_dur=3)

def signal_t3(ind, i):
    """T3: KC squeeze fire + upper BB breakout + volume.
    Squeeze must fire (BB exits KC after ≥3 bar squeeze), close > upper BB,
    volume > 1.5× SMA50. No BBW condition — KC squeeze replaces it."""
    if i < 3: return False
    if np.isnan(ind["bb_upper"][i]) or np.isnan(ind["vol_sma50"][i]): return False
    # Squeeze fire within last 3 bars (fire day or 1-2 bars after)
    fired = False
    for j in range(max(0, i - 2), i + 1):
        if ind["squeeze_fire"][j] and ind["squeeze_dur"][max(0,j-1)] >= 3:
            fired = True; break
    if not fired: return False
    return (ind["close"][i] > ind["bb_upper"][i]
            and ind["volume"][i] > 1.5 * ind["vol_sma50"][i])

def signal_t4(ind, i):
    """T4: T3 + CMF > 0 (full conviction).
    KC squeeze fire + upper BB breakout + volume surge + institutional flow."""
    if not signal_t3(ind, i): return False
    if np.isnan(ind["cmf"][i]): return False
    return ind["cmf"][i] > 0

def signal_t5(ind, i):
    """T5: T2 (BB+KC gate) + minimum 6-bar KC squeeze duration.
    Requires genuine long compression before breakout."""
    if not signal_t1(ind, i): return False
    return _had_kc_squeeze(ind, i, lookback=10, min_dur=6)

def signal_t6(ind, i):
    """T6: T5 + CMF > 0 (long squeeze + institutional flow).
    The highest-conviction tier: BBW squeeze + KC gate (6+ bars) + breakout
    + volume + CMF positive."""
    if not signal_t5(ind, i): return False
    if np.isnan(ind["cmf"][i]): return False
    return ind["cmf"][i] > 0

def signal_t7(ind, i):
    """T7: T6 + squeeze intensity filter.
    Require BB width < 70% of KC width (deep compression)."""
    if not signal_t6(ind, i): return False
    if np.isnan(ind["kc_upper"][i]) or np.isnan(ind["kc_lower"][i]): return False
    kc_width = ind["kc_upper"][i] - ind["kc_lower"][i]
    bb_width = ind["bb_upper"][i] - ind["bb_lower"][i]
    if kc_width <= 0: return False
    intensity = 1 - (bb_width / kc_width)
    return intensity >= 0.3  # BB is at least 30% narrower than KC


# ── Walk-forward backtest engine ────────────────────────────────

STOP_ATR_MULT = 2.0
TARGET_ATR_MULT = 3.0
MAX_HOLD = 30  # bars

def run_backtest(ind, signal_fn, dates):
    n = len(ind["close"])
    trades = []
    in_trade = False
    entry_price = stop = target = entry_idx = 0
    squeeze_dur_at_entry = 0

    for i in range(150, n):
        if in_trade:
            # check exit
            if ind["high"][i] >= target:
                trades.append(_trade(ind, dates, entry_idx, i, target, "WIN",
                                     entry_price, stop, squeeze_dur_at_entry))
                in_trade = False
            elif ind["low"][i] <= stop:
                trades.append(_trade(ind, dates, entry_idx, i, stop, "LOSS",
                                     entry_price, stop, squeeze_dur_at_entry))
                in_trade = False
            elif (i - entry_idx) >= MAX_HOLD:
                result = "TIMEOUT_WIN" if ind["close"][i] > entry_price else "TIMEOUT_LOSS"
                trades.append(_trade(ind, dates, entry_idx, i, ind["close"][i], result,
                                     entry_price, stop, squeeze_dur_at_entry))
                in_trade = False
        else:
            if signal_fn(ind, i):
                atr = ind["atr14"][i]
                if np.isnan(atr) or atr <= 0: continue
                entry_price = ind["close"][i]
                stop = entry_price - STOP_ATR_MULT * atr
                target = entry_price + TARGET_ATR_MULT * atr
                entry_idx = i
                squeeze_dur_at_entry = ind["squeeze_dur"][i-1] if i > 0 else 0
                in_trade = True
    return trades

def _trade(ind, dates, ei, xi, exit_price, result, entry_price, stop, sq_dur):
    risk = entry_price - stop
    if risk <= 0: risk = 0.01
    r_mult = (exit_price - entry_price) / risk
    pnl_pct = (exit_price - entry_price) / entry_price * 100
    return {
        "entry_date": str(dates[ei])[:10],
        "exit_date": str(dates[xi])[:10],
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "stop": round(stop, 2),
        "pnl_pct": round(pnl_pct, 2),
        "r_multiple": round(r_mult, 3),
        "bars_held": xi - ei,
        "result": result,
        "squeeze_duration": sq_dur,
    }


# ── Stats computation ───────────────────────────────────────────

def compute_stats(trades):
    if not trades:
        return {"total": 0, "win_rate": 0, "profit_factor": 0, "expectancy_r": 0,
                "avg_pnl_pct": 0, "avg_winner_pct": 0, "avg_loser_pct": 0,
                "avg_r": 0, "avg_bars": 0, "max_consec_wins": 0, "max_consec_losses": 0,
                "by_squeeze_duration": {}}

    wins = [t for t in trades if t["result"] in ("WIN", "TIMEOUT_WIN")]
    losses = [t for t in trades if t["result"] in ("LOSS", "TIMEOUT_LOSS")]
    total = len(trades)

    total_win_pnl = sum(t["pnl_pct"] for t in wins) if wins else 0
    total_loss_pnl = abs(sum(t["pnl_pct"] for t in losses)) if losses else 0

    # Max consecutive
    max_cw = max_cl = cw = cl = 0
    for t in trades:
        if t["result"] in ("WIN", "TIMEOUT_WIN"):
            cw += 1; cl = 0
            max_cw = max(max_cw, cw)
        else:
            cl += 1; cw = 0
            max_cl = max(max_cl, cl)

    # By squeeze duration bucket
    buckets = {"1-3 bars": [], "4-6 bars": [], "7-10 bars": [], "10+ bars": []}
    for t in trades:
        sd = t.get("squeeze_duration", 0)
        if sd <= 3: buckets["1-3 bars"].append(t)
        elif sd <= 6: buckets["4-6 bars"].append(t)
        elif sd <= 10: buckets["7-10 bars"].append(t)
        else: buckets["10+ bars"].append(t)

    by_dur = {}
    for label, trs in buckets.items():
        if not trs: continue
        w = len([t for t in trs if t["result"] in ("WIN", "TIMEOUT_WIN")])
        by_dur[label] = {
            "trades": len(trs),
            "win_rate": round(w / len(trs) * 100, 1),
            "avg_pnl": round(np.mean([t["pnl_pct"] for t in trs]), 2),
        }

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 1),
        "profit_factor": round(total_win_pnl / max(total_loss_pnl, 0.01), 2),
        "expectancy_r": round(np.mean([t["r_multiple"] for t in trades]), 3),
        "avg_pnl_pct": round(np.mean([t["pnl_pct"] for t in trades]), 2),
        "total_pnl_pct": round(sum(t["pnl_pct"] for t in trades), 1),
        "avg_winner_pct": round(np.mean([t["pnl_pct"] for t in wins]), 2) if wins else 0,
        "avg_loser_pct": round(np.mean([t["pnl_pct"] for t in losses]), 2) if losses else 0,
        "avg_r": round(np.mean([t["r_multiple"] for t in trades]), 3),
        "avg_bars": round(np.mean([t["bars_held"] for t in trades]), 1),
        "max_consec_wins": max_cw,
        "max_consec_losses": max_cl,
        "best_trade_pct": round(max(t["pnl_pct"] for t in trades), 2),
        "worst_trade_pct": round(min(t["pnl_pct"] for t in trades), 2),
        "by_squeeze_duration": by_dur,
    }


# ── Main ────────────────────────────────────────────────────────

def main():
    tickers = sorted(get_all_tickers_from_csv(CSV_DIR))
    print(f"Loading {len(tickers)} tickers from {CSV_DIR}")

    signal_fns = {
        "T1_BB_Only": signal_t1,
        "T2_BB+KC_gate": signal_t2,
        "T5_BB+KC_6bar": signal_t5,
        "T6_BB+KC_6bar+CMF": signal_t6,
        "T7_BB+KC_deep+CMF": signal_t7,
    }

    all_trades = {k: [] for k in signal_fns}
    processed = 0
    skipped = 0
    t0 = time.time()

    for ticker in tickers:
        csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
        if not os.path.exists(csv_path):
            csv_path = os.path.join(CSV_DIR, f"{ticker}.NS.csv")
        if not os.path.exists(csv_path):
            skipped += 1
            continue

        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"])
            if len(df) < 200: skipped += 1; continue
            df = df.dropna(subset=["Close"])
            df = df[df["Close"] > 0].reset_index(drop=True)
            if len(df) < 200: skipped += 1; continue
        except Exception:
            skipped += 1; continue

        try:
            ind = compute_indicators(df)
            dates = df["Date"].values
        except Exception:
            skipped += 1; continue

        for tier, fn in signal_fns.items():
            trades = run_backtest(ind, fn, dates)
            for t in trades:
                t["ticker"] = ticker
            all_trades[tier].extend(trades)

        processed += 1
        if processed % 200 == 0:
            elapsed = time.time() - t0
            print(f"  {processed}/{len(tickers)} tickers processed ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nDone: {processed} tickers processed, {skipped} skipped in {elapsed:.0f}s\n")
    print("=" * 80)

    results = {}
    for tier in signal_fns:
        stats = compute_stats(all_trades[tier])
        results[tier] = stats

        print(f"\n{'─' * 60}")
        print(f"  {tier}")
        print(f"{'─' * 60}")
        print(f"  Total Trades:      {stats['total']:,}")
        print(f"  Wins / Losses:     {stats.get('wins',0):,} / {stats.get('losses',0):,}")
        print(f"  Win Rate:          {stats['win_rate']}%")
        print(f"  Profit Factor:     {stats['profit_factor']}")
        print(f"  Expectancy:        {stats['expectancy_r']:+.3f} R")
        print(f"  Avg PnL/Trade:     {stats['avg_pnl_pct']:+.2f}%")
        print(f"  Total PnL:         {stats.get('total_pnl_pct',0):+.1f}%")
        print(f"  Avg Winner:        {stats['avg_winner_pct']:+.2f}%")
        print(f"  Avg Loser:         {stats['avg_loser_pct']:+.2f}%")
        print(f"  Avg R-Multiple:    {stats['avg_r']:+.3f}")
        print(f"  Avg Bars Held:     {stats['avg_bars']}")
        print(f"  Max Consec Wins:   {stats['max_consec_wins']}")
        print(f"  Max Consec Losses: {stats['max_consec_losses']}")
        if stats['total']:
            print(f"  Best Trade:        {stats['best_trade_pct']:+.2f}%")
            print(f"  Worst Trade:       {stats['worst_trade_pct']:+.2f}%")

        if stats.get("by_squeeze_duration"):
            print(f"\n  By Squeeze Duration:")
            for label, bd in stats["by_squeeze_duration"].items():
                print(f"    {label:>12s}: {bd['trades']:>5d} trades | {bd['win_rate']:>5.1f}% WR | {bd['avg_pnl']:+.2f}% avg")

    # Comparison table
    print(f"\n\n{'=' * 80}")
    print(f"  COMPARISON TABLE")
    print(f"{'=' * 80}")
    print(f"  {'Tier':<22s} {'Trades':>7s} {'WR%':>7s} {'PF':>7s} {'Exp(R)':>8s} {'Avg%':>8s} {'Total%':>10s}")
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*10}")
    for tier in signal_fns:
        s = results[tier]
        print(f"  {tier:<22s} {s['total']:>7,d} {s['win_rate']:>6.1f}% {s['profit_factor']:>7.2f} {s['expectancy_r']:>+7.3f} {s['avg_pnl_pct']:>+7.2f}% {s.get('total_pnl_pct',0):>+9.1f}%")

    # Save results
    out_path = os.path.join(ROOT, "backtest_bb_kc_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
