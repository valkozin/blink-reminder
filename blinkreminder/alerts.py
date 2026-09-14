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


_PillView = None


def _pill_view_class():
    """An NSView that paints a dark rounded pill. Built on first use so that importing
    this module on a machine without AppKit still works.

    A system vibrancy view was tried first and looked wrong: its blur backdrop stays
    rectangular however the layer is rounded, and in light mode the "HUD" material
    turns pale grey under white text. A plain painted pill is the same in every
    appearance and over any wallpaper.
    """
    global _PillView
    if _PillView is None:
        from AppKit import NSBezierPath, NSColor, NSView
        from Foundation import NSInsetRect

        class PillView(NSView):
            def drawRect_(self, _rect):
                # Half a point in, so the 1 pt stroke sits fully inside the view.
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSInsetRect(self.bounds(), 0.5, 0.5), 18.0, 18.0
                )
                NSColor.colorWithCalibratedWhite_alpha_(0.10, 0.92).setFill()
                path.fill()
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.14).setStroke()
                path.setLineWidth_(1.0)
                path.stroke()

            def isOpaque(self):
                return False

        _PillView = PillView
    return _PillView


class _Hud:
    """A borderless, click-through panel that joins every Space, including full-screen apps."""

    WIDTH = 190.0
    HEIGHT = 64.0

    def __init__(self) -> None:
        self._window = None
        self._hide_timer = None

    def _build(self):
        from AppKit import (
            NSAppearance,
            NSBackingStoreBuffered,
            NSColor,
            NSFont,
            NSScreenSaverWindowLevel,
            NSTextAlignmentCenter,
            NSTextField,
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
        # No system shadow: for a transparent window it is computed from a rectangle,
        # which is where the "rounded corners plus sharp corners" look came from.
        window.setHasShadow_(False)
        window.setAlphaValue_(0.0)
        window.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        background = _pill_view_class().alloc().initWithFrame_(rect)

        label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 17, self.WIDTH, 30))
        label.setStringValue_("")
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        # The named constant, never a number: AppKit uses iOS values on Apple silicon,
        # where 2 means *right*-aligned - which is exactly how the hint shipped.
        label.setAlignment_(NSTextAlignmentCenter)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_weight_(19.0, 0.23))  # semibold

        background.addSubview_(label)
        window.setContentView_(background)

        self._window = window
        self._label = label
        return window

    def render_png(self, path: str) -> None:
        """Draw the panel as it will appear, without showing it - for checking the look."""
        from AppKit import NSBitmapImageFileTypePNG

        window = self._window or self._build()
        view = window.contentView()
        bounds = view.bounds()
        rep = view.bitmapImageRepForCachingDisplayInRect_(bounds)
        view.cacheDisplayInRect_toBitmapImageRep_(bounds, rep)
        data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
        data.writeToFile_atomically_(path, True)

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
