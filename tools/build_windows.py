"""Native Windows build with visible post-freeze phases and optional release ZIP."""
from __future__ import annotations
import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from stage_edition import ROOT,stage


def announce(message):
    print('[BUILD STAGE] '+message,flush=True)


def build(edition: str,with_ai: bool=False,skip_dependencies: bool=False,create_zip: bool=False,skip_gpu_test: bool=False) -> Path:
    if sys.platform!='win32':raise SystemExit('Build the Windows EXE on Windows. No EXE was created here.')
    edition=edition.capitalize()
    tree=ast.parse((ROOT/'imagecraft/edition.py').read_text())
    titles=[n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and any(isinstance(t,ast.Name) and t.id=='APP_TITLE' for t in n.targets)]
    brand='hai-VisionDB-Craft' if titles and str(titles[0]).startswith('h.ai') else 'VisionDB-Craft'
    slug=f'{brand}-{edition}'
    version=re.search(r'^version\s*=\s*"([^"]+)"',(ROOT/'pyproject.toml').read_text(),re.M).group(1)
    numeric=tuple(int(x) for x in version.split('.')[:3])+(0,)
    result_path=ROOT/'build-result.json';result_path.unlink(missing_ok=True)
    announce('Prepare the edition source')
    status_path=ROOT/'PACKAGE-STATUS.json';exported=json.loads(status_path.read_text()).get('edition') if status_path.exists() else None
    source=ROOT if exported==edition else stage(edition,ROOT/'build/windows-source')
    gpu=edition=='Plus' and (source/'constraints-gpu.txt').is_file() and (source/'vendor/rtmlib-0.0.16+visiondb.gpu1-py3-none-any.whl').is_file()
    announce('Register application source without reinstalling dependencies' if skip_dependencies else 'Install build-source dependencies')
    subprocess.run([sys.executable,'-m','pip','install',*(['--no-deps'] if skip_dependencies else []),str(source)+('[local-ai]' if with_ai and edition=='Plus' else '')],check=True)
    dist=ROOT/'dist';work=ROOT/'build'/f'freeze-{edition.lower()}'
    metadata=work/'version.txt';work.mkdir(parents=True,exist_ok=True)
    company='h.ai Digital Intelligence' if brand.startswith('hai-') else 'VisionDB Craft'
    strings=[('CompanyName',company),('FileDescription',slug),('FileVersion',version),('ProductName',slug),('ProductVersion',version),('OriginalFilename',slug+'.exe')]
    metadata.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers="+repr(numeric)+",prodvers="+repr(numeric)+",mask=0x3f,flags=0,OS=0x40004,fileType=0x1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',["+','.join('StringStruct('+repr(k)+','+repr(v)+')' for k,v in strings)+"])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])")
    icon='hai.ico' if brand.startswith('hai-') else 'visiondb-craft.ico'
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--name',slug,'--distpath',str(dist),'--workpath',str(work/'pyinstaller'),'--specpath',str(work),'--paths',str(source),'--icon',str(source/'imagecraft/ui/assets'/icon),'--version-file',str(metadata),'--add-data',str(source/'imagecraft/ui')+os.pathsep+'imagecraft/ui','--hidden-import','webview.platforms.edgechromium','--collect-all','webview']
    if edition=='Stable':
        for name in ['imagecraft.plus_features','imagecraft.auto_annotate','imagecraft.local_ai','imagecraft.gpu_runtime','torch','torchvision','transformers','huggingface_hub','onnxruntime','rtmlib','mobile_sam','timm']:
            cmd.extend(['--exclude-module',name])
    elif with_ai:
        packages=['torch','torchvision','transformers','huggingface_hub','onnxruntime','rtmlib','mobile_sam','timm','safetensors']
        if gpu:packages.append('onnx')
        for name in packages:cmd.extend(['--collect-all',name])
    cmd.append(str(source/'launch.py'))
    announce('Create EXE and collect runtime files (PyInstaller; this can take several minutes)')
    subprocess.run(cmd,cwd=source,check=True)
    bundle=dist/slug;exe=bundle/(slug+'.exe')
    if not exe.is_file():raise RuntimeError('PyInstaller returned without the expected application EXE')
    announce('EXE created; copying documentation and source before startup validation')
    for name in ['README.md','LICENSE','TESTING.md','THIRD_PARTY_NOTICES.md','GPU-SETUP.md','SETUP-GUIDE.md']:
        if (source/name).is_file():shutil.copy2(source/name,bundle/name)
    shutil.copytree(source,bundle/'source',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.venv','.build-*','dist','build','models','.git','.pytest_cache','setup.log','Setup-Result.txt','setup-status.json','build-result.json','setup-fix-backups'))
    report=bundle/'startup-self-test.json'
    announce('Run frozen application startup check (90-second limit)')
    subprocess.run([str(exe),'--self-test','--report',str(report)],check=True,timeout=90)
    if not report.is_file() or not json.loads(report.read_text()).get('ok'):raise RuntimeError('Frozen executable startup check did not pass')
    gpu_tested=bool(gpu and with_ai and not skip_gpu_test)
    if gpu_tested:
        announce('Verify frozen NVIDIA GPU runtime (180-second limit)')
        subprocess.run([str(exe),'--gpu-self-test','--report',str(bundle/'gpu-runtime-report.json')],check=True,timeout=180)
    announce('Write build status and resolved dependency inventory')
    status={'edition':edition,'version':version,'kind':'windows-onedir','windows_executable_built':True,'runtime_bundled':True,'ai_runtimes_bundled':edition=='Plus' and with_ai,'gpu_target':gpu,'gpu_self_test_passed':gpu_tested,'interactive_windows_qa':'required'}
    (bundle/'PACKAGE-STATUS.json').write_text(json.dumps(status,indent=2))
    with (bundle/'build-dependencies.txt').open('w',encoding='utf-8') as handle:subprocess.run([sys.executable,'-m','pip','freeze','--all'],stdout=handle,check=True,timeout=120)
    output=bundle
    if create_zip:
        announce('Create optional release ZIP; this is not needed to run the EXE')
        output=dist/(slug+'.zip')
        subprocess.run([sys.executable,'-u',str(ROOT/'tools/archive.py'),str(bundle),str(output)],check=True)
    else:announce('Skip optional ZIP compression; application folder is the deliverable')
    result={'ok':True,'exe':str(exe),'folder':str(bundle),'startup_check':'passed','gpu_check':'passed' if gpu_tested else ('skipped: no working GPU on the build PC' if gpu and with_ai else 'not requested'),'zip':str(output) if create_zip else None}
    result_path.write_text(json.dumps(result,indent=2))
    announce('BUILD FINISHED. Application EXE: '+str(exe))
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('edition',choices=['stable','plus']);p.add_argument('--with-ai',action='store_true');p.add_argument('--skip-dependencies',action='store_true');p.add_argument('--zip',action='store_true',help='Also create an optional release ZIP; adds compression time')
    p.add_argument('--skip-gpu-test',action='store_true',help='build even if this PC has no working NVIDIA GPU (the GPU self-test is then not run)')
    a=p.parse_args();print(build(a.edition,a.with_ai,a.skip_dependencies,a.zip,a.skip_gpu_test),flush=True)
