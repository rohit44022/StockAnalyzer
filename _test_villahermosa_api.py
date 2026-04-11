"""Test the /api/triple/analyze endpoint for Villahermosa data."""
import json, urllib.request, sys

url = 'http://127.0.0.1:5001/api/triple/analyze?ticker=RELIANCE.NS'
print(f"Fetching: {url}")
try:
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = json.loads(resp.read())
except Exception as e:
    print(f"ERROR fetching API: {e}")
    sys.exit(1)

wk = data.get('wyckoff', {})
v = wk.get('villahermosa', {})
if not v:
    print('ERROR: No villahermosa key in API response!')
    print('Wyckoff keys:', list(wk.keys())[:10])
    sys.exit(1)

print('=== VILLAHERMOSA DATA CHECK ===')
for key in sorted(v.keys()):
    val = v[key]
    if isinstance(val, dict):
        print(f'  {key}: dict({len(val)} keys) -> {list(val.keys())[:5]}')
    elif isinstance(val, list):
        print(f'  {key}: list({len(val)} items)')
    else:
        print(f'  {key}: {repr(val)[:60]}')

print(f'\nTotal keys: {len(v)}')
print(f'Composite Man: {v.get("composite_man",{}).get("action","MISSING")}')
print(f'Schematic: {v.get("schematic",{}).get("type","MISSING")}')
tz = v.get("trading_zone", {})
print(f'Trading Zone: {tz.get("zone","?")} — {tz.get("name","MISSING")}')
print(f'Phase letter: {v.get("phase_letter","MISSING")}')
print(f'Last event: {v.get("last_event","MISSING")}')
print(f'Next expected: {v.get("next_expected","MISSING")}')
ec = v.get("entry_context", {})
print(f'Entry: {ec.get("type","MISSING")}')
print(f'Stop rules: {len(v.get("stop_rules",[]))} rules')
print(f'Exit rules: {len(v.get("exit_rules",[]))} rules')
print(f'DNT reasons: {len(v.get("do_not_trade",[]))} reasons')
print(f'Creek: {v.get("creek_ice",{}).get("creek","MISSING")}')
print(f'Ice: {v.get("creek_ice",{}).get("ice","MISSING")}')
print(f'Phase volume: {v.get("phase_volume",{}).get("assessment","MISSING")}')
tl = v.get("three_laws", {})
print(f'3 Laws S/D: {tl.get("supply_demand","MISSING")}')
print(f'3 Laws C/E: {tl.get("cause_effect","MISSING")}')
print(f'3 Laws E/R: {tl.get("effort_result","MISSING")}')

# Check all required keys
required = [
    'composite_man', 'three_laws', 'creek_ice', 'schematic',
    'trading_zone', 'reaccum_dist', 'failed_structure', 'phase_volume',
    'phase_letter', 'last_event', 'next_expected', 'entry_context',
    'stop_rules', 'exit_rules', 'do_not_trade'
]
missing = [k for k in required if k not in v]
if missing:
    print(f'\nMISSING KEYS: {missing}')
    sys.exit(1)

print(f'\n✅ ALL {len(required)} Villahermosa sections present in live API response!')
