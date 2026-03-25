#!/bin/bash
set -euo pipefail

LABEL="com.richard.sunouploader.menubar"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$PROJECT_DIR/scripts/run-menu-bar.sh"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
APP_SUPPORT_DIR="$HOME/Library/Application Support/SunoUploader"
LOG_DIR="$HOME/Library/Logs/SunoUploader"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
TERMINAL_LAUNCHER="$APP_SUPPORT_DIR/login-menu-bar.command"
PROGRAM_BLOCK=""

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR" "$APP_SUPPORT_DIR"

if [ ! -x "$RUNNER" ]; then
  echo "Runner script is not executable: $RUNNER" >&2
  exit 1
fi

case "$PROJECT_DIR" in
  "$HOME/Desktop"/*|"$HOME/Documents"/*|"$HOME/Downloads"/*)
    cat > "$TERMINAL_LAUNCHER" <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
nohup "$RUNNER" > /tmp/suno_menu_app_auto.log 2>&1 &
exit 0
EOF
    chmod +x "$TERMINAL_LAUNCHER"
    PROGRAM_BLOCK=$(cat <<EOF
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-gj</string>
    <string>-a</string>
    <string>Terminal</string>
    <string>$TERMINAL_LAUNCHER</string>
  </array>
EOF
)
    ;;
  *)
    PROGRAM_BLOCK=$(cat <<EOF
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNNER</string>
  </array>
EOF
)
    rm -f "$TERMINAL_LAUNCHER"
    ;;
esac

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
$PROGRAM_BLOCK
  <key>WorkingDirectory</key>
  <string>$HOME</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/menu_bar.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/menu_bar.err.log</string>
</dict>
</plist>
EOF

chmod 644 "$PLIST_PATH"

if [ "${SUNO_SKIP_LAUNCHCTL:-0}" != "1" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl enable "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
fi

echo "Installed auto-start agent: $PLIST_PATH"
