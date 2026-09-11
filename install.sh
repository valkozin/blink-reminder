#!/usr/bin/env bash
# Installs Blink Reminder into a private virtualenv outside this folder, so the
# app keeps working if the project directory is moved, renamed or cloud-synced.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_HOME="${BLINK_HOME:-$HOME/.local/share/blink-reminder}"
VENV="$APP_HOME/venv"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

find_python() {
    for candidate in python3.12 python3.11 python3.10 python3.9; do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

say "Installing Blink Reminder into $VENV"
mkdir -p "$APP_HOME"

if [ ! -x "$VENV/bin/python" ]; then
    if command -v uv >/dev/null 2>&1; then
        # uv downloads a suitable interpreter if the system has none.
        uv venv --python 3.12 "$VENV"
    elif PYTHON="$(find_python)"; then
        "$PYTHON" -m venv "$VENV"
    else
        echo "No suitable Python found. MediaPipe needs Python 3.9-3.12." >&2
        echo "Install one with:  brew install python@3.12" >&2
        exit 1
    fi
fi

say "Installing dependencies (this pulls ~700 MB of MediaPipe/OpenCV wheels, give it a minute)"
if command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="$VENV" uv pip install --quiet "$SRC"
else
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet "$SRC"
fi

"$VENV/bin/blink-reminder" --version

start_as_login_item() {
    say "Registering the login item and starting the app"
    "$VENV/bin/blink-reminder" --install-autostart
    cat <<EOF

macOS will now ask whether Blink Reminder may use the camera - click Allow.
(The request is made by the background agent, which is exactly the context the
app runs in at every login, so this one answer covers it for good.)

An eye appears in the menu bar. Everything is configured from there; use Quit in
that menu to stop it, and run ./uninstall.sh to remove it entirely.
EOF
}

manual_instructions() {
    cat <<EOF

Done. To start it:

    $VENV/bin/blink-reminder

An eye appears in the menu bar; allow camera access when macOS asks. Turn on
"Start at login" in that menu when you are happy with it.
EOF
}

if [ "${1:-}" = "--autostart" ]; then
    start_as_login_item
elif [ -t 0 ] && [ "${1:-}" != "--no-autostart" ]; then
    printf '\n'
    read -r -p "Start Blink Reminder now and at every login? [Y/n] " reply
    case "$reply" in
        [Nn]*) manual_instructions ;;
        *) start_as_login_item ;;
    esac
else
    manual_instructions
fi
