"""Entry point: `python -m blinkreminder` (menu bar) or `--headless` (plain terminal)."""

from __future__ import annotations

import argparse
import fcntl
import logging
import logging.handlers
import os
import signal
import sys
import time

# Quiet down mediapipe/absl before anything imports them.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ABSL_LOGGING_VERBOSITY", "-1")
# We request camera access ourselves (see system.ensure_camera_access), on the main thread.
os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

from typing import Callable, Optional

import numpy as np

from . import APP_NAME, __version__, stats
from .config import AVAILABLE_SOUNDS, CONFIG_DIR, CONFIG_PATH, LOG_DIR, LOG_PATH, Config
from .i18n import set_language

log = logging.getLogger("blinkreminder")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                LOG_PATH, maxBytes=512_000, backupCount=2, encoding="utf-8"
            )
        )
    except OSError:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


_lock_handle = None


def _claim_single_instance() -> bool:
    """Keep a flock for the life of the process, so a second copy bows out."""
    global _lock_handle
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _lock_handle = open(CONFIG_DIR / "running.lock", "w")
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="blinkreminder",
        description=f"{APP_NAME} - a gentle nudge to blink while you work.",
    )
    parser.add_argument("--headless", action="store_true", help="run without the menu bar icon")
    parser.add_argument("--status", action="store_true", help="print what the running app is doing")
    parser.add_argument("--quit", action="store_true", dest="quit_app", help="stop the running app")
    parser.add_argument(
        "--pause",
        nargs="?",
        type=float,
        const=0.0,
        metavar="MINUTES",
        help="pause the running app, optionally for a number of minutes",
    )
    parser.add_argument("--resume", action="store_true", help="resume the running app")
    parser.add_argument("--start", action="store_true", help="start the background app again")
    parser.add_argument("--interval", type=float, help="seconds without a blink before reminding")
    parser.add_argument("--sound", choices=AVAILABLE_SOUNDS, help="reminder sound")
    parser.add_argument("--no-sound", action="store_true", help="mute the reminder sound")
    parser.add_argument("--no-hud", action="store_true", help="hide the on-screen hint")
    parser.add_argument("--camera", type=int, help="camera index (default 0)")
    parser.add_argument("--save", action="store_true", help="persist the options given above")
    parser.add_argument("--install-autostart", action="store_true", help="start at login and exit")
    parser.add_argument("--uninstall-autostart", action="store_true", help="remove the login item and exit")
    parser.add_argument("--reset-config", action="store_true", help="restore default settings and exit")
    parser.add_argument(
        "--diagnose",
        nargs="?",
        type=int,
        const=20,
        metavar="SECONDS",
        help="check the camera and print live detection numbers, then exit",
    )
    parser.add_argument(
        "--record",
        metavar="FILE.csv",
        help="with --diagnose: write per-frame detection data for later analysis",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


def _run_control(args: argparse.Namespace) -> Optional[int]:
    """Commands that talk to an already-running app instead of starting one."""
    from . import control

    if args.status:
        running = control.is_running()
        state = control.read_state()
        if not running:
            print(f"{APP_NAME} is not running.")
            return 0
        if state is None:
            print(f"{APP_NAME} is running, but has not reported its state yet.")
            return 0
        age = time.time() - state.get("updated", 0)
        rate = state.get("rate")
        print(f"{APP_NAME}: {'paused' if state.get('paused') else state.get('state', 'unknown')}")
        print(f"  blinks this session : {state.get('blinks', 0)}"
              + (f"  ({rate:g}/min)" if rate else ""))
        print(f"  reminders sent      : {state.get('reminders', 0)}")
        print(f"  signal quality      : {state.get('signal_quality', 'unknown')}")
        print(f"  seconds since blink : {state.get('seconds_since_blink', 0)}"
              f" of {state.get('interval', 0):g}")
        if age > 30:
            print(f"  (this reading is {age:.0f}s old)")
        return 0

    if args.start:
        from . import autostart

        if control.is_running():
            print(f"{APP_NAME} is already running.")
            return 0
        if not autostart.is_supported() or not autostart.start_agent():
            print(
                "No login item is installed, so there is no background app to start.\n"
                "Install one with --install-autostart, or run blink-reminder with no "
                "arguments to keep it in this terminal.",
                file=sys.stderr,
            )
            return 1
        print(f"{APP_NAME} started.")
        return 0

    command = (
        "quit" if args.quit_app else
        "pause" if args.pause is not None else
        "resume" if args.resume else None
    )
    if command is None:
        return None

    if not control.is_running():
        print(f"{APP_NAME} is not running.", file=sys.stderr)
        return 1
    minutes = args.pause if command == "pause" and args.pause else None
    control.send(command, minutes)
    if command == "pause":
        print("Paused" + (f" for {minutes:g} minutes." if minutes else "."))
    elif command == "resume":
        print("Resumed.")
    else:
        print("Stopping. It will start again at your next login"
              " (use --uninstall-autostart to prevent that).")
    return 0


def _apply_overrides(config: Config, args: argparse.Namespace) -> None:
    if args.interval is not None:
        config.interval = args.interval
        config.min_reminder_gap = max(20.0, args.interval * 2.0)
    if args.sound:
        config.sound_name = args.sound
        config.sound_enabled = True
    if args.no_sound:
        config.sound_enabled = False
    if args.no_hud:
        config.hud_enabled = False
    if args.camera is not None:
        config.camera_index = args.camera
    config.clamp()


def _run_headless(config: Config) -> int:
    from . import system
    from .alerts import Alerts
    from .detector import BlinkDetector

    if not system.ensure_camera_access():
        print(
            "Camera access is denied. Allow it in System Settings > Privacy & Security > Camera.",
            file=sys.stderr,
        )
        return 1

    alerts = Alerts(config)
    alerts.config.hud_enabled = False  # no AppKit run loop here

    def on_reminder() -> None:
        print(f"[{time.strftime('%H:%M:%S')}] blink!", flush=True)
        alerts.play_sound()

    detector = BlinkDetector(config, on_reminder=on_reminder, on_error=lambda kind: log.error("camera unavailable"))
    detector.start()
    print(f"{APP_NAME} {__version__} - reminding after {config.interval:g}s without a blink. Ctrl+C to stop.")

    stop = False

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    from . import control

    while not stop:
        time.sleep(0.5)
        pending = control.take()
        if pending is None:
            continue
        command, argument = pending
        if command == "quit":
            stop = True
        elif command == "pause":
            detector.pause(argument * 60 if argument else None)
        elif command == "resume":
            detector.resume()
        elif command == "toggle":
            detector.toggle_pause()
    detector.stop()
    print("stopped.")
    return 0


def _run_diagnostics(config: Config, seconds: int, record: str | None = None) -> int:
    """Live numbers from the detector - the quickest way to see whether it sees you."""
    from . import system
    from .detector import BlinkDetector, State

    print(f"camera authorisation status: {system.camera_authorization()} (3 = granted)")
    if not system.ensure_camera_access():
        print("Camera access denied - allow it in System Settings > Privacy & Security > Camera.")
        return 1

    reminders: list[float] = []
    trace = None
    recorder: "Callable[[dict], None] | None" = None
    if record:
        import csv

        trace = open(record, "w", newline="", encoding="utf-8")
        state = {"writer": None}

        def write_row(row: dict) -> None:
            """Columns come from the first frame that saw a face, so the richer
            landmark features appear without being listed in two places."""
            writer = state["writer"]
            if writer is None:
                if not row.get("face"):
                    return
                writer = state["writer"] = csv.DictWriter(trace, fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row)

        recorder = write_row

    detector = BlinkDetector(
        config,
        on_reminder=lambda: reminders.append(time.time()),
        on_frame=recorder,
    )
    detector.start()
    print(f"watching for {seconds}s - blink a few times, then look away for a moment\n")
    print(f"{'time':>5}  {'state':<9} {'blinks':>6} {'rate':>6}  {'EAR baseline':>12} {'threshold':>9}")
    started = time.time()
    try:
        while time.time() - started < seconds:
            time.sleep(1.0)
            snap = detector.snapshot()
            baseline = (
                float(np.median(detector._ear_history)) if detector._ear_history else float("nan")
            )
            print(
                f"{time.time() - started:5.0f}  {snap.state:<9} {snap.blinks:>6} "
                f"{(snap.rate if snap.rate is not None else float('nan')):>6.1f}  "
                f"{baseline:>12.3f} {detector._threshold():>9.3f}"
            )
    except KeyboardInterrupt:
        pass
    finally:
        snap = detector.snapshot()
        detector.stop()
        if trace is not None:
            trace.close()
            print(f"per-frame data written to {record}")

    print(
        f"\n{snap.blinks} blinks and {len(reminders)} reminders in "
        f"{stats.format_duration(snap.active_seconds)} of face time."
    )
    if snap.state == State.ERROR:
        print("The camera could not be opened - see the troubleshooting section in the README.")
        return 1
    if snap.active_seconds < 3:
        print("No face was detected. Check the lighting and that you are inside the frame.")
        return 1
    return 0


def _run_menubar(config: Config) -> int:
    try:
        import rumps  # noqa: F401  (checked here so the fallback below is honest)
    except ImportError:
        log.error("rumps is not installed - falling back to headless mode")
        return _run_headless(config)

    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    from . import system
    from .menubar import BlinkReminderApp

    # Menu bar only: no Dock icon, no app switcher entry.
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    granted = system.ensure_camera_access()
    app = BlinkReminderApp(config, camera_granted=granted)
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.verbose)

    control_result = _run_control(args)
    if control_result is not None:
        return control_result

    if args.reset_config:
        CONFIG_PATH.unlink(missing_ok=True)
        print(f"settings reset ({CONFIG_PATH})")
        return 0

    if args.install_autostart or args.uninstall_autostart:
        from . import autostart

        if not autostart.is_supported():
            print("start at login is only implemented for macOS", file=sys.stderr)
            return 1
        if args.install_autostart:
            autostart.enable()
            print(f"login item installed: {autostart.PLIST_PATH}")
        else:
            autostart.disable()
            print("login item removed")
        return 0

    if not _claim_single_instance():
        print(f"{APP_NAME} is already running.", file=sys.stderr)
        return 0

    config = Config.load()
    _apply_overrides(config, args)
    set_language(config.language)
    if args.save:
        config.save()
        print(f"settings saved to {CONFIG_PATH}")

    if args.diagnose:
        return _run_diagnostics(config, args.diagnose, args.record)

    if args.headless or sys.platform != "darwin":
        return _run_headless(config)
    return _run_menubar(config)


if __name__ == "__main__":
    sys.exit(main())
