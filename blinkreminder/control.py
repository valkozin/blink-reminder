"""Talking to the running app from a terminal.

The menu bar icon is not always reachable - a crowded menu bar or a display being
unplugged can leave it out of sight - so pausing or quitting must not depend on it. A one-line command file in the app's own directory is enough: no sockets,
no ports, no permissions to grant, and nothing to leave running.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR

log = logging.getLogger(__name__)


# Paths are worked out on every call rather than fixed at import. With constants, pointing
# CONFIG_DIR somewhere else moved only the files someone remembered to repoint - and the
# pause file, added later, was forgotten, so the test suite read and deleted the real app's
# pause on a developer's machine.
def _path(name: str) -> Path:
    return CONFIG_DIR / name


def command_path() -> Path:
    return _path("command")


def state_path() -> Path:
    return _path("state.json")


def pause_path() -> Path:
    return _path("pause.json")


def lock_path() -> Path:
    return _path("running.lock")


def notices_path() -> Path:
    return _path("notices.json")


# --- unsolicited notices ------------------------------------------------
# "At most once an hour" has to be remembered on disk. Kept in memory it resets on every
# restart - a crash, an update, a login - and the person comes back to a pile of them.


def notice_due(kind: str, every: float = 3600.0) -> bool:
    try:
        seen = json.loads(notices_path().read_text(encoding="utf-8"))
        last = float(seen.get(kind, 0.0))
    except (OSError, ValueError, TypeError):
        return True
    return time.time() - last > every


def notice_shown(kind: str) -> None:
    try:
        seen = json.loads(notices_path().read_text(encoding="utf-8"))
        if not isinstance(seen, dict):
            seen = {}
    except (OSError, ValueError):
        seen = {}
    seen[kind] = time.time()
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = notices_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(seen), encoding="utf-8")
        os.replace(tmp, notices_path())
    except OSError as exc:
        log.debug("could not remember the notice: %s", exc)

VALID_COMMANDS = ("quit", "pause", "resume", "toggle", "reload")


def is_running() -> bool:
    """True when another process holds the instance lock."""
    try:
        handle = open(lock_path(), "a+")
    except OSError:
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True  # somebody else has it: the app is up
    else:
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    finally:
        handle.close()


def send(command: str, argument: Optional[float] = None) -> None:
    """Leave a command for the running app to pick up on its next tick."""
    if command not in VALID_COMMANDS:
        raise ValueError(f"unknown command: {command}")
    text = command if argument is None else f"{command} {argument:g}"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = command_path().with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, command_path())


def take() -> Optional[tuple[str, Optional[float]]]:
    """App side: read and clear a pending command, if any."""
    try:
        text = command_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("could not read the command file: %s", exc)
        return None
    finally:
        command_path().unlink(missing_ok=True)

    if not text:
        return None
    parts = text.split()
    command = parts[0]
    if command not in VALID_COMMANDS:
        log.warning("ignoring unknown command %r", command)
        return None
    argument: Optional[float] = None
    if len(parts) > 1:
        try:
            argument = float(parts[1])
        except ValueError:
            log.warning("ignoring bad argument in %r", text)
    return command, argument


def publish(state: dict) -> None:
    """App side: leave a snapshot on disk so `--status` has something to read."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = state_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({**state, "updated": time.time()}, indent=2), encoding="utf-8")
        os.replace(tmp, state_path())
    except OSError as exc:
        log.debug("could not publish state: %s", exc)


def read_state() -> Optional[dict]:
    try:
        state = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


# --- a pause outlives the process ---------------------------------------
# Restarts happen for reasons that have nothing to do with the person: a crash, a
# login, an update. Forgetting that they asked for quiet and starting to chirp again
# is the one behaviour a pause must never have.


def save_pause(until: Optional[float]) -> None:
    """`until` is a wall-clock deadline, or None for "until I say otherwise"."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = pause_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"until": until}), encoding="utf-8")
        os.replace(tmp, pause_path())
    except OSError as exc:
        log.warning("could not remember the pause: %s", exc)


def clear_pause() -> None:
    pause_path().unlink(missing_ok=True)


def load_pause() -> tuple[bool, Optional[float]]:
    """Returns (paused, deadline). An expired pause clears itself."""
    try:
        data = json.loads(pause_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    until = data.get("until") if isinstance(data, dict) else None
    if until is not None:
        if not isinstance(until, (int, float)) or until <= time.time():
            clear_pause()
            return False, None
    return True, until
