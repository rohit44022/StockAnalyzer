"""
web/options_routes.py — Options trading system UI.

Routes:
  GET  /options              — dashboard (incubation, positions, P/L)
  GET  /options/chain        — option chain viewer with greeks
  GET  /options/strategy     — strategy builder + payoff diagram
  GET  /options/volatility   — vol surface, IV vs RV, term structure
  GET  /options/backtest     — WFA reports, MC validation, equity curves

API:
  GET  /api/options/dashboard    — dashboard summary JSON
  GET  /api/options/trades       — paper trades list
  GET  /api/options/lifecycle    — incubation lifecycle status
  GET  /api/options/chain/<sym>  — chain snapshot + greeks
  GET  /api/options/oi/<sym>     — OI analysis (PCR, max pain, S/R)
  GET  /api/options/payoff/<key> — strategy payoff diagram data
  GET  /api/options/vol/<sym>    — volatility surface + term structure
  GET  /api/options/reports      — backtest report list
  GET  /api/options/report/<name>— single backtest report JSON
"""
from __future__ import annotations
import sys, os, json, glob, math, datetime, sqlite3, logging

from flask import Blueprint, jsonify, render_template, request, Response, stream_with_context

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

log = logging.getLogger(__name__)
options_bp = Blueprint("options", __name__)


def _safe(v, dp=2):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, dp)
    except (TypeError, ValueError):
        return None


