"""Persistent user settings, stored as JSON in the user's application support dir."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

if sys.platform == "darwin":
    CONFIG_DIR = Path.home() / "Library" / "Application Support" / "BlinkReminder"
    LOG_DIR = Path.home() / "Library" / "Logs"
else:
    CONFIG_DIR = Path.home() / ".config" / "blink-reminder"
    LOG_DIR = CONFIG_DIR

CONFIG_PATH = CONFIG_DIR / "config.json"
STATS_PATH = CONFIG_DIR / "stats.json"
LOG_PATH = LOG_DIR / "BlinkReminder.log"

# Soft, short system sounds - anything longer is distracting when it fires all day.
AVAILABLE_SOUNDS = ("Tink", "Pop", "Purr", "Bottle", "Morse", "Submarine", "Glass", "Blow")
INTERVAL_CHOICES = (6, 8, 10, 12, 15, 20, 30)


@dataclass
class Config:
    # --- reminder behaviour ---
    # Staring at a screen drops most people to a blink every 8-12 s, so 12 s is the
    # point where a nudge is useful; the gap keeps it to at most two nudges a minute.
    interval: float = 12.0          # seconds without a blink before reminding
    min_reminder_gap: float = 30.0  # never remind more often than this
    sensitivity: float = 0.78       # blink when EAR drops below this share of the open-eye baseline

    # --- how the reminder is delivered ---
    sound_enabled: bool = True
    sound_name: str = "Tink"
    sound_volume: float = 0.35      # afplay volume, 0..1 (keep it quiet)
    hud_enabled: bool = True
    hud_duration: float = 1.4       # seconds the on-screen hint stays visible
    hud_position: str = "top"       # top | center | bottom

    # --- camera / cpu ---
    camera_index: int = 0
    fps: int = 10                   # frames analysed per second (lower = less CPU)
    # 480x360 is the smallest size that still tracks eyelids reliably - at 320x240
    # MediaPipe keeps finding the face but stops resolving blinks.
    frame_width: int = 480
    frame_height: int = 360

    # --- automatic pausing ---
    absence_timeout: float = 90.0   # no face for this long -> release camera, stand by
    pause_when_locked: bool = True
    pause_when_idle: bool = False   # also pause on no keyboard/mouse activity
    idle_threshold: float = 300.0

    # --- interface ---
    language: str = "auto"          # auto | en | ru
    show_rate_in_menubar: bool = False

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            tmp.replace(CONFIG_PATH)
        except OSError as exc:
            log.warning("could not save config: %s", exc)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if not CONFIG_PATH.exists():
            return cfg
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("could not read config, using defaults: %s", exc)
            return cfg
        known = {f.name: f.type for f in fields(cls)}
        for key, value in raw.items():
            if key not in known:
                continue
            try:
                setattr(cfg, key, value)
            except Exception:  # pragma: no cover - defensive
                log.warning("ignoring bad config value for %s", key)
        cfg.clamp()
        return cfg

    def clamp(self) -> None:
        """Keep hand-edited values inside sane bounds."""
        self.interval = min(max(float(self.interval), 3.0), 300.0)
        self.min_reminder_gap = min(max(float(self.min_reminder_gap), 3.0), 600.0)
        self.sensitivity = min(max(float(self.sensitivity), 0.55), 0.95)
        self.sound_volume = min(max(float(self.sound_volume), 0.0), 1.0)
        self.hud_duration = min(max(float(self.hud_duration), 0.4), 10.0)
        self.fps = int(min(max(int(self.fps), 3), 30))
        self.absence_timeout = max(float(self.absence_timeout), 10.0)
        self.idle_threshold = max(float(self.idle_threshold), 30.0)
        if self.sound_name not in AVAILABLE_SOUNDS:
            self.sound_name = "Tink"
        if self.hud_position not in ("top", "center", "bottom"):
            self.hud_position = "top"
