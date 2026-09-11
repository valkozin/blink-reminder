#!/usr/bin/env bash
# Removes the login item, the virtualenv and (optionally) your settings.
set -euo pipefail

APP_HOME="${BLINK_HOME:-$HOME/.local/share/blink-reminder}"
VENV="$APP_HOME/venv"
LABEL="com.valkozin.blinkreminder"

if [ -x "$VENV/bin/blink-reminder" ]; then
    "$VENV/bin/blink-reminder" --uninstall-autostart || true
else
    /bin/launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
fi

pkill -f "blinkreminder" 2>/dev/null || true
rm -rf "$APP_HOME"
echo "Removed $APP_HOME and the login item."

read -r -p "Also delete settings and statistics? [y/N] " reply
if [ "$reply" = "y" ] || [ "$reply" = "Y" ]; then
    rm -rf "$HOME/Library/Application Support/BlinkReminder"
    echo "Settings removed."
fi
