"""VisionDB Craft setup engine (Windows) and its command-line front end.

The graphical wizard (setup_gui.py) and the unattended command line both drive
SetupEngine, so they always do exactly the same thing.  Standard library only:
this runs on the plain Python 3.12 that Setup.cmd finds or installs.

What Setup can do (every part is optional and re-runnable):
  * install     - private .venv with the app and, for Plus, the NVIDIA GPU stack
  * launcher    - a SMALL "VisionDB Craft Plus.exe" that just opens the app
  * shortcuts   - Desktop / Start Menu shortcuts to the launcher
  * standalone  - OPTIONAL big EXE with Python and every library bundled inside
  * installer   - OPTIONAL Inno Setup wizard for the standalone build
"""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
SETUP_VERSION = "4.0"            # bump to force every existing install to be re-verified
STAMP_NAME = "visiondb-setup.json"
CREATE_NO_WINDOW = 0x08000000
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
PROGRESS_RE = re.compile(r"^Progress (\d+) of (\d+)")

# Rough disk needs in GB (venv + pip cache, bundle, installer output).
NEED_GB = {"deps_plus": 14.0, "deps_stable": 1.5, "launcher": 0.4, "standalone_plus": 9.0,
           "standalone_stable": 1.2, "installer_plus": 5.0, "installer_stable": 0.6}

ERROR_HINTS = [
    (r"WinError 5\b|Access is denied|WinError 32|being used by another process|PermissionError",
     "A file is in use. Close VisionDB Craft (and anything else opened from this folder), then press Try again."),
    (r"No space left|Errno 28|not enough space",
     "The drive is full. Free some disk space (about 15 GB for the full install) and try again."),
    (r"WinError 206|filename or extension is too long|Filename too long|path too long",
     "The folder path is too long for Windows. Move this folder next to the drive root "
     "(for example C:\\VisionDB) and run Setup again."),
    (r"ConnectionError|Read timed out|ReadTimeout|Max retries exceeded|getaddrinfo failed|"
     r"Temporary failure in name resolution|SSLError|ProxyError|Connection reset|IncompleteRead|"
     r"Connection broken",
     "A download was interrupted. Check the internet connection (VPN, proxy, firewall), then press "
     "Try again - files that were already downloaded are reused."),
    (r"No matching distribution found|Could not find a version that satisfies",
     "pip could not find a matching package. This needs 64-bit Python 3.12 and access to pypi.org, "
     "download.pytorch.org and github.com."),
]


# --------------------------------------------------------------------------- helpers
def is_windows() -> bool:
    return sys.platform == "win32"


