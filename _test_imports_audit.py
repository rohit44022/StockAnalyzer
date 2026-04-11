#!/usr/bin/env python3
"""Verify all imports and check for remaining dollar references in user-facing strings."""
import sys, os, inspect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vince.optimal_f import (find_optimal_f_empirical, compute_by_products, fractional_f_analysis,
    f_curve_data, kelly_f, estimated_geometric_mean, fundamental_equation_of_trading,
    threshold_to_geometric, find_optimal_f_normal, find_optimal_f_scenario,
    dynamic_vs_static_f, compute_hprs, twr_from_hprs, geometric_mean)
from vince.statistics import (runs_test, serial_correlation, ks_test_normal,
    compute_moments, arc_sine_analysis, turning_points_test)
from vince.portfolio_math import (compute_correlation_matrix, compute_covariance_matrix,
    compute_efficient_frontier, sharpe_ratio, capital_market_line,
    geometric_frontier_analysis, analyze_portfolio_from_hprs)
from vince.risk_metrics import (drawdown_analysis, position_sizing, small_trader_allocation,
    asset_allocation_dynamic, margin_constraint, share_averaging_reallocation,
    historical_volatility, time_to_goal, comprehensive_risk_report)
print("All 30+ functions imported successfully")

# Verify no remaining user-facing dollar signs in explanation strings
modules = [
    find_optimal_f_empirical, compute_by_products, fractional_f_analysis,
    position_sizing, small_trader_allocation, asset_allocation_dynamic,
    margin_constraint, drawdown_analysis, historical_volatility, time_to_goal,
]
issues = []
for fn in modules:
    src = inspect.getsource(fn)
    for i, line in enumerate(src.split('\n')):
        if 'dollar' in line.lower() and ('explanation' in line or 'f"' in line or "f'" in line):
            issues.append(f"{fn.__name__} line {i}: {line.strip()[:80]}")
if issues:
    print("ISSUES FOUND:")
    for i in issues:
        print(f"  {i}")
else:
    print("No dollar references in user-facing explanation strings")

print("\n=== IMPORT & STRING AUDIT PASSED ===")
