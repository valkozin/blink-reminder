"""Start at login, via a launchd user agent (no extra tooling, survives reboots)."""

from __future__ import annotations

import logging
import plistlib
import subprocess
import sys
from pathlib import Path

from . import BUNDLE_ID
from .config import LOG_PATH

log = logging.getLogger(__name__)

AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = AGENTS_DIR / f"{BUNDLE_ID}.plist"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_supported() -> bool:
    return sys.platform == "darwin"


def is_enabled() -> bool:
    return PLIST_PATH.exists()


def _running_from_source() -> bool:
    """True when the package is imported from a checkout rather than site-packages."""
    return "site-packages" not in str(Path(__file__).resolve())


def _plist() -> dict:
    plist = {
        "Label": BUNDLE_ID,
        "ProgramArguments": [sys.executable, "-m", "blinkreminder"],
        "RunAtLoad": True,
        # Restart if it ever crashes, but respect a deliberate Quit.
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Interactive",
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    if _running_from_source():
        # Launched straight from the repo: launchd needs to be told where that is.
        plist["WorkingDirectory"] = str(PROJECT_ROOT)
        plist["EnvironmentVariables"] = {"PYTHONPATH": str(PROJECT_ROOT)}
    return plist


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/launchctl", *args], capture_output=True, text=True, check=False
    )


def enable() -> None:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(_plist(), handle)
    domain = f"gui/{_uid()}"
    _launchctl("bootout", f"{domain}/{BUNDLE_ID}")  # ignore "not loaded"
    result = _launchctl("bootstrap", domain, str(PLIST_PATH))
    if result.returncode != 0:
        # Older macOS releases only understand load -w.
        fallback = _launchctl("load", "-w", str(PLIST_PATH))
        if fallback.returncode != 0:
            raise RuntimeError(
                (result.stderr or fallback.stderr or "launchctl failed").strip()
            )


def disable() -> None:
    _launchctl("bootout", f"gui/{_uid()}/{BUNDLE_ID}")
    if PLIST_PATH.exists():
        _launchctl("unload", "-w", str(PLIST_PATH))
        PLIST_PATH.unlink(missing_ok=True)


def start_agent() -> bool:
    """Kick the login item back into life. False if there is no login item to kick."""
    if not is_enabled():
        return False
    result = _launchctl("kickstart", "-k", f"gui/{_uid()}/{BUNDLE_ID}")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "launchctl kickstart failed").strip())
    return True


def toggle() -> bool:
    if is_enabled():
        disable()
    else:
        enable()
    return is_enabled()


def _uid() -> int:
    import os

    return os.getuid()
