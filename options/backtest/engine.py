"""
Day-by-day options strategy backtester.

Fill simulation per ARCHITECTURE.md:
  Buy fill  = LTP + half_spread × slippage_mult
  Sell fill = LTP - half_spread × slippage_mult
  Volume < 5× lot_size → skip entry
  Full NSE cost model on every fill.

C6 partial: BSM reprice uses last-seen ATM IV, not entry IV.
C10 partial: volume/OI-aware synthetic spread widening.
"""

import datetime
import math
import pandas as pd
from . import metrics
from ..risk import margin as margin_mod
from ..core import event_calendar


def run(config, chain_loader, spot_series):
    """
    Run a full options strategy backtest.

    config : dict — strategy_key, symbol, lot_size, initial_capital, max_lots,
        max_concurrent, r, entry_dte_range, vp_threshold, slippage_mult,
        rv_window, profit_target_pct, stop_loss_pct, exit_dte, signal_mode
    chain_loader : callable(date) -> DataFrame or None
        Columns: strike, option_type, expiry(date), close/settle, volume, oi
    spot_series : dict {date: close_price}
    """
    from ..core import bsm, iv as iv_mod, cost_model, volatility
    from ..strategies import builder, registry, regime

    cfg = _defaults(config)
    trades = []
    open_positions = []
    equity = float(cfg['initial_capital'])
    peak_equity = equity
    equity_curve = [equity]
    equity_dates = []
    warn = []
    tid = 0

    dates_sorted = sorted(spot_series.keys())
    start = cfg.get('start_date', dates_sorted[0])
    end = cfg.get('end_date', dates_sorted[-1])
    trading_dates = [d for d in dates_sorted if start <= d <= end]

    spot_list = [spot_series[d] for d in dates_sorted]
    date_idx = {d: i for i, d in enumerate(dates_sorted)}

    for dt in trading_dates:
        chain_raw = chain_loader(dt)
        spot = spot_series[dt]

        if chain_raw is None or (isinstance(chain_raw, pd.DataFrame) and chain_raw.empty):
            equity_dates.append(dt)
            ur = _unrealized(open_positions, None, spot, dt, cfg, bsm)
            equity_curve.append(equity + ur)
            continue

        chain = _enrich_chain(chain_raw, spot, dt, cfg['r'], iv_mod, cfg['lot_size'])

        # --- exits ---
        still_open = []
        for pos in open_positions:
            reason = _check_exit(pos, chain, spot, dt, cfg, bsm)
            if reason:
                tid += 1
                trade = _close(pos, chain, spot, dt, reason, cfg, tid, cost_model, bsm)
                trades.append(trade)
                equity += trade['net_pnl']
            else:
                still_open.append(pos)
        open_positions = still_open

        # --- entry ---
        if len(open_positions) < cfg['max_concurrent']:
            vp_val = None
            enter = cfg['signal_mode'] not in ('vp', 'regime')

            idx = date_idx.get(dt, 0)
            w = cfg['rv_window']
            rv = None
            atm_iv_val = _atm_iv(chain, spot)
            if idx >= w:
                rv = volatility.close_to_close_vol(spot_list[idx - w:idx + 1], window=w)

            if cfg['signal_mode'] == 'vp':
                if rv is not None and not math.isnan(rv) and atm_iv_val is not None:
                    vp_val = atm_iv_val - rv
                    enter = vp_val >= cfg['vp_threshold']

            elif cfg['signal_mode'] == 'regime':
                reg = regime.detect_regime(spot_list, idx, dt, atm_iv_val, rv, w)
                strat = registry.get(cfg['strategy_key'])
                if strat and regime.strategy_fits_regime(strat, reg):
                    enter = True
                    if atm_iv_val is not None and rv is not None and not math.isnan(rv):
                        vp_val = atm_iv_val - rv

            peak_equity = max(peak_equity, equity)
            cfg['_peak_equity'] = peak_equity
            strat_obj = registry.get(cfg['strategy_key']) if enter else None

            # Fix #3: event calendar — suppress sell strategies near known events
            if enter and cfg.get('event_filter', True) and strat_obj:
                if strat_obj.category == 'income':
                    ev = event_calendar.event_near(dt)
                    if ev:
                        enter = False
                        warn.append(f"{dt}: sell suppressed ({ev})")

            # Fix #7: VIX-level guard — skip sell when premiums too thin
            if enter and strat_obj and atm_iv_val is not None:
                if strat_obj.category == 'income' and atm_iv_val < 0.11:
                    enter = False
                    warn.append(f"{dt}: IV too low ({atm_iv_val:.1%})")

            # Fix #6: correlation — don't stack same-category+outlook
            if enter and strat_obj and open_positions:
                for op in open_positions:
                    existing = registry.get(op['strategy_key'])
                    if existing and existing.category == strat_obj.category and existing.outlook == strat_obj.outlook:
                        enter = False
                        warn.append(f"{dt}: correlated with open {op['strategy_key']}")
                        break

            if enter:
                pos = _open(cfg, chain, spot, dt, vp_val, builder, cost_model, equity)
                if pos:
                    open_positions.append(pos)
                else:
                    warn.append(f"{dt}: entry skipped (illiquid/build failed)")

        current_iv = _atm_iv(chain, spot)
        if current_iv is not None:
            for pos in open_positions:
                pos['last_iv'] = current_iv

        ur = _unrealized(open_positions, chain, spot, dt, cfg, bsm)
        equity_dates.append(dt)
        equity_curve.append(equity + ur)

    # force-close remaining
    for pos in open_positions:
        tid += 1
        last_spot = spot_series[trading_dates[-1]]
        trade = _close(pos, None, last_spot, trading_dates[-1],
                       'end_of_backtest', cfg, tid, cost_model, bsm)
        trades.append(trade)
        equity += trade['net_pnl']
    if equity_curve:
        equity_curve[-1] = equity

    return {
        'trades': trades,
        'equity_curve': equity_curve,
        'equity_dates': equity_dates,
        'metrics': metrics.compute_all(trades, equity_curve, cfg['r']),
        'config': cfg,
        'warnings': warn,
    }


