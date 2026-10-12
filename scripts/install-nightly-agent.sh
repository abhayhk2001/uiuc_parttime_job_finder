#!/usr/bin/env bash
# Install (or remove) the launchd nightly-scan agent.
#
# The agent points at the *built* .app binary, not the repo's Python
# source, so rebuilding the app with ./build-mac.sh never breaks the
# schedule: the bundle is replaced in place at the same path.
#
# Usage:
#   scripts/install-nightly-agent.sh            # install + (re)bootstrap
#   scripts/install-nightly-agent.sh --uninstall
#
# What it installs:
#   ~/Library/LaunchAgents/edu.illinois.jobscanner.nightly.plist
#
# Schedule (all in the user's GUI session, so it also runs while the
# screen is locked):
#   - every day at 21:00 local time (StartCalendarInterval);
#   - when the Mac wakes after sleeping through 21:00 (launchd runs
#     missed calendar jobs at wake);
#   - on every login/reboot (RunAtLoad) -- the app's own
#     ".last_nightly_scan" marker keeps this from re-scanning when the
#     21:00 slot already ran successfully.
#
# The agent runs "UIUC Part-Time Job Scanner --scan-and-open", which
# scans every source and then opens the GUI showing fresh results.
set -euo pipefail

LABEL="edu.illinois.jobscanner.nightly"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_BIN="$REPO_ROOT/dist/UIUC Part-Time Job Scanner.app/Contents/MacOS/UIUC Part-Time Job Scanner"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/$LABEL.plist"
DATA_DIR="$HOME/Library/Application Support/UIUC Part-Time Job Scanner"
LOG_OUT="$DATA_DIR/scanner-nightly.log"
LOG_ERR="$DATA_DIR/scanner-nightly.err.log"

DOMAIN="gui/$(id -u)/$LABEL"

# Escape XML-special characters in file paths baked into the plist.
xml_escape() {
    local s="$1"
    s="${s//&/&amp;}"
    s="${s//</&lt;}"
    s="${s//>/&gt;}"
    printf '%s' "$s"
}

if [[ "${1:-}" == "--uninstall" ]]; then
    launchctl bootout "$DOMAIN" >/dev/null 2>&1 || true
    rm -f "$PLIST"
    echo "Removed $PLIST and unloaded the agent."
    exit 0
fi

if [[ ! -x "$APP_BIN" ]]; then
    echo "error: $APP_BIN not found or not executable." >&2
    echo "Run ./build-mac.sh first, then re-run this script." >&2
    exit 1
fi

mkdir -p "$AGENT_DIR" "$DATA_DIR"

BIN_ESC="$(xml_escape "$APP_BIN")"
OUT_ESC="$(xml_escape "$LOG_OUT")"
ERR_ESC="$(xml_escape "$LOG_ERR")"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BIN_ESC</string>
        <string>--scan-and-open</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>21</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>$OUT_ESC</string>
    <key>StandardErrorPath</key>
    <string>$ERR_ESC</string>
</dict>
</plist>
EOF

# Reload: bootout the old instance (may not exist -- that's fine), then
# bootstrap the fresh plist.
launchctl bootout "$DOMAIN" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed $PLIST"
echo "Schedule: every day at 21:00 local; missed slots run at wake/reboot."
echo "Logs:     $LOG_OUT"
echo "Remove:   scripts/install-nightly-agent.sh --uninstall"
