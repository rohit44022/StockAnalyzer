"""
Chain storage: SQLite backend for historical option chain snapshots.

Tier 1 (FREE): NSE Bhavcopy — daily OHLC + OI per contract.
  Available ~2011+ from NSE archives. No bid-ask, LTP only.

Tier 2 (FREE): Periodic live snapshots via NSE/broker API.
  Captures bid-ask-qty at snapshot time. 5-15 min intervals.

Storage: SQLite (~50 MB/day for Nifty+BankNifty 5-min snapshots).
1 year of Tier 1 ≈ 3 GB. Compressed ≈ under 1 GB.

Bhavcopy limitation: LTP-based, no bid-ask.
  ATM Nifty/BankNifty spread: ~₹0.05 (1 tick)
  1 OTM: 1-2 ticks
  Deep OTM: 3-10+ ticks
  chain_store.estimate_spread() provides conservative estimates.
"""

import os
import sqlite3
import datetime
import logging
import pandas as pd
import numpy as np

log = logging.getLogger(__name__)

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_now_ist = lambda: datetime.datetime.now(_IST).replace(tzinfo=None)
_DEFAULT_DB = 'options_chain_store.db'


def _get_db_path(db_path=None):
    if db_path:
        return db_path
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, _DEFAULT_DB)


def init_db(db_path=None):
    """
    Initialize SQLite database with chain storage schema.

    Tables:
        chain_snapshot – timestamped chain rows
        bhavcopy       – daily bhavcopy data (OHLC + OI)
        metadata       – key-value store for last-update timestamps etc.
    """
    db = _get_db_path(db_path)
    conn = sqlite3.connect(db)
    try:
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS chain_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            expiry TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            ltp REAL,
            bid REAL,
            ask REAL,
            bid_qty INTEGER DEFAULT 0,
            ask_qty INTEGER DEFAULT 0,
            oi INTEGER,
            volume INTEGER,
            iv REAL,
            change_oi INTEGER DEFAULT 0,
            underlying_price REAL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS bhavcopy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            expiry TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            settle_price REAL,
            oi INTEGER,
            volume INTEGER,
            change_oi INTEGER DEFAULT 0,
            UNIQUE(date, symbol, expiry, strike, option_type)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            detail TEXT,
            UNIQUE(date, symbol, metric)
        )''')

        c.execute('''CREATE INDEX IF NOT EXISTS idx_snap_sym_exp
                     ON chain_snapshot(symbol, expiry, timestamp)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_bhav_sym_date
                     ON bhavcopy(symbol, date, expiry)''')
        # migrate existing DBs: add UNIQUE constraint via index (safe if table already has it)
        try:
            c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_bhav_unique
                         ON bhavcopy(date, symbol, expiry, strike, option_type)''')
        except sqlite3.IntegrityError:
            log.warning('bhavcopy has duplicates — run dedup before UNIQUE index can be added')

        try:
            c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_snap_unique
                         ON chain_snapshot(substr(timestamp,1,10), symbol, expiry, strike, option_type)''')
        except sqlite3.IntegrityError:
            log.warning('chain_snapshot has duplicates — run dedup before UNIQUE index can be added')

        conn.commit()
    finally:
        conn.close()
    return db


def store_snapshot(chain_df, symbol, timestamp=None, db_path=None):
    """
    Store a chain snapshot to SQLite.

    Parameters
    ----------
    chain_df : DataFrame – canonical chain schema
    symbol : str – 'NIFTY', 'BANKNIFTY', etc.
    timestamp : str or None – ISO timestamp (default: now)
    db_path : str or None
    """
    db = _get_db_path(db_path)
    if timestamp is None:
        timestamp = _now_ist().isoformat()

    conn = sqlite3.connect(db)
    try:
        for _, row in chain_df.iterrows():
            conn.execute(
                '''INSERT OR IGNORE INTO chain_snapshot
                   (timestamp, symbol, expiry, strike, option_type,
                    ltp, bid, ask, bid_qty, ask_qty, oi, volume, iv,
                    change_oi, underlying_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (timestamp, symbol, str(row.get('expiry', '')),
                 float(row['strike']), row['option_type'],
                 float(row.get('ltp', 0)), float(row.get('bid', 0)),
                 float(row.get('ask', 0)), int(row.get('bid_qty', 0)),
                 int(row.get('ask_qty', 0)), int(row.get('oi', 0)),
                 int(row.get('volume', 0)),
                 float(row.get('iv', 0)) if row.get('iv') == row.get('iv') else None,
                 int(row.get('change_oi', 0)),
                 float(row.get('underlying_price', 0)) if row.get('underlying_price') else None)
            )
        conn.commit()
    finally:
        conn.close()