# ── config ──────────────────────────────────────────────────────────────

def _defaults(config):
    cfg = {
        'strategy_key': 'short_straddle',
        'symbol': 'NIFTY',
        'lot_size': 65,
        'initial_capital': 1_000_000,
        'max_lots': 1,
        'max_concurrent': 1,
        'r': 0.07,
        'entry_dte_range': (7, 30),
        'vp_threshold': 0.02,
        'slippage_mult': 1.0,
        'rv_window': 21,
        'profit_target_pct': 0.50,
        'stop_loss_pct': 0.70,
        'exit_dte': 2,
        'signal_mode': 'vp',
    }
    cfg.update(config)
    return cfg


# ── chain enrichment ────────────────────────────────────────────────────

def _enrich_chain(df_raw, spot, dt, r, iv_mod, lot_size=65):
    df = df_raw.copy()

    price_col = 'settle' if 'settle' in df.columns else 'close'
    df['ltp'] = df[price_col].clip(lower=0.05)

    if 'expiry' in df.columns and 'expiry_years' not in df.columns:
        df['expiry_years'] = df['expiry'].apply(
            lambda e: max((_to_date(e) - dt).days, 1) / 365
        )

    if 'iv' not in df.columns:
        ivs = []
        for _, row in df.iterrows():
            ltp_v = row.get('ltp', 0)
            t_v = row.get('expiry_years', 0.05)
            if ltp_v > 0.05 and t_v > 0.001:
                try:
                    v = iv_mod.implied_vol(ltp_v, spot, row['strike'], t_v, r, row['option_type'])
                    ivs.append(v if not math.isnan(v) and 0.01 < v < 3.0 else 0.15)
                except Exception:
                    ivs.append(0.15)
            else:
                ivs.append(0.15)
        df['iv'] = ivs

    if 'bid' not in df.columns:
        mon = ((df['strike'] - spot) / spot).abs()
        sp = pd.Series(0.30, index=df.index)
        sp[mon < 0.03] = 0.15
        sp[mon < 0.01] = 0.05
        if 'volume' in df.columns:
            sp[df['volume'] < lot_size * 20] *= 2.0
        if 'oi' in df.columns:
            sp[df['oi'] < lot_size * 100] *= 1.5
        df['spread'] = sp
        df['bid'] = (df['ltp'] - sp / 2).clip(lower=0.05)
        df['ask'] = df['ltp'] + sp / 2
    elif 'spread' not in df.columns:
        df['spread'] = (df['ask'] - df['bid']).clip(lower=0.05)

    return df


