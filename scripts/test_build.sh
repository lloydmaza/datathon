#!/usr/bin/env bash
# Mirrors the GitHub Actions deploy workflow locally.
# Run from the repo root: bash scripts/test_build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> [1/3] Building web data (CSV → JSON)..."
python scripts/build_web_data.py

echo ""
echo "==> [2/3] Installing JS dependencies..."
cd web
NODE_ENV=development npm ci --include=dev

echo ""
echo "==> [3/3] Building static site..."
npm run build

echo ""
echo "✓ Build complete. Output in web/dist/"
echo "  Preview with: cd web && npm run preview"
