# VisionDB Craft Stable 3.6.0 - testing notes

The automated suite passes in the build environment (165 passed, 6 expected skips). Run them with `python -m pytest -q` inside the project's `.venv`. `python launch.py --self-test --report smoke.json` starts the backend headless. The setup engine tests record the commands instead of running them, so they work on any OS.

## Acceptance checklist on a real Windows 10/11 PC

1. Setup.cmd opens the wizard even without Python 3.12 installed, and the Start button is visible at your screen size and display scaling.
2. The default run creates `VisionDB Craft Stable.exe` and the shortcuts, and the launcher opens the app.
3. A second Setup run skips the downloads. Cancelling mid-way and re-running resumes.
4. The optional standalone EXE builds, passes its own startup self-test and opens by itself.
5. Annotate, Transform, Augment, History and dataset export work on your own images.

Not verified in the build environment: items 1-5 (no Windows hardware was available).
