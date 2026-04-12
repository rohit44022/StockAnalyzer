#!/bin/bash
# Hiranya — Clear cache & run the app

echo "🧹 Clearing caches..."

# Kill existing server on port 5001
lsof -ti :5001 | xargs kill -9 2>/dev/null

# Clear Python bytecode caches
find "$(dirname "$0")" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Clear app cache
rm -rf "$(dirname "$0")/bb_squeeze/cache/"* 2>/dev/null

# Clear .pyc files
find "$(dirname "$0")" -name "*.pyc" -delete 2>/dev/null

echo "✅ Cache cleared"
sleep 1

echo "🚀 Starting Hiranya..."
cd "$(dirname "$0")" && python3 web/app.py
