"""Setup engine, launcher and wizard plumbing. Runs on any OS: commands are recorded, not executed."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import setup_app  # noqa: E402
from setup_app import Options, SetupEngine  # noqa: E402

OK_PREFLIGHT = {"checks": [], "blocking": [], "free_gb": 500.0, "state": "missing", "inno": None}


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A fake Plus app folder with a venv, and an engine whose subprocess calls are recorded."""
    (tmp_path / "imagecraft").mkdir()
    (tmp_path / "imagecraft/edition.py").write_text('EDITION = "Plus"\nAPP_TITLE = "VisionDB Craft Plus"\n')
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "constraints-gpu.txt").write_text("torch==2.8.0+cu128\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/rtmlib-0.0.16+visiondb.gpu1-py3-none-any.whl").write_bytes(b"x")
    monkeypatch.setattr(setup_app, "is_windows", lambda: True)
    monkeypatch.setattr(setup_app, "preflight", lambda root, dry_run=False: dict(OK_PREFLIGHT))
    monkeypatch.setattr(setup_app, "webview2_installed", lambda: True)
    (tmp_path / ".venv/Scripts").mkdir(parents=True)
    (tmp_path / ".venv/Scripts/python.exe").touch()
    calls, events = [], []

    def make(**opts):
        engine = SetupEngine(Options(**opts), lambda kind, **d: events.append((kind, d)), root=tmp_path)

        def fake(args, **kw):
            calls.append([str(a) for a in args])
            if kw.get("capture") is not None and any("make_shortcut" in str(a) for a in args):
                kw["capture"].append("CREATED: C:\\Desktop\\VisionDB Craft Plus.lnk")
            if "gpu_runtime" in " ".join(map(str, args)):
                (tmp_path / "gpu-runtime-report.json").write_text(json.dumps({"ok": True, "gpu": "RTX Test"}))
            if "tools/build_windows.py" in " ".join(map(str, args)).replace("\\", "/"):
                exe = tmp_path / "dist/VisionDB-Craft-Plus/VisionDB-Craft-Plus.exe"
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.write_bytes(b"MZ")
                (tmp_path / "build-result.json").write_text(json.dumps({"ok": True, "exe": str(exe), "zip": None}))
            if "tools/make_launcher.py" in " ".join(map(str, args)).replace("\\", "/"):
                (tmp_path / "VisionDB Craft Plus.exe").write_bytes(b"MZ")
            return 0
        engine._execute = fake
        engine._venv_healthy = lambda: True
        engine._imports_ok = lambda: True
        return engine
    return tmp_path, make, calls, events


def index(calls, needle):
    return next(i for i, c in enumerate(calls) if needle in " ".join(c).replace("\\", "/"))


def test_default_plan_is_launcher_not_standalone(app):
    _, make, _, _ = app
    keys = [s.key for s in make().plan()]
    assert keys == ["check", "env", "torch", "libs", "verify", "launcher", "shortcuts"]
    assert "standalone" not in keys


def test_standalone_and_installer_are_opt_in(app):
    _, make, _, _ = app
    keys = [s.key for s in make(standalone=True, installer=True).plan()]
    assert keys[-2:] == ["standalone", "installer"]
    assert "installer" not in [s.key for s in make(standalone=False, installer=True).plan()]


def test_install_order_cuda_then_vendor_then_extra_then_verify(app):
    _, make, calls, _ = app
    summary = make(launcher=False).run()
    assert summary["ok"]
    cuda, vendor = index(calls, "torch==2.8.0+cu128"), index(calls, ".whl")
    extra, check = index(calls, ".[local-ai,build]"), index(calls, "pip check")
    verify = index(calls, "imagecraft.gpu_runtime")
    assert cuda < vendor < extra < check < verify
    assert any("uninstall" in c and "onnxruntime" in c for c in calls)
    assert not any("install" in c and "onnxruntime==1.23.2" in c for c in calls)


def test_launcher_is_built_and_verified_and_shortcuts_made(app):
    root, make, calls, _ = app
    summary = make().run()
    assert summary["ok"] and summary["launcher"].endswith("VisionDB Craft Plus.exe")
    assert summary["shortcuts"] == ["C:\\Desktop\\VisionDB Craft Plus.lnk"]
    assert any(c[-1] == "--check" for c in calls)
    assert any("-Desktop" in c and "-StartMenu" in c for c in calls)
    assert not any("build_windows" in " ".join(c) for c in calls)


def test_standalone_runs_only_when_requested_and_after_gpu_check(app):
    root, make, calls, _ = app
    summary = make(standalone=True).run()
    build = index(calls, "build_windows.py")
    assert index(calls, "imagecraft.gpu_runtime") < build
    assert "--skip-dependencies" in calls[build] and "--with-ai" in calls[build] and "--skip-gpu-test" not in calls[build]
    assert summary["standalone"].endswith("VisionDB-Craft-Plus.exe")


