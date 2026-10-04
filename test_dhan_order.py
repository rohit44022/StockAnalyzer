"""Quick test: POST a minimal order to Dhan API v2 to debug DH-905.
Run: .venv/bin/python test_dhan_order.py
"""
import socket
import json
import os
import sys

# Force IPv4
_orig = socket.getaddrinfo
def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4

import requests
from dotenv import load_dotenv
load_dotenv()

CID = os.getenv("DHAN_CLIENT_ID")
TOK = os.getenv("DHAN_ACCESS_TOKEN")
BASE = "https://api.dhan.co/v2"
HEADERS = {
    "access-token": TOK,
    "client-id": CID,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Pick a known liquid stock: RELIANCE = 2885
SID = "2885"

print(f"Client ID: {CID}")
print(f"Token (last 20): ...{TOK[-20:]}")
print()

# Test 1: GET orders (should work)
print("=== Test 1: GET /orders (read-only) ===")
r = requests.get(f"{BASE}/orders", headers=HEADERS, timeout=10)
print(f"  Status: {r.status_code}")
print(f"  Body:   {r.text[:200]}")
print()

# Test 2: POST /orders — matching docs format EXACTLY
print("=== Test 2: POST /orders (docs-exact format) ===")
payload_docs = {
    "dhanClientId": CID,
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "INTRADAY",
    "orderType": "LIMIT",
    "validity": "DAY",
    "securityId": SID,
    "quantity": 1,
    "price": 1.0,
    "disclosedQuantity": 0,
    "afterMarketOrder": False,
    "amoTime": "OPEN",
    "boProfitValue": 0,
    "boStopLossValue": 0,
}
body = json.dumps(payload_docs)
print(f"  Payload: {body}")
r = requests.post(f"{BASE}/orders", data=body, headers=HEADERS, timeout=10)
print(f"  Status:  {r.status_code}")
print(f"  Body:    {r.text[:300]}")
print()

# Test 3: POST /orders — minimal payload (our format)
print("=== Test 3: POST /orders (our minimal format) ===")
payload_ours = {
    "dhanClientId": CID,
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "INTRADAY",
    "orderType": "MARKET",
    "validity": "DAY",
    "securityId": SID,
    "quantity": 1,
    "price": 0.0,
    "triggerPrice": 0.0,
}
body = json.dumps(payload_ours)
print(f"  Payload: {body}")
r = requests.post(f"{BASE}/orders", data=body, headers=HEADERS, timeout=10)
print(f"  Status:  {r.status_code}")
print(f"  Body:    {r.text[:300]}")
print()

# Test 4: POST /orders — without dhanClientId (SDK adds it)
print("=== Test 4: POST /orders (no dhanClientId) ===")
payload_no_cid = {
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "INTRADAY",
    "orderType": "LIMIT",
    "validity": "DAY",
    "securityId": SID,
    "quantity": 1,
    "price": 1.0,
}
body = json.dumps(payload_no_cid)
print(f"  Payload: {body}")
r = requests.post(f"{BASE}/orders", data=body, headers=HEADERS, timeout=10)
print(f"  Status:  {r.status_code}")
print(f"  Body:    {r.text[:300]}")
print()

# Test 5: Super Order
print("=== Test 5: POST /super/orders ===")
payload_super = {
    "dhanClientId": CID,
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "INTRADAY",
    "orderType": "LIMIT",
    "securityId": SID,
    "quantity": 1,
    "price": 1300.0,
    "targetPrice": 1350.0,
    "stopLossPrice": 1280.0,
    "trailingJump": 0.0,
}
body = json.dumps(payload_super)
print(f"  Payload: {body}")
r = requests.post(f"{BASE}/super/orders", data=body, headers=HEADERS, timeout=10)
print(f"  Status:  {r.status_code}")
print(f"  Body:    {r.text[:300]}")
print()

print("Done. If ALL POST tests return DH-905, the issue is the token or account,")
print("not the payload. Regenerate the access token on Dhan portal.")
