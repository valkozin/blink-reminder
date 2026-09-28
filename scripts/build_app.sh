#!/usr/bin/env bash
# Builds "Blink Reminder.app" and a .dmg for it with PyInstaller. Run on a Mac:
#
#   ./scripts/build_app.sh
#       Signed ad hoc: runs on this Mac, but other Macs refuse to open it.
#
#   BLINK_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./scripts/build_app.sh
#       Signed with your Developer ID and the hardened runtime.
#
#   ... BLINK_NOTARY_PROFILE=blink ./scripts/build_app.sh
#       Also notarizes and staples the .dmg. Create the profile once with
#       xcrun notarytool store-credentials blink --apple-id ... --team-id ...
#
# The result lands in dist/. The app is built for this Mac's architecture only: the
# OpenCV wheels are not universal.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$SRC/build/app"
DIST="$SRC/dist"
VENV="$BUILD/venv"
SPEC="$SRC/packaging/macos/BlinkReminder.spec"
APP_NAME="Blink Reminder"
APP="$DIST/$APP_NAME.app"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

if [ "$(uname -s)" != "Darwin" ]; then
    echo "The app can only be built on macOS." >&2
    exit 1
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/blinkreminder/__init__.py")"
mkdir -p "$BUILD"

# ---------------------------------------------------------------- build environment
# A virtualenv of its own, apart from the one install.sh uses, so building never
# disturbs the copy you run every day.
if [ ! -x "$VENV/bin/python" ]; then
    say "Creating the build environment in $VENV"
    # A Homebrew or python.org interpreter first: those are what PyInstaller is tested on.
    PYTHON=""
    for candidate in python3.12 python3.11 python3.10 python3.9; do
        if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
    done
    if [ -n "$PYTHON" ]; then
        "$PYTHON" -m venv "$VENV"
    elif command -v uv >/dev/null 2>&1; then
        uv venv --seed --python 3.12 "$VENV"
    else
        echo "No suitable Python found. MediaPipe needs Python 3.9-3.12." >&2
        echo "Install one with:  brew install python@3.12" >&2
        exit 1
    fi
fi
PY="$VENV/bin/python"

say "Installing dependencies and PyInstaller"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$SRC/requirements.txt" "pyinstaller>=6.10"

# MediaPipe depends on opencv-contrib-python, requirements.txt on opencv-python, and
# both unpack into the same cv2/ folder - the bundle would get a mix of the two plus both
# sets of libraries. Keep the plain one: the app uses nothing from contrib.
if "$PY" -m pip show --quiet opencv-contrib-python >/dev/null 2>&1; then
    OPENCV="$("$PY" -m pip show opencv-python | sed -n 's/^Version: //p')"
    "$PY" -m pip uninstall --quiet --yes opencv-contrib-python
    "$PY" -m pip install --quiet --force-reinstall --no-deps "opencv-python==$OPENCV"
fi

# ---------------------------------------------------------------- icon
ICNS="$BUILD/BlinkReminder.icns"
ICONSET="$BUILD/BlinkReminder.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$SRC/docs/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    # The source is 512 px, so there is no 512@2x.
    if [ "$double" -le 512 ]; then
        sips -z "$double" "$double" "$SRC/docs/icon.png" \
            --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
    fi
done
iconutil -c icns "$ICONSET" -o "$ICNS"

# ---------------------------------------------------------------- the app
say "Building $APP_NAME.app $VERSION"
rm -rf "$APP" "$DIST/BlinkReminder"
BLINK_ICON="$ICNS" "$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN \
    --distpath "$DIST" --workpath "$BUILD/work" "$SPEC"
rm -rf "$DIST/BlinkReminder"  # the bare folder PyInstaller builds the bundle from

codesign --verify --deep --strict "$APP"

say "Checking the face mesh inside the bundle"
BLINK_SELFTEST=1 "$APP/Contents/MacOS/BlinkReminder"
"$APP/Contents/MacOS/BlinkReminder" --version

# ---------------------------------------------------------------- disk image
DMG="$DIST/BlinkReminder-$VERSION.dmg"
STAGING="$BUILD/dmg"
rm -rf "$STAGING" "$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -quiet -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
rm -rf "$STAGING"

if [ -n "${BLINK_CODESIGN_IDENTITY:-}" ]; then
    codesign --sign "$BLINK_CODESIGN_IDENTITY" --timestamp "$DMG"
fi
if [ -n "${BLINK_NOTARY_PROFILE:-}" ]; then
    if [ -z "${BLINK_CODESIGN_IDENTITY:-}" ]; then
        echo "Notarization needs a Developer ID: set BLINK_CODESIGN_IDENTITY too." >&2
        exit 1
    fi
    say "Notarizing (this usually takes a few minutes)"
    xcrun notarytool submit "$DMG" --keychain-profile "$BLINK_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
fi

say "Done"
printf '  %-7s %s  (%s)\n' app "$APP" "$(du -sh "$APP" | cut -f1)"
printf '  %-7s %s  (%s)\n' dmg "$DMG" "$(du -sh "$DMG" | cut -f1)"