def test_failed_gpu_check_warns_but_does_not_stop_and_skips_gpu_self_test(app):
    root, make, calls, _ = app
    engine = make(standalone=True)
    inner = engine._execute

    def failing(args, **kw):
        code = inner(args, **kw)
        if "gpu_runtime" in " ".join(map(str, args)):
            (root / "gpu-runtime-report.json").write_text(json.dumps({"ok": False, "error": "no CUDA"}))
            return 1
        return code
    engine._execute = failing
    summary = engine.run()
    assert summary["ok"] and summary["gpu"]["ok"] is False
    assert any("GPU check failed" in w for w in summary["warnings"])
    assert "--skip-gpu-test" in calls[index(calls, "build_windows.py")]


def test_up_to_date_install_skips_every_download(app):
    root, make, calls, _ = app
    (root / ".venv" / setup_app.STAMP_NAME).write_text(json.dumps({"fingerprint": setup_app.deps_fingerprint(root)}))
    engine = make(launcher=False)
    engine._imports_ok = lambda: True
    assert setup_app.deps_state(root) == "current"
    assert engine.run()["ok"]
    assert not any(" install" in " ".join(c) or "uninstall" in c for c in calls)
    assert any("imagecraft.gpu_runtime" in " ".join(c) for c in calls)     # GPU is still re-checked


def test_changed_requirements_invalidate_the_stamp(app):
    root, _, _, _ = app
    (root / ".venv" / setup_app.STAMP_NAME).write_text(json.dumps({"fingerprint": setup_app.deps_fingerprint(root)}))
    assert setup_app.deps_state(root) == "current"
    (root / "pyproject.toml").write_text("[project]\nname='changed'\n")
    assert setup_app.deps_state(root) == "outdated"


def test_failure_reports_hint_and_stops(app):
    root, make, calls, events = app
    engine = make(launcher=False)

    def boom(args, **kw):
        if "torch==2.8.0+cu128" in " ".join(map(str, args)):
            engine._tail.append("urllib3.exceptions.ReadTimeoutError: Read timed out.")
            raise setup_app.SetupError("pip failed", engine._hint("\n".join(engine._tail)))
        return 0
    engine._execute = boom
    summary = engine.run()
    done = [d for k, d in events if k == "done"][0]
    assert not summary["ok"] and not done["ok"] and "internet connection" in done["hint"]


def test_cancel_before_start_is_clean(app):
    _, make, calls, events = app
    engine = make()
    engine.cancel()
    engine.run()
    done = [d for k, d in events if k == "done"][0]
    assert done["cancelled"] and not done["ok"] and not calls


def test_not_installed_and_nothing_to_install_is_refused(app):
    root, make, _, events = app
    (root / ".venv/Scripts/python.exe").unlink()
    make(install_deps=False).run()
    done = [d for k, d in events if k == "done"][0]
    assert not done["ok"] and "not installed" in done["error"]


def test_dry_run_touches_nothing_end_to_end(tmp_path, monkeypatch):
    (tmp_path / "imagecraft").mkdir()
    (tmp_path / "imagecraft/edition.py").write_text('EDITION = "Plus"\n')
    (tmp_path / "pyproject.toml").write_text("x")
    monkeypatch.setattr(setup_app, "preflight", lambda root, dry_run=False: dict(OK_PREFLIGHT))
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/rtmlib-0.0.16-py3-none-any.whl").write_bytes(b"x")
    events = []
    summary = SetupEngine(Options(standalone=True, dry_run=True), lambda k, **d: events.append(k), root=tmp_path).run()
    assert summary["ok"] and "done" in events
    assert not (tmp_path / ".venv").exists() and not (tmp_path / "dist").exists() and not (tmp_path / "models").exists()
    assert (tmp_path / "setup.log").is_file()


def test_stable_edition_skips_gpu_and_ai_steps(tmp_path):
    (tmp_path / "imagecraft").mkdir()
    (tmp_path / "imagecraft/edition.py").write_text('EDITION = "Stable"\nAPP_TITLE = "VisionDB Craft Stable"\n')
    engine = SetupEngine(Options(), root=tmp_path)
    keys = [s.key for s in engine.plan()]
    assert "torch" not in keys and engine.title == "VisionDB Craft Stable"


def test_pip_progress_lines_drive_the_bar_not_the_log(tmp_path):
    events = []
    engine = SetupEngine(Options(), lambda k, **d: events.append((k, d)), root=tmp_path)
    engine._handle_line("Progress 500 of 1000", None)
    engine._handle_line("Collecting torch==2.8.0", None)
    kinds = [k for k, _ in events]
    assert ("progress", {"value": 0.5}) in events and kinds.count("log") == 1


