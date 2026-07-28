#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
uv sync                                    # ensures .venv/bin/hoops exists
cp scripts/com.guhan.hoops.plist ~/Library/LaunchAgents/
launchctl bootout "gui/$(id -u)/com.guhan.hoops" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.guhan.hoops.plist
launchctl print "gui/$(id -u)/com.guhan.hoops" | head -20
echo "installed: hoops poll every 300s, logs in logs/poll.log"

# Force one real run now and check that it actually succeeded — a clean
# bootstrap only means launchd accepted the job, not that `hoops poll` can
# read the inbox (e.g. TCC/Full Disk Access denials fail silently here).
launchctl kickstart -k "gui/$(id -u)/com.guhan.hoops"
sleep 5
if launchctl list com.guhan.hoops | grep -q '"LastExitStatus" = 0;'; then
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
