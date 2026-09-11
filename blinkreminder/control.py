"""Talking to the running app from a terminal.

The menu bar icon is not always reachable - macOS hides status items that do not fit
the notch on a laptop screen, and it does so silently - so pausing or quitting must not
depend on it. A one-line command file in the app's own directory is enough: no sockets,
no ports, no permissions to grant, and nothing to leave running.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from typing import Optional

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

COMMAND_PATH = CONFIG_DIR / "command"
STATE_PATH = CONFIG_DIR / "state.json"
PAUSE_PATH = CONFIG_DIR / "pause.json"
LOCK_PATH = CONFIG_DIR / "running.lock"

VALID_COMMANDS = ("quit", "pause", "resume", "toggle", "reload")


def is_running() -> bool:
    """True when another process holds the instance lock."""
    try:
        handle = open(LOCK_PATH, "a+")
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
    tmp = COMMAND_PATH.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, COMMAND_PATH)


def take() -> Optional[tuple[str, Optional[float]]]:
    """App side: read and clear a pending command, if any."""
    try:
        text = COMMAND_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("could not read the command file: %s", exc)
        return None
    finally:
        COMMAND_PATH.unlink(missing_ok=True)

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
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({**state, "updated": time.time()}, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        log.debug("could not publish state: %s", exc)


def read_state() -> Optional[dict]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
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
        tmp = PAUSE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"until": until}), encoding="utf-8")
        os.replace(tmp, PAUSE_PATH)
    except OSError as exc:
        log.warning("could not remember the pause: %s", exc)


def clear_pause() -> None:
    PAUSE_PATH.unlink(missing_ok=True)


def load_pause() -> tuple[bool, Optional[float]]:
    """Returns (paused, deadline). An expired pause clears itself."""
    try:
        data = json.loads(PAUSE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    until = data.get("until") if isinstance(data, dict) else None
    if until is not None:
        if not isinstance(until, (int, float)) or until <= time.time():
            clear_pause()
            return False, None
    return True, until
