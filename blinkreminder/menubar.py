"""The menu bar app: one eye icon, a pause switch and everything else tucked away."""

from __future__ import annotations

import logging
import time

import rumps

from . import APP_NAME, autostart, control, stats, system
from .alerts import Alerts
from .config import AVAILABLE_SOUNDS, INTERVAL_CHOICES, Config
from .detector import BlinkDetector, State
from .preview import PreviewWindow
from .i18n import t

log = logging.getLogger(__name__)

ICONS = {
    State.ACTIVE: "👁",
    State.STARTING: "👁",
    State.NO_FACE: "👁",
    State.STANDBY: "💤",
    State.PAUSED: "⏸",
    State.LOCKED: "⏸",
    State.IDLE: "⏸",
    State.ERROR: "⚠️",
}

SENSITIVITY_LEVELS = (("sensitivity_low", 0.74), ("sensitivity_normal", 0.82), ("sensitivity_high", 0.88))
VOLUME_LEVELS = (15, 25, 35, 50, 75, 100)
SNOOZE_CHOICES = (("snooze_15", 15), ("snooze_30", 30), ("snooze_60", 60))
MENUBAR_CHOICES = (("menubar_none", "none"), ("menubar_rate", "rate"), ("menubar_count", "count"))
UNSEEN_ICON = "🙈"
UNUSABLE_ICON = "🙈"