def read_edition(root: Path = ROOT) -> tuple[str, str]:
    """(EDITION, APP_TITLE) read without importing the app (importing would load torch)."""
    edition, title = "Plus", ""
    try:
        tree = ast.parse((root / "imagecraft/edition.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("EDITION", "APP_TITLE"):
                    value = ast.literal_eval(node.value)
                    if name == "EDITION":
                        edition = value
                    else:
                        title = value
    except (OSError, SyntaxError, ValueError):
        pass
    return edition, title or f"VisionDB Craft {edition}"


def is_hai(title: str) -> bool:
    """h.ai branded editions use their own icon, logo, palette and file names."""
    return title.lower().startswith("h.ai")


def venv_python(root: Path = ROOT) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if is_windows() else "bin/python")


def base_python() -> str:
    """python.exe, even when we were started by pythonw.exe (a venv should be made from python.exe)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.with_name("python.exe")).is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def deps_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256(SETUP_VERSION.encode())
    for name in ("pyproject.toml", "constraints-gpu.txt"):
        path = root / name
        digest.update(path.read_bytes() if path.is_file() else b"-")
    vendor = root / "vendor"
    if vendor.is_dir():
        for wheel in sorted(vendor.glob("*.whl")):
            digest.update(wheel.name.encode() + str(wheel.stat().st_size).encode())
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def deps_state(root: Path = ROOT) -> str:
    """'missing' (no .venv), 'current' (installed by this setup version) or 'outdated'."""
    if not venv_python(root).exists():
        return "missing"
    stamp = _read_json(root / ".venv" / STAMP_NAME)
    return "current" if stamp.get("fingerprint") == deps_fingerprint(root) else "outdated"


def webview2_installed() -> bool:
    if not is_windows():
        return True
    import winreg
    locations = [(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
                 (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
                 (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}")]
    for hive, key in locations:
        try:
            with winreg.OpenKey(hive, key) as handle:
                version = winreg.QueryValueEx(handle, "pv")[0]
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def detect_nvidia() -> dict[str, Any] | None:
    candidates = [shutil.which("nvidia-smi")]
    for base in (os.environ.get("SystemRoot", r"C:\Windows"), os.environ.get("ProgramFiles", r"C:\Program Files")):
        candidates.append(str(Path(base) / "System32/nvidia-smi.exe"))
        candidates.append(str(Path(base) / "NVIDIA Corporation/NVSMI/nvidia-smi.exe"))
    exe = next((c for c in candidates if c and Path(c).is_file()), None)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
                             creationflags=CREATE_NO_WINDOW if is_windows() else 0).stdout
        name, driver, vram = [part.strip() for part in out.strip().splitlines()[0].split(",")][:3]
        return {"name": name, "driver": driver, "vram_mb": int(float(vram))}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def find_inno() -> str | None:
    found = shutil.which("ISCC.exe")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")):
        candidate = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if base and candidate.is_file():
            return str(candidate)
    return None


# --------------------------------------------------------------------------- options / checks
@dataclass
class Options:
    install_deps: bool = True        # create .venv and install everything
    reinstall: bool = False          # wipe .venv first (repair)
    launcher: bool = True            # small quick-launch EXE
    desktop_shortcut: bool = True
    start_menu_shortcut: bool = True
    standalone: bool = False         # OPTIONAL: big EXE with everything inside
    installer: bool = False          # OPTIONAL: Inno Setup wizard for the standalone build
    dry_run: bool = False            # print what would happen; touch nothing


def estimate_gb(opts: Options, state: str, edition: str = "Plus") -> float:
    kind = "plus" if edition == "Plus" else "stable"
    need = 0.0
    if opts.install_deps and (opts.reinstall or state != "current"):
        need += NEED_GB[f"deps_{kind}"]
    if opts.launcher:
        need += NEED_GB["launcher"]
    if opts.standalone:
        need += NEED_GB[f"standalone_{kind}"]
        if opts.installer:
            need += NEED_GB[f"installer_{kind}"]
    return need


def preflight(root: Path = ROOT, dry_run: bool = False) -> dict[str, Any]:
    """Look at the PC. Returns {'checks': [...], 'free_gb', 'state', 'inno', 'blocking'}.

    status: ok | warn | fail | info.  Only 'fail' blocks the Install button.
    """
    edition, title = read_edition(root)
    checks: list[dict[str, str]] = []

    def add(key: str, status: str, label: str, detail: str = "") -> None:
        checks.append({"key": key, "status": status, "label": label, "detail": detail})

    # Windows 10/11 x64
    if is_windows():
        import platform
        machine = platform.machine().upper()
        build = getattr(sys, "getwindowsversion", lambda: None)()
        if machine not in ("AMD64", "X86_64"):
            add("os", "fail", "Windows 10/11 64-bit", f"This PC is {machine}; a 64-bit (x64) Windows is required.")
        elif build and build.major < 10:
            add("os", "fail", "Windows 10/11 64-bit", "Windows 10 or newer is required.")
        else:
            add("os", "ok", "Windows 10/11 64-bit", platform.platform(terse=True))
    elif dry_run:
        add("os", "info", "Windows 10/11 64-bit", "Dry run on a non-Windows system: nothing will be installed.")
    else:
        add("os", "fail", "Windows 10/11 64-bit", "This setup only runs on Windows 10/11 x64.")

    # Python 3.12
    ver = sys.version_info
    if ver[:2] == (3, 12):
        add("python", "ok", "Python 3.12", f"{ver.major}.{ver.minor}.{ver.micro}")
    else:
        add("python", "fail", "Python 3.12",
            f"Found {ver.major}.{ver.minor}. Start Setup with Setup.cmd - it installs the right Python for you.")

    # Folder: writable + sensible path
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".write-test-", delete=True):
            pass
        writable = True
    except OSError:
        writable = False
    path_text = str(root)
    notes = []
    if not writable:
        add("folder", "fail", "App folder is writable", f"Cannot write to {path_text}. Extract the zip to a normal folder such as C:\\VisionDB.")
    else:
        if len(path_text) > 70:
            notes.append("path is long - Windows may hit its 260-character limit; C:\\VisionDB is safer")
        if not path_text.isascii():
            notes.append("path has non-English characters - plain ASCII is safer")
        if "onedrive" in path_text.lower():
            notes.append("folder is inside OneDrive - it will try to sync ~10 GB; prefer a folder outside it")
        if "program files" in path_text.lower():
            notes.append("Program Files needs admin rights; prefer another folder")
        add("folder", "warn" if notes else "ok", "App folder", "; ".join(notes) if notes else path_text)

    # Disk space
    try:
        free_gb = shutil.disk_usage(root).free / 1024 ** 3
    except OSError:
        free_gb = 0.0
    add("disk", "ok" if free_gb >= 15 else "warn", "Free disk space", f"{free_gb:.0f} GB free on this drive")

    # WebView2 (the window the app draws in)
    if webview2_installed():
        add("webview2", "ok", "Microsoft WebView2", "Installed")
    else:
        add("webview2", "warn", "Microsoft WebView2", "Missing - Setup will install it for you (Windows may ask for permission).")

    # NVIDIA GPU (Plus only)
    gpu = None
    if edition == "Plus":
        gpu = detect_nvidia()
        if gpu is None:
            add("gpu", "warn", "NVIDIA GPU", "No NVIDIA driver found. The app installs, but GPU AI features will not "
                "pass verification until a GPU and current driver are present (CPU can be chosen in the app).")
        else:
            try:
                major = int(gpu["driver"].split(".")[0])
            except ValueError:
                major = 999
            detail = f"{gpu['name']} - {gpu['vram_mb'] // 1024} GB - driver {gpu['driver']}"
            if major < 527:
                add("gpu", "warn", "NVIDIA GPU", detail + " (driver is old; update it for CUDA 12.8)")
            else:
                add("gpu", "ok", "NVIDIA GPU", detail)

    # Existing install
    state = deps_state(root)
    labels = {"missing": ("info", "Not installed yet"),
              "current": ("ok", "Already installed and up to date - Setup will only verify it"),
              "outdated": ("info", "Installed, but Setup will refresh it")}
    add("install", labels[state][0], "Python environment (.venv)", labels[state][1])

    inno = find_inno()
    return {"checks": checks, "free_gb": free_gb, "state": state, "inno": inno, "edition": edition, "title": title,
            "blocking": [c for c in checks if c["status"] == "fail"]}


# --------------------------------------------------------------------------- engine
class Cancelled(Exception):
    pass


class SetupError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass
class Step:
    key: str
    label: str
    weight: int


Emit = Callable[..., None]


class SetupEngine:
    """Runs the selected steps. Reports everything through emit(kind, **data):

    plan(steps) step(index,key,label) status(text) progress(value|None) overall(value)
    log(text) warn(text) done(ok, cancelled, summary, error, hint)
    """

    def __init__(self, options: Options, emit: Emit | None = None, root: Path = ROOT) -> None:
        self.opts = options
        self.root = Path(root)
        self.emit: Emit = emit or (lambda kind, **data: None)
        self.edition, self.title = read_edition(self.root)
        self.plus = self.edition == "Plus"
        self.hai = is_hai(self.title)
        self.slug = f"{'hai-' if self.hai else ''}VisionDB-Craft-{self.edition}"
        self.log_path = self.root / "setup.log"
        self.summary: dict[str, Any] = {"edition": self.edition, "title": self.title, "warnings": [], "shortcuts": []}
        self._log = None
        self._proc: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._tail: collections.deque[str] = collections.deque(maxlen=80)
        self._last_progress = (0.0, 0.0)
        self._done_weight = 0
        self._total_weight = 1
        self._gpu_ok: bool | None = None
        self._skip_install = False

    # ----- planning
    def plan(self) -> list[Step]:
        o = self.opts
        steps = [Step("check", "Checking your PC", 1)]
        if o.install_deps:
            steps.append(Step("env", "Creating the Python environment", 2))
            if self.plus:
                steps.append(Step("torch", "Installing GPU PyTorch (largest download)", 40))
            steps.append(Step("libs", "Installing the app and AI libraries" if self.plus else "Installing the app", 25 if self.plus else 8))
            steps.append(Step("verify", "Verifying the install" + (" and your GPU" if self.plus else ""), 3))
        if o.launcher:
            steps.append(Step("launcher", "Building the quick-launch EXE", 5))
            if o.desktop_shortcut or o.start_menu_shortcut:
                steps.append(Step("shortcuts", "Creating shortcuts", 1))
        if o.standalone:
            steps.append(Step("standalone", "Building the standalone EXE (slow)", 70 if self.plus else 15))
            if o.installer:
                steps.append(Step("installer", "Creating the Windows installer", 6))
        return steps

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                if is_windows():
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                                   creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)
                else:
                    proc.kill()
            except OSError:
                pass

    # ----- logging / subprocess plumbing
    def _write(self, text: str) -> None:
        if self._log:
            self._log.write(text + "\n")
            self._log.flush()

    def _say(self, text: str) -> None:
        self._write(text)
        self.emit("log", text=text)

    def _check_cancel(self) -> None:
        if self._cancelled:
            raise Cancelled()

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k.upper() not in ("PYTHONHOME", "PYTHONPATH") and not k.startswith("_PYI")}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
        return env

    def _handle_line(self, line: str, capture: list[str] | None) -> None:
        match = PROGRESS_RE.match(line)
        if match:                                    # pip --progress-bar raw: drive the bar, keep the log clean
            done, total = int(match[1]), int(match[2])
            if total > 0:
                now = time.monotonic()
                frac = done / total
                if frac >= 1 or frac - self._last_progress[0] >= 0.005 or now - self._last_progress[1] > 0.4:
                    self._last_progress = (frac, now)
                    self.emit("progress", value=frac)
                    self.emit("status", text=f"Downloading... {done / 1048576:,.0f} of {total / 1048576:,.0f} MB")
            return
        self._tail.append(line)
        if line.startswith("[BUILD STAGE]"):             # stage names printed by tools/build_windows.py
            self.emit("status", text=line[len("[BUILD STAGE]"):].strip())
        if capture is not None:
            capture.append(line)
        self._say(line)
        if line.startswith(("Downloading ", "Collecting ", "Installing collected", "Successfully installed",
                            "Building wheel", "Preparing metadata", "Uninstalling ", "Found existing")):
            self.emit("status", text=line[:120])

    def _execute(self, args: list[Any], *, check: bool = True, cwd: Path | None = None,
                 capture: list[str] | None = None, timeout: int | None = None) -> int:
        cmd = [str(a) for a in args]
        self._check_cancel()
        self._tail.clear()
        self._say("> " + subprocess.list2cmdline(cmd))
        if self.opts.dry_run:
            self._dry_run_output(cmd, capture)
            return 0
        flags = CREATE_NO_WINDOW if is_windows() else 0
        try:
            proc = subprocess.Popen(cmd, cwd=str(cwd or self.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                    env=self._env(), creationflags=flags)
        except OSError as exc:
            raise SetupError(f"Could not start {Path(cmd[0]).name}: {exc}")
        self._proc = proc
        timed_out = []
        timer = None
        if timeout:
            timer = threading.Timer(timeout, lambda: (timed_out.append(1), self.cancel_process()))
            timer.start()
        self._last_progress = (0.0, 0.0)
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                self._handle_line(raw.rstrip("\r\n"), capture)
            code = proc.wait()
        finally:
            if timer:
                timer.cancel()
            self._proc = None
        if self._cancelled:
            raise Cancelled()
        if timed_out:
            raise SetupError(f"{Path(cmd[0]).name} did not finish within {timeout // 60} minutes and was stopped.")
        if check and code:
            raise SetupError(f"A setup command failed (exit code {code}): {' '.join(cmd[:4])[:120]}",
                             self._hint("\n".join(self._tail)))
        return code

    def cancel_process(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def _dry_run_output(self, cmd: list[str], capture: list[str] | None) -> None:
        big = any("torch" in c or ".[local-ai" in c or "PyInstaller" in c for c in cmd)
        for i in range(1, 11 if big else 3):
            self._check_cancel()
            time.sleep(0.04)
            self.emit("progress", value=i / (10 if big else 2))
            self.emit("status", text=f"(dry run) {Path(cmd[0]).name} {i * 10 if big else i * 50}%")
        if "make_shortcut.ps1" in " ".join(cmd):
            for line in ("CREATED: C:\\Users\\you\\Desktop\\" + self.title + ".lnk",
                         "CREATED: C:\\Users\\you\\Start Menu\\Programs\\" + self.title + ".lnk"):
                self._handle_line(line, capture)

    @staticmethod
    def _hint(text: str) -> str:
        for pattern, hint in ERROR_HINTS:
            if re.search(pattern, text, re.I):
                return hint
        return ""

    # ----- step framework
    def run(self) -> dict[str, Any]:
        steps = self.plan()
        self._total_weight = sum(s.weight for s in steps)
        ok, cancelled, error, hint = False, False, "", ""
        try:
            previous = self.log_path.with_name("setup.previous.log")
            if self.log_path.is_file():
                shutil.copyfile(self.log_path, previous)
            self._log = self.log_path.open("w", encoding="utf-8")
        except OSError:
            self._log = None
        self._write(f"{self.title} setup {SETUP_VERSION} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self._write(f"options: {json.dumps(asdict(self.opts))}")
        self.emit("plan", steps=[(s.key, s.label) for s in steps])
        try:
            for index, step in enumerate(steps):
                self._check_cancel()
                self.emit("step", index=index, key=step.key, label=step.label)
                self.emit("progress", value=None)
                self.emit("status", text="")
                self._write(f"\n=== {step.label} ===")
                getattr(self, f"_step_{step.key}")()
                self._done_weight += step.weight
                self.emit("overall", value=self._done_weight / self._total_weight)
            ok = True
        except Cancelled:
            cancelled = True
            self._say("Setup was cancelled.")
        except SetupError as exc:
            error, hint = str(exc), exc.hint
            self._say(f"ERROR: {error}")
        except Exception as exc:                      # unexpected: keep the traceback in the log
            error = f"Unexpected problem: {exc}"
            self._write(traceback.format_exc())
        self.summary["ok"] = ok
        self._write_reports(ok, cancelled, error)
        if self._log:
            self._write(f"\nresult: ok={ok} cancelled={cancelled} error={error!r}")
            self._log.close()
            self._log = None
        self.emit("done", ok=ok, cancelled=cancelled, summary=self.summary, error=error, hint=hint)
        return self.summary

    def _write_reports(self, ok: bool, cancelled: bool, error: str) -> None:
        """setup-status.json and Setup-Result.txt: a plain record of how this run ended."""
        if self.opts.dry_run:
            return
        state = "complete_with_warning" if ok and self.summary["warnings"] else "complete" if ok else "cancelled" if cancelled else "failed"
        outputs = {k: self.summary[k] for k in ("launcher", "standalone", "standalone_zip", "installer") if k in self.summary}
        try:
            (self.root / "setup-status.json").write_text(json.dumps(
                {"status": state, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "outputs": outputs,
                 "warnings": self.summary["warnings"], "error": error}, indent=2), encoding="utf-8")
            head = {"complete": "SETUP COMPLETE", "complete_with_warning": "SETUP COMPLETE - WITH NOTES",
                    "cancelled": "SETUP WAS STOPPED", "failed": "SETUP FAILED"}[state]
            lines = [head, ""] + [f"{k}: {v}" for k, v in outputs.items()] + [f"note: {w}" for w in self.summary["warnings"]]
            if error:
                lines.append(f"error: {error}")
            lines += ["", f"Log: {self.log_path}"]
            (self.root / "Setup-Result.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _warn(self, text: str) -> None:
        self.summary["warnings"].append(text)
        self._write("WARNING: " + text)
        self.emit("warn", text=text)

    # ----- steps
    def _step_check(self) -> None:
        info = preflight(self.root, self.opts.dry_run)
        for check in info["blocking"]:
            raise SetupError(f"{check['label']}: {check['detail']}")
        need = estimate_gb(self.opts, info["state"], self.edition)
        if info["free_gb"] < need and not self.opts.dry_run:
            raise SetupError(f"Not enough disk space: about {need:.0f} GB needed, {info['free_gb']:.0f} GB free.",
                             "Free some space on this drive, or untick the optional standalone EXE, then try again.")
        if not self.opts.install_deps and (self.opts.launcher or self.opts.standalone) \
                and not venv_python(self.root).exists() and not self.opts.dry_run:
            raise SetupError("The app is not installed yet.", "Tick 'Install the app' so Setup can create it first.")
        for check in info["checks"]:
            if check["status"] == "warn" and check["key"] != "webview2":
                self._warn(f"{check['label']}: {check['detail']}")
        if self.plus and not self.opts.dry_run:
            (self.root / "models").mkdir(exist_ok=True)
        if not webview2_installed() and not self.opts.dry_run:
            self._install_webview2()

    def _install_webview2(self) -> None:
        self.emit("status", text="Installing Microsoft WebView2 (Windows may ask for permission)...")
        try:
            target = Path(tempfile.gettempdir()) / "MicrosoftEdgeWebview2Setup.exe"
            urllib.request.urlretrieve(WEBVIEW2_URL, target)
            self._execute([target, "/silent", "/install"], check=False, timeout=600)
        except (OSError, SetupError) as exc:
            self._write(f"WebView2 install problem: {exc}")
        if not webview2_installed():
            self._warn("Microsoft WebView2 could not be installed automatically. Install the 'Evergreen' runtime from "
                       "https://developer.microsoft.com/microsoft-edge/webview2/ - the app will not open without it.")

    def _venv_healthy(self) -> bool:
        py = venv_python(self.root)
        try:
            out = subprocess.run([str(py), "-c", "import sys;print(sys.version_info[:2])"], capture_output=True, text=True,
                                 timeout=60, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if is_windows() else 0)
            return out.returncode == 0 and "(3, 12)" in out.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    def _remove_venv(self) -> None:
        venv = self.root / ".venv"
        self.emit("status", text="Removing the old environment...")

        def on_error(func, path, _exc):               # read-only files on Windows
            os.chmod(path, 0o700)
            func(path)
        try:
            shutil.rmtree(venv, onerror=on_error)
        except OSError as exc:
            raise SetupError(f"Could not remove the old .venv folder: {exc}",
                             "Close VisionDB Craft and any window using this folder, then try again.")

    def _step_env(self) -> None:
        py = venv_python(self.root)
        if not self.opts.dry_run and (self.root / ".venv").exists():
            if self.opts.reinstall or not py.exists() or not self._venv_healthy():
                self._remove_venv()
        if not py.exists():
            self._execute([base_python(), "-m", "venv", self.root / ".venv"])
        self._skip_install = False
        if not self.opts.reinstall and deps_state(self.root) == "current" and self._imports_ok():
            self._skip_install = True
            self.emit("status", text="Libraries are already installed - nothing to download.")
            self._say("Dependencies already installed for this version; skipping downloads.")
            return
        self._execute([py, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", *self._pip_opts()])

    def _pip_opts(self) -> list[str]:
        return ["--progress-bar", "raw", "--disable-pip-version-check", "--retries", "8", "--timeout", "60"]

    def _imports_ok(self) -> bool:
        if self.opts.dry_run:
            return False
        modules = "cv2, numpy, yaml, webview" + (", torch, torchvision, transformers, PIL, huggingface_hub, mobile_sam, rtmlib, onnxruntime" if self.plus else "")
        return self._execute([venv_python(self.root), "-c", f"import {modules}"], check=False) == 0

    def _step_torch(self) -> None:
        if self._skip_install:
            return
        py = venv_python(self.root)
        # CPU and GPU ONNX wheels must never share an environment.
        self._execute([py, "-m", "pip", "uninstall", "-y", "onnxruntime", "onnxruntime-gpu"])
        self._execute([py, "-m", "pip", "install", "torch==2.8.0+cu128", "torchvision==0.23.0+cu128",
                       "--index-url", CUDA_INDEX, "-c", "constraints-gpu.txt", *self._pip_opts()])

    def _step_libs(self) -> None:
        if self._skip_install:
            return
        py = venv_python(self.root)
        if self.plus:
            wheel = next(iter(sorted((self.root / "vendor").glob("rtmlib-*.whl"))), None)
            if wheel is None:
                raise SetupError("The corrected rtmlib wheel is missing from the vendor folder.",
                                 "Extract the zip again; do not delete files inside it.")
            self._execute([py, "-m", "pip", "install", "--no-deps", wheel, *self._pip_opts()])
        extra = ".[local-ai,build]" if self.plus else ".[build]"
        self._execute([py, "-m", "pip", "install", extra, *(["-c", "constraints-gpu.txt"] if self.plus else []),
                       *self._pip_opts()])

    def _step_verify(self) -> None:
        py = venv_python(self.root)
        if not self._skip_install:
            self._execute([py, "-m", "pip", "check"])
            if not self.opts.dry_run and not self._imports_ok():
                raise SetupError("The libraries installed but cannot be imported.", "Choose 'Clean reinstall' in Setup and try again.")
            if not self.opts.dry_run:
                self._write_stamp()
        if self.plus:
            report = self.root / "gpu-runtime-report.json"
            self.emit("status", text="Running a real CUDA test on your GPU...")
            code = self._execute([py, "-m", "imagecraft.gpu_runtime", "--report", report], check=False, timeout=600)
            data = {"ok": True, "gpu": "(dry run)"} if self.opts.dry_run else _read_json(report)
            self._gpu_ok = bool(data.get("ok")) and code == 0
            self.summary["gpu"] = {"ok": self._gpu_ok, "name": data.get("gpu", ""), "error": data.get("error", "")}
            if not self._gpu_ok:
                self._warn("GPU check failed: " + (data.get("error") or "see setup.log") +
                           "  The app is installed; AI features need a working NVIDIA driver. Update the driver, "
                           "then run Setup again (it will only re-check the GPU).")

    def _write_stamp(self) -> None:
        stamp = {"fingerprint": deps_fingerprint(self.root), "setup": SETUP_VERSION,
                 "installed": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            (self.root / ".venv" / STAMP_NAME).write_text(json.dumps(stamp, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _ensure_pyinstaller(self) -> None:
        py = venv_python(self.root)
        if self.opts.dry_run or self._execute([py, "-c", "import PyInstaller"], check=False) != 0:
            self.emit("status", text="Installing PyInstaller...")
            self._execute([py, "-m", "pip", "install", "pyinstaller>=6.0", *self._pip_opts()])

    def _step_launcher(self) -> None:
        py = venv_python(self.root)
        self._ensure_pyinstaller()
        self.emit("status", text="Compiling the launcher...")
        lines: list[str] = []
        self._execute([py, "tools/make_launcher.py", "--root", self.root, "--name", self.title], capture=lines)
        exe = self.root / f"{self.title}.exe"
        if not exe.is_file() and not self.opts.dry_run:
            raise SetupError("The launcher EXE was not created.", self._hint("\n".join(lines)))
        if not self.opts.dry_run and self._execute([exe, "--check"], check=False, timeout=60) != 0:
            raise SetupError("The launcher was built but does not find the app.", "Run Setup again and keep all files in one folder.")
        self.summary["launcher"] = str(exe)

    def _step_shortcuts(self) -> None:
        exe = self.root / f"{self.title}.exe"
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", self.root / "tools/make_shortcut.ps1",
               "-Target", exe, "-WorkDir", self.root, "-Name", self.title, "-Description", f"Open {self.title}"]
        if self.opts.desktop_shortcut:
            cmd.append("-Desktop")
        if self.opts.start_menu_shortcut:
            cmd.append("-StartMenu")
        lines: list[str] = []
        code = self._execute(cmd, check=False, capture=lines)
        self.summary["shortcuts"] = [l.split(":", 1)[1].strip() for l in lines if l.startswith("CREATED:")]
        if code or not self.summary["shortcuts"]:
            self._warn("Shortcuts could not be created. You can still open the app with the launcher EXE in the app folder.")

    def _step_standalone(self) -> None:
        py = venv_python(self.root)
        self._ensure_pyinstaller()
        cmd = [py, "tools/build_windows.py", self.edition.lower(), "--skip-dependencies"]
        if self.plus:
            cmd.append("--with-ai")
            if self._gpu_ok is False:
                cmd.append("--skip-gpu-test")      # no GPU on this PC: still build, but do not claim GPU was tested
                self._warn("Standalone EXE was built without its GPU self-test because this PC's GPU check failed.")
        self.emit("status", text="Bundling Python and every library (this takes a while)...")
        (self.root / "build-result.json").unlink(missing_ok=True)
        self._execute(cmd, timeout=3 * 3600)
        result = {} if self.opts.dry_run else _read_json(self.root / "build-result.json")
        folder = self.root / "dist" / self.slug
        exe = Path(result.get("exe") or folder / f"{self.slug}.exe")
        if not self.opts.dry_run and not (result.get("ok") and exe.is_file()):
            raise SetupError("The standalone build finished but did not report a working EXE.",
                             "See setup.log for the PyInstaller output.")
        self.summary["standalone"] = str(exe)
        if result.get("zip"):
            self.summary["standalone_zip"] = result["zip"]

    def _step_installer(self) -> None:
        compiler = find_inno()
        if not compiler:
            self._warn("Inno Setup 6 was not found, so the Windows installer wizard was skipped "
                       "(get it from jrsoftware.org, then run Setup again). The standalone EXE is ready.")
            return
        self._execute([venv_python(self.root), "tools/create_installer.py", self.edition.lower(), "--compiler", compiler])
        self.summary["installer"] = str(self.root / "dist" / f"{self.slug}-Setup.exe")


# --------------------------------------------------------------------------- command line
def make_cli_emit(verbose: bool = True) -> Emit:
    state = {"index": 0, "total": 0, "last": ""}

    def emit(kind: str, **data: Any) -> None:
        if kind == "plan":
            state["total"] = len(data["steps"])
        elif kind == "step":
            print(f"\n[{data['index'] + 1}/{state['total']}] {data['label']}", flush=True)
        elif kind == "log" and verbose:
            print("   " + data["text"], flush=True)
        elif kind == "warn":
            print("   ! " + data["text"], flush=True)
        elif kind == "done":
            print("\n" + ("DONE." if data["ok"] else "CANCELLED." if data["cancelled"] else "FAILED: " + data["error"]), flush=True)
            if data.get("hint"):
                print("  -> " + data["hint"], flush=True)
    return emit


def ask(question: str, default: bool) -> bool:
    answer = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer.startswith("y")


def console_options(opts: Options, edition: str) -> Options:
    print(f"\nVisionDB Craft {edition} setup\n")
    opts.install_deps = ask("Install the app and its libraries?", True)
    opts.launcher = ask("Create the small quick-launch EXE (recommended)?", True)
    if opts.launcher:
        opts.desktop_shortcut = ask("  Desktop shortcut?", True)
        opts.start_menu_shortcut = ask("  Start Menu shortcut?", True)
    opts.standalone = ask("Also build the OPTIONAL standalone EXE with everything bundled (large, slow)?", False)
    return opts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VisionDB Craft setup. Run without options for the graphical wizard.")
    parser.add_argument("--console", action="store_true", help="answer questions in this window instead of the wizard")
    parser.add_argument("--yes", "-y", action="store_true", help="no questions: do the recommended setup (plus any flags)")
    parser.add_argument("--no-deps", action="store_true", help="do not install libraries")
    parser.add_argument("--reinstall", action="store_true", help="delete .venv and install everything again")
    parser.add_argument("--no-launcher", action="store_true", help="skip the quick-launch EXE")
    parser.add_argument("--no-shortcuts", action="store_true", help="no Desktop/Start Menu shortcuts")
    parser.add_argument("--standalone", action="store_true", help="also build the optional standalone EXE")
    parser.add_argument("--installer", action="store_true", help="with --standalone: also build the Inno Setup installer")
    parser.add_argument("--check", action="store_true", help="only print the system check as JSON")
    parser.add_argument("--dry-run", action="store_true", help="show the steps without installing anything")
    args = parser.parse_args(argv)

    if args.check:
        print(json.dumps(preflight(ROOT, args.dry_run), indent=2))
        return 0
    opts = Options(install_deps=not args.no_deps, reinstall=args.reinstall, launcher=not args.no_launcher,
                   desktop_shortcut=not args.no_shortcuts, start_menu_shortcut=not args.no_shortcuts,
                   standalone=args.standalone, installer=args.installer and args.standalone, dry_run=args.dry_run)
    unattended = args.yes or any([args.no_deps, args.reinstall, args.no_launcher, args.no_shortcuts, args.standalone,
                                  args.installer, args.dry_run])
    if not unattended:
        if not args.console:
            try:
                import setup_gui
                return setup_gui.main()
            except ImportError as exc:               # no tkinter: fall back to questions
                print(f"(Graphical wizard unavailable: {exc}. Using the console.)")
        opts = console_options(opts, read_edition()[0])
    if not (is_windows() or opts.dry_run):
        print("This setup must run on Windows 10/11 x64 (use --dry-run to preview the steps).", file=sys.stderr)
        return 2
    summary = SetupEngine(opts, make_cli_emit()).run()
    if summary.get("ok"):
        print(f"\nQuick launcher: {summary.get('launcher', '(not built)')}")
        if summary.get("standalone"):
            print(f"Standalone EXE: {summary['standalone']}")
        for warning in summary["warnings"]:
            print("Note: " + warning)
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
