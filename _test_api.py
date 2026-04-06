"""Test: hit the Flask API and check delivery fields."""
import requests, json
r = requests.get("http://localhost:5001/api/analyze/RELIANCE.NS", timeout=120)
d = r.json()
f = d.get("fundamentals", {})
for k in ["delivery_pct","delivery_quantity","traded_quantity","delivery_date"]:
    print(f"{k}: {f.get(k)}")
ana = f.get("delivery_analysis") or ""
print(f"delivery_analysis: {ana[:300]}")
print(f"error: {f.get('error','none')}")
