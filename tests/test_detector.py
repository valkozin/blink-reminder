"""Logic tests for the blink detector, with the camera and MediaPipe stubbed out."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blinkreminder.config import Config
from blinkreminder.detector import CALIBRATION_SAMPLES, BlinkDetector, State

FRAME = np.zeros((480, 480, 3), dtype=np.uint8)  # square, so the EAR aspect fix is a no-op
FAKE_START = 1000.0


class _Landmark:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def _landmarks_for(ear: float):
    """478 landmarks where both eyes have exactly the requested aspect ratio."""
    points = [_Landmark(0.5, 0.5) for _ in range(478)]
    width = 0.1
    height = ear * width
    for outer, up1, up2, inner, low2, low1 in (
        (362, 385, 387, 263, 373, 380),
        (33, 160, 158, 133, 153, 144),
    ):
        points[outer] = _Landmark(0.3, 0.5)
        points[inner] = _Landmark(0.3 + width, 0.5)
        points[up1] = _Landmark(0.33, 0.5 + height / 2)
        points[up2] = _Landmark(0.36, 0.5 + height / 2)
        points[low1] = _Landmark(0.33, 0.5 - height / 2)
        points[low2] = _Landmark(0.36, 0.5 - height / 2)
    return points


class _Result:
    def __init__(self, landmarks) -> None:
        self.multi_face_landmarks = landmarks


class _FakeFaceMesh:
    """Returns whatever EAR the test asks for, or no face at all."""

    def __init__(self) -> None:
        self.ear: float | None = 0.30

    def process(self, _rgb):
        if self.ear is None:
            return _Result(None)
        holder = type("Face", (), {"landmark": _landmarks_for(self.ear)})()
        return _Result([holder])

    def close(self) -> None:
        pass


def _detector(**overrides):
    config = Config()
    config.interval = 10.0
    config.min_reminder_gap = 12.0
    for key, value in overrides.items():
        setattr(config, key, value)
    config.clamp()

    reminders: list[float] = []
    detector = BlinkDetector(config, on_reminder=lambda: reminders.append(time.monotonic()))
    mesh = _FakeFaceMesh()
    detector._ensure_face_mesh = lambda: mesh  # type: ignore[method-assign]
    # Tests drive a fake clock that starts at 1000.0; line the detector up with it.
    detector._last_blink = detector._last_face = detector._last_tick = FAKE_START
    return detector, mesh, reminders, config


def _feed(detector, mesh, ear, seconds, start, step=0.1):
    """Run the per-frame pipeline over a stretch of fake time."""
    mesh.ear = ear
    frames = max(int(seconds / step), 1)
    now = start
    for _ in range(frames):
        detector._process(FRAME, now)
        now += step
    return now


def test_open_eyes_calibrate_then_stay_active():
    detector, mesh, reminders, _ = _detector()
    now = _feed(detector, mesh, 0.30, 1.0, start=FAKE_START)
    assert detector._state == State.STARTING, "should still be calibrating after 10 frames"
    _feed(detector, mesh, 0.30, 4.0, start=now)
    assert len(detector._ear_history) > CALIBRATION_SAMPLES
    assert detector._state == State.ACTIVE


def test_blink_is_counted_once():
    detector, mesh, _, _ = _detector()
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, 0.10, 0.2, start=now)   # eyes shut for two frames
    now = _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().blinks == 1

    now = _feed(detector, mesh, 0.10, 0.2, start=now)
    now = _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().blinks == 2


def test_threshold_follows_the_persons_own_baseline():
    detector, mesh, _, _ = _detector(sensitivity=0.78)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, 0.26, 0.3, start=now)   # 87% of baseline: a squint, not a blink
    now = _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().blinks == 0

    now = _feed(detector, mesh, 0.20, 0.3, start=now)   # 67% of baseline: a real blink
    _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().blinks == 1


def test_long_closure_resets_the_timer_without_counting_as_a_blink():
    detector, mesh, reminders, _ = _detector()
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, 0.10, 3.0, start=now)   # resting with eyes closed
    _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().blinks == 0
    assert reminders == [], "eyes closed for three seconds must not trigger a reminder"


def test_reminder_after_the_configured_interval():
    detector, mesh, reminders, config = _detector(interval=10.0)
    now = _feed(detector, mesh, 0.30, 9.0, start=FAKE_START)
    assert reminders == []
    now = _feed(detector, mesh, 0.30, 2.0, start=now)
    assert len(reminders) == 1, "one reminder just past the interval"

    # A blink right after should restart the countdown.
    now = _feed(detector, mesh, 0.10, 0.2, start=now)
    now = _feed(detector, mesh, 0.30, 9.0, start=now)
    assert len(reminders) == 1


def test_reminders_respect_the_minimum_gap():
    detector, mesh, reminders, _ = _detector(interval=6.0, min_reminder_gap=30.0)
    now = _feed(detector, mesh, 0.30, 7.0, start=FAKE_START)
    assert len(reminders) == 1
    now = _feed(detector, mesh, 0.30, 20.0, start=now)
    assert len(reminders) == 1, "gap not elapsed yet"
    _feed(detector, mesh, 0.30, 15.0, start=now)
    assert len(reminders) == 2


def test_no_reminders_when_the_face_is_gone():
    detector, mesh, reminders, _ = _detector(interval=8.0, absence_timeout=30.0)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, None, 20.0, start=now)
    assert reminders == []
    assert detector._state == State.NO_FACE
    now = _feed(detector, mesh, None, 20.0, start=now)
    assert detector._state == State.STANDBY, "should stop looking after the absence timeout"

    # Coming back must not fire a stale reminder.
    detector._state = State.NO_FACE
    _feed(detector, mesh, 0.30, 3.0, start=now)
    assert reminders == []
    assert detector._state == State.ACTIVE


def test_a_glance_away_freezes_the_countdown_instead_of_restarting_it():
    """Looking at the keyboard for a few seconds must not buy you a fresh interval."""
    detector, mesh, reminders, _ = _detector(interval=10.0)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)   # calibrate
    now = _feed(detector, mesh, 0.10, 0.2, start=now)          # blink: countdown at zero
    now = _feed(detector, mesh, 0.30, 8.0, start=now)          # 8 s without a blink
    now = _feed(detector, mesh, None, 5.0, start=now)          # glance away
    assert reminders == []
    now = _feed(detector, mesh, 0.30, 3.0, start=now)          # back: 8 s + 3 s > interval
    assert len(reminders) == 1, "the countdown should resume where it stopped"


def test_a_long_absence_starts_over():
    detector, mesh, reminders, _ = _detector(interval=10.0, absence_timeout=600.0)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, 0.10, 0.2, start=now)          # blink: countdown at zero
    now = _feed(detector, mesh, 0.30, 8.0, start=now)
    now = _feed(detector, mesh, None, 25.0, start=now)         # away long enough to have blinked
    now = _feed(detector, mesh, 0.30, 5.0, start=now)
    assert reminders == [], "a fresh interval after a real break"
    _feed(detector, mesh, 0.30, 6.0, start=now)
    assert len(reminders) == 1


def test_baseline_ignores_closed_eyes():
    """A long closure must not drag the median down and blind the detector."""
    detector, mesh, _, _ = _detector()
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    before = detector._threshold()
    now = _feed(detector, mesh, 0.10, 2.5, start=now)          # eyes shut, 25 frames
    assert abs(detector._threshold() - before) < 1e-9, "closed frames must stay out of the baseline"

    now = _feed(detector, mesh, 0.30, 1.0, start=now)
    now = _feed(detector, mesh, 0.12, 0.2, start=now)          # a normal blink still registers
    _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().blinks == 1


def test_baseline_relearns_when_the_eyes_look_closed_for_good():
    """If the face moves and EAR drops for good, the detector must re-calibrate, not go deaf."""
    detector, mesh, _, _ = _detector()
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, 0.18, 30.0, start=now)         # new normal, well under the old threshold
    assert detector._threshold() < 0.30 * 0.78, "threshold should have followed the new baseline"
    now = _feed(detector, mesh, 0.08, 0.2, start=now)          # a blink from the new baseline
    _feed(detector, mesh, 0.18, 1.0, start=now)
    assert detector.snapshot().blinks >= 1


def test_reminders_stop_when_blinks_stop_being_measurable():
    """A camera angle that hides the eyelids must silence the app, not make it invent."""
    import blinkreminder.detector as module

    detector, mesh, reminders, _ = _detector(interval=12.0, min_reminder_gap=30.0)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    # Eyes visibly open the whole time, with only the shallow wobble a bad angle gives.
    now = _feed(detector, mesh, 0.29, module.SIGNAL_TIMEOUT + 10, start=now)
    assert detector.snapshot().signal_unusable, "two minutes without a measurable blink"
    fired_by_then = len(reminders)
    assert fired_by_then > 0, "it does try before giving up"
    _feed(detector, mesh, 0.29, 120.0, start=now)
    assert len(reminders) == fired_by_then, "no more guesses once the signal is unusable"


def test_one_measurable_blink_brings_the_app_back():
    import blinkreminder.detector as module

    detector, mesh, reminders, _ = _detector(interval=12.0, min_reminder_gap=30.0)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    now = _feed(detector, mesh, 0.29, module.SIGNAL_TIMEOUT + 10, start=now)
    assert detector.snapshot().signal_unusable

    now = _feed(detector, mesh, 0.15, 0.3, start=now)      # the camera gets turned; a real blink
    now = _feed(detector, mesh, 0.30, 1.0, start=now)
    assert not detector.snapshot().signal_unusable
    before = len(reminders)
    _feed(detector, mesh, 0.30, 45.0, start=now)
    assert len(reminders) > before, "reminders resume once blinks are measurable again"


def test_a_blink_is_timestamped_and_measured_for_the_live_preview():
    detector, mesh, _, _ = _detector(sensitivity=0.82)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    assert detector._last_blink_event == 0.0

    now = _feed(detector, mesh, 0.15, 0.2, start=now)
    end = _feed(detector, mesh, 0.30, 0.5, start=now)
    assert detector._last_blink_event > 0, "the preview flashes off this timestamp"
    assert end - detector._last_blink_event < 1.0
    assert detector._last_blink_depth is not None
    assert 0.45 < detector._last_blink_depth < 0.55, "0.15 is half of the 0.30 baseline"


def test_signal_quality_reflects_how_deep_the_blinks_look():
    """Shallow blinks mean the camera is seeing the eyelids at an angle."""
    detector, mesh, _, _ = _detector(sensitivity=0.82)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)
    assert detector.signal_quality == "unknown", "no verdict before there is evidence"

    for _ in range(6):                                     # barely-there dips: 20% below
        now = _feed(detector, mesh, 0.24, 0.2, start=now)
        now = _feed(detector, mesh, 0.30, 1.0, start=now)
    assert detector.snapshot().signal_quality == "weak"

    detector2, mesh2, _, _ = _detector(sensitivity=0.82)
    now = _feed(detector2, mesh2, 0.30, 6.0, start=FAKE_START)
    for _ in range(6):                                     # proper blinks: 50% below
        now = _feed(detector2, mesh2, 0.15, 0.2, start=now)
        now = _feed(detector2, mesh2, 0.30, 1.0, start=now)
    assert detector2.snapshot().signal_quality == "good"


def test_pause_and_resume():
    detector, _, _, _ = _detector()
    assert detector.paused is False
    assert detector.toggle_pause() is True
    assert detector._blocking_state() == State.PAUSED
    detector.resume()
    assert detector.paused is False

    detector.pause(seconds=0.2)
    assert detector.paused is True
    time.sleep(0.25)
    assert detector.paused is False, "timed pause must expire on its own"


def test_standby_does_not_thrash_the_camera_when_you_are_out_of_frame():
    """Typing while the camera cannot see you must not hold the camera open forever."""
    import blinkreminder.detector as module

    detector, _, _, _ = _detector()
    original = module.system.idle_seconds
    module.system.idle_seconds = lambda: 0.0  # at the keyboard the whole time
    try:
        detector._state = State.STANDBY
        detector._standby_since = FAKE_START
        assert not detector._standby_should_wake(FAKE_START + 5), "too soon to reopen the camera"
        assert detector._standby_should_wake(FAKE_START + module.STANDBY_MIN_SLEEP + 1)

        # Three probes that found nobody: back off to one look every few minutes.
        detector._failed_probes = module.PROBE_BACKOFF_AFTER
        assert not detector._standby_should_wake(FAKE_START + 60)
        assert detector._standby_should_wake(FAKE_START + module.PROBE_BACKOFF_SLEEP + 1)

        # Seeing a face clears the backoff.
        detector._failed_probes = 0
        assert detector._standby_should_wake(FAKE_START + module.STANDBY_MIN_SLEEP + 1)
    finally:
        module.system.idle_seconds = original


def test_failed_probes_are_counted_and_reset():
    import blinkreminder.detector as module

    # Config.clamp() keeps absence_timeout at 10 s or more, so feed a little longer.
    detector, mesh, _, _ = _detector(absence_timeout=10.0)
    now = _feed(detector, mesh, 0.30, 6.0, start=FAKE_START)     # face seen
    assert detector._failed_probes == 0
    now = _feed(detector, mesh, None, 13.0, start=now)           # gone -> standby
    # _feed drives _process directly, so the state flips back to no_face on the frame
    # after standby is entered; _standby_since is the durable evidence it happened.
    assert detector._standby_since is not None
    assert detector._failed_probes == 0, "the first standby is not a failed probe"

    detector._state = State.NO_FACE                             # a probe starts
    detector._probe_started = now
    now = _feed(detector, mesh, None, module.STANDBY_PROBE_WINDOW + 2, start=now)
    assert detector._failed_probes == 1
    _feed(detector, mesh, 0.30, 1.0, start=now)                 # found again
    assert detector._failed_probes == 0


def test_thread_releases_the_camera_while_paused():
    """The loop must close the camera when paused, so the green light goes off."""
    detector, mesh, _, _ = _detector()
    opened = {"count": 0, "released": 0}

    class _FakeCapture:
        def __init__(self, *_args):
            opened["count"] += 1
            self._open = True

        def isOpened(self):
            return self._open

        def set(self, *_args):
            return True

        def read(self):
            return True, FRAME

        def release(self):
            opened["released"] += 1
            self._open = False

    import blinkreminder.detector as module

    original = module.cv2.VideoCapture
    module.cv2.VideoCapture = _FakeCapture  # type: ignore[assignment]
    try:
        detector.start()
        time.sleep(1.0)
        assert opened["count"] >= 1
        assert detector.snapshot().state in (State.STARTING, State.ACTIVE)

        detector.pause()
        time.sleep(1.5)
        assert opened["released"] >= 1
        assert detector.snapshot().state == State.PAUSED

        detector.resume()
        time.sleep(1.0)
        assert opened["count"] >= 2, "camera should come back after resume"

        # The framing preview needs the camera even while the app is paused.
        opened_before = opened["count"]
        detector.pause()
        time.sleep(1.5)
        detector.set_preview(True)
        time.sleep(1.5)
        assert opened["count"] > opened_before, "preview must reopen the camera"
        assert detector.preview_jpeg(), "preview should be producing frames"
        detector.set_preview(False)
    finally:
        detector.stop()
        module.cv2.VideoCapture = original


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
        except Exception as exc:  # pragma: no cover
            failures += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print("all tests passed" if not failures else f"{failures} test(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
