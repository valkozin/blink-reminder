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


SCHEMA_VERSION = 3  # bump when the detection defaults below are retuned


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    # --- reminder behaviour ---
    # Staring at a screen drops most people to a blink every 8-12 s, so 12 s is the
    # point where a nudge is useful; the gap keeps it to at most two nudges a minute.
    interval: float = 12.0          # seconds without a blink before reminding
    min_reminder_gap: float = 30.0  # never remind more often than this
    # A blink lasts ~150 ms, so even at 15 fps it is caught in one or two frames, often
    # on the way down rather than fully shut. Measured traces show real blinks reaching
    # 35-60% below the baseline but being sampled at 15-25%, so the bar sits at 18%.
    sensitivity: float = 0.82       # blink when EAR drops below this share of the open-eye baseline

    # --- how the reminder is delivered ---
    sound_enabled: bool = True
    sound_name: str = "Tink"
    sound_volume: float = 0.35      # afplay volume, 0..1 (keep it quiet)
    hud_enabled: bool = True
    hud_duration: float = 1.4       # seconds the on-screen hint stays visible
    hud_position: str = "top"       # top | center | bottom

    # --- camera / cpu ---
    camera_index: int = 0
    fps: int = 15                   # frames analysed per second (lower = less CPU, more missed blinks)
    # Ask the camera for a high-quality stream and shrink it ourselves: the sensor's
    # own low-resolution modes are noticeably noisier (measured: 0.068 vs 0.042 wobble
    # in the eyelid signal), while MediaPipe gains nothing from the extra pixels.
    frame_width: int = 1280
    frame_height: int = 720
    process_width: int = 480        # what actually reaches the landmark model

    # --- automatic pausing ---
    absence_timeout: float = 90.0   # no face for this long -> release camera, stand by
    pause_when_locked: bool = True
    pause_when_idle: bool = False   # also pause on no keyboard/mouse activity
    idle_threshold: float = 300.0

    # --- interface ---
    language: str = "auto"          # auto | en | ru
    menubar_extra: str = "none"     # none | rate | count - what sits beside the icon

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
        # A file written before versioning existed is version 1 by definition.
        file_version = int(raw.get("schema_version", 1))
        known = {f.name: f.type for f in fields(cls)}
        for key, value in raw.items():
            if key not in known:
                continue
            try:
                setattr(cfg, key, value)
            except Exception:  # pragma: no cover - defensive
                log.warning("ignoring bad config value for %s", key)
        cfg.migrate(file_version, raw)
        cfg.clamp()
        return cfg

    def migrate(self, file_version: int, raw: dict) -> None:
        """Carry user choices forward while new defaults and renamed settings take effect."""
        if file_version >= SCHEMA_VERSION:
            return
        defaults = Config()
        if file_version < 2:
            # fps has never been in the menu, and a sensitivity still sitting on the old
            # default was never chosen by anyone - both should follow the new tuning.
            self.fps = defaults.fps
            if abs(self.sensitivity - 0.78) < 1e-9:  # the version 1 default
                self.sensitivity = defaults.sensitivity
        if file_version < 3 and raw.get("show_rate_in_menubar"):
            self.menubar_extra = "rate"  # renamed when the blink counter joined it
        self.schema_version = SCHEMA_VERSION
        self.save()

    def clamp(self) -> None:
        """Keep hand-edited values inside sane bounds."""
        self.interval = min(max(float(self.interval), 3.0), 300.0)
        self.min_reminder_gap = min(max(float(self.min_reminder_gap), 3.0), 600.0)
        self.sensitivity = min(max(float(self.sensitivity), 0.55), 0.92)
        self.sound_volume = min(max(float(self.sound_volume), 0.0), 1.0)
        self.hud_duration = min(max(float(self.hud_duration), 0.4), 10.0)
        self.fps = int(min(max(int(self.fps), 3), 30))
        self.process_width = int(min(max(int(self.process_width), 320), 1280))
        self.absence_timeout = max(float(self.absence_timeout), 10.0)
        self.idle_threshold = max(float(self.idle_threshold), 30.0)
        if self.sound_name not in AVAILABLE_SOUNDS:
            self.sound_name = "Tink"
        if self.hud_position not in ("top", "center", "bottom"):
            self.hud_position = "top"
        if self.menubar_extra not in ("none", "rate", "count"):
            self.menubar_extra = "none"
