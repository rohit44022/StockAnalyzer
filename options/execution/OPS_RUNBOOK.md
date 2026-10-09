# VM Migration & Disaster Recovery Runbook

## VM Setup (Fresh Deploy)

### Requirements
- Ubuntu 22.04+ or macOS (arm64/x86)
- Python 3.11+, SQLite 3.35+
- Static IP (Dhan API requires whitelisted IP for order mutations)
- Cron (systemd-timer or launchd as alternative)

### Steps
```bash
# 1. Clone + venv
git clone <repo> && cd historical_data
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Credentials
cp .env.example .env
chmod 600 .env
# Edit: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, AUTOPILOT_API_TOKEN

# 3. Validate
python -m options.autopilot check_env
python -m options.autopilot selfcheck
python -m options.paper_trade selfcheck

# 4. Restore DB (if migrating)
scp old-vm:~/historical_data/options/paper_trades.db options/
python -m options.autopilot status  # verify trade count

# 5. Install cron
python -m options.autopilot enable
python -m options.autopilot cron    # verify schedule
crontab -l                          # confirm installed

# 6. Whitelist new IP on Dhan
# Login to Dhan web → Settings → API → Update allowed IPs
```

### Dhan Token Refresh (Daily)
Token is a JWT valid ~24h. No programmatic refresh — manual web login required.
```bash
# Check remaining hours:
python -m options.autopilot check_env
# If expired: login at partners.dhan.co, copy new token to .env
```

---

## Disaster Recovery

### Scenario 1: VM Crash (Unplanned)

**Priority**: Close open live positions manually via Dhan app.

```bash
# On new VM after restore:
python -m options.autopilot status          # check open positions
python -m options.autopilot reconcile       # compare DB vs Dhan
# If positions exist on Dhan but not in DB:
#   → close manually via Dhan app/web
# If DB shows positions but Dhan doesn't:
#   → paper-exit them: python -m options.paper_trade exit <id> --reason "DR recovery"
```

### Scenario 2: DB Corruption

```bash
# Backups are in options/backups/paper_trades_YYYY-MM-DD.db (7 days retained)
cp options/backups/paper_trades_2026-10-08.db options/paper_trades.db
python -m options.autopilot reconcile  # verify against Dhan
```

### Scenario 3: Token Expired During Market Hours

Autopilot preflight blocks cycles when JWT <4h remaining.
```bash
# 1. Refresh token at partners.dhan.co
# 2. Update .env with new DHAN_ACCESS_TOKEN
# 3. Verify: python -m options.autopilot check_env
# 4. Autopilot resumes on next cron tick
```

### Scenario 4: RESIDUAL Position (Partial Fill)

Autopilot retries 3x (LIMIT), then escalates to MARKET order.
If all retries fail, EMERGENCY alert fires → manual exit required.
```bash
# Check status:
python -m options.autopilot alerts -u
# Manual exit via Dhan app, then update DB:
python -m options.paper_trade exit <trade_id> --reason "Manual RESIDUAL unwind"
```

### Scenario 5: Emergency — Close Everything

```bash
python -m options.autopilot emergency
# This:
#   1. Activates Dhan kill switch (blocks new orders)
#   2. Exits all live positions at MARKET
#   3. Paper-closes all open trades
#   4. Disables autopilot
```

---

## Monitoring Checklist (Daily)

| Check | Command | Expected |
|---|---|---|
| Token valid | `check_env` | OK, >4h remaining |
| No unacked alerts | `alerts -u` | 0 alerts |
| Cycle ran today | `status` | Last cycle within 1h |
| Positions reconcile | `reconcile` | 0 mismatches, 0 phantoms |
| DB backed up | `ls options/backups/` | Today's date present |

## Cron Schedule (12 scans/day)

Default scan times: `09:45 10:30 11:30 13:00 14:00 15:20` IST.
EOD cycle auto-detects from time (after 15:00).

```
# Verify:
python -m options.autopilot cron
# Manual trigger:
python -m options.autopilot run morning
python -m options.autopilot run eod
```
