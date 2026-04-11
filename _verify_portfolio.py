import urllib.request, sys

html = urllib.request.urlopen('http://127.0.0.1:5001/portfolio').read().decode()
checks = [
    ('Educational Intro', 'HOW TO READ THIS ANALYSIS'),
    ('Strategy Bar Chart', 'strategyBarChart'),
    ('Confirm Donut Chart', 'confirmDonutChart'),
    ('RR Bar Chart', 'rrBarChart'),
    ('Vince Radar Chart', 'vinceRadarChart'),
    ('Vince Metric Bars', 'vinceMetricBars'),
    ('Vince Verdict Box', 'vinceVerdictBox'),
    ('Vince Educational Intro', 'WHAT IS THIS SECTION'),
    ('Optimal f tooltip', 'mathematically ideal fraction'),
    ('Kelly f tooltip', 'Kelly Criterion'),
    ('Geo Mean tooltip', 'average growth factor'),
    ('TWR tooltip', 'Terminal Wealth Relative'),
    ('Max DD tooltip', 'worst peak-to-valley'),
    ('Volatility tooltip', 'how wildly the stock'),
    ('Biggest Loss tooltip', 'largest amount this stock dropped'),
    ('Time to 2x tooltip', 'how many trading days'),
    ('Position Sizing hint', 'driving at half the speed'),
    ('Dependency hint', 'each coin flip'),
    ('renderStrategyBarChart', 'function renderStrategyBarChart'),
    ('renderConfirmDonut', 'function renderConfirmDonut'),
    ('renderRiskRewardChart', 'function renderRiskRewardChart'),
    ('renderVinceCharts', 'function renderVinceCharts'),
    ('vinceRadarInstance var', 'vinceRadarInstance'),
    ('Chart call wiring', 'renderVinceCharts(vr)'),
    ('RR call wiring', 'renderRiskRewardChart(tgt'),
]
ok = True
for name, pat in checks:
    found = pat in html
    s = '\u2705' if found else '\u274c'
    if not found: ok = False
    print(f'  {s} {name}')
print()
print(f'\u2705 ALL {len(checks)} CHECKS PASSED' if ok else '\u274c SOME CHECKS FAILED')
print(f'Total HTML lines: {len(html.splitlines())}')