class BlinkReminderApp(rumps.App):
    def __init__(self, config: Config, camera_granted: bool = True) -> None:
        super().__init__(APP_NAME, title="👁", quit_button=None)
        self.config = config
        self.camera_granted = camera_granted
        self.alerts = Alerts(config)
        self.detector = BlinkDetector(config, on_reminder=self._on_reminder, on_error=self._on_error)

        self._last_flush = time.monotonic()
        self._last_published = 0.0
        self._flushed_blinks = 0
        self._flushed_reminders = 0
        self._flushed_active = 0.0
        self._error_shown = False
        self._unseen_warned_at = 0.0
        self._preview = PreviewWindow(t("preview_title"))
        self._preview_timer = None

        self._build_menu()
        if camera_granted:
            self.detector.start()
        else:
            self.title = ICONS[State.ERROR]
            self._error_shown = True
            rumps.Timer(self._camera_denied, 1).start()
        self._start_tick_timer()

    def _start_tick_timer(self) -> None:
        """One tick a second, in common run loop modes.

        rumps schedules its timers in the default mode only, which stops them while a menu
        is open - exactly when the blink counter and the countdown below are being read.
        """
        from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer

        def fire(_timer) -> None:
            try:
                self._tick()
            except Exception:  # pragma: no cover - a bad tick must not kill the app
                log.exception("menu refresh failed")

        self._tick_timer = NSTimer.timerWithTimeInterval_repeats_block_(1.0, True, fire)
        NSRunLoop.currentRunLoop().addTimer_forMode_(self._tick_timer, NSRunLoopCommonModes)

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        self.status_item = rumps.MenuItem(t("state_starting"))
        self.rate_item = rumps.MenuItem(t("rate_unknown"))
        self.timing_item = rumps.MenuItem("")
        self.pause_item = rumps.MenuItem(t("pause"), callback=self.on_toggle_pause)

        snooze = rumps.MenuItem(t("snooze"))
        for key, minutes in SNOOZE_CHOICES:
            snooze.add(rumps.MenuItem(t(key), callback=self._snooze_callback(minutes)))

        interval = rumps.MenuItem(t("interval"))
        self.interval_items = {}
        for seconds in INTERVAL_CHOICES:
            item = rumps.MenuItem(t("interval_item", sec=seconds), callback=self._interval_callback(seconds))
            self.interval_items[seconds] = item
            interval.add(item)

        sound = rumps.MenuItem(t("sound"))
        self.sound_items = {}
        for name in AVAILABLE_SOUNDS:
            item = rumps.MenuItem(name, callback=self._sound_callback(name))
            self.sound_items[name] = item
            sound.add(item)
        sound.add(rumps.separator)
        self.silent_item = rumps.MenuItem(t("sound_off"), callback=self.on_toggle_sound)
        sound.add(self.silent_item)
        volume = rumps.MenuItem(t("sound_volume"))
        self.volume_items = {}
        for percent in VOLUME_LEVELS:
            item = rumps.MenuItem(t("volume_item", percent=percent), callback=self._volume_callback(percent))
            self.volume_items[percent] = item
            volume.add(item)
        sound.add(volume)

        self.hud_item = rumps.MenuItem(t("hud"), callback=self.on_toggle_hud)
        menubar_extra = rumps.MenuItem(t("menubar_extra"))
        self.menubar_extra_items = {}
        for key, value in MENUBAR_CHOICES:
            item = rumps.MenuItem(t(key), callback=self._menubar_extra_callback(value))
            self.menubar_extra_items[value] = item
            menubar_extra.add(item)

        sensitivity = rumps.MenuItem(t("sensitivity"))
        self.sensitivity_items = {}
        for key, value in SENSITIVITY_LEVELS:
            item = rumps.MenuItem(t(key), callback=self._sensitivity_callback(value))
            self.sensitivity_items[value] = item
            sensitivity.add(item)

        camera = rumps.MenuItem(t("camera"))
        self.camera_items = {}
        for index, name in enumerate(system.list_cameras()):
            item = rumps.MenuItem(name, callback=self._camera_callback(index))
            self.camera_items[index] = item
            camera.add(item)
        camera.add(rumps.separator)
        camera.add(rumps.MenuItem(t("preview"), callback=self.on_preview))

        self.idle_item = rumps.MenuItem(t("pause_when_idle"), callback=self.on_toggle_idle)
        self.lock_item = rumps.MenuItem(t("pause_when_locked"), callback=self.on_toggle_lock)
        self.login_item = rumps.MenuItem(t("start_at_login"), callback=self.on_toggle_login)

        self.menu = [
            self.status_item,
            self.rate_item,
            self.timing_item,
            None,
            self.pause_item,
            snooze,
            None,
            interval,
            sound,
            self.hud_item,
            menubar_extra,
            sensitivity,
            camera,
            None,
            self.idle_item,
            self.lock_item,
            self.login_item,
            None,
            rumps.MenuItem(t("stats"), callback=self.on_stats),
            rumps.MenuItem(t("quit"), callback=self.on_quit),
        ]
        self.status_item.set_callback(None)
        self.rate_item.set_callback(None)
        self.timing_item.set_callback(None)
        self._refresh_checkmarks()

    def _refresh_checkmarks(self) -> None:
        for seconds, item in self.interval_items.items():
            item.state = int(abs(self.config.interval - seconds) < 0.01)
        for name, item in self.sound_items.items():
            item.state = int(self.config.sound_enabled and self.config.sound_name == name)
        self.silent_item.state = int(not self.config.sound_enabled)
        nearest_volume = min(VOLUME_LEVELS, key=lambda p: abs(p / 100 - self.config.sound_volume))
        for percent, item in self.volume_items.items():
            item.state = int(percent == nearest_volume)
        for value, item in self.sensitivity_items.items():
            item.state = int(abs(self.config.sensitivity - value) < 0.01)
        self.hud_item.state = int(self.config.hud_enabled)
        for value, item in self.menubar_extra_items.items():
            item.state = int(value == self.config.menubar_extra)
        for index, item in self.camera_items.items():
            item.state = int(index == self.config.camera_index)
        self.idle_item.state = int(self.config.pause_when_idle)
        self.lock_item.state = int(self.config.pause_when_locked)
        self.login_item.state = int(autostart.is_enabled())

    # ------------------------------------------------------------------ callbacks

    def on_toggle_pause(self, _=None) -> None:
        self.detector.toggle_pause()
        self._tick()

    def _snooze_callback(self, minutes: int):
        def handler(_=None) -> None:
            self.detector.pause(minutes * 60)
            self._tick()

        return handler

    def _interval_callback(self, seconds: int):
        def handler(_=None) -> None:
            self.config.interval = float(seconds)
            self.config.min_reminder_gap = max(20.0, seconds * 2.0)
            self._save()

        return handler

    def _sound_callback(self, name: str):
        def handler(_=None) -> None:
            self.config.sound_name = name
            self.config.sound_enabled = True
            self._save()
            self.alerts.play_sound()

        return handler

    def _volume_callback(self, percent: int):
        def handler(_=None) -> None:
            self.config.sound_volume = percent / 100.0
            self.config.sound_enabled = True
            self._save()
            self.alerts.play_sound()

        return handler

    def _sensitivity_callback(self, value: float):
        def handler(_=None) -> None:
            self.config.sensitivity = value
            self._save()

        return handler

    def on_toggle_sound(self, _=None) -> None:
        self.config.sound_enabled = not self.config.sound_enabled
        self._save()

    def on_toggle_hud(self, _=None) -> None:
        self.config.hud_enabled = not self.config.hud_enabled
        self._save()
        if self.config.hud_enabled:
            self.alerts.show_hint()

    def _camera_callback(self, index: int):
        def handler(_=None) -> None:
            self.config.camera_index = index
            self._save()
            self.detector.reopen_camera()

        return handler

    def on_preview(self, _=None) -> None:
        """Show what the camera sees, so it can be aimed at a face."""
        self.detector.set_preview(True)
        self._preview.show()
        if self._preview_timer is None:
            self._preview_timer = rumps.Timer(self._refresh_preview, 0.15)
            self._preview_timer.start()

    def _refresh_preview(self, _=None) -> None:
        if not self._preview.is_open():
            self.detector.set_preview(False)
            if self._preview_timer is not None:
                self._preview_timer.stop()
                self._preview_timer = None
            return
        jpeg = self.detector.preview_jpeg()
        if jpeg:
            self._preview.update(jpeg)

    def _menubar_extra_callback(self, value: str):
        def handler(_=None) -> None:
            self.config.menubar_extra = value
            self._save()
            self._tick()

        return handler

    def on_toggle_idle(self, _=None) -> None:
        self.config.pause_when_idle = not self.config.pause_when_idle
        self._save()

    def on_toggle_lock(self, _=None) -> None:
        self.config.pause_when_locked = not self.config.pause_when_locked
        self._save()

    def on_toggle_login(self, _=None) -> None:
        try:
            autostart.toggle()
        except Exception as exc:
            rumps.alert(title=t("autostart_error_title"), message=str(exc))
        self._refresh_checkmarks()

    def on_stats(self, _=None) -> None:
        self._flush_stats(force=True)
        today = stats.today()
        snap = self.detector.snapshot()
        minutes = max(today["active_seconds"] / 60.0, 1.0)
        rumps.alert(
            title=t("stats_title"),
            message=t(
                "stats_body",
                active=stats.format_duration(today["active_seconds"]),
                blinks=today["blinks"],
                rate=round(today["blinks"] / minutes, 1),
                reminders=today["reminders"],
                session_blinks=snap.blinks,
                session_reminders=snap.reminders,
            ),
            ok="OK",
        )

    def on_quit(self, _=None) -> None:
        self._flush_stats(force=True)
        control.state_path().unlink(missing_ok=True)
        self.detector.stop()
        rumps.quit_application()

    # ------------------------------------------------------------------ plumbing

    def _save(self) -> None:
        self.config.clamp()
        self.config.save()
        self._refresh_checkmarks()

    def _on_reminder(self) -> None:
        self.alerts.remind()

    def _on_error(self, kind: str) -> None:
        if self._error_shown:
            return
        self._error_shown = True

        def show() -> None:
            rumps.alert(title=t("camera_error_title"), message=t("camera_error_body"), ok="OK")

        from PyObjCTools import AppHelper

        AppHelper.callAfter(show)

    def _camera_denied(self, timer=None) -> None:
        if timer is not None:
            timer.stop()
        rumps.alert(title=t("camera_error_title"), message=t("camera_denied_body"), ok="OK")

    def _tick(self, _=None) -> None:
        self._handle_command()
        if not self.camera_granted:
            self.title = ICONS[State.ERROR]
            self.status_item.title = t("state_error")
            return
        snap = self.detector.snapshot()
        blind = snap.unseen_at_keyboard or snap.signal_unusable
        icon = UNSEEN_ICON if blind else ICONS.get(snap.state, "👁")
        # The menu bar icon and the status line carry this continuously; the modal
        # explanation is worth one interruption, not one an hour of them.
        if blind and time.monotonic() - self._unseen_warned_at > 3600:
            self._unseen_warned_at = time.monotonic()
            body = "unusable_body" if snap.signal_unusable else "unseen_body"
            rumps.alert(title=t("unseen_title"), message=t(body), ok="OK")
        extra = self.config.menubar_extra
        if extra == "count":
            # A number that ticks up the moment you blink - the quickest way to tell
            # whether the camera is actually seeing you.
            self.title = f"{icon} {snap.blinks}"
        elif extra == "rate" and snap.rate is not None and snap.state == State.ACTIVE:
            self.title = f"{icon} {snap.rate:g}"
        else:
            self.title = icon

        self.status_item.title = self._status_text(snap)
        if snap.signal_quality == "weak":
            self.rate_item.title = t("signal_weak")
        elif snap.rate is not None:
            self.rate_item.title = t("rate_total", rate=f"{snap.rate:g}", total=snap.blinks)
        else:
            self.rate_item.title = t("rate_unknown_total", total=snap.blinks)
        self.pause_item.title = t("resume") if self.detector.paused else t("pause")
        self.timing_item.title = self._timing_text(snap)
        self._flush_stats()
        self._publish_state(snap)

    def _handle_command(self) -> None:
        """Act on `blink-reminder --pause/--resume/--quit` from a terminal."""
        pending = control.take()
        if pending is None:
            return
        command, argument = pending
        log.info("command from the terminal: %s", command)
        if command == "quit":
            self.on_quit()
        elif command == "pause":
            self.detector.pause(argument * 60 if argument else None)
        elif command == "resume":
            self.detector.resume()
        elif command == "toggle":
            self.detector.toggle_pause()
        elif command == "reload":
            self._reload_config()

    def _menu_bar_report(self) -> dict:
        """Where the status item actually is - an icon can be missing for reasons that
        look identical from the outside, and macOS parks items it cannot fit underneath
        the notch, where they report themselves visible but cannot be seen or clicked."""
        report: dict = {}
        try:
            from AppKit import NSScreen

            item = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
            if item is None:
                report["status_item"] = "missing"
                return report
            report["status_item"] = "present"
            report["visible"] = bool(item.isVisible())
            report["title"] = str(item.title() or "")
            button = item.button()
            window = button.window() if button is not None else None
            if window is not None:
                frame = window.frame()
                report["frame"] = [round(frame.origin.x), round(frame.origin.y),
                                   round(frame.size.width), round(frame.size.height)]
                report["placed"] = bool(window.isVisible()) and frame.size.height > 0
            screen = (NSScreen.screens() or [None])[0]
            if screen is not None and hasattr(screen, "auxiliaryTopLeftArea"):
                left, right = screen.auxiliaryTopLeftArea(), screen.auxiliaryTopRightArea()
                if left is not None and right is not None and report.get("frame"):
                    notch = (float(left.size.width), float(right.origin.x))
                    centre = report["frame"][0] + report["frame"][2] / 2
                    report["notch"] = [round(notch[0]), round(notch[1])]
                    report["behind_notch"] = bool(notch[0] < centre < notch[1])
        except Exception as exc:  # pragma: no cover - diagnostics must never break the app
            report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    def _reload_config(self) -> None:
        """Re-read the settings file in place.

        The detector holds the same Config object, so the fields are updated rather
        than the object replaced - otherwise half the app would keep the old settings.
        """
        from dataclasses import fields

        fresh = Config.load()
        for field in fields(Config):
            setattr(self.config, field.name, getattr(fresh, field.name))
        self._refresh_checkmarks()
        self._tick()

    def _publish_state(self, snap) -> None:
        """A snapshot on disk, so the app can be inspected without its menu."""
        now = time.monotonic()
        if now - self._last_published < 5.0:
            return
        self._last_published = now
        control.publish(
            {
                "menu_bar": self._menu_bar_report(),
                "state": snap.state,
                "paused": self.detector.paused,
                "paused_until": snap.paused_until,
                "blinks": snap.blinks,
                "reminders": snap.reminders,
                "rate": snap.rate,
                "signal_quality": snap.signal_quality,
                "seconds_since_blink": round(snap.seconds_since_blink, 1),
                "interval": self.config.interval,
            }
        )

    def _timing_text(self, snap) -> str:
        """Why nothing is happening right now - otherwise the gap reads as a failure.

        Every reason a reminder cannot fire gets its own line, because a countdown that
        reads "36 s of 6" while the app is silent is worse than no countdown at all.
        """
        if self.detector.paused or snap.state not in (State.ACTIVE, State.NO_FACE, State.STARTING):
            return t("timing_idle")
        if snap.state == State.NO_FACE:
            return t("timing_no_face")
        if snap.state == State.STARTING:
            return t("timing_calibrating")
        if snap.signal_unusable:
            return t("timing_unusable")
        if snap.reminder_hold > 0:
            return t("timing_hold", seconds=int(snap.reminder_hold) + 1)
        return t(
            "timing_countdown",
            seconds=int(snap.seconds_since_blink),
            interval=f"{self.config.interval:g}",
        )

    def _status_text(self, snap) -> str:
        if snap.signal_unusable:
            return t("state_unusable")
        if snap.unseen_at_keyboard:
            return t("state_unseen")
        if snap.state == State.PAUSED and snap.paused_until:
            return t("snooze_until", time=time.strftime("%H:%M", time.localtime(snap.paused_until)))
        return t(f"state_{snap.state}")

    def _flush_stats(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_flush < 60.0:
            return
        self._last_flush = now
        snap = self.detector.snapshot()
        stats.record(
            blinks=snap.blinks - self._flushed_blinks,
            reminders=snap.reminders - self._flushed_reminders,
            active_seconds=snap.active_seconds - self._flushed_active,
        )
        self._flushed_blinks = snap.blinks
        self._flushed_reminders = snap.reminders
        self._flushed_active = snap.active_seconds
