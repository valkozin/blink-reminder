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
STANDBY_PROBE_EVERY = 60.0      # while standing by, take a look every minute
STANDBY_PROBE_WINDOW = 8.0      # ...and give the probe this long to find a face


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
    ) -> None:
        self.config = config
        self._on_reminder = on_reminder
        self._on_error = on_error

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
        self._camera_failed_at: Optional[float] = None
        self._error_reported = False

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

    def snapshot(self) -> Snapshot:
        now = time.monotonic()
        self._trim_blink_times(now)
        rate: Optional[float] = None
        if self._active_seconds >= 25.0:
            window = min(60.0, max(self._active_seconds, 1.0))
            rate = round(len(self._blink_times) * 60.0 / window, 1)
        return Snapshot(
            state=self._state,
            blinks=self._blinks,
            reminders=self._reminders,
            rate=rate,
            seconds_since_blink=now - self._last_blink,
            active_seconds=self._active_seconds,
            paused_until=self._paused_until,
        )

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
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        return self._face_mesh

    # ------------------------------------------------------------------ helpers

    def _reset_timers(self) -> None:
        now = time.monotonic()
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
        if system.idle_seconds() < 3.0:
            return True
        return self._standby_since is not None and now - self._standby_since > STANDBY_PROBE_EVERY

    # ------------------------------------------------------------------ main loop

    def _run(self) -> None:
        while not self._stop.is_set():
            loop_started = time.monotonic()

            blocked = self._blocking_state()
            if blocked is not None:
                self._state = blocked
                self._release_camera()
                self._reset_timers()
                self._stop.wait(1.0)
                continue

            if self._state == State.STANDBY:
                if not self._standby_should_wake(loop_started):
                    self._stop.wait(1.0)
                    continue
                self._standby_since = None
                self._probe_started = loop_started
                self._state = State.NO_FACE
                self._reset_timers()

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

        if results.multi_face_landmarks:
            self._last_face = now
            self._probe_started = None
            landmarks = results.multi_face_landmarks[0].landmark
            indices = LEFT_EYE + RIGHT_EYE
            points = np.array(
                [(landmarks[i].x, landmarks[i].y * aspect) for i in indices],
                dtype=np.float64,
            )
            ear = (_ear(points[:6]) + _ear(points[6:])) / 2.0
            self._ear_history.append(ear)
            self._update_blink_state(ear, now)

        face_present = now - self._last_face < FACE_GRACE

        if face_present:
            self._active_seconds += dt
            calibrating = len(self._ear_history) < CALIBRATION_SAMPLES
            self._state = State.STARTING if calibrating else State.ACTIVE
            if not calibrating:
                self._maybe_remind(now)
            return

        # Nobody in front of the camera.
        self._state = State.NO_FACE
        self._reset_timers()

        probing = self._probe_started is not None
        away_for = now - self._last_face
        if probing and now - self._probe_started > STANDBY_PROBE_WINDOW:
            self._enter_standby(now)
        elif not probing and away_for > self.config.absence_timeout:
            self._enter_standby(now)

    def _enter_standby(self, now: float) -> None:
        self._state = State.STANDBY
        self._standby_since = now
        self._probe_started = None
        self._release_camera()

    def _update_blink_state(self, ear: float, now: float) -> None:
        threshold = self._threshold()
        if not self._eyes_closed and ear < threshold:
            self._eyes_closed = True
            self._closed_since = now
            self._last_blink = now  # closed eyes are moist eyes - nothing to remind about
        elif self._eyes_closed and ear > threshold * REOPEN_MARGIN:
            duration = now - (self._closed_since or now)
            self._eyes_closed = False
            self._closed_since = None
            self._last_blink = now
            if duration <= MAX_BLINK_SECONDS:
                self._blinks += 1
                self._blink_times.append(now)
        elif self._eyes_closed:
            self._last_blink = now

    def _maybe_remind(self, now: float) -> None:
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
