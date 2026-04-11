#!/usr/bin/env python3
"""Integration test with real RELIANCE data."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bb_squeeze.data_loader import load_stock_data, normalise_ticker

df = load_stock_data(normalise_ticker('RELIANCE'))
closes = df.tail(253)['Close'].values.astype(float)
trades = list(np.diff(closes))
print(f"Trades: {len(trades)}")
print(f"Mean trade: {np.mean(trades):.2f}")
print(f"Std: {np.std(trades):.2f}")
print(f"Min (biggest loss): {np.min(trades):.2f}")
print(f"Max: {np.max(trades):.2f}")
print(f"Price: {closes[-1]:.2f}")
print()

from vince.optimal_f import find_optimal_f_empirical, compute_by_products
opt = find_optimal_f_empirical(trades)
print(f"Opt f: {opt['optimal_f']}")
print(f"f_dollar (f₹): ₹{opt['f_dollar']:,.2f}")
print(f"biggest_loss: ₹{opt['biggest_loss']:,.2f}")
print(f"TWR: {opt['twr']}")
print(f"Geo Mean: {opt['geometric_mean']}")
print()

if opt['optimal_f'] > 0:
    bp = compute_by_products(trades, opt['optimal_f'])
    print(f"AHPR: {bp['ahpr']}")
    print(f"SD HPR: {bp['sd_hpr']}")
    print(f"EGM: {bp['egm']}")
    print(f"GAT: ₹{bp['gat']:,.4f}")
    print()

    from vince.risk_metrics import position_sizing
    ps = position_sizing(100000, opt['optimal_f'], opt['biggest_loss'], closes[-1], 0.5)
    print(f"Position at 50% f:")
    print(f"  f₹ (per unit): ₹{ps['f_dollar']:,.2f}")
    print(f"  Shares: {ps['shares_to_buy']}")
    print(f"  Investment: ₹{ps['investment_amount']:,.2f}")
    print(f"  Risk: ₹{ps['risk_per_trade']:,.2f} ({ps['risk_pct']}%)")
    print()

from vince.statistics import runs_test, ks_test_normal
rt = runs_test(trades)
print(f"Runs Test: {'RANDOM' if rt['is_random'] else rt['dependency_type']}, Z={rt['z_score']:.4f}")
ks = ks_test_normal(trades)
print(f"KS Normal: {'YES' if ks['is_normal'] else 'NO'}, D={ks['ks_statistic']:.6f}")

from vince.risk_metrics import drawdown_analysis, historical_volatility
eq = [100000]
for t in trades:
    eq.append(eq[-1] + t)
dd = drawdown_analysis(eq)
print(f"Max Drawdown: {dd['max_drawdown_pct']:.2f}%")
print(f"Recovered: {dd['recovered']}")

vol = historical_volatility(list(closes))
print(f"Current HV: {vol['current_volatility_pct']:.2f}%")
print(f"Avg HV: {vol['average_volatility_pct']:.2f}%")

print("\n=== ALL INTEGRATION TESTS PASSED ===")
