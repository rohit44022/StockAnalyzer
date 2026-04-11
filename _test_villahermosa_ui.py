"""Quick test to verify Villahermosa backend enrichment produces valid data."""
from wyckoff.engine import wyckoff_to_dict, WyckoffResult
from wyckoff.phases import WyckoffPhase, WyckoffEvent
from wyckoff.volume_analysis import VolumeCharacter

class MockWave:
    def __init__(self, d, b, pm, cv, sp, ep):
        self.direction = d
        self.bars = b
        self.price_move = pm
        self.cum_volume = cv
        self.start_price = sp
        self.end_price = ep

# Test 1: Accumulation with Spring + SOS
phase = WyckoffPhase(
    phase='ACCUMULATION', sub_phase='LATE', confidence=85.0,
    events=[
        WyckoffEvent('SPRING', 50, 80.0, 100.5, 1.5, 'Spring detected', True),
        WyckoffEvent('SOS', 55, 75.0, 105.0, 1.8, 'SOS detected', True),
    ],
    support=98.0, resistance=108.0,
    description='Accumulation with Spring confirmed'
)
vol = VolumeCharacter('ABOVE_AVG', 1.6, 'INCREASING', 'Above average volume')
waves = [
    MockWave('UP', 5, 3.5, 500000, 100, 103.5),
    MockWave('DOWN', 3, 1.2, 200000, 103.5, 102.3),
    MockWave('UP', 4, 4.0, 600000, 102.3, 106.3),
    MockWave('DOWN', 2, 0.8, 150000, 106.3, 105.5),
]
result = WyckoffResult(
    phase=phase, volume_character=vol,
    wave_balance={'balance': 'DEMAND_DOMINANT', 'ratio': 2.5,
                  'up_volume': 1100000, 'down_volume': 350000,
                  'description': 'Buyers clearly dominant'},
    shortening={'detected': False, 'direction': '', 'waves_analyzed': 0,
                'thrust_ratio': 0, 'severity': ''},
    effort_result=[], waves=waves,
    follow_through={}, wyckoff_bonus=18, bias='BULLISH',
    summary='Accumulation with Spring confirmed',
    hints=['LPS entry zone approaching'],
    source_labels=[]
)
d = wyckoff_to_dict(result)
v = d['villahermosa']

assert v['composite_man']['action'] == 'ACCUMULATING', f"Expected ACCUMULATING, got {v['composite_man']['action']}"
assert v['schematic']['type'] == 'ACCUMULATION_1', f"Expected ACCUMULATION_1, got {v['schematic']['type']}"
assert v['trading_zone']['zone'] == 2, f"Expected zone 2, got {v['trading_zone']['zone']}"
assert v['phase_letter'] == 'D', f"Expected D, got {v['phase_letter']}"
assert v['last_event'] == 'SOS', f"Expected SOS, got {v['last_event']}"
assert v['entry_context']['type'] == 'LPS_BUEC_BUY', f"Expected LPS_BUEC_BUY, got {v['entry_context']['type']}"
assert len(v['stop_rules']) >= 2, f"Expected >=2 stop rules, got {len(v['stop_rules'])}"
assert len(v['exit_rules']) >= 1, f"Expected >=1 exit rules"
assert v['creek_ice']['creek'] == 108.0
assert v['creek_ice']['ice'] == 98.0
assert v['phase_volume']['assessment'] == 'WATCH', f"Expected WATCH (above avg in accum), got {v['phase_volume']['assessment']}"
assert v['three_laws']['supply_demand'] == 'DEMAND_DOMINANT'
assert v['failed_structure']['detected'] == False
print("Test 1 PASSED: Accumulation with Spring + SOS")

# Test 2: Distribution with Upthrust
phase2 = WyckoffPhase(
    phase='DISTRIBUTION', sub_phase='MIDDLE', confidence=70.0,
    events=[WyckoffEvent('UPTHRUST', 40, 72.0, 150.0, 2.0, 'Upthrust detected', False)],
    support=130.0, resistance=155.0,
    description='Distribution with Upthrust'
)
vol2 = VolumeCharacter('SPIKE', 2.5, 'INCREASING', 'Spike volume')
result2 = WyckoffResult(
    phase=phase2, volume_character=vol2,
    wave_balance={'balance': 'SUPPLY_DOMINANT', 'ratio': 0.6,
                  'up_volume': 300000, 'down_volume': 500000,
                  'description': 'Sellers dominant'},
    shortening={'detected': False}, effort_result=[], waves=waves,
    follow_through={}, wyckoff_bonus=-15, bias='BEARISH',
    summary='Distribution detected', hints=[], source_labels=[]
)
d2 = wyckoff_to_dict(result2)
v2 = d2['villahermosa']
assert v2['composite_man']['action'] == 'DISTRIBUTING'
assert v2['schematic']['type'] == 'DISTRIBUTION_1'
assert v2['trading_zone']['zone'] == 1
assert v2['entry_context']['type'] == 'UTAD_SELL'
assert 'Upthrust' in v2['composite_man']['counterparty']
print("Test 2 PASSED: Distribution with Upthrust")

# Test 3: Markup phase
phase3 = WyckoffPhase(
    phase='MARKUP', sub_phase='CONFIRMED', confidence=90.0,
    events=[], support=200.0, resistance=250.0,
    description='Strong uptrend'
)
vol3 = VolumeCharacter('ABOVE_AVG', 1.4, 'STABLE', 'Normal volume')
result3 = WyckoffResult(
    phase=phase3, volume_character=vol3,
    wave_balance={'balance': 'DEMAND_DOMINANT', 'ratio': 1.8,
                  'up_volume': 800000, 'down_volume': 450000},
    shortening={'detected': False}, effort_result=[], waves=waves,
    follow_through={}, wyckoff_bonus=12, bias='BULLISH',
    summary='Markup confirmed', hints=[], source_labels=[]
)
d3 = wyckoff_to_dict(result3)
v3 = d3['villahermosa']
assert v3['composite_man']['action'] == 'MARKING_UP'
assert v3['trading_zone']['zone'] == 3
assert v3['trading_zone']['name'] == 'Zone 3 — Phase E (Trend)'
assert v3['entry_context']['type'] == 'PHASE_E_LPS_BUY'
assert v3['phase_volume']['assessment'] == 'HEALTHY'
print("Test 3 PASSED: Markup phase")

# Test all keys exist
required_keys = [
    'composite_man', 'three_laws', 'creek_ice', 'schematic',
    'trading_zone', 'reaccum_dist', 'failed_structure', 'phase_volume',
    'phase_letter', 'last_event', 'next_expected', 'entry_context',
    'stop_rules', 'exit_rules', 'do_not_trade'
]
for key in required_keys:
    assert key in v, f"Missing key: {key}"
print(f"Test 4 PASSED: All {len(required_keys)} required keys present")

print("\n✅ ALL TESTS PASSED — Villahermosa backend enrichment working correctly!")
