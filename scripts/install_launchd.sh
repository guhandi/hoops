#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
LABEL="com.hoops.poller"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p logs
uv sync --inexact                          # ensures .venv/bin/hoops exists, removes nothing
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/hoops</string>
    <string>poll</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>$REPO/logs/poll.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/poll.log</string>
</dict>
</plist>
EOF
if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "dry run: wrote $PLIST, skipping bootstrap"; exit 0
fi
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL" | head -20
echo "installed: hoops poll every 300s, logs in logs/poll.log"

# Force one real run now and check that it actually succeeded — a clean
# bootstrap only means launchd accepted the job, not that `hoops poll` can
# read the inbox (e.g. TCC/Full Disk Access denials fail silently here).
launchctl kickstart -k "gui/$(id -u)/$LABEL"
sleep 5
if launchctl list "$LABEL" | grep -q '"LastExitStatus" = 0;'; then
    echo "verified: last run exited 0"
else
    echo "ERROR: hoops poll did not exit cleanly on its test run." >&2
    echo "This usually means the interpreter lacks Full Disk Access —" >&2
    echo "grant it in System Settings > Privacy & Security > Full Disk Access" >&2
    echo "for the Python binary hoops runs under, then re-run this script." >&2
    echo "--- last lines of logs/poll.log ---" >&2
    tail -n 20 logs/poll.log >&2 2>/dev/null || echo "(no logs/poll.log yet)" >&2
    exit 1
fi
