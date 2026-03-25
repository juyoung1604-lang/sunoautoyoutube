#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$PROJECT_DIR/venv/bin/python"
APP="$PROJECT_DIR/menu_bar_app.py"

if [ ! -x "$PYTHON" ]; then
  echo "venv Python not found: $PYTHON" >&2
  exit 1
fi

if [ ! -f "$APP" ]; then
  echo "menu_bar_app.py not found: $APP" >&2
  exit 1
fi

cd "$PROJECT_DIR"
exec "$PYTHON" "$APP"
