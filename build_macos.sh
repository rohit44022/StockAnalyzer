#!/bin/bash
# ================================================================
#  Build Stock Analyzer — macOS .app
# ================================================================
#  Prerequisites: Python 3.10+ installed
#  Output:        dist/StockAnalyzer.app
#
#  Usage:
#    chmod +x build_macos.sh
#    ./build_macos.sh
#
#  After build:
#    - Drag  dist/StockAnalyzer.app  to /Applications
#    - Double-click to launch
#    - Data stored in ~/Documents/StockAnalyzer/
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         Stock Analyzer — macOS App Builder              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Install / upgrade build dependencies ────────────────
echo "▸ Installing build dependencies..."
pip3 install --upgrade pyinstaller pywebview 2>&1 | tail -5
echo "  ✓ pyinstaller + pywebview installed"
echo ""

# ── Step 2: Install runtime dependencies ────────────────────────
echo "▸ Installing runtime dependencies..."
pip3 install flask pandas numpy yfinance requests rich 2>&1 | tail -5
echo "  ✓ Runtime packages installed"
echo ""

# ── Step 3: Verify desktop_app.py compiles ──────────────────────
echo "▸ Verifying desktop_app.py..."
python3 -c "import py_compile; py_compile.compile('desktop_app.py', doraise=True)"
echo "  ✓ No syntax errors"
echo ""

# ── Step 4: Clean previous builds ──────────────────────────────
echo "▸ Cleaning previous builds..."
rm -rf build/StockAnalyzer dist/StockAnalyzer dist/StockAnalyzer.app
echo "  ✓ Clean"
echo ""

# ── Step 5: Run PyInstaller ────────────────────────────────────
echo "▸ Building .app bundle (this takes a few minutes)..."
echo ""
pyinstaller StockAnalyzer.spec --clean --noconfirm 2>&1

echo ""
echo "──────────────────────────────────────────────────────────"

# ── Step 6: Verify output ──────────────────────────────────────
if [ -d "dist/StockAnalyzer.app" ]; then
    SIZE=$(du -sh "dist/StockAnalyzer.app" | cut -f1)
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  ✅  BUILD SUCCESSFUL                                   ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  App:   dist/StockAnalyzer.app                          ║"
    echo "║  Size:  $SIZE                                          ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  To install:                                            ║"
    echo "║    cp -r dist/StockAnalyzer.app /Applications/          ║"
    echo "║                                                         ║"
    echo "║  To run:                                                ║"
    echo "║    open dist/StockAnalyzer.app                          ║"
    echo "║                                                         ║"
    echo "║  Data directory (created on first launch):              ║"
    echo "║    ~/Documents/StockAnalyzer/                           ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
else
    echo ""
    echo "  ❌  BUILD FAILED — dist/StockAnalyzer.app not found"
    echo "  Check the output above for errors."
    exit 1
fi
