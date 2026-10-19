r"""Build the small quick-launch EXE with PyInstaller (run with the app's .venv python).

    .venv\Scripts\python.exe tools\make_launcher.py --name "VisionDB Craft Plus"
"""
from __future__ import annotations
import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def brand_info(root: Path) -> tuple[str, str, str]:
    """(icon file, company, version) from the edition identity and pyproject."""
    title = ""
    try:
        tree = ast.parse((root / "imagecraft/edition.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and any(
                    isinstance(t, ast.Name) and t.id == "APP_TITLE" for t in node.targets):
                title = str(node.value.value)
    except (OSError, SyntaxError):
        pass
    version = "0.0.0"
    match = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    if match:
        version = match.group(1)
    hai = title.lower().startswith("h.ai")
    return ("hai.ico" if hai else "visiondb-craft.ico"), ("h.ai Digital Intelligence" if hai else "VisionDB Craft"), version


def version_file(path: Path, name: str, version: str = "3.6.0", company: str = "VisionDB Craft") -> None:
    parts = ",".join((version.split(".") + ["0"] * 4)[:4])
    path.write_text(
        f"VSVersionInfo(ffi=FixedFileInfo(filevers=({parts}),prodvers=({parts}),mask=0x3f,flags=0,OS=0x40004,fileType=0x1,subtype=0,date=(0,0)),"
        f"kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','{company}'),"
        f"StringStruct('FileDescription','{name} launcher'),StringStruct('FileVersion','{version}'),"
        f"StringStruct('ProductName','{name}'),StringStruct('ProductVersion','{version}'),"
        f"StringStruct('OriginalFilename','{name}.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])",
        encoding="utf-8")


def build(root: Path, name: str) -> Path:
    work = root / "build" / "launcher"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    icon, company, version = brand_info(root)
    meta = work / "version.txt"
    version_file(meta, name, version, company)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--name", name, "--icon", str(root / "imagecraft/ui/assets" / icon),
           "--version-file", str(meta), "--distpath", str(work / "dist"), "--workpath", str(work / "pyi"),
           "--specpath", str(work), "--exclude-module", "tkinter", str(HERE / "launcher_stub.py")]
    subprocess.run(cmd, check=True, cwd=root)
    built = work / "dist" / f"{name}.exe"
    if not built.is_file():
        raise SystemExit("PyInstaller finished but the launcher EXE is missing.")
    target = root / f"{name}.exe"
    try:
        shutil.copyfile(built, target)
    except PermissionError:
        raise SystemExit(f"Cannot replace {target.name}: it is running or locked. Close the app and try again (Access is denied).")
    shutil.rmtree(work, ignore_errors=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE.parent)
    parser.add_argument("--name", default="VisionDB Craft Plus")
    args = parser.parse_args()
    print("LAUNCHER:", build(args.root.resolve(), args.name))
