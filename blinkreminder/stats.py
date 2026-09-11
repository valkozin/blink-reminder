"""Daily totals, so the numbers survive a restart. Nothing leaves this machine."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .config import CONFIG_DIR, STATS_PATH
from .i18n import t

log = logging.getLogger(__name__)

KEEP_DAYS = 60
EMPTY_DAY = {"blinks": 0, "reminders": 0, "active_seconds": 0.0}


def _load() -> dict:
    if not STATS_PATH.exists():
        return {}
    try:
        data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("could not read stats: %s", exc)
        return {}


def _save(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(STATS_PATH)
    except OSError as exc:
        log.warning("could not save stats: %s", exc)


def record(blinks: int = 0, reminders: int = 0, active_seconds: float = 0.0) -> None:
    """Add today's deltas. Called once a minute, so writes stay cheap."""
    if not (blinks or reminders or active_seconds):
        return
    data = _load()
    key = date.today().isoformat()
    day = {**EMPTY_DAY, **data.get(key, {})}
    day["blinks"] += int(blinks)
    day["reminders"] += int(reminders)
    day["active_seconds"] += float(active_seconds)
    data[key] = day

    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    data = {k: v for k, v in data.items() if k >= cutoff}
    _save(data)


def today() -> dict:
    return {**EMPTY_DAY, **_load().get(date.today().isoformat(), {})}


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, minutes = divmod(total // 60, 60)
    if hours:
        return f"{hours} {t('dur_hours')} {minutes} {t('dur_minutes')}"
    return f"{minutes} {t('dur_minutes')}"
