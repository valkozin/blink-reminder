#!/usr/bin/env bash
# Installs Blink Reminder into a private virtualenv outside this folder, so the
# app keeps working if the project directory is moved, renamed or cloud-synced.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_HOME="${BLINK_HOME:-$HOME/.local/share/blink-reminder}"
VENV="$APP_HOME/venv"
BIN_DIR="${BLINK_BIN:-$HOME/.local/bin}"

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

# The login item runs through a tiny app bundle, so the camera permission is granted to
# Blink Reminder rather than to a Python interpreter anything else can run (see
# macos/launcher.c). autostart.py falls back to plain Python when the bundle is missing.
APP="$APP_HOME/Blink Reminder.app"
build_app() {
    rm -rf "$APP"
    # set -e is off inside a function called from `if`, hence the explicit returns.
    mkdir -p "$APP/Contents/MacOS" || return 1
    clang -O2 -DPYTHON="\"$VENV/bin/python3\"" -o "$APP/Contents/MacOS/blink-reminder" \
        "$SRC/macos/launcher.c" || return 1
    cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>com.valkozin.blinkreminder</string>
    <key>CFBundleName</key><string>Blink Reminder</string>
    <key>CFBundleExecutable</key><string>blink-reminder</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSUIElement</key><true/>
    <key>NSCameraUsageDescription</key>
    <string>Blink Reminder counts your blinks. Frames never leave this Mac.</string>
</dict>
</plist>
EOF
    codesign --force --sign - "$APP"
}
if xcode-select -p >/dev/null 2>&1 && build_app; then
    say "Built $APP"
else
    rm -rf "$APP"
    echo "Could not build the app bundle (install the tools with: xcode-select --install)." >&2
    echo "Falling back to plain Python: the camera permission will belong to the interpreter." >&2
fi

# Put the command on PATH the way uv and pipx do: a link in ~/.local/bin. Without it the
# terminal controls (--quit, --pause, --status) only work by their full path, and the one
# moment you need them - the menu bar icon is out of reach - is when you remember that least.
link_command() {
    local target="$BIN_DIR/blink-reminder"
    mkdir -p "$BIN_DIR"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        echo "Not linking: $target exists and is not ours. Use $VENV/bin/blink-reminder." >&2
        return 0
    fi
    ln -sfn "$VENV/bin/blink-reminder" "$target"
    case ":$PATH:" in
        *":$BIN_DIR:"*)
            say "Linked the command: blink-reminder --help" ;;
        *)
            say "Linked $target"
            echo "  $BIN_DIR is not on your PATH yet. Add this line to ~/.zshrc and open a new terminal:"
            echo "      export PATH=\"$BIN_DIR:\$PATH\"" ;;
    esac
}
link_command

start_as_login_item() {
    say "Registering the login item and starting the app"
    "$VENV/bin/blink-reminder" --install-autostart
    cat <<EOF

macOS will now ask whether Blink Reminder may use the camera - click Allow.
(The request is made by the background agent, which is exactly the context the
app runs in at every login, so this one answer covers it for good.)

An eye appears in the menu bar. Everything is configured from there; use Quit in
that menu to stop it, and run ./uninstall.sh to remove it entirely.

From a terminal, whether or not the icon is in sight:
    blink-reminder --status     blink-reminder --pause 30
    blink-reminder --quit       blink-reminder --start
EOF
}

manual_instructions() {
    cat <<EOF

Done. To start it:

    blink-reminder --start

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
