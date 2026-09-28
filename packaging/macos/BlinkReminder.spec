# -*- mode: python -*-
"""PyInstaller recipe for Blink Reminder.app. Build with scripts/build_app.sh.

Environment (all optional):
  BLINK_CODESIGN_IDENTITY  "Developer ID Application: ..." - sign with hardened runtime;
                           without it the app is signed ad hoc, which only this Mac trusts
  BLINK_ICON               path to an .icns file
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

HERE = Path(SPECPATH).resolve()
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from blinkreminder import APP_NAME, BUNDLE_ID, __version__  # noqa: E402

IDENTITY = os.environ.get("BLINK_CODESIGN_IDENTITY") or None
ICON = os.environ.get("BLINK_ICON") or None

# MediaPipe ships models for hands, poses, segmentation and more (~30 MB). The face mesh
# with refined eyes needs the short-range face detector and the face landmark graph only.
mediapipe_models = collect_data_files(
    "mediapipe",
    includes=[
        "modules/face_detection/face_detection_short_range*",
        "modules/face_landmark/*",
    ],
)

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT)],
    datas=mediapipe_models + [
        (str(HERE / "en.lproj" / "InfoPlist.strings"), "en.lproj"),
        (str(HERE / "ru.lproj" / "InfoPlist.strings"), "ru.lproj"),
    ],
    # Pulled in by MediaPipe's dependency list, never imported by the face mesh.
    # matplotlib is replaced by an empty stub in launcher.py.
    excludes=[
        "matplotlib", "PIL", "jax", "jaxlib", "scipy", "sounddevice", "sentencepiece",
        "tkinter", "_tkinter", "IPython", "pytest", "pip", "setuptools",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BlinkReminder",
    console=False,
    strip=False,
    upx=False,
    argv_emulation=False,
    codesign_identity=IDENTITY,
    entitlements_file=str(HERE / "entitlements.plist"),
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BlinkReminder")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "CFBundleDevelopmentRegion": "en",
            "CFBundleLocalizations": ["en", "ru"],
            # Menu bar only: no Dock icon, not even while launching.
            "LSUIElement": True,
            # The OpenCV wheels for Apple Silicon need macOS 13.
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.healthcare-fitness",
            "NSHighResolutionCapable": True,
            # Without it macOS kills the app the moment it asks for the camera.
            # Translated in ru.lproj/InfoPlist.strings.
            "NSCameraUsageDescription": (
                "Blink Reminder watches your eyelids to count blinks. Frames are "
                "analysed on this Mac and are never saved or sent anywhere."
            ),
        },
    )
