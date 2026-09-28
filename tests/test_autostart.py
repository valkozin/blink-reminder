"""The login item: launchd has to be told exactly how to start whichever copy is installed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import blinkreminder.autostart as autostart


class _As:
    """Pretend, for one test, to be a given interpreter - or Blink Reminder.app itself."""

    def __init__(self, executable: str, frozen: bool) -> None:
        self.executable = executable
        self.frozen = frozen

    def __enter__(self):
        self._saved = (sys.executable, getattr(sys, "frozen", None))
        sys.executable = self.executable
        if self.frozen:
            sys.frozen = True
        elif hasattr(sys, "frozen"):
            del sys.frozen

    def __exit__(self, *exc):
        sys.executable, frozen = self._saved
        if frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = frozen


def test_a_python_install_is_started_as_a_module():
    with _As("/venv/bin/python3", frozen=False):
        args = autostart._plist()["ProgramArguments"]
    assert args == ["/venv/bin/python3", "-m", "blinkreminder"], args


def test_the_app_is_started_as_itself():
    binary = "/Applications/Blink Reminder.app/Contents/MacOS/BlinkReminder"
    with _As(binary, frozen=True):
        plist = autostart._plist()
    # The app binary has no -m: handed one, argparse would refuse to start at all.
    assert plist["ProgramArguments"] == [binary], plist["ProgramArguments"]
    # Nor does it live in site-packages, which must not be mistaken for a source checkout.
    assert "EnvironmentVariables" not in plist, "the app needs no PYTHONPATH"
    assert "WorkingDirectory" not in plist


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
