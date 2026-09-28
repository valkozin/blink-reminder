"""Entry point of Blink Reminder.app - see BlinkReminder.spec and scripts/build_app.sh.

Set BLINK_SELFTEST to check a built app without a camera: `1` loads the face mesh on a
blank frame, a path to a photo of a face also checks that all 478 landmarks come back.
"""

from __future__ import annotations

import os
import sys
import types

# An app started from Finder may have no stdio at all, and the app prints to stderr.
for _stream in ("stdout", "stderr"):
    if getattr(sys, _stream) is None:
        setattr(sys, _stream, open(os.devnull, "w"))

# MediaPipe imports matplotlib at the top of its drawing helpers, which this app never
# calls. The bundle leaves matplotlib and Pillow out (~40 MB); empty modules satisfy it.
for _name in ("matplotlib", "matplotlib.pyplot"):
    sys.modules.setdefault(_name, types.ModuleType(_name))


def _self_test(target: str) -> int:
    import cv2
    import numpy as np
    from mediapipe.python.solutions import face_mesh

    mesh = face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True)
    if target == "1":
        mesh.process(np.zeros((360, 480, 3), np.uint8))
        print("self-test ok: face mesh loaded")
        return 0
    image = cv2.imread(target)
    if image is None:
        print(f"self-test: cannot read {target}")
        return 1
    result = mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    count = len(result.multi_face_landmarks[0].landmark) if result.multi_face_landmarks else 0
    print(f"self-test {'ok' if count == 478 else 'FAILED'}: {count} of 478 landmarks")
    return 0 if count == 478 else 1


if __name__ == "__main__":
    if os.environ.get("BLINK_SELFTEST"):
        sys.exit(_self_test(os.environ["BLINK_SELFTEST"]))

    from blinkreminder.__main__ import main

    sys.exit(main())
