"""Settings: clamping and the upgrade path for retuned detection defaults."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import blinkreminder.config as config_module
from blinkreminder.config import Config


def _with_config_file(contents: dict):
    """Point the module at a throwaway config file holding `contents`."""
    tmp = Path(tempfile.mkdtemp()) / "config.json"
    tmp.write_text(json.dumps(contents), encoding="utf-8")
    config_module.CONFIG_PATH = tmp
    config_module.CONFIG_DIR = tmp.parent
    return tmp


def test_an_unversioned_file_gets_the_new_detection_defaults():
    """Version 1 files were written before fps and sensitivity were retuned."""
    path = _with_config_file({"fps": 10, "sensitivity": 0.78, "interval": 6.0, "sound_name": "Purr"})
    cfg = Config.load()
    assert cfg.fps == Config().fps
    assert cfg.sensitivity == Config().sensitivity
    assert cfg.interval == 6.0, "a deliberate choice must survive the upgrade"
    assert cfg.sound_name == "Purr"
    assert json.loads(path.read_text())["schema_version"] == config_module.SCHEMA_VERSION


def test_the_old_menu_bar_rate_toggle_is_carried_over():
    _with_config_file({"show_rate_in_menubar": True})
    assert Config.load().menubar_extra == "rate"


def test_menu_bar_extra_rejects_nonsense():
    cfg = Config()
    cfg.menubar_extra = "fireworks"
    cfg.clamp()
    assert cfg.menubar_extra == "none"


def test_a_hand_picked_sensitivity_is_kept():
    _with_config_file({"fps": 10, "sensitivity": 0.70})
    assert Config.load().sensitivity == 0.70


def test_a_current_file_is_left_alone():
    _with_config_file(
        {"schema_version": config_module.SCHEMA_VERSION, "fps": 8, "sensitivity": 0.78}
    )
    cfg = Config.load()
    assert cfg.fps == 8 and cfg.sensitivity == 0.78


def test_clamping_rejects_nonsense():
    cfg = Config()
    cfg.interval, cfg.fps, cfg.sensitivity, cfg.sound_name = -5, 900, 3.0, "Kazoo"
    cfg.clamp()
    assert cfg.interval == 3.0 and cfg.fps == 30
    assert cfg.sensitivity == 0.92 and cfg.sound_name == "Tink"


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
