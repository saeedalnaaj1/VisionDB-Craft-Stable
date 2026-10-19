"""Quick-launch EXE: opens the app from the .venv that sits next to this file.

Tiny on purpose - it contains no app code and no libraries.  Keep the EXE in the
app folder (next to launch.py and .venv).  Built by tools/make_launcher.py.
"""
import ctypes
import os
import subprocess
import sys
from pathlib import Path

MB_ERROR, MB_YESNO_QUESTION, IDYES = 0x10, 0x24, 6
DETACHED_PROCESS = 0x00000008


def app_folder() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def title() -> str:
    return Path(sys.executable).stem if getattr(sys, "frozen", False) else "VisionDB Craft"


def box(text: str, flags: int) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, title(), flags)


def main() -> int:
    root = app_folder()
    python = root / ".venv" / "Scripts" / "pythonw.exe"
    entry = root / "launch.py"
    setup = root / "Setup.cmd"
    if "--check" in sys.argv:                       # used by Setup to verify this EXE
        return 0 if python.is_file() and entry.is_file() else 2
    if not entry.is_file():
        box(f"launch.py was not found.\n\nKeep this EXE inside the app folder it was created in:\n{root}", MB_ERROR)
        return 3
    if not python.is_file():
        if setup.is_file() and box("The app is not set up on this PC yet.\n\nRun Setup now?", MB_YESNO_QUESTION) == IDYES:
            os.startfile(str(setup))
        return 4
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PYTHONHOME", "PYTHONPATH") and not k.startswith("_PYI")}
    process = subprocess.Popen([str(python), str(entry)], cwd=str(root), env=env, creationflags=DETACHED_PROCESS,
                               close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = process.wait(timeout=5)              # still running after 5 s = started fine
    except subprocess.TimeoutExpired:
        return 0
    if code not in (0, 1):                          # 1 = launch.py already showed its own error box
        box(f"{title()} closed right after starting (error {code}).\n\n"
            f"Run Setup.cmd and tick 'Clean reinstall' to repair the installation.", MB_ERROR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
