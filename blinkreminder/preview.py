"""A small floating window showing what the camera sees - for aiming it at your face."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class PreviewWindow:
    """Titled, floating, closable. Lives on the main thread like every AppKit object."""

    WIDTH = 480.0
    HEIGHT = 360.0

    def __init__(self, title: str) -> None:
        self._title = title
        self._window = None
        self._image_view = None

    def _build(self):
        from AppKit import (
            NSBackingStoreBuffered,
            NSFloatingWindowLevel,
            NSImageScaleProportionallyUpOrDown,
            NSImageView,
            NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskTitled,
        )
        from Foundation import NSMakeRect

        rect = NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False
        )
        window.setTitle_(self._title)
        window.setLevel_(NSFloatingWindowLevel)
        window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
        window.setReleasedWhenClosed_(False)

        view = NSImageView.alloc().initWithFrame_(rect)
        view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        window.setContentView_(view)

        self._window = window
        self._image_view = view
        return window

    def show(self) -> None:
        from AppKit import NSApplication

        window = self._window or self._build()
        window.center()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        window.makeKeyAndOrderFront_(None)

    def update(self, jpeg: bytes) -> None:
        if self._window is None or not jpeg:
            return
        from AppKit import NSImage
        from Foundation import NSData

        data = NSData.dataWithBytes_length_(jpeg, len(jpeg))
        image = NSImage.alloc().initWithData_(data)
        if image is not None:
            self._image_view.setImage_(image)

    def is_open(self) -> bool:
        return self._window is not None and bool(self._window.isVisible())

    def close(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)
