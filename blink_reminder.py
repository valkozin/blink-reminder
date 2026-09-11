#!/usr/bin/env python3
"""Backwards-compatible launcher: `python blink_reminder.py` still works.

The app itself lives in the `blinkreminder` package - see `python -m blinkreminder --help`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blinkreminder.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
