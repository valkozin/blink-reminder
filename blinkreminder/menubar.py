"""The menu bar app: one eye icon, a pause switch and everything else tucked away."""

from __future__ import annotations

import logging
import time

import rumps

from . import APP_NAME, autostart, stats
from .alerts import Alerts
from .config import AVAILABLE_SOUNDS, INTERVAL_CHOICES, Config
from .detector import BlinkDetector, State
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

SENSITIVITY_LEVELS = (("sensitivity_low", 0.70), ("sensitivity_normal", 0.78), ("sensitivity_high", 0.86))
VOLUME_LEVELS = (15, 25, 35, 50, 75, 100)
SNOOZE_CHOICES = (("snooze_15", 15), ("snooze_30", 30), ("snooze_60", 60))


class BlinkReminderApp(rumps.App):
    def __init__(self, config: Config, camera_granted: bool = True) -> None:
        super().__init__(APP_NAME, title="👁", quit_button=None)
        self.config = config
        self.camera_granted = camera_granted
        self.alerts = Alerts(config)
        self.detector = BlinkDetector(config, on_reminder=self._on_reminder, on_error=self._on_error)

        self._last_flush = time.monotonic()
        self._flushed_blinks = 0
        self._flushed_reminders = 0
        self._flushed_active = 0.0
        self._error_shown = False

        self._build_menu()
        if camera_granted:
            self.detector.start()
        else:
            self.title = ICONS[State.ERROR]
            self._error_shown = True
            rumps.Timer(self._camera_denied, 1).start()
        self._tick_timer = rumps.Timer(self._tick, 1)
        self._tick_timer.start()

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        self.status_item = rumps.MenuItem(t("state_starting"))
        self.rate_item = rumps.MenuItem(t("rate_unknown"))
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
        self.rate_in_bar_item = rumps.MenuItem(t("show_rate"), callback=self.on_toggle_rate_in_bar)

        sensitivity = rumps.MenuItem(t("sensitivity"))
        self.sensitivity_items = {}
        for key, value in SENSITIVITY_LEVELS:
            item = rumps.MenuItem(t(key), callback=self._sensitivity_callback(value))
            self.sensitivity_items[value] = item
            sensitivity.add(item)

        self.idle_item = rumps.MenuItem(t("pause_when_idle"), callback=self.on_toggle_idle)
        self.lock_item = rumps.MenuItem(t("pause_when_locked"), callback=self.on_toggle_lock)
        self.login_item = rumps.MenuItem(t("start_at_login"), callback=self.on_toggle_login)

        self.menu = [
            self.status_item,
            self.rate_item,
            None,
            self.pause_item,
            snooze,
            None,
            interval,
            sound,
            self.hud_item,
            self.rate_in_bar_item,
            sensitivity,
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
        self.rate_in_bar_item.state = int(self.config.show_rate_in_menubar)
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

    def on_toggle_rate_in_bar(self, _=None) -> None:
        self.config.show_rate_in_menubar = not self.config.show_rate_in_menubar
        self._save()
        self._tick()

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
        if not self.camera_granted:
            self.title = ICONS[State.ERROR]
            self.status_item.title = t("state_error")
            return
        snap = self.detector.snapshot()
        icon = ICONS.get(snap.state, "👁")
        if self.config.show_rate_in_menubar and snap.rate is not None and snap.state == State.ACTIVE:
            self.title = f"{icon} {snap.rate:g}"
        else:
            self.title = icon

        self.status_item.title = self._status_text(snap)
        self.rate_item.title = t("rate", rate=f"{snap.rate:g}") if snap.rate is not None else t("rate_unknown")
        self.pause_item.title = t("resume") if self.detector.paused else t("pause")
        self._flush_stats()

    def _status_text(self, snap) -> str:
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
