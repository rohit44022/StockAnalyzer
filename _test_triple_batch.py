#!/usr/bin/env python3
"""Stress test: run triple engine on 10 major stocks."""
from bb_squeeze.data_loader import load_stock_data
from bb_squeeze.config import CSV_DIR
from hybrid_pa_engine import run_triple_analysis
import json

tickers = ['RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ICICIBANK.NS',
           'SBIN.NS', 'TATAMOTORS.NS', 'ADANIENT.NS', 'ITC.NS', 'BAJFINANCE.NS']
ok = 0
for t in tickers:
    df = load_stock_data(t, CSV_DIR)
    if df is None or df.empty:
        print(f'  {t}: NO DATA')
        continue
    r = run_triple_analysis(df, ticker=t)
    if 'error' in r:
        print(f'  {t}: ERROR - {r["error"]}')
        continue
    json.dumps(r)
    v = r['triple_verdict']
    c = r['cross_validation']
    print(f'  {t:20s} {v["verdict"]:20s} Score={v["score"]:+7.1f}  BB={r["bb_score"]["total"]:+6.1f}  TA={r["ta_score"]["total"]:+6.1f}  PA={r["pa_score"]["total"]:+6.1f}  Align={c["alignment"]}')
    ok += 1
print(f'\n  {ok}/{len(tickers)} passed')
