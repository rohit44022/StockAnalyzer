#!/bin/bash
# Hiranya — Production server (Gunicorn)
#
# Usage:  bash run_prod.sh
# Before first run:
#   1. pip install -r requirements.txt
#   2. Set FLASK_ENV=production in .env
#   3. Ensure HTTPS is configured (reverse proxy / Cloudflare)

set -e
cd "$(dirname "$0")"

export FLASK_ENV=production

echo "🚀 Starting Hiranya (production)..."
exec gunicorn \
    --bind 0.0.0.0:5001 \
    --workers 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    web.app:app
