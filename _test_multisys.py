"""Quick test: verify multi-system analysis in portfolio API."""
import json, urllib.request

url = "http://127.0.0.1:5001/api/portfolio/6/analyze"
r = urllib.request.urlopen(url, timeout=120)
d = json.loads(r.read())

ms = d.get("multi_system", {})
if not ms:
    print("ERROR: no multi_system key")
    print("Keys:", list(d.keys()))
    exit(1)

print("=== MULTI SYSTEM KEYS:", list(ms.keys()))

# Hybrid
h = ms.get("hybrid", {})
print(f"\nHYBRID: verdict={h.get('verdict')} score={h.get('score')}/{h.get('max_score')} conf={h.get('confidence')}%")
print(f"  bb={h.get('bb_score')} ta={h.get('ta_score')} ta_verdict={h.get('ta_verdict')}")

# Triple
t = ms.get("triple", {})
print(f"\nTRIPLE: verdict={t.get('verdict')} score={t.get('score')}/{t.get('max_score')} conf={t.get('confidence')}%")
print(f"  bb={t.get('bb_score')} ta={t.get('ta_score')} pa={t.get('pa_score')}")

# Price Action
pa = ms.get("price_action", {})
print(f"\nPA: signal={pa.get('signal')} setup={pa.get('setup')} strength={pa.get('strength')}")
print(f"  always_in={pa.get('always_in')} trend={pa.get('trend')} conf={pa.get('confidence')}%")
print(f"  stop={pa.get('stop_loss')} t1={pa.get('target_1')} t2={pa.get('target_2')}")
print(f"  bar={pa.get('bar_type')}: {pa.get('bar_desc')}")
print(f"  patterns={pa.get('patterns')}")
print(f"  context={pa.get('context')[:120] if pa.get('context') else 'N/A'}")

# Master Summary
s = ms.get("master_summary", {})
print(f"\nMASTER SUMMARY:")
print(f"  consensus={s.get('consensus')} direction={s.get('direction')} action={s.get('action_word')}")
print(f"  agreement={s.get('agreement')} avg_conf={s.get('avg_confidence')}%")
print(f"  votes={s.get('votes')}")
print(f"  Plain-language advice:")
for line in s.get("plain_text", []):
    print(f"    → {line}")

print("\n✅ All multi-system data present!")
