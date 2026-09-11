"""The reminder itself: a quiet sound plus a floating hint that shows above every app."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

from .config import Config
from .i18n import t

log = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"
SOUND_DIR = "/System/Library/Sounds"


def _play_sound(name: str, volume: float) -> None:
    """Fire and forget - afplay exits on its own, we never block the detector thread."""
    if not IS_MAC:
        print("\a", end="", flush=True)
        return
    path = f"{SOUND_DIR}/{name}.aiff"
    try:
        subprocess.Popen(
            ["/usr/bin/afplay", "-v", f"{volume:.2f}", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log.warning("could not play %s: %s", path, exc)


class _Hud:
    """A borderless, click-through panel that joins every Space, including full-screen apps."""

    WIDTH = 190.0
    HEIGHT = 64.0

    def __init__(self) -> None:
        self._window = None
        self._hide_timer = None

    def _build(self):
        from AppKit import (
            NSBackingStoreBuffered,
            NSColor,
            NSFont,
            NSScreenSaverWindowLevel,
            NSTextField,
            NSVisualEffectBlendingModeBehindWindow,
            NSVisualEffectMaterialHUDWindow,
            NSVisualEffectStateActive,
            NSVisualEffectView,
            NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
        )
        from Foundation import NSMakeRect

        rect = NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setLevel_(NSScreenSaverWindowLevel)
        window.setIgnoresMouseEvents_(True)
        window.setHasShadow_(True)
        window.setAlphaValue_(0.0)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        effect = NSVisualEffectView.alloc().initWithFrame_(rect)
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(16.0)
        effect.layer().setMasksToBounds_(True)

        label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 16, self.WIDTH, 30))
        label.setStringValue_("")
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(2)  # NSTextAlignmentCenter
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_weight_(19.0, 0.23))  # semibold

        effect.addSubview_(label)
        window.setContentView_(effect)

        self._window = window
        self._label = label
        return window

    def _place(self, position: str) -> None:
        from AppKit import NSEvent, NSScreen

        point = NSEvent.mouseLocation()
        screen = None
        for candidate in NSScreen.screens():
            frame = candidate.frame()
            if (
                frame.origin.x <= point.x <= frame.origin.x + frame.size.width
                and frame.origin.y <= point.y <= frame.origin.y + frame.size.height
            ):
                screen = candidate
                break
        if screen is None:
            screen = NSScreen.mainScreen()
        if screen is None:  # pragma: no cover - headless machine
            return

        frame = screen.frame()
        visible = screen.visibleFrame()
        x = frame.origin.x + (frame.size.width - self.WIDTH) / 2.0
        if position == "bottom":
            y = visible.origin.y + 90.0
        elif position == "center":
            y = frame.origin.y + (frame.size.height - self.HEIGHT) / 2.0
        else:  # top - just below the menu bar
            y = visible.origin.y + visible.size.height - self.HEIGHT - 12.0
        self._window.setFrameOrigin_((x, y))

    def show(self, text: str, duration: float, position: str) -> None:
        """Must run on the main thread."""
        from AppKit import NSAnimationContext
        from Foundation import NSTimer

        window = self._window or self._build()
        self._label.setStringValue_(text)
        self._place(position)

        if self._hide_timer is not None:
            self._hide_timer.invalidate()
            self._hide_timer = None

        window.orderFrontRegardless()
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.18)
        window.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()

        self._hide_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            duration, False, lambda timer: self._fade_out()
        )

    def _fade_out(self) -> None:
        from AppKit import NSAnimationContext

        self._hide_timer = None
        if self._window is None:
            return
        window = self._window
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.45)
        NSAnimationContext.currentContext().setCompletionHandler_(
            lambda: window.orderOut_(None)
        )
        window.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()


class Alerts:
    """Delivers reminders. Safe to call from any thread."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._hud = _Hud() if IS_MAC else None
        self._lock = threading.Lock()

    def remind(self) -> None:
        self.play_sound()
        if self.config.hud_enabled:
            self.show_hint()

    def play_sound(self) -> None:
        if self.config.sound_enabled:
            _play_sound(self.config.sound_name, self.config.sound_volume)

    def show_hint(self, text: str | None = None) -> None:
        if self._hud is None:
            return
        message = text or f"👁  {t('hud_text')}"
        duration = self.config.hud_duration
        position = self.config.hud_position

        def run() -> None:
            with self._lock:
                try:
                    self._hud.show(message, duration, position)
                except Exception as exc:  # pragma: no cover - AppKit hiccup
                    log.warning("could not show the on-screen hint: %s", exc)

        from PyObjCTools import AppHelper

        AppHelper.callAfter(run)