def _to_date(val):
    if isinstance(val, datetime.datetime):
        return val.date()
    return val


def _atm_iv(chain, spot):
    calls = chain[chain['option_type'] == 'CE']
    if calls.empty:
        return None
    ranked = (calls['strike'] - spot).abs().argsort()
    for pos in ranked:
        iv = calls.iloc[pos]['iv']
        if isinstance(iv, (int, float)) and not math.isnan(iv) and iv > 0:
            return iv
    return None


# ── fill simulation ─────────────────────────────────────────────────────

def _fill_price(ltp, spread, action, slippage_mult):
    half = spread / 2 * slippage_mult
    if action == 'BUY':
        return max(0.05, ltp + half)
    return max(0.05, ltp - half)


def _leg_spread(chain, strike, option_type):
    row = chain[(chain['strike'] == strike) & (chain['option_type'] == option_type)]
    if not row.empty and 'spread' in row.columns:
        return float(row.iloc[0]['spread'])
    if not row.empty:
        prem = float(row.iloc[0].get('settle', row.iloc[0].get('close', row.iloc[0].get('ltp', 0))))
        if prem > 100:
            return 0.50
        if prem > 30:
            return 0.75
        if prem > 10:
            return 1.00
        if prem > 2:
            return 1.50
        return 2.00
    return 1.00


# ── position lifecycle ──────────────────────────────────────────────────

def _find_expiry(chain, dt, dte_range):
    if 'expiry' not in chain.columns:
        return None
    min_d, max_d = dte_range
    best = None
    for exp in chain['expiry'].unique():
        dte = (_to_date(exp) - dt).days
        if min_d <= dte <= max_d:
            if best is None or dte < best[0]:
                best = (dte, exp)
    return _to_date(best[1]) if best else None


