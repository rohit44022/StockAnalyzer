#!/usr/bin/env python3
"""Quick test for vince package."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vince.optimal_f import find_optimal_f_empirical, compute_by_products, f_curve_data, fractional_f_analysis
from vince.statistics import runs_test, serial_correlation, ks_test_normal, compute_moments, arc_sine_analysis, turning_points_test
from vince.risk_metrics import drawdown_analysis, position_sizing, historical_volatility, time_to_goal
from vince.portfolio_math import compute_correlation_matrix, compute_covariance_matrix, compute_efficient_frontier
print("All vince modules imported successfully!")

import random
random.seed(42)
trades = [random.gauss(2, 15) for _ in range(100)]

opt = find_optimal_f_empirical(trades)
print(f"Optimal f: {opt['optimal_f']:.4f}")
print(f"TWR: {opt['twr']:.4f}")
print(f"Geometric Mean: {opt['geometric_mean']:.6f}")

bp = compute_by_products(trades, opt["optimal_f"])
print(f"BP Geometric Mean: {bp['geometric_mean']:.6f}")
print(f"AHPR: {bp['ahpr']:.6f}")

rt = runs_test(trades)
print(f"Runs Test Z: {rt['z_score']:.4f}, Random: {rt['is_random']}")

ks = ks_test_normal(trades)
print(f"K-S Normal: {ks['is_normal']}")

dd = drawdown_analysis([100000 + sum(trades[:i]) for i in range(len(trades)+1)])
print(f"Max DD: {dd['max_drawdown_pct']:.2f}%")

ps = position_sizing(100000, opt["optimal_f"], opt["biggest_loss"], 500, 0.5)
print(f"Shares to buy: {ps['shares_to_buy']}")

fc = f_curve_data(trades, 30)
print(f"f-curve points: {len(fc['f_values'])}")

frac = fractional_f_analysis(bp["ahpr"], bp["sd_hpr"], opt["optimal_f"], opt["biggest_loss"])
print(f"Fractional f entries: {len(frac['fractions'])}")

sc = serial_correlation(trades)
print(f"Serial Corr: {sc['correlation']:.4f}")

mom = compute_moments(trades)
print(f"Skewness: {mom['skewness']:.4f}, Kurtosis: {mom['kurtosis']:.4f}")

tp = turning_points_test(trades)
print(f"Turning Points: {tp['turning_points']}, Z: {tp['z_score']:.4f}")

arc = arc_sine_analysis(len(trades))
print(f"Arc Sine extreme prob: {arc['prob_extreme']:.4f}")

print("\nAll tests passed!")
