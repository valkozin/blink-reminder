"""The terminal control channel: it is the only way in when the menu bar icon is hidden."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import blinkreminder.control as control


def _isolate():
    """Point the module at a throwaway directory."""
    tmp = Path(tempfile.mkdtemp())
    control.CONFIG_DIR = tmp
    control.COMMAND_PATH = tmp / "command"
    control.STATE_PATH = tmp / "state.json"
    control.LOCK_PATH = tmp / "running.lock"
    return tmp


def test_a_command_survives_the_trip_and_is_consumed_once():
    _isolate()
    assert control.take() is None, "nothing pending to begin with"

    control.send("pause", 15)
    assert control.take() == ("pause", 15.0)
    assert control.take() is None, "a command must not be acted on twice"


def test_commands_without_an_argument():
    _isolate()
    for command in ("quit", "resume", "toggle"):
        control.send(command)
        assert control.take() == (command, None)


def test_nonsense_is_refused_at_both_ends():
    tmp = _isolate()
    try:
        control.send("self-destruct")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown commands must not be sendable")

    (tmp / "command").write_text("self-destruct", encoding="utf-8")
    assert control.take() is None, "and must not be actionable either"
    assert not (tmp / "command").exists(), "the bad command is cleared, not left to repeat"

    (tmp / "command").write_text("pause soon", encoding="utf-8")
    assert control.take() == ("pause", None), "a bad argument falls back to an open-ended pause"


def test_is_running_follows_the_instance_lock():
    import fcntl

    tmp = _isolate()
    assert control.is_running() is False

    handle = open(tmp / "running.lock", "w")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert control.is_running() is True, "the lock is how a second copy knows to bow out"
    finally:
        handle.close()
    assert control.is_running() is False


def test_a_pause_is_remembered_across_a_restart():
    import time

    _isolate()
    assert control.load_pause() == (False, None)

    control.save_pause(None)                       # "until I say otherwise"
    assert control.load_pause() == (True, None)

    deadline = time.time() + 600
    control.save_pause(deadline)
    paused, until = control.load_pause()
    assert paused and abs(until - deadline) < 1

    control.clear_pause()
    assert control.load_pause() == (False, None)


def test_a_pause_that_has_already_expired_is_dropped():
    import time

    _isolate()
    control.save_pause(time.time() - 1)
    assert control.load_pause() == (False, None), "waking up should not restore a lapsed pause"
    assert not control.PAUSE_PATH.exists(), "and the stale file is cleaned up"


def test_state_round_trip():
    _isolate()
    assert control.read_state() is None
    control.publish({"state": "active", "blinks": 12})
    state = control.read_state()
    assert state["state"] == "active" and state["blinks"] == 12
    assert "updated" in state, "--status needs to know how stale the reading is"


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
        else:
            print(f"ok   {name}")
    print("all tests passed" if not failures else f"{failures} test(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
