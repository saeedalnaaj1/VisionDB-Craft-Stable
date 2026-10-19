# VisionDB Craft Stable 3.6.0 - build notes

## End users

Double-click Setup.cmd (see README.md). It builds the small quick-launch EXE by default and the full bundled EXE only when ticked.

## Manual build helpers

`tools/make_launcher.py --name "VisionDB Craft Stable"` builds the quick-launch EXE; `tools/build_windows.py stable` builds the standalone onedir bundle (Windows x64 + Python 3.12 required; PyInstaller cannot cross-build); `tools/create_installer.py stable --compiler <ISCC.exe>` wraps it in an Inno Setup wizard.

## Source layout

`imagecraft/engine.py`, `models/`, `dataset/` and the shared frontend contain the existing core. The internal Python package name, project suffix, manifest identifiers and custom frontend event names remain `imagecraft` for compatibility. User-facing branding is VisionDB Craft.

`plus_features.py` holds the original detector/inference engine methods, extracted without changing their algorithms. `auto_annotate.py`, `local_ai.py` and their two frontend panels are Plus-only. `edition.py` is a fixed build-time descriptor, not a user environment switch. `core_features.py` supplies the no-model lifecycle for Stable. Lightweight proposal serialization remains in the shared core to preserve existing project data.

`tools/stage_edition.py` copies shared files into an independent tree and physically removes Plus modules, dependency extras, panels, launcher cards and Plus lessons for Stable. Edit shared source, then export the affected edition; no second source fork must be maintained.

## Source exports

Python 3.12 and Node.js 18+ are needed to export (Node parses existing JavaScript tutorial data). Node is not needed to run the application.

```powershell
python tools/stage_edition.py stable --output build/source
python tools/stage_edition.py plus --output build/source
python tools/archive.py build/source/VisionDB-Craft-Stable dist/VisionDB-Craft-Stable.zip
python tools/archive.py build/source/VisionDB-Craft-Plus dist/VisionDB-Craft-Plus.zip
```

Read `PACKAGE-STATUS.json`: source exports explicitly have no bundled runtime or executable. Each has its own README, setup/start scripts, dependencies declared in pyproject, resources, tests and build scripts. Stable may be built independently from its exported folder; that folder cannot recreate Plus files.

## Native Windows executable release

Run on Windows x64 using Python 3.12, Git (Plus) and Node.js 18+. PyInstaller builds for its current operating system, so Linux cannot produce the requested native Windows application with this recipe. Use a fresh environment for each edition. WebView2 Runtime is an explicit system prerequisite.

```powershell
py -3.12 -m venv .build-stable
.build-stable\Scripts\python.exe -m pip install pyinstaller==6.22.3
.build-stable\Scripts\python.exe tools/build_windows.py stable

py -3.12 -m venv .build-plus
.build-plus\Scripts\python.exe -m pip install pyinstaller==6.22.3
.build-plus\Scripts\python.exe tools/build_windows.py plus --with-ai
```

Each command stages its edition, installs dependencies into its current interpreter, builds in **onedir** mode, runs the frozen executable's headless self-test, and creates `dist/VisionDB-Craft-<Edition>.zip`. The release ZIP contains `VisionDB-Craft-<Edition>.exe`, an adjacent `_internal` directory with Python/dependencies/UI assets, an independent source copy, README, licenses, a package-status file and the startup-test report. AI weights are not collected. Plus runtime libraries are large even without weights; they remain separate files rather than one enormous executable. Omitting `--with-ai` produces a core-runtime Plus build that reports missing AI dependencies; use the flag for the full release.

The workflow `.github/workflows/ci.yml` provides separate Windows matrix jobs. It has not been executed against a remote repository in this task. A staged Stable source export must use its local build command (the master workflow describes the shared repository).

## Reproducibility and checks

Core dependencies are pinned to the versions used for verification. AI requirements preserve existing compatibility ranges and include rtmlib/MobileSAM that the original extra omitted. AI upstream dependencies and the MobileSAM Git ref are not fully locked, so an AI build is reproducible as a process, **not guaranteed byte-identical across dates**. `build-dependencies.txt` records resolved versions for a successful Windows build. Freeze the full AI environment and a reviewed MobileSAM commit before public binary release.

Source archive entries have fixed timestamps and sorted names. `SHA256SUMS.json` records staged file hashes. Rebuild it whenever staged files are edited. Source packages contain no model weights or development virtual environments.

```powershell
python -m pip install ".[dev]"
python -m pytest -q
python launch.py --self-test --report source-smoke.json
```

Run the same core suite in the Stable export. Native executable self-tests verify backend startup and packaged resources; they do not replace interactive Windows testing. Follow TESTING.md before calling a release ready.

## Branding

Vector mark: camera/annotation frame surrounding an eye. Ink `#122333`, mint `#2dd4bf`, pale text `#f0f6fa`. The same logo is used by both editions; edition labels distinguish them. Assets in `imagecraft/ui/assets`: SVG mark and wordmark, PNG previews, multi-size ICO. Regenerate with `python tools/make_branding.py` after installing `cairosvg` and `Pillow`; SVG conversion needs Cairo. These are asset-authoring dependencies, not application dependencies.

## Updates and data

Never update by deleting user-selected directories. Unzip releases into a new folder and keep project files/settings/model caches outside it. The supplied build scripts operate on staging/build output only, not user project directories. Preserve existing MIT LICENSE. Collect third-party license texts and review model terms before redistributing a frozen binary.
