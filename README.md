# Blink Reminder 👁️

A quiet macOS menu bar app that watches your blink rate through the webcam and nudges you
when you forget to blink. Built for people who sit in front of a screen all day: it runs in
the background, reminds you over *any* app — including full-screen ones — and gets out of the
way when you step away from the desk.

Everything happens locally. No frames, no statistics and nothing else ever leaves the machine.

## What it does

- **Detects real blinks**, not a fixed timer, using MediaPipe Face Mesh and the Eye Aspect Ratio.
  The threshold adapts to *your* eyes — glasses, lighting and distance to the screen are
  calibrated away within the first few seconds.
- **Reminds you gently**: a short system sound (default: `Tink`, at 35% volume) plus a small
  translucent hint that floats above every window and every Space, full-screen apps included.
  Never more than twice a minute, however hard you stare.
- **Pause whenever you want** — a toggle in the menu, or a timed pause of 15/30/60 minutes.
- **Pauses itself** when the screen is locked, when the display sleeps, and — optionally — when
  the keyboard has been idle for a while.
- **Stands by when you leave.** If your face is out of view for a minute and a half, the camera
  is released (green light off, no CPU) and only reopened when you are back.
- **Starts at login** via a launchd agent, from the menu or the command line.
- Interface is English or Russian, picked from the system language.

Measured cost on an M1 Pro: about 15% of a single core (≈1.5% of the machine) and 280 MB while
it is actually watching you — roughly half of that is the camera pipeline itself, which is why
the app releases the camera the moment you leave the desk. Frames are analysed 10 times per
second at 480×360 and nothing is rendered.

## Install

Requires macOS and Python 3.9–3.12 (MediaPipe has no 3.13+ wheels yet). If you have neither,
`install.sh` fetches a private interpreter through [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/valkozin/blink-reminder.git
cd blink-reminder
./install.sh
```

The app is installed into `~/.local/share/blink-reminder/venv`, deliberately outside the source
folder, so it keeps working if you move, rename or cloud-sync the repository.

The installer offers to register the login item and start the app straight away — say yes.
macOS then asks for camera access; click **Allow**. An eye appears in the menu bar.

> **Why that order matters.** Camera permission on macOS is granted to whatever process asks
> for it. Letting the launchd agent ask means the answer is recorded for exactly the process
> that will run at every login. If you start the app from a terminal instead, the permission is
> recorded for your terminal, and the login agent will have to ask a second time later.

To remove everything again: `./uninstall.sh`. To keep the app but drop the login item, untick
**Start at login** in the menu (or run `blink-reminder --uninstall-autostart`).

## Using it

Click the eye in the menu bar:

| Menu item | What it does |
|---|---|
| *Watching your blinks* | Current state and the blink rate over the last minute (15–20/min is healthy) |
| **Pause / Resume** | Stops the reminders and closes the camera |
| **Pause for…** | 15, 30 or 60 minutes, then it resumes by itself |
| **Remind after…** | 6–30 seconds without a blink (default: 12) |
| **Sound** | Eight short system sounds, volume, or silent |
| **Show on-screen hint** | The floating hint, on or off |
| **Detection sensitivity** | Raise it if light blinks are missed, lower it if squinting is counted |
| **Pause when keyboard is idle** | Off by default — reading without touching the keyboard still counts as screen time |
| **Pause when screen is locked** | On by default |
| **Start at login** | Installs/removes the launchd agent |
| **Today’s statistics…** | Screen time, blinks, average rate, reminders |

Menu bar icon: 👁 watching · ⏸ paused · 💤 standing by · ⚠️ camera problem.

### Command line

```bash
blink-reminder                      # menu bar app
blink-reminder --headless           # terminal only, no menu bar
blink-reminder --interval 15 --sound Purr --save
blink-reminder --install-autostart  # or --uninstall-autostart
blink-reminder --reset-config
blink-reminder --diagnose 20         # live detection numbers, to check the camera
```

Settings live in `~/Library/Application Support/BlinkReminder/config.json` and hold a few knobs
that are not in the menu (`camera_index`, `fps`, `absence_timeout`, `hud_position`, `language`).
Lowering `fps` saves less than you would hope (10 → 5 fps takes 15% of a core down to 11%) and
costs a lot of accuracy, because a blink lasts about 150 ms. Do not set the frame size below
480×360 either — blinks stop being resolved.
Logs go to `~/Library/Logs/BlinkReminder.log`.

## How it works

For each eye, six landmarks give the **Eye Aspect Ratio** — eye height over eye width. The app
keeps a rolling median of your open-eye EAR over the last minute; a blink is a dip below
`sensitivity × baseline` that lasts less than 0.7 s, with a little hysteresis so a borderline
frame cannot flicker. Longer closures still reset the timer (closed eyes are moist eyes) but are
not counted as blinks. If no face is visible the countdown is suspended, so you are never
reminded to blink at an empty chair.

## Troubleshooting

**"Camera unavailable" or nothing is detected.** Another app may be holding the camera (Zoom,
Teams, Photo Booth). Otherwise check System Settings › Privacy & Security › Camera.

**The reminder never fires.** Your blink rate is probably fine. Lower *Remind after…* to 6
seconds to confirm the detection works, then set it back.

**Blinks are missed** (rate reads much lower than it feels): raise the detection sensitivity, and
make sure your face is reasonably lit and inside the frame.

**⚠️ in the menu bar after login.** The camera permission was denied for the background agent.
Open System Settings › Privacy & Security › Camera and allow the `python` entry belonging to
`~/.local/share/blink-reminder/venv`, then restart the app:
`launchctl kickstart -k gui/$(id -u)/com.valkozin.blinkreminder`.

**MediaPipe fails to install.** You are on Python 3.13+. Install Python 3.12 (`brew install
python@3.12`) or let `install.sh` use uv, which downloads a matching interpreter itself.

## Development

```bash
VENV=~/.local/share/blink-reminder/venv          # created by ./install.sh
$VENV/bin/python tests/test_detector.py          # camera and MediaPipe are stubbed out
$VENV/bin/python -m blinkreminder --verbose      # run straight from this checkout
```

Re-run `./install.sh` to push local changes into the installed copy.

`blinkreminder/` holds the app: `detector.py` (camera loop and blink logic), `alerts.py` (sound
and the floating hint), `menubar.py` (the UI), `autostart.py` (launchd agent), `config.py`,
`stats.py`, `system.py`, `i18n.py`.

A separate browser demo of the same idea lives in `src/` (React + MediaPipe Tasks) — see
[LOCAL_SETUP.md](LOCAL_SETUP.md). It is a toy: the menu bar app is the one to use daily.

## License

MIT — see [LICENSE](LICENSE).