def store_bhavcopy(bhav_df, db_path=None):
    """
    Store bhavcopy data to SQLite.

    Parameters
    ----------
    bhav_df : DataFrame with columns:
        date, symbol, expiry, strike, option_type,
        open, high, low, close, settle_price, oi, volume
    """
    db = _get_db_path(db_path)
    conn = sqlite3.connect(db)
    try:
        for _, row in bhav_df.iterrows():
            conn.execute(
                '''INSERT OR REPLACE INTO bhavcopy
                   (date, symbol, expiry, strike, option_type,
                    open, high, low, close, settle_price, oi, volume, change_oi)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (str(row['date']), row['symbol'], str(row['expiry']),
                 float(row['strike']), row['option_type'],
                 float(row.get('open', 0)), float(row.get('high', 0)),
                 float(row.get('low', 0)), float(row.get('close', 0)),
                 float(row.get('settle_price', 0)), int(row.get('oi', 0)),
                 int(row.get('volume', 0)), int(row.get('change_oi', 0)))
            )
        conn.commit()
    finally:
        conn.close()


def get_chain_snapshot(symbol, expiry=None, timestamp=None, db_path=None):
    """
    Retrieve latest chain snapshot from SQLite.

    Parameters
    ----------
    symbol : str
    expiry : str or date – filter to specific expiry (optional)
    timestamp : str – get snapshot nearest to this time (optional)
    db_path : str

    Returns
    -------
    DataFrame in canonical chain schema
    """
    db = _get_db_path(db_path)
    conn = sqlite3.connect(db)

    # Subquery for latest timestamp — avoids loading entire table
    ts_query = 'SELECT MAX(timestamp) FROM chain_snapshot WHERE symbol = ?'
    ts_params = [symbol]

    if expiry:
        ts_query += ' AND expiry = ?'
        ts_params.append(str(expiry))

    if timestamp:
        ts_query += ' AND timestamp <= ?'
        ts_params.append(timestamp)

    query = f'SELECT * FROM chain_snapshot WHERE symbol = ? AND timestamp = ({ts_query})'
    params = [symbol] + ts_params

    if expiry:
        query += ' AND expiry = ?'
        params.append(str(expiry))

    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df


def get_bhavcopy(symbol, date, expiry=None, db_path=None):
    """
    Retrieve bhavcopy data for a specific date.

    Returns
    -------
    DataFrame
    """
    db = _get_db_path(db_path)
    conn = sqlite3.connect(db)

    query = 'SELECT * FROM bhavcopy WHERE symbol = ? AND date = ?'
    params = [symbol, str(date)]

    if expiry:
        query += ' AND expiry = ?'
        params.append(str(expiry))

    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df


def estimate_spread(strike, spot, option_type='CE', oi=0, volume=0,
                    bid=None, ask=None):
    """
    Bid-ask spread: uses actual bid/ask when available, falls back to heuristic.

    Based on NSE empirical observations:
      ATM: 1 tick (₹0.05 for Nifty options)
      1 OTM: 1-2 ticks
      Deep OTM (>2% OTM): 2-5+ ticks

    OI/volume adjustment: high liquidity tightens spread, low widens it.

    Parameters
    ----------
    strike : float
    spot : float
    option_type : str
    oi : int – open interest (0 = use moneyness-only estimate)
    volume : int – day's traded volume
    bid : float or None – actual bid price from L2 data
    ask : float or None – actual ask price from L2 data

    Returns
    -------
    float – estimated half-spread (one-side cost in ₹)
    """
    if bid is not None and ask is not None and bid > 0 and ask > bid:
        return round((ask - bid) / 2, 2)

    moneyness = strike / spot
    if option_type == 'CE':
        otm_pct = max(0, moneyness - 1)
    else:
        otm_pct = max(0, 1 - moneyness)

    # base spread from moneyness
    if otm_pct < 0.005:
        base = 0.05
    elif otm_pct < 0.02:
        base = 0.10
    elif otm_pct < 0.05:
        base = 0.25
    else:
        base = 0.50 + otm_pct * 5.0

    # liquidity multiplier: high OI/volume tightens, low widens
    if oi > 0 or volume > 0:
        liq = max(oi, volume * 5)  # volume is more indicative of live liquidity
        if liq > 100000:
            multiplier = 0.7   # very liquid → tighter than base
        elif liq > 20000:
            multiplier = 1.0   # normal
        elif liq > 5000:
            multiplier = 1.5   # thin
        else:
            multiplier = 2.5   # illiquid → much wider
        base *= multiplier

    return round(base, 2)


def store_analytics(date, symbol, metrics, db_path=None):
    """
    Persist computed analytics to SQLite.

    Parameters
    ----------
    date : str or date – trading date
    symbol : str
    metrics : dict – {metric_name: value} or {metric_name: (value, detail_json)}
    db_path : str
    """
    db = _get_db_path(db_path)
    conn = sqlite3.connect(db)
    import json
    for metric, val in metrics.items():
        if isinstance(val, tuple):
            value, detail = val
        else:
            value, detail = val, None
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail)
        # NaN → None for SQLite
        if value != value:
            value = None
        conn.execute(
            '''INSERT OR REPLACE INTO analytics (date, symbol, metric, value, detail)
               VALUES (?, ?, ?, ?, ?)''',
            (str(date), symbol, metric, value, detail))
    try:
        conn.commit()
    finally:
        conn.close()


def get_analytics(symbol, metric=None, start_date=None, end_date=None, db_path=None):
    """
    Retrieve historical analytics.

    Returns DataFrame with columns: date, symbol, metric, value, detail
    """
    db = _get_db_path(db_path)
    conn = sqlite3.connect(db)

    query = 'SELECT date, symbol, metric, value, detail FROM analytics WHERE symbol = ?'
    params = [symbol]
    if metric:
        query += ' AND metric = ?'
        params.append(metric)
    if start_date:
        query += ' AND date >= ?'
        params.append(str(start_date))
    if end_date:
        query += ' AND date <= ?'
        params.append(str(end_date))
    query += ' ORDER BY date'

    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df


def db_stats(db_path=None):
    """Summary statistics of the chain store."""
    db = _get_db_path(db_path)
    if not os.path.exists(db):
        return {'exists': False}

    conn = sqlite3.connect(db)
    try:
        c = conn.cursor()

        stats = {'exists': True}
        c.execute('SELECT COUNT(*) FROM chain_snapshot')
        stats['snapshot_rows'] = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM bhavcopy')
        stats['bhavcopy_rows'] = c.fetchone()[0]
        c.execute('SELECT MIN(timestamp), MAX(timestamp) FROM chain_snapshot')
        row = c.fetchone()
        stats['snapshot_range'] = (row[0], row[1])
        c.execute('SELECT MIN(date), MAX(date) FROM bhavcopy')
        row = c.fetchone()
        stats['bhavcopy_range'] = (row[0], row[1])
    finally:
        conn.close()
    return stats


def _self_check():
    import tempfile
    db = os.path.join(tempfile.gettempdir(), 'test_chain_store.db')
    if os.path.exists(db):
        os.remove(db)

    # init
    init_db(db)

    # store snapshot
    chain = pd.DataFrame([
        {'strike': 24000, 'option_type': 'CE', 'expiry': '2026-10-08',
         'ltp': 150, 'bid': 149, 'ask': 151, 'oi': 50000, 'volume': 10000,
         'iv': 0.14, 'change_oi': 5000},
        {'strike': 24000, 'option_type': 'PE', 'expiry': '2026-10-08',
         'ltp': 120, 'bid': 119, 'ask': 121, 'oi': 40000, 'volume': 8000,
         'iv': 0.15, 'change_oi': -2000},
    ])
    store_snapshot(chain, 'NIFTY', '2026-10-06T15:30:00', db)

    # retrieve
    result = get_chain_snapshot('NIFTY', db_path=db)
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    assert result.iloc[0]['strike'] == 24000

    # spread estimate
    assert estimate_spread(24000, 24000) == 0.05  # ATM, no liquidity data
    assert estimate_spread(25000, 24000) > 0.10   # OTM
    assert estimate_spread(24000, 24000, oi=200000) < estimate_spread(24000, 24000, oi=1000)  # liquid < illiquid

    # stats
    s = db_stats(db)
    assert s['exists'] is True
    assert s['snapshot_rows'] == 2

    os.remove(db)
    print("chain_store.py: all checks passed")


if __name__ == '__main__':
    _self_check()