def test_disk_estimate_grows_with_optional_standalone():
    base = setup_app.estimate_gb(Options(), "missing")
    assert setup_app.estimate_gb(Options(standalone=True), "missing") > base
    assert setup_app.estimate_gb(Options(), "current") < base       # nothing to download again


def test_every_error_hint_pattern_is_reachable():
    cases = {"WinError 5 Access is denied": "in use", "OSError: [Errno 28] No space left": "drive is full",
             "WinError 206": "too long", "Max retries exceeded": "interrupted", "No matching distribution found for x": "pip could not"}
    for text, expect in cases.items():
        assert expect in SetupEngine._hint(text)
    assert SetupEngine._hint("all fine") == ""


def test_launcher_stub_check_mode(tmp_path, monkeypatch):
    import launcher_stub
    monkeypatch.setattr(launcher_stub, "app_folder", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["launcher", "--check"])
    assert launcher_stub.main() == 2
    (tmp_path / ".venv/Scripts").mkdir(parents=True)
    (tmp_path / ".venv/Scripts/pythonw.exe").touch()
    (tmp_path / "launch.py").touch()
    assert launcher_stub.main() == 0


def test_cmd_and_bootstrap_scripts_are_wired_together():
    cmd = (ROOT / "Setup.cmd").read_text()
    boot = (ROOT / "tools/bootstrap.ps1").read_text()
    assert "tools\\bootstrap.ps1" in cmd and "-ExecutionPolicy Bypass" in cmd
    assert "setup_gui.py" in boot and "setup_app.py" in boot and "3.12" in boot
    assert (ROOT / "tools/make_shortcut.ps1").is_file() and (ROOT / "setup_gui.py").is_file()


def test_reports_are_written_for_a_real_run(app):
    root, make, _, _ = app
    make().run()
    status = json.loads((root / "setup-status.json").read_text())
    assert status["status"] in ("complete", "complete_with_warning") and "launcher" in status["outputs"]
    assert "SETUP COMPLETE" in (root / "Setup-Result.txt").read_text()


def test_build_stage_lines_become_status_text(tmp_path):
    events = []
    engine = SetupEngine(Options(), lambda k, **d: events.append((k, d)), root=tmp_path)
    engine._handle_line("[BUILD STAGE] Run frozen application startup check (90-second limit)", None)
    assert ("status", {"text": "Run frozen application startup check (90-second limit)"}) in events


def test_hai_brand_is_detected_and_names_follow(tmp_path):
    (tmp_path / "imagecraft").mkdir()
    (tmp_path / "imagecraft/edition.py").write_text('EDITION = "Plus"\nAPP_TITLE = "h.ai VisionDB Craft Plus"\n')
    engine = SetupEngine(Options(), root=tmp_path)
    assert engine.hai and engine.slug == "hai-VisionDB-Craft-Plus" and engine.title == "h.ai VisionDB Craft Plus"
    (tmp_path / "imagecraft/edition.py").write_text('EDITION = "Plus"\nAPP_TITLE = "VisionDB Craft Plus"\n')
    other = SetupEngine(Options(), root=tmp_path)
    assert not other.hai and other.slug == "VisionDB-Craft-Plus"


def test_build_script_accepts_skip_gpu_test_and_installer_follows_the_brand():
    build = (ROOT / "tools/build_windows.py").read_text()
    installer = (ROOT / "tools/create_installer.py").read_text()
    assert "--skip-gpu-test" in build and "h.ai" in installer and "pyproject.toml" in installer


@pytest.mark.parametrize("title", ["VisionDB Craft Plus", "VisionDB Craft Stable", "h.ai VisionDB Craft Plus", "h.ai VisionDB Craft Stable"])
def test_wizard_module_loads_for_every_brand(monkeypatch, title):
    """The palette block must define every colour name for both brands (a missing name crashed the window at import)."""
    pytest.importorskip("tkinter")
    import importlib.util
    edition = "Plus" if "Plus" in title else "Stable"
    monkeypatch.setattr(setup_app, "read_edition", lambda root: (edition, title))
    spec = importlib.util.spec_from_file_location("setup_gui_brand_probe", ROOT / "setup_gui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.HAI == title.startswith("h.ai")
    for name in ("BG", "CARD", "LINE", "TEXT", "MUTED", "MINT", "MINT_HOVER", "INK", "OK", "WARN", "FAIL", "INFO",
                 "BTN2", "BTN2_HOVER", "DISABLED_FG", "THIN", "LOGO", "ICON"):
        assert getattr(module, name), name
