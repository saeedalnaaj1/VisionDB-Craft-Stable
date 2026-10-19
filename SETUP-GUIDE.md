# VisionDB Craft Stable 3.6.0 - Setup guide

## Start

1. Extract the zip into a **new** folder on Windows 10/11 x64. A short path such as `C:\VisionDB` is best (avoid OneDrive-synced folders).
2. Double-click **Setup.cmd**. If Python 3.12 is missing, Setup downloads and installs it for your user account (signature-checked, no admin rights) and carries on by itself.
3. In the setup window, leave the recommended boxes ticked and press **Start setup**:

| Option | What it does | Default |
|---|---|---|
| Install the app | Private `.venv` in this folder with OpenCV, NumPy, pywebview and PyYAML. A small download, a few minutes | on |
| Quick-launch EXE | Tiny `VisionDB Craft Stable.exe` that just opens the app from the `.venv`. Ready in under a minute | on |
| Desktop / Start Menu shortcut | Shortcuts to that launcher | on |
| Standalone EXE with everything inside | PyInstaller build with Python and all libraries bundled in `dist\VisionDB-Craft-Stable\` (+ ZIP). Runs on a PC with no setup | **off** (optional) |
| Windows installer for the standalone build | Inno Setup wizard; only offered when Inno Setup 6 is installed | off |
| Clean reinstall | Deletes `.venv` and installs everything again (repair) | off |

4. When it says the app is ready, press **Open VisionDB Craft Stable**. Afterwards use the Desktop shortcut, or the launcher EXE in this folder.

Setup is safe to run again at any time: if the requirements have not changed it skips every download and only re-verifies the install. Close the app before re-running Setup. **Cancel** keeps what was downloaded.

### What the launcher EXE is (and is not)

The launcher contains no app code and no libraries. It must stay in this folder next to `launch.py` and `.venv`; it offers to run Setup if they are missing. Moving the whole folder usually keeps it working, but the Desktop shortcut still points at the old place: run Setup again afterwards (tick Clean reinstall if the app no longer opens). Some antivirus products dislike unsigned EXEs; if yours quarantines the launcher, allow it or open the app with `Start.cmd`, which does the same thing.

### Command line (optional)

`Setup.cmd --yes` does the recommended setup without the window. Flags: `--standalone` (also build the standalone EXE), `--installer`, `--no-launcher`, `--no-shortcuts`, `--no-deps`, `--reinstall`, `--console` (answer questions in the console), `--check` (print the PC check as JSON), `--dry-run` (show the steps, change nothing). Details are logged to `setup.log`.

### Uninstall

Delete this folder, the Desktop shortcut and the Start Menu shortcut. Settings are stored separately under `%APPDATA%\VisionDB-Craft` and are not touched; your projects and exports stay wherever you saved them.
