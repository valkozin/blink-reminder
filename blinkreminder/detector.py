"""Camera loop: detects blinks, notices when you leave, and asks for a reminder when needed."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

from .config import Config
from . import system

log = logging.getLogger(__name__)

# MediaPipe Face Mesh landmark indices: outer, upper x2, inner, lower x2.
LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)

FALLBACK_EAR_THRESHOLD = 0.21   # used until the personal baseline is ready
REOPEN_MARGIN = 1.06            # hysteresis, so a borderline EAR does not flicker
MAX_BLINK_SECONDS = 0.7         # longer than this is "eyes closed", not a blink
CALIBRATION_SAMPLES = 40
FACE_GRACE = 2.0                # keep trusting the last detection for this long
ABSENCE_RESET = 20.0            # away longer than this: assume you blinked, start over
STUCK_CLOSED_SECONDS = 3.0      # EAR below threshold this long is the new normal, not a blink
STANDBY_PROBE_EVERY = 60.0      # while standing by, take a look every minute
STANDBY_PROBE_WINDOW = 8.0      # ...and give the probe this long to find a face
STANDBY_MIN_SLEEP = 20.0        # but never reopen the camera sooner than this
PROBE_BACKOFF_AFTER = 3         # fruitless probes before backing right off
PROBE_BACKOFF_SLEEP = 300.0     # ...to one look every five minutes
UNSEEN_WARNING_AFTER = 180.0    # at the keyboard, unseen this long: say so
# Nobody goes two minutes without blinking. If the face is right there and not one
# blink is measurable in all that time, the camera angle is hiding the eyelids - the
# signal is unusable and reminders based on it would be invented, so we stop.
SIGNAL_TIMEOUT = 120.0
# How far below the baseline a blink reaches says how well the camera sees the eyelids.
# Well-aimed: 35-60%. Steep angle: barely past the threshold, and half the blinks are lost.
WEAK_BLINK_DEPTH = 0.25
MIN_DEPTH_SAMPLES = 5


class State:
    STARTING = "starting"
    ACTIVE = "active"
    NO_FACE = "no_face"
    STANDBY = "standby"
    PAUSED = "paused"
    LOCKED = "locked"
    IDLE = "idle"
    ERROR = "error"


@dataclass
class Snapshot:
    state: str = State.STARTING
    blinks: int = 0
    reminders: int = 0
    rate: Optional[float] = None      # blinks per minute over the last 60 s
    seconds_since_blink: float = 0.0
    active_seconds: float = 0.0       # time with your face in front of the camera
    paused_until: Optional[float] = None
    seconds_since_face: float = 0.0
    unseen_at_keyboard: bool = False  # you are typing, but the camera cannot find you
    signal_unusable: bool = False     # your face is visible but blinks are not measurable
    signal_quality: str = "unknown"    # good | weak | unknown - how clearly blinks show up


def _ear(points: np.ndarray) -> float:
    """Eye Aspect Ratio for six landmarks already scaled to pixel-ish proportions."""
    vertical = np.linalg.norm(points[1] - points[5]) + np.linalg.norm(points[2] - points[4])
    horizontal = np.linalg.norm(points[0] - points[3])
    if horizontal < 1e-6:
        return 0.0
    return float(vertical / (2.0 * horizontal))


class BlinkDetector:
    def __init__(
        self,
        config: Config,
        on_reminder: Callable[[], None],
        on_error: Optional[Callable[[str], None]] = None,
        on_frame: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.config = config
        self._on_reminder = on_reminder
        self._on_error = on_error
        self._on_frame = on_frame  # diagnostics only; see --diagnose

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._paused = False
        self._paused_until: Optional[float] = None

        self._cap = None
        self._face_mesh = None

        # detection state
        self._ear_history: deque[float] = deque(maxlen=600)
        self._blink_times: deque[float] = deque()
        self._closed_since: Optional[float] = None
        self._eyes_closed = False
        self._last_blink = time.monotonic()
        self._last_face = time.monotonic()
        self._last_reminder = 0.0
        self._standby_since: Optional[float] = None
        self._probe_started: Optional[float] = None
        self._failed_probes = 0
        self._camera_failed_at: Optional[float] = None
        self._error_reported = False
        self._reopen_requested = False

        self._preview_wanted = False
        self._preview_jpeg: Optional[bytes] = None

        self._face_seconds_since_blink = 0.0
        self._blink_depths: deque[float] = deque(maxlen=30)
        self._closed_min_ear: Optional[float] = None

        self._state = State.STARTING
        self._blinks = 0
        self._reminders = 0
        self._active_seconds = 0.0
        self._last_tick = time.monotonic()

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="blink-detector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._release_camera()
        if self._face_mesh is not None:
            try:
                self._face_mesh.close()
            except Exception:  # pragma: no cover - defensive
                pass
            self._face_mesh = None

    @property
    def paused(self) -> bool:
        with self._lock:
            if self._paused_until is not None and time.time() >= self._paused_until:
                self._paused_until = None
                self._paused = False
            return self._paused

    def pause(self, seconds: Optional[float] = None) -> None:
        with self._lock:
            self._paused = True
            self._paused_until = time.time() + seconds if seconds else None

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._paused_until = None
        self._reset_timers()

    def toggle_pause(self) -> bool:
        if self.paused:
            self.resume()
        else:
            self.pause()
        return self.paused

    def set_preview(self, enabled: bool) -> None:
        """Turn the camera-framing preview on or off. Keeps the camera awake while on."""
        self._preview_wanted = enabled
        if not enabled:
            self._preview_jpeg = None

    def preview_jpeg(self) -> Optional[bytes]:
        return self._preview_jpeg

    def reopen_camera(self) -> None:
        """Drop the capture so the next loop picks up a new camera index."""
        self._reopen_requested = True

    def snapshot(self) -> Snapshot:
        now = time.monotonic()
        self._trim_blink_times(now)
        rate: Optional[float] = None
        if self._active_seconds >= 25.0:
            window = min(60.0, max(self._active_seconds, 1.0))
            rate = round(len(self._blink_times) * 60.0 / window, 1)
        since_face = now - self._last_face
        return Snapshot(
            state=self._state,
            blinks=self._blinks,
            reminders=self._reminders,
            rate=rate,
            seconds_since_blink=now - self._last_blink,
            active_seconds=self._active_seconds,
            paused_until=self._paused_until,
            seconds_since_face=since_face,
            signal_unusable=self.signal_unusable,
            signal_quality=self.signal_quality,
            unseen_at_keyboard=(
                since_face > UNSEEN_WARNING_AFTER
                and system.idle_seconds() < 60.0
                and self._state in (State.NO_FACE, State.STANDBY)
            ),
        )

    @property
    def signal_unusable(self) -> bool:
        return self._face_seconds_since_blink > SIGNAL_TIMEOUT

    @property
    def signal_quality(self) -> str:
        """How deep the blinks look - a proxy for whether the camera sees the eyelids."""
        if len(self._blink_depths) < MIN_DEPTH_SAMPLES:
            return "unknown"
        return "weak" if float(np.median(self._blink_depths)) < WEAK_BLINK_DEPTH else "good"

    # ------------------------------------------------------------------ camera

    def _open_camera(self) -> bool:
        if self._cap is not None:
            return True
        backend = cv2.CAP_AVFOUNDATION if system.IS_MAC else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.config.camera_index, backend)
        if not cap.isOpened():
            cap.release()
            self._state = State.ERROR
            if not self._error_reported and self._on_error:
                self._error_reported = True
                self._on_error("camera")
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.frame_height)
        # AVFoundation usually ignores this, but it costs nothing to ask.
        cap.set(cv2.CAP_PROP_FPS, self.config.fps)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # pragma: no cover - backend without that property
            pass
        self._cap = cap
        self._error_reported = False
        return True

    def _release_camera(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # pragma: no cover - defensive
                pass
            self._cap = None

    def _ensure_face_mesh(self):
        if self._face_mesh is None:
            try:
                from mediapipe.python.solutions import face_mesh as mp_face_mesh
            except ImportError:  # pragma: no cover - older mediapipe layouts
                import mediapipe as mp

                mp_face_mesh = mp.solutions.face_mesh
            # refine_landmarks adds the iris/lips attention mesh - roughly doubles the
            # cost per frame and none of those points are used here.
            self._face_mesh = mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=False,
                # Low, on purpose: the camera is often off to one side of the screen
                # the person is actually looking at, so the face is never frontal.
                min_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
        return self._face_mesh

    # ------------------------------------------------------------------ helpers

    def _reset_timers(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self._last_blink = now
        self._last_reminder = 0.0
        self._closed_since = None
        self._eyes_closed = False

    def _trim_blink_times(self, now: float) -> None:
        while self._blink_times and now - self._blink_times[0] > 60.0:
            self._blink_times.popleft()

    def _threshold(self) -> float:
        if len(self._ear_history) < CALIBRATION_SAMPLES:
            return FALLBACK_EAR_THRESHOLD
        baseline = float(np.median(self._ear_history))
        return baseline * self.config.sensitivity

    def _blocking_state(self) -> Optional[str]:
        """Reasons to keep the camera off, in priority order."""
        if self.paused:
            return State.PAUSED
        if self.config.pause_when_locked and (
            system.screen_is_locked() or system.display_is_asleep()
        ):
            return State.LOCKED
        if self.config.pause_when_idle and system.idle_seconds() > self.config.idle_threshold:
            return State.IDLE
        return None

    def _standby_should_wake(self, now: float) -> bool:
        """Opening the camera costs a second and 15% of a core - do it sparingly.

        Without the minimum sleep below, a user who is typing but out of frame (laptop
        camera off to one side) makes this bounce between probe and standby forever,
        holding the camera open the whole time for nothing.
        """
        asleep_for = now - (self._standby_since or now)
        floor = PROBE_BACKOFF_SLEEP if self._failed_probes >= PROBE_BACKOFF_AFTER else STANDBY_MIN_SLEEP
        if asleep_for < floor:
            return False
        if system.idle_seconds() < 3.0:
            return True
        return asleep_for > max(STANDBY_PROBE_EVERY, floor)

    # ------------------------------------------------------------------ main loop

    def _run(self) -> None:
        while not self._stop.is_set():
            loop_started = time.monotonic()

            if self._reopen_requested:
                self._reopen_requested = False
                self._release_camera()

            if self._preview_wanted:
                # Aiming the camera only works if it is actually running.
                if self._state == State.STANDBY:
                    self._state = State.NO_FACE
                    self._standby_since = None
                    self._probe_started = None
                    self._failed_probes = 0
            else:
                blocked = self._blocking_state()
                if blocked is not None:
                    self._state = blocked
                    self._release_camera()
                    self._reset_timers(loop_started)
                    self._stop.wait(1.0)
                    continue

            if not self._preview_wanted and self._state == State.STANDBY:
                if not self._standby_should_wake(loop_started):
                    self._stop.wait(1.0)
                    continue
                self._standby_since = None
                self._probe_started = loop_started
                self._state = State.NO_FACE
                self._reset_timers(loop_started)

            if self._cap is None and self._camera_failed_at is not None:
                if loop_started - self._camera_failed_at < 15.0:
                    self._stop.wait(1.0)
                    continue
                self._camera_failed_at = None

            if not self._open_camera():
                self._camera_failed_at = loop_started
                self._stop.wait(1.0)
                continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                log.warning("dropped frame from the camera")
                self._release_camera()
                self._camera_failed_at = loop_started
                self._stop.wait(1.0)
                continue

            self._process(frame, loop_started)

            frame_budget = 1.0 / max(self.config.fps, 1)  # re-read: fps is user-settable
            elapsed = time.monotonic() - loop_started
            if elapsed < frame_budget:
                self._stop.wait(frame_budget - elapsed)

        self._release_camera()

    def _process(self, frame, now: float) -> None:
        dt = min(now - self._last_tick, 2.0)
        self._last_tick = now

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._ensure_face_mesh().process(rgb)

        height, width = frame.shape[:2]
        aspect = height / float(width) if width else 1.0

        ear_now = float("nan")
        if results.multi_face_landmarks:
            self._last_face = now
            self._probe_started = None
            self._failed_probes = 0
            landmarks = results.multi_face_landmarks[0].landmark
            indices = LEFT_EYE + RIGHT_EYE
            points = np.array(
                [(landmarks[i].x, landmarks[i].y * aspect) for i in indices],
                dtype=np.float64,
            )
            ear = ear_now = (_ear(points[:6]) + _ear(points[6:])) / 2.0
            self._update_blink_state(ear, now)
            self._record_baseline(ear, now)

        face_present = now - self._last_face < FACE_GRACE

        if self._preview_wanted:
            self._render_preview(frame, results, ear_now, face_present)

        if self._on_frame is not None:
            self._on_frame(
                {
                    "t": now,
                    "face": int(bool(results.multi_face_landmarks)),
                    "ear": ear_now,
                    "baseline": float(np.median(self._ear_history)) if self._ear_history else float("nan"),
                    "threshold": self._threshold(),
                    "closed": int(self._eyes_closed),
                    "blinks": self._blinks,
                    "reminders": self._reminders,
                    "since_blink": now - self._last_blink,
                    "state": self._state,
                }
            )

        if face_present:
            self._active_seconds += dt
            self._face_seconds_since_blink += dt
            calibrating = len(self._ear_history) < CALIBRATION_SAMPLES
            self._state = State.STARTING if calibrating else State.ACTIVE
            if not calibrating:
                self._maybe_remind(now)
            return

        # Nobody in front of the camera. Hold the countdown where it is rather than
        # restarting it: glancing at the keyboard for three seconds does not moisten
        # your eyes, and restarting on every glance means the reminder never arrives.
        self._state = State.NO_FACE
        if now - self._last_face > ABSENCE_RESET:
            self._reset_timers(now)
            self._face_seconds_since_blink = 0.0
        else:
            self._last_blink += dt
            if self._last_reminder:
                self._last_reminder += dt

        probing = self._probe_started is not None
        away_for = now - self._last_face
        if probing and now - self._probe_started > STANDBY_PROBE_WINDOW:
            self._enter_standby(now)
        elif not probing and away_for > self.config.absence_timeout:
            self._enter_standby(now)

    def _render_preview(self, frame, results, ear: float, face_present: bool) -> None:
        """Annotate the frame so you can see whether the camera has found your eyes."""
        try:
            view = cv2.flip(frame, 1)  # mirror, so moving the laptop feels right
            height, width = view.shape[:2]
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0].landmark
                for index in LEFT_EYE + RIGHT_EYE:
                    point = landmarks[index]
                    cv2.circle(
                        view,
                        (int((1.0 - point.x) * width), int(point.y * height)),
                        2,
                        (0, 200, 0),
                        -1,
                    )
            colour = (0, 200, 0) if face_present else (0, 0, 230)
            label = f"EAR {ear:.2f}  thr {self._threshold():.2f}" if face_present else "NO FACE"
            cv2.rectangle(view, (0, 0), (width - 1, height - 1), colour, 3)
            cv2.putText(view, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
            ok, buffer = cv2.imencode(".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                self._preview_jpeg = buffer.tobytes()
        except Exception:  # pragma: no cover - the preview must never break detection
            log.debug("preview rendering failed", exc_info=True)

    def _enter_standby(self, now: float) -> None:
        if self._probe_started is not None:
            self._failed_probes += 1
        self._state = State.STANDBY
        self._standby_since = now
        self._probe_started = None
        self._release_camera()

    def _record_baseline(self, ear: float, now: float) -> None:
        """Keep the rolling baseline made of open-eye frames only.

        Feeding it every frame lets a long closure - or a burst of blinking - drag the
        median down and quietly raise the bar for the next blink.
        """
        if len(self._ear_history) < CALIBRATION_SAMPLES:
            self._ear_history.append(ear)
            return
        if not self._eyes_closed:
            self._ear_history.append(ear)
        elif self._closed_since is not None and now - self._closed_since > STUCK_CLOSED_SECONDS:
            # Below the threshold for seconds on end: the face moved, the light changed,
            # or the baseline is simply wrong. Let it re-learn instead of going deaf.
            self._ear_history.append(ear)

    def _update_blink_state(self, ear: float, now: float) -> None:
        threshold = self._threshold()
        if not self._eyes_closed and ear < threshold:
            self._eyes_closed = True
            self._closed_since = now
            self._closed_min_ear = ear
            self._last_blink = now  # closed eyes are moist eyes - nothing to remind about
        elif self._eyes_closed and ear > threshold * REOPEN_MARGIN:
            duration = now - (self._closed_since or now)
            deepest = self._closed_min_ear if self._closed_min_ear is not None else ear
            self._eyes_closed = False
            self._closed_since = None
            self._closed_min_ear = None
            self._last_blink = now
            self._face_seconds_since_blink = 0.0
            if duration <= MAX_BLINK_SECONDS:
                self._blinks += 1
                self._blink_times.append(now)
                baseline = float(np.median(self._ear_history)) if self._ear_history else 0.0
                if baseline > 0:
                    self._blink_depths.append((baseline - deepest) / baseline)
        elif self._eyes_closed:
            self._last_blink = now
            if self._closed_min_ear is None or ear < self._closed_min_ear:
                self._closed_min_ear = ear

    def _maybe_remind(self, now: float) -> None:
        if self.signal_unusable:
            return  # we are not measuring anything; a reminder now would be a guess
        if now - self._last_blink < self.config.interval:
            return
        if now - self._last_reminder < self.config.min_reminder_gap:
            return
        self._last_reminder = now
        self._last_blink = now
        self._reminders += 1
        try:
            self._on_reminder()
        except Exception:  # pragma: no cover - never let a callback kill the loop
            log.exception("reminder callback failed")
