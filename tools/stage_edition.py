"""Export standalone edition source trees from shared code (no runtime unlocks)."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PLUS_FILES = ['Check-GPU.cmd', 'constraints-gpu.txt', 'GPU-SETUP.md', 'imagecraft/gpu_runtime.py', 'tests/test_gpu_runtime.py', 'imagecraft/plus_features.py', 'imagecraft/local_ai.py', 'imagecraft/auto_annotate.py', 'imagecraft/ui/js/panels/local_ai.js', 'imagecraft/ui/js/panels/auto_annotate.js', 'tests/test_local_ai.py', 'tests/test_auto_annotate.py', 'docs/local-ai-models.md', 'docs/local-ai-benchmark.md', 'local-ai-models.md', 'local-ai-benchmark.md']


def literal_array(source: str, name: str):
    start = re.search(r'\b(?:export\s+)?const\s+' + name + r'\s*=\s*\[', source).end()-1
    # Let the JS parser identify the end, rather than parsing strings/templates as Python.
    ends = [m.start()+1 for m in re.finditer(r'\];', source[start:])]
    for end in ends:
        stop = start+end
        expression = source[start:stop]
        run = subprocess.run(['node','-e','const c=(name,meaning,effect)=>({name,meaning,effect}); process.stdout.write(JSON.stringify('+expression+'));'],capture_output=True,text=True)
        if run.returncode == 0:
            return start, stop, json.loads(run.stdout)
    raise ValueError(f'Cannot parse {name}')


def strip_tutorials(folder: Path):
    for filename,name in [('tutorial.js','STEPS'),('guided_tutorials.js','GUIDED_TUTORIALS'),('advanced_tutorial.js','ADVANCED_TOPICS')]:
        p=folder/filename; s=p.read_text();start,end,rows=literal_array(s,name)
        rows=[r for r in rows if r.get('panel',r.get('tab')) not in ('auto_annotate','local_ai') and not re.search(r'Auto Annotate|AI Annotate',r.get('title',''))]
        for row in rows:
            for section in row.get('sections',[]):
                section['controls']=[c for c in section.get('controls',[]) if not re.search(r'Auto Annotate|AI Annotate|proposal',json.dumps(c),re.I)]
        text=json.dumps(rows,ensure_ascii=False,indent=2)
        text=text.replace('all five modes','all three modes').replace('Five focused modes','Three focused modes')
        text=text.replace('or\\n      <b>Auto Annotate BETA</b> as your focused mode.', 'as your focused mode.')
        text=text.replace('committed auto annotations, and completed batches','and completed batches').replace('Live slider previews and Auto Annotate BETA detection proposals are temporary, so they do not enter History. Apply or Commit Selected is the boundary that creates a reversible operation.','Live slider previews are temporary. Apply creates a reversible operation.').replace('<b>Annotate</b>, as your focused mode.','or <b>Annotate</b> as your focused mode.')
        s=s[:start]+text+s[end:]
        s=s.replace('"Annotate", "Auto Annotate BETA", "AI Annotate", "Dataset", "Reference"','"Annotate", "Dataset", "Reference"')
        p.write_text(s)


def stage(edition: str, destination: Path) -> Path:
    edition=edition.capitalize(); target=destination.resolve()/f'VisionDB-Craft-{edition}'
    if edition == 'Plus' and not (ROOT/'imagecraft/plus_features.py').is_file():
        raise ValueError('This Stable source export contains no Plus components. Use the shared source for Plus builds.')
    if target == ROOT or ROOT in target.parents and any(p.name == 'imagecraft' for p in target.parents):
        raise ValueError('Output cannot overwrite source')
    if target.exists(): shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in ['imagecraft','tests','docs','tools','branding','.github','vendor']:
        if (ROOT/name).exists():
            shutil.copytree(ROOT/name,target/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['pyproject.toml','LICENSE','CHANGELOG.md','BUILD.md','TESTING.md','THIRD_PARTY_NOTICES.md','launch.py','setup_app.py','setup_gui.py','SETUP-GUIDE.md','GPU-SETUP.md','constraints-gpu.txt','Check-GPU.cmd']:
        if (ROOT/name).exists():shutil.copy2(ROOT/name,target/name)
    shutil.copy2(ROOT/'docs'/f'README-{edition}.md',target/'README.md')
    for p in (target/'docs').glob('README-*.md'): p.unlink()
    (target/'Start.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nif not exist ".venv\\Scripts\\pythonw.exe" (\r\n  echo Run Setup.cmd once before starting this source package.\r\n  pause\r\n  exit /b 1\r\n)\r\nstart "" ".venv\\Scripts\\pythonw.exe" "launch.py"\r\n')
    shutil.copy2(ROOT/'Setup.cmd',target/'Setup.cmd')
    if edition=='Stable':
        if (target/'vendor').exists(): shutil.rmtree(target/'vendor')
        for name in PLUS_FILES:
            p=target/name
            if p.exists():p.unlink()
        (target/'imagecraft/edition.py').write_text('from imagecraft.core_features import CoreFeatures as Features\nEDITION = "Stable"\nAPP_TITLE = "VisionDB Craft Stable"\nMODES = ("transform", "augment", "annotate")\n')
        (target/'imagecraft/ui/js/edition.js').write_text('export const EDITION = "Stable";\nexport const APP_TITLE = "VisionDB Craft Stable";\nexport const MODES = ["transform", "augment", "annotate"];\n')
        p=target/'imagecraft/ui/index.html';s=p.read_text().replace('VisionDB Craft Plus','VisionDB Craft Stable').replace('<small>Plus</small>','<small>Stable</small>')
        s=re.sub(r'\s*<button class="mode-card" data-working-mode="(?:auto_annotate|ai_annotate)">.*?</button>','',s,flags=re.S);p.write_text(s)
        p=target/'imagecraft/ui/js/sidebar.js';s=p.read_text();s=re.sub(r'^import .*from "\./panels/(?:auto_annotate|local_ai)\.js";\n','',s,flags=re.M);s=re.sub(r'^  \{ id: "(?:auto_annotate|local_ai)".*\n','',s,flags=re.M);p.write_text(s)
        p=target/'imagecraft/ui/js/mode_manager.js';s=p.read_text();s=re.sub(r'^  (?:auto_annotate|ai_annotate): \{ label:.*\n','',s,flags=re.M);p.write_text(s)
        p=target/'imagecraft/ui/js/app.js';s=p.read_text();s=re.sub(r'^    "[89]":.*\n','',s,flags=re.M);p.write_text(s)
        p=target/'imagecraft/ui/js/app.js';s=p.read_text();start,end,groups=literal_array(s,'groups')
        groups=[g for g in groups if not re.search(r'Auto Annotate|AI Annotate',g.get('title',''))]
        for g in groups:g['items']=[item for item in g.get('items',[]) if not re.search(r'Auto Annotate|AI Annotate',json.dumps(item))]
        p.write_text(s[:start]+json.dumps(groups,ensure_ascii=False,indent=2)+s[end:])
        strip_tutorials(target/'imagecraft/ui/js')
        p=target/'pyproject.toml';s=p.read_text().replace('visiondb-craft-plus','visiondb-craft-stable');s=re.sub(r'local-ai = \[.*?\]\n','',s,flags=re.S);p.write_text(s)
        # Stable's core regression suite is kept; Plus-only UI assertions stay in Plus.
        p=target/'tests/test_ui_contract.py';s=p.read_text();tree=ast.parse(s);lines=s.splitlines(keepends=True)
        omit={'test_advanced_tutorial_is_non_linear_searchable_and_comprehensive','test_auto_annotate_panel_is_separate_user_controlled_and_taught'}
        for n in reversed(tree.body):
            if isinstance(n,ast.FunctionDef) and n.name in omit:del lines[n.lineno-1:n.end_lineno]
        p.write_text(''.join(lines))
        p=target/'.github/workflows/ci.yml';p.write_text(p.read_text().replace('edition: [stable, plus]','edition: [stable]'))
        # No Plus-only defaults or documentation advertised in the public edition.
        p=target/'imagecraft/settings.py';s=p.read_text();s=re.sub(r'^    "auto_(?:annotate|annotation)[^\n]*\n','',s,flags=re.M);p.write_text(s)
        for name in ['README-Plus.md','local-ai-models.md','local-ai-benchmark.md']:
            p=target/'docs'/name
            if p.exists():p.unlink()
        (target/'CHANGELOG.md').write_text('# VisionDB Craft Stable 3.6.0\n\nRebranded from ImageCraft 3.4.0. Established manual annotation, transformation, augmentation, project storage, history and dataset exports retained. Plus inference and detector modules are excluded. MIT license preserved. See TESTING.md for release limits.\n')
    status={'edition':edition,'version':'3.6.0','kind':'source','windows_executable_built':False,'runtime_bundled':False}
    (target/'PACKAGE-STATUS.json').write_text(json.dumps(status,indent=2)+'\n')
    manifest={str(p.relative_to(target)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(target.rglob('*')) if p.is_file()}
    (target/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('edition',choices=['stable','plus']);parser.add_argument('--output',type=Path,default=ROOT/'build/source');args=parser.parse_args()
    print(stage(args.edition,args.output))
