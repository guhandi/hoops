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
