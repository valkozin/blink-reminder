"""Every menu action, driven for real against a stubbed camera.

The menu is the part a person actually touches, and until now nothing exercised it:
a rename that broke _tick shipped unnoticed because no test ever opened the menu.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


from test_detector import FRAME, _FakeFaceMesh

import blinkreminder.config as config_module
import blinkreminder.control as control_module
import blinkreminder.detector as detector_module
import blinkreminder.stats as stats_module

# Never let a test depend on the machine it runs on. The detector pauses itself while the
# screen is locked or the display sleeps, so the thread tests used to pass only while the
# developer's screen happened to be on - and a CI runner has no screen at all.
import blinkreminder.system as system_module

system_module.screen_is_locked = lambda: False
system_module.display_is_asleep = lambda: False
system_module.idle_seconds = lambda: 0.0

# rumps.alert is modal: it blocks until somebody clicks OK, and in a test nobody will.
# Record what would have been shown instead, so tests can check the explanation arrived.
import rumps

ALERTS: list[str] = []


def _record_alert(title=None, message="", ok=None, cancel=None, other=None, icon_path=None):
    ALERTS.append(title)
    return 1


rumps.alert = _record_alert


class _FakeCapture:
    opened = 0
    released = 0

    def __init__(self, *_args):
        _FakeCapture.opened += 1
        self._open = True

    def isOpened(self):
        return self._open

    def set(self, *_args):
        return True

    def read(self):
        return True, FRAME

    def release(self):
        _FakeCapture.released += 1
        self._open = False


def _app():
    """A real BlinkReminderApp with the camera and MediaPipe replaced."""
    return _app_in(Path(tempfile.mkdtemp()))


def _app_in(tmp):
    """The same app, in a folder you choose - a second one simulates a restart."""
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    for module in (config_module, control_module):
        module.CONFIG_DIR = tmp
    config_module.CONFIG_PATH = tmp / "config.json"
    config_module.STATS_PATH = tmp / "stats.json"
    stats_module.STATS_PATH = tmp / "stats.json"
    stats_module.CONFIG_DIR = tmp

    detector_module.cv2.VideoCapture = _FakeCapture
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    from blinkreminder.config import Config
    from blinkreminder.menubar import BlinkReminderApp

    config = Config()
    config.interval = 6.0
    app = BlinkReminderApp(config)
    mesh = _FakeFaceMesh()
    mesh.ear = 0.30
    app.detector._ensure_face_mesh = lambda: mesh
    return app, mesh, tmp


def test_pause_and_resume_from_the_menu():
    app, _, _ = _app()
    try:
        assert app.detector.paused is False
        app.on_toggle_pause()
        assert app.detector.paused is True
        app._tick()
        assert app.title == "⏸", f"the icon should show the pause, got {app.title!r}"
        assert app.pause_item.title == "Resume"

        app.on_toggle_pause()
        assert app.detector.paused is False
        app._tick()
        assert app.title != "⏸"
        assert app.pause_item.title == "Pause"
    finally:
        app.detector.stop()


def test_pause_releases_the_camera_and_resume_takes_it_back():
    app, _, _ = _app()
    try:
        time.sleep(1.0)
        opened = _FakeCapture.opened
        app.on_toggle_pause()
        time.sleep(1.5)
        assert app.detector.snapshot().state == "paused"
        released = _FakeCapture.released
        assert released > 0, "a paused app must let go of the camera"

        app.on_toggle_pause()
        time.sleep(1.5)
        assert _FakeCapture.opened > opened, "resume must reopen the camera"
        assert app.detector.snapshot().state != "paused"
    finally:
        app.detector.stop()


def test_snooze_sets_a_deadline_that_the_menu_shows():
    app, _, _ = _app()
    try:
        handler = app._snooze_callback(15)
        handler()
        assert app.detector.paused is True
        snap = app.detector.snapshot()
        assert snap.paused_until is not None
        remaining = snap.paused_until - time.time()
        assert 14 * 60 < remaining <= 15 * 60, f"got {remaining:.0f}s"
        app._tick()
        assert "Paused until" in app.status_item.title, app.status_item.title
    finally:
        app.detector.stop()


def test_a_terminal_command_reaches_the_running_app():
    app, _, _ = _app()
    try:
        control_module.send("pause", 30)
        app._tick()
        assert app.detector.paused is True

        control_module.send("resume")
        app._tick()
        assert app.detector.paused is False

        control_module.send("toggle")
        app._tick()
        assert app.detector.paused is True
    finally:
        app.detector.stop()


def test_a_pause_survives_the_app_being_restarted():
    """A crash or a login must not quietly cancel the quiet the person asked for."""
    app, _, tmp = _app()
    try:
        app._snooze_callback(30)()
        assert app.detector.paused is True
        assert (tmp / "pause.json").exists()
    finally:
        app.detector.stop()

    from blinkreminder.config import Config
    from blinkreminder.detector import BlinkDetector

    revived = BlinkDetector(Config(), on_reminder=lambda: None)
    revived.start()
    try:
        time.sleep(0.5)
        assert revived.paused is True, "the new process should pick the pause back up"
        snap = revived.snapshot()
        assert snap.state == "paused"
        assert snap.paused_until is not None
        revived.resume()
        assert not (tmp / "pause.json").exists(), "resuming clears it"
    finally:
        revived.stop()


def test_a_terminal_reload_applies_settings_edited_elsewhere():
    app, _, tmp = _app()
    try:
        import json as _json

        saved = _json.loads((tmp / "config.json").read_text()) if (tmp / "config.json").exists() else {}
        saved.update({"interval": 25.0, "menubar_extra": "rate"})
        (tmp / "config.json").write_text(_json.dumps(saved))

        control_module.send("reload")
        app._tick()
        assert app.config.interval == 25.0
        assert app.config.menubar_extra == "rate"
        assert app.interval_items[20].state == 0
    finally:
        app.detector.stop()


def test_settings_chosen_in_the_menu_are_applied_and_saved():
    app, _, tmp = _app()
    try:
        app._interval_callback(20)()
        assert app.config.interval == 20
        assert app.config.min_reminder_gap == 40, "the floor follows the interval"
        assert app.interval_items[20].state == 1
        assert app.interval_items[6].state == 0

        app._sensitivity_callback(0.74)()
        assert app.config.sensitivity == 0.74
        assert app.sensitivity_items[0.74].state == 1

        app.on_toggle_hud()
        assert app.config.hud_enabled is False
        assert app.hud_item.state == 0

        app.on_toggle_sound()
        assert app.config.sound_enabled is False
        assert app.silent_item.state == 1

        app._menubar_extra_callback("count")()
        assert app.config.menubar_extra == "count"
        app._tick()
        assert app.title.endswith(str(app.detector.snapshot().blinks))

        saved = json.loads((tmp / "config.json").read_text())
        assert saved["interval"] == 20 and saved["sensitivity"] == 0.74
        assert saved["hud_enabled"] is False and saved["menubar_extra"] == "count"
    finally:
        app.detector.stop()


def test_the_timing_line_explains_every_state():
    app, _, _ = _app()
    try:
        for _ in range(30):            # let the detector finish calibrating
            time.sleep(0.1)
            if app.detector.snapshot().state == "active":
                break
        app._tick()
        assert "No blink for" in app.timing_item.title, app.timing_item.title

        app.on_toggle_pause()
        app._tick()
        assert app.timing_item.title == "Not counting right now"
        app.on_toggle_pause()
    finally:
        app.detector.stop()


def test_the_timing_line_never_counts_when_nothing_can_fire():
    """Bug: '36 s of 6' with no reminder - the line kept counting while the app was
    silent for a reason it did not mention."""
    app, mesh, _ = _app()
    try:
        for _ in range(30):
            time.sleep(0.1)
            if app.detector.snapshot().state == "active":
                break

        mesh.ear = None                                   # face lost
        time.sleep(detector_module.FACE_GRACE + 0.6)
        app._tick()
        assert app.timing_item.title.startswith("Face not in view"), app.timing_item.title

        mesh.ear = 0.30                                   # face back, but blinks unmeasurable
        time.sleep(0.5)
        app.detector._face_seconds_since_blink = detector_module.SIGNAL_TIMEOUT + 1
        notices: list[str] = []
        app.alerts.notice = lambda text, seconds=4.5: notices.append(text)
        app._tick()
        assert app.timing_item.title.startswith("Blinks not measurable"), app.timing_item.title
        assert "of 6" not in app.timing_item.title
        assert notices, "the reason should be explained, not left to guesswork"
    finally:
        app.detector.stop()


def test_the_on_screen_hint_is_centred():
    """Bug: the label was aligned with a hard-coded 2, which is right-aligned on Apple
    silicon, so 'Blink' sat against the right edge and was clipped."""
    from AppKit import NSApplication, NSTextAlignmentCenter

    from blinkreminder.alerts import _Hud

    NSApplication.sharedApplication()
    hud = _Hud()
    hud._build()
    assert hud._label.alignment() == NSTextAlignmentCenter
    assert hud._label.frame().size.width == hud.WIDTH, "the label must span the whole pill"


def test_the_menu_bar_counter_stays_narrow_while_the_menu_keeps_the_total():
    app, _, _ = _app()
    try:
        app.config.menubar_extra = "count"
        app.detector._blinks = 938
        app._tick()
        assert app.title.endswith(" 38"), f"a rolling hundred, not 938: {app.title!r}"
        assert "938" in app.rate_item.title, app.rate_item.title
    finally:
        app.detector.stop()


def test_being_unseen_shows_a_passing_notice_not_a_dialog():
    """Bug: unattended modal alerts stacked up - three windows waiting after lunch - and
    each one froze the menu until it was clicked."""
    app, _, tmp = _app()
    notices: list[str] = []
    app.alerts.notice = lambda text, seconds=4.5: notices.append(text)
    try:
        for _ in range(30):
            time.sleep(0.1)
            if app.detector.snapshot().state == "active":
                break

        ALERTS.clear()
        app.detector._face_seconds_since_blink = detector_module.SIGNAL_TIMEOUT + 1
        app._tick()
        assert notices == ["🙈  Cannot see you blink"], notices
        assert ALERTS == [], "nothing modal may appear on its own"

        app._tick()
        assert len(notices) == 1, "and not again on every tick"

        # A restart must not start the counting over: that is how they piled up.
        second, _, _ = _app_in(tmp)
        try:
            second.alerts.notice = lambda text, seconds=4.5: notices.append(text)
            second.detector._face_seconds_since_blink = detector_module.SIGNAL_TIMEOUT + 1
            second._tick()
            assert len(notices) == 1, "the hour is remembered on disk, not in memory"
        finally:
            second.detector.stop()
    finally:
        app.detector.stop()


def test_state_is_published_for_the_status_command():
    app, _, tmp = _app()
    try:
        app._last_published = 0.0
        app._tick()
        state = json.loads((tmp / "state.json").read_text())
        assert state["state"] and "paused" in state and "menu_bar" in state
        assert "blinks" in state and "interval" in state
    finally:
        app.detector.stop()


def _main() -> int:
    failures = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print("all tests passed" if not failures else f"{failures} test(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
