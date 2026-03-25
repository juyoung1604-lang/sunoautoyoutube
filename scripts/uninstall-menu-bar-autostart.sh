#!/bin/bash
set -euo pipefail

LABEL="com.richard.sunouploader.menubar"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
APP_SUPPORT_DIR="$HOME/Library/Application Support/SunoUploader"
TERMINAL_LAUNCHER="$APP_SUPPORT_DIR/login-menu-bar.command"

if [ "${SUNO_SKIP_LAUNCHCTL:-0}" != "1" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl disable "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
fi

rm -f "$PLIST_PATH"
rm -f "$TERMINAL_LAUNCHER"

echo "Removed auto-start agent: $PLIST_PATH"
