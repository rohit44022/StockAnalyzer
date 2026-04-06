# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Stock Analyzer macOS App
============================================
Bundles the Flask web dashboard + all analysis engines into a native
macOS .app that opens in a WebKit window (pywebview).

Build:  pyinstaller StockAnalyzer.spec --clean --noconfirm
Output: dist/StockAnalyzer.app
"""

import os, glob

ROOT = os.path.abspath(".")

# ── Data files to bundle ────────────────────────────────────────
templates = [(f, "web/templates") for f in glob.glob("web/templates/*.html")]
stock_csvs = [(f, "stock_csv") for f in glob.glob("stock_csv/*.csv")]

extra = []
if os.path.exists("tickers_cache.json"):
    extra.append(("tickers_cache.json", "."))

datas = templates + stock_csvs + extra

# ── Hidden imports (PyInstaller can't auto-detect all of these) ──
hidden = [
    # Flask & web layer
    "flask", "jinja2", "markupsafe", "werkzeug", "itsdangerous", "click", "blinker",
    "web", "web.app", "web.ta_routes", "web.hybrid_routes",
    "web.top_picks_routes", "web.pa_routes",
    # Data / numeric
    "pandas", "numpy", "yfinance", "requests", "urllib3", "certifi",
    "charset_normalizer", "idna", "lxml", "html5lib",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.np_datetime",
    # BB Squeeze
    "bb_squeeze", "bb_squeeze.config", "bb_squeeze.data_loader",
    "bb_squeeze.indicators", "bb_squeeze.signals", "bb_squeeze.fundamentals",
    "bb_squeeze.strategies", "bb_squeeze.quant_strategy", "bb_squeeze.scanner",
    "bb_squeeze.display", "bb_squeeze.exporter", "bb_squeeze.trade_db",
    "bb_squeeze.trade_calculator", "bb_squeeze.portfolio_db",
    "bb_squeeze.portfolio_analyzer", "bb_squeeze.strategy_config",
    # Technical Analysis
    "technical_analysis", "technical_analysis.indicators",
    "technical_analysis.candlesticks", "technical_analysis.patterns",
    "technical_analysis.signals", "technical_analysis.risk_manager",
    "technical_analysis.target_price", "technical_analysis.education",
    "technical_analysis.config",
    # Hybrid
    "hybrid_engine",
    # Price Action
    "price_action", "price_action.engine", "price_action.bar_types",
    "price_action.breakouts", "price_action.channels", "price_action.config",
    "price_action.patterns", "price_action.scanner", "price_action.signals",
    "price_action.trend_analyzer",
    # Top Picks
    "top_picks", "top_picks.config", "top_picks.engine", "top_picks.scorer",
    # pywebview
    "webview",
    # Historical data (ticker management)
    "historical_data",
    # Rich (used by main.py, may be pulled in)
    "rich",
    # sqlite built-in
    "sqlite3",
]

# ── Analysis ────────────────────────────────────────────────────
a = Analysis(
    ["desktop_app.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "matplotlib.backends",
        "test",
        "unittest",
        "IPython",
        "notebook",
        "pytest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StockAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # ← No terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="StockAnalyzer",
)

app = BUNDLE(
    coll,
    name="StockAnalyzer.app",
    icon=None,               # Add a .icns file here for a custom icon
    bundle_identifier="com.stockanalyzer.app",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleName": "Stock Analyzer",
        "CFBundleDisplayName": "Stock Analyzer",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.15",
    },
)
