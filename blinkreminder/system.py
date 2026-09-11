"""Thin wrappers around the few OS facts the reminder loop needs."""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"

_quartz = None
if IS_MAC:
    try:
        import Quartz as _quartz  # type: ignore
    except ImportError:  # pragma: no cover - pyobjc missing
        log.warning("Quartz unavailable: idle and lock detection are disabled")


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse/trackpad event (0.0 if unknown)."""
    if _quartz is None:
        return 0.0
    try:
        return float(
            _quartz.CGEventSourceSecondsSinceLastEventType(
                _quartz.kCGEventSourceStateHIDSystemState,
                _quartz.kCGAnyInputEventType,
            )
        )
    except Exception:  # pragma: no cover - defensive
        return 0.0


def screen_is_locked() -> bool:
    """True while the login window / lock screen is in front."""
    if _quartz is None:
        return False
    try:
        session = _quartz.CGSessionCopyCurrentDictionary()
        if not session:
            return False
        return bool(session.get("CGSSessionScreenIsLocked", 0))
    except Exception:  # pragma: no cover - defensive
        return False


def display_is_asleep() -> bool:
    """True when the display has been put to sleep."""
    if _quartz is None:
        return False
    try:
        return bool(_quartz.CGDisplayIsAsleep(_quartz.CGMainDisplayID()))
    except Exception:  # pragma: no cover - defensive
        return False


# --- camera authorisation -------------------------------------------------
# OpenCV asks AVFoundation for camera access from whichever thread opens the
# capture, and AVFoundation can only put that prompt up from the main thread.
# We therefore ask for permission ourselves, before the detector thread starts.

NOT_DETERMINED, RESTRICTED, DENIED, AUTHORIZED = 0, 1, 2, 3


def camera_authorization() -> int:
    if not IS_MAC:
        return AUTHORIZED
    try:
        import AVFoundation as av  # type: ignore

        return int(av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo))
    except ImportError:
        log.debug("pyobjc-framework-AVFoundation missing; skipping the permission check")
        return AUTHORIZED
    except Exception:  # pragma: no cover - defensive
        return AUTHORIZED


def ensure_camera_access(timeout: float = 90.0) -> bool:
    """Ask for camera access if needed. Must run on the main thread; blocks until answered."""
    status = camera_authorization()
    if status == AUTHORIZED:
        return True
    if status in (DENIED, RESTRICTED):
        return False

    import time

    import AVFoundation as av  # type: ignore
    from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop

    answer: dict[str, bool] = {}

    def completion(granted) -> None:
        # PyObjC insists this block returns void - do not turn it into a lambda.
        answer["granted"] = bool(granted)

    av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        av.AVMediaTypeVideo, completion
    )

    loop = NSRunLoop.currentRunLoop()
    deadline = time.time() + timeout
    while "granted" not in answer and time.time() < deadline:
        loop.runMode_beforeDate_(NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1))
    return answer.get("granted", False)