def _open(cfg, chain, spot, dt, vp_val, builder, cost_model, equity=None):
    target = _find_expiry(chain, dt, cfg['entry_dte_range'])
    if not target:
        return None

    exp_chain = chain[chain['expiry'].apply(_to_date) == target].copy()
    if exp_chain.empty:
        return None

    if 'volume' in exp_chain.columns:
        near = exp_chain[(exp_chain['strike'] - spot).abs() < spot * 0.05]
        if not near.empty and near['volume'].min() < cfg['lot_size'] * 5:
            return None

    result = builder.build(cfg['strategy_key'], exp_chain, spot,
                           r=cfg['r'], lot_size=cfg['lot_size'])
    if not result or not result.get('legs'):
        return None

    slip = cfg['slippage_mult']
    for leg in result['legs']:
        prem = leg.get('premium', leg.get('ltp', 0))
        sp = _leg_spread(chain, leg['strike'], leg['option_type'])
        leg['entry_ltp'] = prem
        leg['entry_fill'] = _fill_price(prem, sp, leg['action'], slip)
        leg['spread_at_entry'] = sp

    net_prem = sum(
        leg['entry_fill'] * (1 if leg['action'] == 'SELL' else -1)
        for leg in result['legs']
    )

    # Drawdown-scaled lot sizing (Davey Ch.23 equity bands)
    lots = cfg['max_lots']
    if equity is not None and equity > 0:
        peak = cfg.get('_peak_equity', equity)
        if equity < peak:
            dd_pct = (peak - equity) / peak
            abort_dd = cfg.get('abort_dd_pct', 0.35)
            if dd_pct > abort_dd * 0.75:
                lots = 1
            elif dd_pct > abort_dd * 0.50:
                lots = max(1, lots // 2)
        max_usage = cfg.get('max_margin_usage', 0.40)
        try:
            margin_legs = [
                {'strike': l['strike'], 'option_type': l['option_type'],
                 'action': l['action'], 'premium': l['entry_fill'],
                 'expiry_years': (target - dt).days / 365.0}
                for l in result['legs']
            ]
            m_est = margin_mod.estimate_margin(
                margin_legs, spot, cfg['lot_size'], cfg.get('symbol', 'NIFTY'))
            margin_per_lot = m_est.get('total_margin', 0)
            if margin_per_lot > 0:
                affordable = int(equity * max_usage / margin_per_lot)
                lots = max(1, min(lots, affordable))
        except Exception:
            pass

    entry_cost = 0.0
    for leg in result['legs']:
        tc = cost_model.trade_cost(leg['entry_fill'], cfg['lot_size'], leg['action'])
        entry_cost += tc['total']
    entry_cost *= lots

    return {
        'strategy_key': cfg['strategy_key'],
        'symbol': cfg['symbol'],
        'entry_date': dt,
        'entry_spot': spot,
        'expiry': target,
        'legs': result['legs'],
        'lots': lots,
        'lot_size': cfg['lot_size'],
        'net_premium': round(net_prem, 2),
        'max_profit': result.get('max_profit', abs(net_prem) * cfg['lot_size']),
        'max_loss': result.get('max_loss', float('-inf')),
        'entry_cost': round(entry_cost, 2),
        'entry_iv': _atm_iv(chain, spot) or 0.15,
        'vp_at_entry': vp_val,
    }


def _current_price(leg, chain, spot, dt, pos, cfg, bsm):
    if chain is not None and not chain.empty:
        mask = (chain['strike'] == leg['strike']) & (chain['option_type'] == leg['option_type'])
        if 'expiry' in chain.columns:
            exp_mask = chain['expiry'].apply(_to_date) == pos['expiry']
            match = chain[mask & exp_mask]
            if match.empty:
                match = chain[mask]
        else:
            match = chain[mask]
        if not match.empty:
            return float(match.iloc[0].get('ltp', match.iloc[0].get('settle',
                         match.iloc[0].get('close', 0))))

    dte = max((_to_date(pos['expiry']) - dt).days, 0)
    t = max(dte, 1) / 365
    iv = pos.get('last_iv', leg.get('iv', 0.15))
    return max(0.0, bsm.bsm_price(spot, leg['strike'], t, cfg.get('r', 0.07), iv, leg['option_type']))


def _pnl_per_unit(pos, chain, spot, dt, cfg, bsm):
    total = 0.0
    for leg in pos['legs']:
        cur = _current_price(leg, chain, spot, dt, pos, cfg, bsm)
        if leg['action'] == 'SELL':
            total += leg['entry_fill'] - cur
        else:
            total += cur - leg['entry_fill']
    return total


def _check_exit(pos, chain, spot, dt, cfg, bsm):
    dte = (_to_date(pos['expiry']) - dt).days

    if dte <= 0:
        return 'expiry'
    if dte <= cfg.get('exit_dte', 2):
        return f'dte_{dte}'

    cur_gross = _pnl_per_unit(pos, chain, spot, dt, cfg, bsm) * pos['lot_size'] * pos['lots']

    lots = pos['lots']
    mp = pos.get('max_profit', 0)
    if mp > 0 and cur_gross >= mp * lots * cfg.get('profit_target_pct', 0.50):
        return 'profit_target'

    ml = pos.get('max_loss', float('-inf'))
    if ml != float('-inf') and ml < 0 and cur_gross <= ml * lots * cfg.get('stop_loss_pct', 0.70):
        return 'stop_loss'

    spot_chg = abs(spot - pos['entry_spot']) / pos['entry_spot']
    if spot_chg >= 0.03 and 'short' in pos['strategy_key']:
        return f'spot_move_{spot_chg:+.1%}'

    return None


def _close(pos, chain, spot, dt, reason, cfg, tid, cost_model, bsm):
    slip = cfg['slippage_mult']
    is_expiry = reason == 'expiry'
    dte = (_to_date(pos['expiry']) - dt).days
    if not is_expiry and 0 < dte <= 3:
        slip *= 2.0

    for leg in pos['legs']:
        cur = _current_price(leg, chain, spot, dt, pos, cfg, bsm)
        if is_expiry:
            intr = max(0, spot - leg['strike']) if leg['option_type'] == 'CE' \
                else max(0, leg['strike'] - spot)
            leg['exit_fill'] = round(intr, 2)
        else:
            sp = leg.get('spread_at_entry', 0.05)
            if chain is not None:
                sp = _leg_spread(chain, leg['strike'], leg['option_type'])
            rev = 'BUY' if leg['action'] == 'SELL' else 'SELL'
            leg['exit_fill'] = _fill_price(cur, sp, rev, slip)
        leg['exit_ltp'] = cur

    pnl_pu = sum(
        (leg['entry_fill'] - leg['exit_fill']) if leg['action'] == 'SELL'
        else (leg['exit_fill'] - leg['entry_fill'])
        for leg in pos['legs']
    )
    gross = round(pnl_pu * pos['lot_size'] * pos['lots'], 2)

    exit_cost = 0.0
    for leg in pos['legs']:
        rev = 'BUY' if leg['action'] == 'SELL' else 'SELL'
        tc = cost_model.trade_cost(leg['exit_fill'], pos['lot_size'], rev)
        exit_cost += tc['total'] * pos['lots']
    total_cost = round(pos['entry_cost'] + exit_cost, 2)

    return {
        'trade_id': tid,
        'strategy': pos['strategy_key'],
        'symbol': pos.get('symbol', cfg.get('symbol', 'NIFTY')),
        'entry_date': pos['entry_date'].isoformat(),
        'exit_date': dt.isoformat() if isinstance(dt, datetime.date) else str(dt),
        'holding_days': (dt - pos['entry_date']).days,
        'entry_spot': pos['entry_spot'],
        'exit_spot': spot,
        'entry_iv': pos.get('entry_iv', 0.15),
        'exit_iv': _atm_iv(chain, spot) if chain is not None else pos.get('last_iv', pos.get('entry_iv', 0.15)),
        'vp_at_entry': pos.get('vp_at_entry'),
        'lots': pos['lots'],
        'gross_pnl': gross,
        'costs_total': total_cost,
        'net_pnl': round(gross - total_cost, 2),
        'exit_reason': reason,
    }


def _unrealized(positions, chain, spot, dt, cfg, bsm):
    return sum(
        _pnl_per_unit(p, chain, spot, dt, cfg, bsm) * p['lot_size'] * p['lots']
        for p in positions
    )


# ── self-check ──────────────────────────────────────────────────────────

def _self_check():
    from ..core import bsm
    import random

    spot = 24000.0
    entry = datetime.date(2026, 9, 1)
    expiry = datetime.date(2026, 9, 30)

    def make_chain(dt, sp):
        rows = []
        t = max((expiry - dt).days, 1) / 365
        for k in range(23000, 25001, 100):
            for ot in ['CE', 'PE']:
                p = max(0.05, bsm.bsm_price(sp, k, t, 0.07, 0.16, ot))
                rows.append({'strike': float(k), 'option_type': ot,
                             'expiry': expiry, 'settle': round(p, 2),
                             'volume': 50000, 'oi': 100000})
        return pd.DataFrame(rows)

    random.seed(42)
    spots = {}
    s = spot
    for i in range(40):
        d = entry + datetime.timedelta(days=i)
        if d.weekday() < 5:
            s += random.gauss(0, 50)
            spots[d] = round(s, 2)

    cache = {}
    def loader(dt):
        if dt not in spots:
            return None
        if dt not in cache:
            cache[dt] = make_chain(dt, spots[dt])
        return cache[dt]

    result = run({
        'strategy_key': 'short_straddle',
        'lot_size': 65,
        'initial_capital': 1_000_000,
        'signal_mode': 'always',
        'entry_dte_range': (5, 35),
        'exit_dte': 2,
        'max_lots': 1,
    }, loader, spots)

    assert len(result['trades']) >= 1, f"Expected trades, got {len(result['trades'])}"
    assert len(result['equity_curve']) > 1
    for t in result['trades']:
        assert t['costs_total'] > 0, f"Trade {t['trade_id']}: costs must be > 0"

    m = result['metrics']
    print(f"engine.py: {m['total_trades']} trades, net ₹{m['net_pnl']:,.0f}, "
          f"costs ₹{m['total_costs']:,.0f} ({m['cost_pct_of_gross']}%), "
          f"win {m['win_rate_pct']}%")
    print("engine.py: all checks passed")


if __name__ == '__main__':
    _self_check()
