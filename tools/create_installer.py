# Package the built Windows application with Inno Setup 6.
from pathlib import Path
import argparse, ast, re, subprocess
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument("edition",choices=["stable","plus"]);p.add_argument("--compiler",default="ISCC.exe");a=p.parse_args()
    tree=ast.parse((ROOT/"imagecraft/edition.py").read_text())
    titles=[n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and any(isinstance(t,ast.Name) and t.id=="APP_TITLE" for t in n.targets)]
    brand='hai-VisionDB-Craft' if titles and str(titles[0]).startswith('h.ai') else 'VisionDB-Craft'
    version=re.search(r'^version\s*=\s*"([^"]+)"',(ROOT/"pyproject.toml").read_text(),re.M).group(1)
    slug=brand+"-"+a.edition.capitalize()
    bundle=ROOT/"dist"/slug
    if not (bundle/(slug+".exe")).is_file(): raise SystemExit("Build the application EXE before creating the installer.")
    script=ROOT/"build"/"installer.iss";script.parent.mkdir(exist_ok=True)
    script.write_text(f'''[Setup]
AppId={slug}
AppName={slug}
AppVersion={version}
DefaultDirName={{userdocs}}\\{slug}
PrivilegesRequired=lowest
OutputDir={ROOT / "dist"}
OutputBaseFilename={slug}-Setup
Compression=lzma2
SolidCompression=yes
[Files]
Source: "{bundle}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Dirs]
Name: "{{app}}\\models"; Flags: uninsneveruninstall
[Icons]
Name: "{{userprograms}}\\{slug}"; Filename: "{{app}}\\{slug}.exe"
[Run]
Filename: "{{app}}\\{slug}.exe"; Description: "Launch {slug}"; Flags: nowait postinstall skipifsilent
''',encoding="utf-8")
    subprocess.run([a.compiler,str(script)],check=True)

if __name__=="__main__": main()
