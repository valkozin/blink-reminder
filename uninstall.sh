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

# Only processes running from our venv: a bare "blinkreminder" also matched an editor or
# shell sitting in the source folder.
pkill -f "$VENV/bin/" 2>/dev/null || true

# The command link, but only if it is ours - never someone else's blink-reminder.
LINK="${BLINK_BIN:-$HOME/.local/bin}/blink-reminder"
if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$VENV/bin/blink-reminder" ]; then
    rm -f "$LINK"
fi

# The venv, not the whole of APP_HOME: BLINK_HOME=~ would otherwise delete the home folder.
rm -rf "$VENV"
rmdir "$APP_HOME" 2>/dev/null || true
echo "Removed $APP_HOME and the login item."

read -r -p "Also delete settings and statistics? [y/N] " reply
if [ "$reply" = "y" ] || [ "$reply" = "Y" ]; then
    rm -rf "$HOME/Library/Application Support/BlinkReminder"
    echo "Settings removed."
fi