def _json_clean(obj):
    """Recursively convert numpy/non-JSON types for Flask jsonify."""
    import numpy as np
    if isinstance(obj, dict):
        return {str(k): _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _json_clean(obj.tolist())
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


# ── Page routes ──────────────────────────────────────────────────

@options_bp.route("/options")
def dashboard_page():
    return render_template("options_dashboard.html")


@options_bp.route("/options/chain")
def chain_page():
    return render_template("options_chain.html")


@options_bp.route("/options/strategy")
def strategy_page():
    return render_template("options_strategy.html")


@options_bp.route("/options/volatility")
def volatility_page():
    return render_template("options_volatility.html")


@options_bp.route("/options/backtest")
def backtest_page():
    return render_template("options_backtest.html")


# ── API routes ───────────────────────────────────────────────────

@options_bp.route("/api/options/dashboard")
def api_dashboard():
    try:
        from options import paper_trade
        from options.data import chain_store

        db = paper_trade._db_path()
        paper_trade.init_db(db)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            # Open trades
            open_trades = conn.execute(
                "SELECT * FROM trades WHERE status='open' ORDER BY opened_at DESC"
            ).fetchall()
            trades_out = []
            for t in open_trades:
                trades_out.append({
                    'id': t['id'], 'symbol': t['symbol'],
                    'strategy': t['strategy'], 'opened_at': t['opened_at'],
                    'entry_spot': _safe(t['entry_spot']),
                    'lots': t['lots'], 'lot_size': t['lot_size'],
                    'capital_risked': _safe(t['capital_risked']),
                    'status': t['status'],
                })

            # Closed trades summary
            closed = conn.execute(
                "SELECT COUNT(*) as cnt, SUM(net_pnl) as total_pnl, "
                "AVG(net_pnl) as avg_pnl FROM trades WHERE status='closed'"
            ).fetchone()
            closed_summary = {
                'count': closed['cnt'] or 0,
                'total_pnl': _safe(closed['total_pnl']),
                'avg_pnl': _safe(closed['avg_pnl']),
            }

            # Recent recommendations
            recs = conn.execute(
                "SELECT id, timestamp, symbol, strategy, spot, score, status "
                "FROM recommendations ORDER BY id DESC LIMIT 10"
            ).fetchall()
            recs_out = [{k: r[k] for k in r.keys()} for r in recs]

            # Lifecycle status
            lifecycles = conn.execute(
                "SELECT * FROM strategy_lifecycle ORDER BY start_date"
            ).fetchall()
            lc_out = []
            for lc in lifecycles:
                lc_out.append({k: lc[k] for k in lc.keys()})
        finally:
            conn.close()

        # Chain store stats
        try:
            cs_stats = chain_store.db_stats()
        except Exception:
            cs_stats = {'exists': False}

        return jsonify(_json_clean({
            'open_trades': trades_out,
            'closed_summary': closed_summary,
            'recent_recommendations': recs_out,
            'lifecycles': lc_out,
            'chain_store': cs_stats,
        }))
    except Exception as e:
        log.exception("dashboard API error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/trades")
def api_trades():
    try:
        from options import paper_trade
        db = paper_trade._db_path()
        paper_trade.init_db(db)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            status = request.args.get('status', 'all')
            if status == 'all':
                rows = conn.execute("SELECT * FROM trades ORDER BY id DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()

            trades = []
            for t in rows:
                d = {k: t[k] for k in t.keys()}
                d['legs'] = json.loads(d.get('legs', '[]'))
                trades.append(d)
        finally:
            conn.close()
        return jsonify(_json_clean({'trades': trades}))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/lifecycle")
def api_lifecycle():
    try:
        from options import paper_trade
        import sqlite3 as _sq
        db = paper_trade._db_path()
        paper_trade.init_db(db)
        conn = _sq.connect(db)
        conn.row_factory = _sq.Row
        try:
            key = request.args.get('strategy')
            if key:
                rows = conn.execute(
                    'SELECT * FROM strategy_lifecycle WHERE strategy_key=?', (key,)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM strategy_lifecycle ORDER BY status, strategy_key'
                ).fetchall()
        finally:
            conn.close()
        out = [{k: r[k] for k in r.keys()} for r in rows]
        return jsonify(_json_clean(out))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/chain/<symbol>")
def api_chain(symbol):
    try:
        from options.data import chain_store
        from options.core import bsm, iv as iv_mod

        symbol = symbol.upper()
        expiry = request.args.get('expiry')
        date_str = request.args.get('date')

        ts_query = None
        if date_str:
            ts_query = date_str + 'T23:59:59' if 'T' not in date_str else date_str

        df = chain_store.get_chain_snapshot(symbol, expiry=expiry,
                                            timestamp=ts_query)
        if df.empty:
            df = chain_store.get_bhavcopy(symbol, date_str or
                                          str(datetime.date.today()), expiry=expiry)

        if df.empty:
            return jsonify({'error': 'No chain data found', 'rows': []}), 404

        spot_col = 'underlying_price' if 'underlying_price' in df.columns else None
        spot = None
        if spot_col:
            spot = df[spot_col].dropna().iloc[0] if not df[spot_col].dropna().empty else None

        rows = []
        for _, r in df.iterrows():
            row = {}
            for c in df.columns:
                v = r[c]
                if hasattr(v, 'item'):
                    v = v.item()
                row[c] = v
            if spot and row.get('strike') and row.get('option_type'):
                try:
                    premium = row.get('ltp') or row.get('close') or 0
                    s = float(row['strike'])
                    t_years = max(1, row.get('dte', 7)) / 365.0
                    comp_iv = iv_mod.implied_volatility(
                        premium, spot, s, t_years,
                        option_type=row['option_type']
                    ) if premium > 0 else None
                    greeks = bsm.bsm_greeks(spot, s, t_years,
                                            0.07, comp_iv or 0.20, row['option_type'])
                    row['computed_iv'] = _safe(comp_iv, 4)
                    row['delta'] = _safe(greeks.get('delta'), 4)
                    row['gamma'] = _safe(greeks.get('gamma'), 6)
                    row['theta'] = _safe(greeks.get('theta'), 2)
                    row['vega'] = _safe(greeks.get('vega'), 2)
                except Exception:
                    pass
            rows.append(row)

        return jsonify(_json_clean({
            'symbol': symbol, 'spot': _safe(spot),
            'rows': rows, 'count': len(rows),
        }))
    except Exception as e:
        log.exception("chain API error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/oi/<symbol>")
def api_oi(symbol):
    try:
        from options.data import chain_store, oi_analysis
        symbol = symbol.upper()
        date_str = request.args.get('date', str(datetime.date.today()))

        df = chain_store.get_chain_snapshot(symbol)
        if df.empty:
            df = chain_store.get_bhavcopy(symbol, date_str)
        if df.empty:
            return jsonify({'error': 'No data'}), 404

        spot_col = 'underlying_price' if 'underlying_price' in df.columns else None
        spot = df[spot_col].dropna().iloc[0] if spot_col and not df[spot_col].dropna().empty else None

        result = {}
        try:
            result['pcr'] = oi_analysis.pcr_oi(df)
        except Exception:
            pass
        try:
            result['max_pain'] = oi_analysis.max_pain(df)
        except Exception:
            pass
        if spot:
            try:
                result['support_resistance'] = oi_analysis.oi_support_resistance(df, spot)
            except Exception:
                pass
            try:
                result['dashboard'] = oi_analysis.oi_dashboard(df, spot)
            except Exception:
                pass

        return jsonify(_json_clean({'symbol': symbol, 'spot': _safe(spot), **result}))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/payoff/<key>")
def api_payoff(key):
    try:
        from options.strategies import registry
        from options.core import payoff

        strat = registry.get(key)
        if not strat:
            return jsonify({'error': f'Unknown strategy: {key}'}), 404

        spot = float(request.args.get('spot', 24000))
        iv = float(request.args.get('iv', 0.15))
        lot_size = int(request.args.get('lot_size', 75))

        import numpy as np
        step = 50 if spot > 10000 else 100
        legs = []
        for leg_spec in strat.legs:
            strike = spot + leg_spec.strike_offset * step
            premium = spot * iv * 0.04 * (1 + abs(leg_spec.strike_offset) / 10)
            legs.append({
                'strike': strike, 'option_type': leg_spec.option_type,
                'action': leg_spec.action, 'premium': round(premium, 2),
                'qty': leg_spec.qty,
            })

        summary = payoff.strategy_summary(legs, lot_size=lot_size)
        S_range = np.linspace(spot * 0.85, spot * 1.15, 200)
        pnl_raw = payoff.strategy_payoff(legs, S_range=S_range)
        # strategy_payoff returns list of dicts {price, payoff, per_leg}
        if pnl_raw and isinstance(pnl_raw[0], dict):
            pnl_vals = [p['payoff'] for p in pnl_raw]
        else:
            pnl_vals = pnl_raw

        return jsonify(_json_clean({
            'strategy': key, 'name': strat.name,
            'category': strat.category, 'outlook': strat.outlook,
            'legs': legs, 'summary': summary,
            'payoff_curve': {
                'spot_range': list(S_range),
                'pnl': list(pnl_vals),
            },
        }))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/vol/<symbol>")
def api_vol(symbol):
    try:
        from options.data import chain_store
        from options.core import vol_surface, volatility

        symbol = symbol.upper()
        df = chain_store.get_chain_snapshot(symbol)
        if df.empty:
            df = chain_store.get_bhavcopy(
                symbol, str(datetime.date.today()))

        if df.empty:
            return jsonify({'error': 'No chain data'}), 404

        spot = None
        for col in ['underlying_price', 'spot', 'close']:
            if col in df.columns and not df[col].dropna().empty:
                spot = float(df[col].dropna().iloc[0])
                break
        if not spot:
            strikes = sorted(df['strike'].unique()) if 'strike' in df.columns else []
            if strikes:
                spot = float(strikes[len(strikes) // 2])
            else:
                return jsonify({'error': 'Cannot determine spot price'}), 400

        # vol_surface expects 'expiry_years' (float) — derive from 'expiry' date strings
        if 'expiry' in df.columns and 'expiry_years' not in df.columns:
            import pandas as pd
            today = pd.Timestamp.now().normalize()
            df['expiry_dt'] = pd.to_datetime(df['expiry'], errors='coerce')
            df['expiry_years'] = (df['expiry_dt'] - today).dt.days / 365.0
            df.loc[df['expiry_years'] <= 0, 'expiry_years'] = 1 / 365.0

        result = {'symbol': symbol, 'spot': _safe(spot)}

        try:
            ts = vol_surface.term_structure(df, spot)
            if ts is not None and not ts.empty:
                result['term_structure'] = [
                    {'expiry': f"{int(r.get('expiry_days', 0))} DTE",
                     'days': _safe(r.get('expiry_days'), 0),
                     'atm_iv': _safe(r.get('atm_iv'), 4)}
                    for _, r in ts.iterrows()
                ]
                result['inverted'] = vol_surface.is_inverted(ts)
        except Exception:
            pass

        try:
            surface = vol_surface.build_surface(df, spot)
            if surface and 'surface' in surface:
                import pandas as pd
                surf_df = surface['surface']
                if isinstance(surf_df, pd.DataFrame) and not surf_df.empty:
                    expiries = []
                    for col in surf_df.columns:
                        valid = surf_df[col].dropna()
                        if valid.empty:
                            continue
                        expiries.append({
                            'expiry': f'{int(col)} DTE',
                            'strikes': [float(s) for s in valid.index],
                            'ivs': [float(v) for v in valid.values],
                        })
                    result['surface'] = {'expiries': expiries}
        except Exception:
            pass

        return jsonify(_json_clean(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/reports")
def api_reports():
    try:
        report_dir = os.path.join(_ROOT, 'options', 'backtest', 'reports')
        reports = []
        if os.path.isdir(report_dir):
            for f in sorted(glob.glob(os.path.join(report_dir, '*.json'))):
                name = os.path.basename(f)
                if name.startswith('_'):
                    continue
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    sm = data.get('summary', data.get('metrics', {}))
                    variant = ''
                    if '_regime_' in name:
                        variant = 'regime'
                    elif '_vp_' in name:
                        variant = 'vp'
                    elif '_wfa_' in name:
                        variant = 'wfa'
                    reports.append({
                        'filename': name,
                        'strategy': data.get('strategy', name.replace('.json', '')),
                        'variant': variant,
                        'symbol': data.get('symbol', ''),
                        'net_pnl': _safe(sm.get('net_pnl')),
                        'trades': sm.get('total_trades', 0),
                        'gates': data.get('davey_gates', {}),
                    })
                except Exception:
                    pass
        return jsonify({'reports': reports})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/report/<name>")
def api_report(name):
    try:
        if '..' in name or '/' in name:
            return jsonify({'error': 'invalid name'}), 400
        path = os.path.join(_ROOT, 'options', 'backtest', 'reports', name)
        if not os.path.exists(path):
            return jsonify({'error': 'not found'}), 404
        with open(path) as f:
            data = json.load(f)
        return jsonify(_json_clean(data))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/options/paper-trade")
def page_paper_trade():
    return render_template("options_paper_trade.html")


@options_bp.route("/api/options/paper/recommend", methods=['POST'])
def api_paper_recommend():
    """Generate a fresh recommendation via the full pipeline."""
    try:
        from options import paper_trade
        symbol = request.json.get('symbol', 'NIFTY') if request.is_json else 'NIFTY'
        capital = float(request.json.get('capital', 500000)) if request.is_json else 500000
        result = paper_trade.recommend(symbol=symbol, capital=capital)
        return jsonify(_json_clean(result))
    except Exception as e:
        log.exception("paper recommend API error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/paper/enter", methods=['POST'])
def api_paper_enter():
    """Enter a pending recommendation as a paper trade."""
    try:
        from options import paper_trade
        rec_id = request.json.get('recommendation_id')
        if not rec_id:
            return jsonify({'error': 'recommendation_id required'}), 400
        result = paper_trade.enter(int(rec_id))
        return jsonify(_json_clean(result))
    except Exception as e:
        log.exception("paper enter API error")
        return jsonify({'error': str(e)}), 500


def _live_spot(sym='NIFTY', fallback=24000):
    """Get spot from live feed, fall back to API, then to static value."""
    try:
        from options.data.live_feed import feed, INDEX_SID
        sid = INDEX_SID.get(sym.upper())
        ltp = feed.ltp(sid) if sid else None
        if ltp is not None:
            return ltp
    except Exception:
        pass
    try:
        from options.data import dhan_fetch
        return dhan_fetch.fetch_spot(sym)
    except Exception:
        return fallback


@options_bp.route("/api/options/paper/exit", methods=['POST'])
def api_paper_exit():
    """Exit an open paper trade."""
    try:
        from options import paper_trade
        trade_id = request.json.get('trade_id')
        if not trade_id:
            return jsonify({'error': 'trade_id required'}), 400
        spot = request.json.get('spot') or _live_spot()
        result = paper_trade.exit_trade(int(trade_id), spot=float(spot))
        return jsonify(_json_clean(result))
    except Exception as e:
        log.exception("paper exit API error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/paper/check", methods=['POST'])
def api_paper_check():
    """Run daily check on all open paper trades."""
    try:
        from options import paper_trade
        spot = request.json.get('spot') if request.is_json else None
        if not spot:
            spot = _live_spot()
        result = paper_trade.daily_check(spot=float(spot))
        return jsonify(_json_clean(result))
    except Exception as e:
        log.exception("paper check API error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/paper/explain/<int:rec_id>")
def api_paper_explain(rec_id):
    """Get detailed explanation for a recommendation."""
    try:
        from options import paper_trade
        import sqlite3
        db = paper_trade._db_path()
        paper_trade.init_db(db)
        conn = sqlite3.connect(db, timeout=10)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM recommendations WHERE id=?', (rec_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({'error': 'Recommendation not found'}), 404

        import json
        rec_data = {k: row[k] for k in row.keys()}
        legs = json.loads(rec_data.get('legs', '[]'))
        strategy = rec_data.get('strategy', '')

        from options.strategies import registry, explainer as expl_mod
        strat = registry.get(strategy)
        strat_info = {}
        if strat:
            strat_info = {
                'name': strat.name,
                'category': strat.category,
                'outlook': strat.outlook,
                'vol_regimes': list(strat.vol_regimes) if strat.vol_regimes else [],
                'description': _strategy_description(strategy),
                'plain_english': _strategy_plain_english(strategy),
            }

        return jsonify(_json_clean({
            'recommendation': rec_data,
            'legs': legs,
            'strategy_info': strat_info,
        }))
    except Exception as e:
        log.exception("paper explain API error")
        return jsonify({'error': str(e)}), 500


def _strategy_description(key):
    """Return a beginner-friendly description for each strategy."""
    descs = {
        'iron_condor': 'Sell options both above and below the current price, with protective wings. You profit if the market stays in a range. Like being a landlord — you collect rent (premium) as long as nothing extreme happens.',
        'iron_butterfly': 'Sell ATM call and put, buy protective wings. Maximum profit if the market stays exactly where it is. Higher premium than iron condor but narrower profit zone.',
        'short_straddle': 'Sell both a call and put at the same strike price. You profit from time decay if the market stays near that price. High premium but unlimited risk — use with caution.',
        'short_strangle': 'Sell an OTM call and OTM put. Wider profit zone than straddle but less premium collected. You win if market stays between your two strikes.',
        'long_straddle': 'Buy both a call and put at the same strike. You profit from a big move in EITHER direction. Loses money from time decay if the market stays still.',
        'long_strangle': 'Buy an OTM call and OTM put. Cheaper than a straddle but needs a bigger move to profit. Best when you expect a large move but don\'t know which direction.',
        'bull_call_spread': 'Buy a lower-strike call, sell a higher-strike call. You profit if the market goes up, with capped risk and capped reward.',
        'bear_put_spread': 'Buy a higher-strike put, sell a lower-strike put. You profit if the market goes down, with capped risk and capped reward.',
        'bull_put_spread': 'Sell a higher-strike put, buy a lower-strike put. A credit spread — you collect premium and profit if the market stays above your sold strike.',
        'bear_call_spread': 'Sell a lower-strike call, buy a higher-strike call. A credit spread — you collect premium and profit if the market stays below your sold strike.',
        'long_call': 'Buy a call option. The simplest bullish bet — unlimited profit potential if the market rises, risk limited to the premium paid.',
        'long_put': 'Buy a put option. A bearish bet — profits if the market falls. Risk is limited to the premium paid. Like buying insurance on your portfolio.',
        'ratio_call_backspread': 'Sell 1 ATM call, buy 2 OTM calls. Profits from a strong upward move. Small debit or credit entry with asymmetric payoff.',
        'ratio_put_backspread': 'Sell 1 ATM put, buy 2 OTM puts. Profits from a strong downward move. Crash protection with limited cost.',
        'long_butterfly': 'Buy 1 lower call, sell 2 ATM calls, buy 1 higher call. Low cost bet that the market stays near a specific price. Very limited risk.',
        'calendar_call': 'Sell a near-term call, buy a longer-term call at the same strike. Profits from the faster time decay of the near-term option.',
    }
    return descs.get(key, 'A multi-leg options strategy. Check the strategy page for details.')


def _strategy_plain_english(key):
    """One-line plain English for strategy."""
    pe = {
        'iron_condor': 'Betting the market stays in a range',
        'iron_butterfly': 'Betting the market stays exactly here',
        'short_straddle': 'Betting the market doesn\'t move much',
        'short_strangle': 'Betting the market stays between two prices',
        'long_straddle': 'Betting on a big move, either direction',
        'long_strangle': 'Betting on a very big move, either direction',
        'bull_call_spread': 'Moderately bullish — market goes up',
        'bear_put_spread': 'Moderately bearish — market goes down',
        'bull_put_spread': 'Neutral to bullish — market stays above a level',
        'bear_call_spread': 'Neutral to bearish — market stays below a level',
        'long_call': 'Bullish — market goes up',
        'long_put': 'Bearish — market goes down',
        'ratio_call_backspread': 'Strongly bullish with crash protection',
        'ratio_put_backspread': 'Strongly bearish / crash protection',
        'long_butterfly': 'Pinpoint bet — market stays near one price',
        'calendar_call': 'Profiting from time passing faster on the short option',
    }
    return pe.get(key, 'Options strategy')


@options_bp.route("/api/options/dhan-token", methods=['GET'])
def api_dhan_token_status():
    try:
        from options.data import dhan_fetch
        return jsonify(dhan_fetch.get_token_status())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/dhan-token", methods=['POST'])
def api_dhan_token_save():
    try:
        from options.data import dhan_fetch
        token = request.json.get('token', '').strip() if request.is_json else ''
        if not token or len(token) < 20:
            return jsonify({'error': 'Invalid token — must be a valid Dhan JWT'}), 400
        result = dhan_fetch.save_runtime_token(token)
        try:
            from options.data.live_feed import feed, order_feed, depth_feed
            for f in [feed, order_feed, depth_feed]:
                f.stop()
                f.reconnect(force_recheck=True)
        except Exception:
            pass
        return jsonify(result)
    except Exception as e:
        log.exception("dhan token save error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/live/status")
def api_live_status():
    """Unified status of all real-time feeds."""
    from options.data.live_feed import feed, order_feed, depth_feed, chain_poller, position_poller, INDEX_SID
    mf = feed.status()
    mf['prices'] = {sym: feed.ltp(sid) for sym, sid in INDEX_SID.items()}
    return jsonify({
        'market_feed': mf,
        'order_feed': order_feed.status(),
        'depth_feed': depth_feed.status(),
        'chain_poller': chain_poller.status(),
        'position_poller': position_poller.status(),
    })


@options_bp.route("/api/options/strategies")
def api_strategies():
    try:
        from options.strategies import registry
        strats = registry.list_strategies()
        out = []
        for s in strats:
            out.append({
                'key': s.key, 'name': s.name,
                'category': s.category, 'outlook': s.outlook,
                'vol_regime': ', '.join(s.vol_regimes) if s.vol_regimes else '',
                'legs_count': len(s.legs),
            })
        return jsonify({'strategies': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Autopilot routes ───────────────────────────────────────────

@options_bp.route("/options/autopilot")
def options_autopilot():
    try:
        from options.autopilot import load_config
        cfg = load_config()
    except Exception:
        cfg = {}
    import datetime, zoneinfo
    now = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))
    is_holiday = False
    try:
        from options.data import event_calendar
        is_holiday = event_calendar.is_nse_holiday(now.date())
    except Exception:
        pass
    mkt_open = now.weekday() < 5 and not is_holiday and datetime.time(9, 15) <= now.time() < datetime.time(15, 30)
    live_mode = cfg.get('live_mode', 'paper')
    effective_live = live_mode == 'live' and mkt_open
    return render_template("options_autopilot.html",
                           live_mode=live_mode, effective_live=effective_live, cfg=cfg)


@options_bp.route("/api/options/autopilot/dashboard")
def api_autopilot_dashboard():
    try:
        from options import autopilot
        import datetime, zoneinfo
        data = autopilot.dashboard_data()
        now = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))
        is_hol = False
        try:
            from options.data import event_calendar as ec
            is_hol = ec.is_nse_holiday(now.date())
        except Exception:
            pass
        data['market_open'] = now.weekday() < 5 and not is_hol and datetime.time(9, 15) <= now.time() < datetime.time(15, 30)
        try:
            from options import paper_trade
            dash_spot = data.get('spot') or data.get('last_spot')
            data['portfolio_greeks'] = paper_trade.portfolio_greeks(spot=dash_spot)
        except Exception:
            data['portfolio_greeks'] = None
        return jsonify(_json_clean(data))
    except Exception as e:
        log.exception("autopilot dashboard error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/status")
def api_autopilot_status():
    try:
        from options import autopilot
        return jsonify(_json_clean(autopilot.status()))
    except Exception as e:
        log.exception("autopilot status error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/config", methods=['GET'])
def api_autopilot_config_get():
    try:
        from options import autopilot
        return jsonify(autopilot.load_config())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/config", methods=['POST'])
def api_autopilot_config_save():
    try:
        from options import autopilot
        cfg = request.json or {}
        saved = autopilot.save_config(cfg)
        return jsonify(saved)
    except Exception as e:
        log.exception("autopilot config save error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/enable", methods=['POST'])
def api_autopilot_enable():
    try:
        from options import autopilot
        return jsonify(autopilot.enable())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/disable", methods=['POST'])
def api_autopilot_disable():
    try:
        from options import autopilot
        return jsonify(autopilot.disable())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/emergency", methods=['POST'])
def api_autopilot_emergency():
    try:
        from options import autopilot
        return jsonify(autopilot.emergency_stop())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/cycle", methods=['POST'])
def api_autopilot_run_cycle():
    try:
        from options import autopilot
        cycle_type = (request.json or {}).get('cycle_type', 'auto')
        result = autopilot.cron_run_cycle(cycle_type=cycle_type)
        return jsonify(_json_clean(result))
    except Exception as e:
        log.exception("autopilot cycle error")
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/log")
def api_autopilot_log():
    try:
        from options import autopilot
        limit = request.args.get('limit', 50, type=int)
        entries = autopilot.get_decision_log(limit=limit)
        return jsonify(_json_clean({'entries': entries}))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── V5: Alerts + Execution Stats ─────────────────────────────────


@options_bp.route("/api/options/autopilot/alerts")
def api_autopilot_alerts():
    try:
        from options import autopilot
        limit = request.args.get('limit', 50, type=int)
        unacked = request.args.get('unacked', '0') == '1'
        alerts = autopilot.get_alerts(limit=limit, unacked_only=unacked)
        return jsonify(_json_clean({'alerts': alerts}))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/alerts/ack", methods=['POST'])
def api_autopilot_alerts_ack():
    try:
        from options import autopilot
        alert_id = (request.json or {}).get('id')
        if not alert_id:
            return jsonify({'error': 'Missing alert id'}), 400
        autopilot.ack_alert(int(alert_id))
        return jsonify({'acknowledged': alert_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/alerts/stream")
def api_autopilot_alerts_stream():
    """SSE: polls autopilot_alerts for new rows. Works across all processes (cron, Flask)."""
    import time as _t
    since = int(request.args.get('since', 0))
    SSE_MAX_LIFETIME = 300

    def generate():
        nonlocal since
        start = _t.time()
        while _t.time() - start < SSE_MAX_LIFETIME:
            try:
                from options import paper_trade
                db = paper_trade._db_path()
                conn = sqlite3.connect(db, timeout=5)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, timestamp, severity, category, title, detail "
                    "FROM autopilot_alerts WHERE id > ? ORDER BY id LIMIT 10",
                    (since,)
                ).fetchall()
                conn.close()
                for row in rows:
                    since = row['id']
                    yield f"data: {json.dumps(dict(row))}\n\n"
                if not rows:
                    yield ": heartbeat\n\n"
            except Exception:
                yield ": heartbeat\n\n"
            _t.sleep(2)

    return Response(stream_with_context(generate()),
                    content_type='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@options_bp.route("/api/options/autopilot/killswitch", methods=['POST'])
def api_autopilot_killswitch():
    """Activate/deactivate Dhan kill switch directly."""
    try:
        from options.data import dhan_fetch
        action = (request.json or {}).get('action', 'status')
        if action == 'activate':
            return jsonify(_json_clean(dhan_fetch.activate_kill_switch()))
        elif action == 'deactivate':
            return jsonify(_json_clean(dhan_fetch.deactivate_kill_switch()))
        else:
            return jsonify(_json_clean(dhan_fetch.kill_switch_status()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/execution")
def api_autopilot_execution():
    try:
        from options import paper_trade
        import sqlite3
        db = paper_trade._db_path()
        conn = sqlite3.connect(db, timeout=10)
        try:
            conn.execute('PRAGMA busy_timeout=10000')
            conn.row_factory = sqlite3.Row
        except Exception:
            conn.close()
            raise

        stats = {}

        # Queue stats
        try:
            q = conn.execute(
                "SELECT status, COUNT(*) as n FROM order_queue GROUP BY status"
            ).fetchall()
            stats['queue'] = {r['status']: r['n'] for r in q}
        except Exception:
            stats['queue'] = {}

        # Recent order events
        try:
            events = conn.execute(
                "SELECT * FROM order_events ORDER BY id DESC LIMIT 20"
            ).fetchall()
            stats['recent_events'] = [dict(r) for r in events]
        except Exception:
            stats['recent_events'] = []

        # Safety events
        try:
            safety = conn.execute(
                "SELECT * FROM safety_events ORDER BY id DESC LIMIT 10"
            ).fetchall()
            stats['safety_events'] = [dict(r) for r in safety]
        except Exception:
            stats['safety_events'] = []

        # Last reconciliation
        try:
            recon = conn.execute(
                "SELECT * FROM reconciliation_log ORDER BY id DESC LIMIT 5"
            ).fetchall()
            stats['reconciliation'] = [dict(r) for r in recon]
        except Exception:
            stats['reconciliation'] = []

        # Shadow comparison stats
        try:
            shadow = conn.execute(
                "SELECT COUNT(*) as total, SUM(match) as matches FROM shadow_log"
            ).fetchone()
            stats['shadow'] = {
                'total': shadow['total'] or 0,
                'matches': shadow['matches'] or 0,
                'match_rate': round((shadow['matches'] or 0) / max(1, shadow['total'] or 1) * 100, 1),
            }
        except Exception:
            stats['shadow'] = {'total': 0, 'matches': 0, 'match_rate': 0}

        return jsonify(_json_clean(stats))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@options_bp.route("/api/options/autopilot/account")
def api_autopilot_account():
    try:
        from options.data import dhan_fetch
        tok_status = dhan_fetch.get_token_status()
        result = {'token': tok_status, 'funds': None, 'positions': None}
        client = None
        if tok_status.get('active'):
            try:
                client = dhan_fetch._get_client()
                resp = client.get_fund_limits()
                if resp.get('status') == 'success':
                    result['funds'] = resp.get('data', {})
            except Exception as e:
                result['funds_error'] = str(e)
            try:
                if not client:
                    client = dhan_fetch._get_client()
                pos = client.get_positions()
                if pos.get('status') == 'success':
                    raw = pos.get('data', []) or []
                    result['positions'] = {
                        'count': len(raw),
                        'items': [{'symbol': p.get('tradingSymbol', ''),
                                   'qty': p.get('netQty', 0),
                                   'pnl': p.get('realizedProfit', 0) + p.get('unrealizedProfit', 0),
                                   'exchange': p.get('exchangeSegment', '')}
                                  for p in raw if p.get('netQty', 0) != 0],
                    }
            except Exception as e:
                result['positions_error'] = str(e)
        return jsonify(_json_clean(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/today")
def api_autopilot_today():
    try:
        from options import autopilot, paper_trade
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        log = autopilot.get_decision_log(limit=200)
        today_log = [e for e in log if (e.get('timestamp') or '')[:10] == today]
        entries = sum(1 for e in today_log if e.get('action') == 'enter')
        exits = sum(1 for e in today_log if e.get('action') == 'exit')
        skips = sum(1 for e in today_log if e.get('action') in ('skip_entry', 'no_opportunity'))
        cycles = sum(1 for e in today_log if e.get('action') == 'cycle_complete')
        preflight_ok = any(e.get('action') == 'preflight_ok' for e in today_log)

        db = paper_trade._db_path()
        conn = sqlite3.connect(db, timeout=10)
        conn.execute('PRAGMA busy_timeout=10000')
        conn.row_factory = sqlite3.Row
        closed_today = conn.execute(
            "SELECT COUNT(*) as n, COALESCE(SUM(net_pnl),0) as pnl, "
            "COALESCE(SUM(COALESCE(entry_cost,0)+COALESCE(exit_cost,0)),0) as costs "
            "FROM trades WHERE closed_at LIKE ? AND status='closed'",
            (today + '%',)
        ).fetchone()
        conn.close()

        return jsonify(_json_clean({
            'date': today,
            'entries': entries, 'exits': exits, 'skips': skips,
            'cycles': cycles, 'preflight_ok': preflight_ok,
            'closed_trades': closed_today['n'],
            'realized_pnl': closed_today['pnl'],
            'costs': closed_today['costs'],
        }))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/config-audit")
def api_autopilot_config_audit():
    try:
        from options.autopilot import _CONFIG_AUDIT
        entries = []
        if os.path.exists(_CONFIG_AUDIT):
            with open(_CONFIG_AUDIT) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        entries.reverse()
        limit = request.args.get('limit', 20, type=int)
        return jsonify({'entries': entries[:limit]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/autopilot/syslog")
def api_autopilot_syslog():
    try:
        from options.autopilot import get_syslog
        limit = request.args.get('limit', 100, type=int)
        level = request.args.get('level', None)
        return jsonify({'entries': get_syslog(limit, level)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Live Feed ─────────────────────────────────────────────────────


@options_bp.route("/api/options/live/subscribe", methods=['POST'])
def api_live_subscribe():
    try:
        from options.data.live_feed import feed
        symbols = (request.json or {}).get('symbols', ['NIFTY'])
        for sym in symbols:
            feed.subscribe_index(sym.upper())
        return jsonify({'ok': True, 'connected': feed.connected})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/live/stream")
def api_live_stream():
    """SSE endpoint — streams LTP updates sub-second via tick_event wake."""
    import time as _t, json as _json
    from options.data.live_feed import feed, INDEX_SID

    for sym in ['NIFTY', 'BANKNIFTY']:
        try:
            feed.subscribe_index(sym)
        except Exception:
            pass

    def generate():
        last = {}
        last_send = _t.time()
        started = last_send
        SSE_MAX_LIFETIME = 300
        last_rest_poll = 0
        REST_POLL_INTERVAL = 10
        st = feed.status()
        yield f"event: status\ndata: {_json.dumps(st)}\n\n"
        try:
            while _t.time() - started < SSE_MAX_LIFETIME:
                if not feed.connected and not feed._token_bad:
                    try:
                        feed.reconnect()
                    except Exception:
                        pass
                feed.wait_tick(timeout=5.0)
                snap = feed.snapshot()
                named = {}
                for sym, sid in INDEX_SID.items():
                    ltp = snap.get(sid)
                    if ltp is not None:
                        named[sym] = ltp
                now = _t.time()
                if not named and now - last_rest_poll > REST_POLL_INTERVAL:
                    last_rest_poll = now
                    try:
                        from options.data import dhan_fetch
                        for sym in ['NIFTY', 'BANKNIFTY']:
                            try:
                                spot = dhan_fetch.fetch_spot(sym)
                                if spot:
                                    named[sym] = spot
                            except Exception:
                                pass
                    except Exception:
                        pass
                if named != last:
                    payload = {'prices': named, 'ws_live': feed.connected}
                    yield f"data: {_json.dumps(payload)}\n\n"
                    last = dict(named)
                    last_send = now
                elif now - last_send > 15:
                    yield f": keepalive {int(now)}\n\n"
                    last_send = now
        except (GeneratorExit, BrokenPipeError, ConnectionResetError, OSError):
            return

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@options_bp.route("/api/options/live/orders/stream")
def api_order_stream():
    """SSE endpoint — real-time order updates via Dhan OrderUpdate WebSocket."""
    import time as _t, json as _json
    from options.data.live_feed import order_feed

    order_feed.start()

    def generate():
        seen = 0
        last_send = _t.time()
        started = last_send
        SSE_MAX_LIFETIME = 300
        st = order_feed.status()
        yield f"event: status\ndata: {_json.dumps(st)}\n\n"
        try:
            while _t.time() - started < SSE_MAX_LIFETIME:
                if not order_feed._started and not order_feed._token_bad:
                    try:
                        order_feed.reconnect()
                    except Exception:
                        pass
                order_feed.wait_update(timeout=0.3)
                orders = order_feed.recent(50)
                if len(orders) > seen:
                    for o in orders[seen:]:
                        payload = _json_clean(o)
                        yield f"data: {_json.dumps(payload)}\n\n"
                    seen = len(orders)
                    last_send = _t.time()
                elif _t.time() - last_send > 15:
                    yield f": keepalive {int(_t.time())}\n\n"
                    last_send = _t.time()
        except (GeneratorExit, BrokenPipeError, ConnectionResetError, OSError):
            return

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@options_bp.route("/api/options/live/depth/stream")
def api_depth_stream():
    """SSE endpoint — real-time 20-depth market data via FullDepth WebSocket."""
    import time as _t, json as _json
    from options.data.live_feed import depth_feed

    def generate():
        last_snap = {}
        last_send = _t.time()
        started = last_send
        SSE_MAX_LIFETIME = 300
        st = depth_feed.status()
        yield f"event: status\ndata: {_json.dumps(st)}\n\n"
        try:
            while _t.time() - started < SSE_MAX_LIFETIME:
                if not depth_feed._started and not depth_feed._token_bad and depth_feed._instruments:
                    try:
                        depth_feed.reconnect()
                    except Exception:
                        pass
                depth_feed.wait_tick(timeout=0.15)
                snap = depth_feed.snapshot()
                if snap != last_snap:
                    payload = _json_clean(snap)
                    yield f"data: {_json.dumps(payload)}\n\n"
                    last_snap = dict(snap)
                    last_send = _t.time()
                elif _t.time() - last_send > 15:
                    yield f": keepalive {int(_t.time())}\n\n"
                    last_send = _t.time()
        except (GeneratorExit, BrokenPipeError, ConnectionResetError, OSError):
            return

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@options_bp.route("/api/options/live/depth/subscribe", methods=['POST'])
def api_depth_subscribe():
    """Subscribe instruments to FullDepth WebSocket."""
    from options.data.live_feed import depth_feed, NSE_FNO
    try:
        data = request.json or {}
        instruments = data.get('instruments', [])
        for inst in instruments:
            seg = inst.get('segment', NSE_FNO)
            sid = inst.get('security_id')
            if sid:
                depth_feed.subscribe(seg, int(sid))
        return jsonify({'ok': True, **depth_feed.status()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@options_bp.route("/api/options/live/chain/stream")
def api_chain_stream():
    """SSE endpoint — option chain updates polled at ~1s via REST (no WS available)."""
    import time as _t, json as _json
    from options.data.live_feed import chain_poller

    symbol = request.args.get('symbol', 'NIFTY').upper()
    chain_poller.add_symbol(symbol)

    def generate():
        last_ts = 0
        last_send = _t.time()
        started = last_send
        SSE_MAX_LIFETIME = 300
        st = chain_poller.status()
        yield f"event: status\ndata: {_json.dumps(st)}\n\n"
        try:
            while _t.time() - started < SSE_MAX_LIFETIME:
                chain_poller.wait_update(timeout=0.5)
                chain = chain_poller.chain(symbol)
                if chain and chain.get('timestamp', 0) > last_ts:
                    last_ts = chain['timestamp']
                    payload = _json_clean({
                        'symbol': symbol,
                        'spot': chain.get('spot'),
                        'timestamp': last_ts,
                        'chain': chain.get('data'),
                    })
                    yield f"data: {_json.dumps(payload)}\n\n"
                    last_send = _t.time()
                elif _t.time() - last_send > 15:
                    yield f": keepalive {int(_t.time())}\n\n"
                    last_send = _t.time()
        except (GeneratorExit, BrokenPipeError, ConnectionResetError, OSError):
            return

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@options_bp.route("/api/options/live/positions/stream")
def api_positions_stream():
    """SSE endpoint — positions/orders polled at ~0.5s via REST."""
    import time as _t, json as _json
    from options.data.live_feed import position_poller

    position_poller.start()

    def generate():
        last_send = _t.time()
        started = last_send
        SSE_MAX_LIFETIME = 300
        last_data = None
        st = position_poller.status()
        yield f"event: status\ndata: {_json.dumps(st)}\n\n"
        try:
            while _t.time() - started < SSE_MAX_LIFETIME:
                position_poller.wait_update(timeout=0.5)
                current = {
                    'positions': position_poller.positions(),
                    'orders': position_poller.orders(),
                }
                if current != last_data:
                    payload = _json_clean(current)
                    yield f"data: {_json.dumps(payload)}\n\n"
                    last_data = current
                    last_send = _t.time()
                elif _t.time() - last_send > 15:
                    yield f": keepalive {int(_t.time())}\n\n"
                    last_send = _t.time()
        except (GeneratorExit, BrokenPipeError, ConnectionResetError, OSError):
            return

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
