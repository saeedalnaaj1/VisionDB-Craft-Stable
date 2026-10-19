"""Edition boundary, compatibility and distribution regression tests."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
from imagecraft.edition import EDITION, APP_TITLE, MODES
from imagecraft.engine import BackendEngine
from imagecraft.settings import Settings

ROOT=Path(__file__).resolve().parents[1]


def test_edition_identity_and_backend_modes(tmp_path):
    e=BackendEngine(settings=Settings(tmp_path/'settings.json'))
    assert e.get_app_info()['name']==APP_TITLE
    for mode in MODES: assert e.set_working_mode(mode)['ok']
    assert not e.set_working_mode('unknown')['ok']
    if EDITION=='Stable':
        assert not e.set_working_mode('ai_annotate')['ok']
        assert not e.set_working_mode('auto_annotate')['ok']
        assert not hasattr(e,'download_local_ai_model')
        assert not hasattr(e,'preview_auto_annotations')
        assert 'imagecraft.local_ai' not in sys.modules


def test_frontend_modules_resolve_and_parse():
    js=ROOT/'imagecraft/ui/js'
    for p in js.rglob('*.js'):
        for rel in re.findall(r'from\s+["\'](\.[^"\']+)["\']',p.read_text()):
            assert (p.parent/rel).is_file(),(p,rel)
        checked=subprocess.run(['node','--check',str(p)],capture_output=True,text=True)
        assert checked.returncode==0,checked.stderr


def test_stable_ui_and_exclusive_files_absent():
    if EDITION!='Stable': pytest.skip('Stable export only')
    for name in ['plus_features.py','local_ai.py','auto_annotate.py']:
        assert not (ROOT/'imagecraft'/name).exists()
    assert 'local-ai = [' not in (ROOT/'pyproject.toml').read_text()
    for name in ['index.html','js/tutorial.js','js/advanced_tutorial.js','js/guided_tutorials.js','js/app.js']:
        text=(ROOT/'imagecraft/ui'/name).read_text()
        assert 'Auto Annotate' not in text
        assert 'AI Annotate' not in text
    sidebar=(ROOT/'imagecraft/ui/js/sidebar.js').read_text()
    assert 'buildLocalAIPanel' not in sidebar and 'buildAutoAnnotatePanel' not in sidebar


def test_independent_headless_startup_from_another_directory(tmp_path):
    run=subprocess.run([sys.executable,str(ROOT/'launch.py'),'--self-test'],cwd=tmp_path,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)['edition']==EDITION


def test_legacy_settings_seed_without_overwrite(tmp_path,monkeypatch):
    monkeypatch.setenv('APPDATA',str(tmp_path))
    monkeypatch.delenv('IMAGECRAFT_CONFIG',raising=False);monkeypatch.delenv('VISIONDB_CRAFT_CONFIG',raising=False)
    legacy=tmp_path/'ImageCraft/settings.json';legacy.parent.mkdir();legacy.write_text('{"sidebar_width": 420}')
    s=Settings();assert s.get('sidebar_width')==420
    s.set('sidebar_width',421)
    assert json.loads(legacy.read_text())['sidebar_width']==420
    assert Settings().get('sidebar_width')==421
    assert EDITION.lower() in s._path.parts


def test_new_config_overrides_are_edition_scoped(tmp_path,monkeypatch):
    monkeypatch.setenv('VISIONDB_CRAFT_CONFIG',str(tmp_path))
    s=Settings();s.set('sidebar_width',444)
    assert s._path==tmp_path/EDITION.lower()/'settings.json'
    assert Settings().get('sidebar_width')==444


@pytest.mark.skipif(EDITION!='Plus',reason='Plus model store only')
def test_portable_model_store_survives_restart(tmp_path,monkeypatch):
    from imagecraft.local_ai import ModelManager,default_model_root
    monkeypatch.setattr('imagecraft.paths.application_root',lambda:tmp_path)
    monkeypatch.setenv('VISIONDB_CRAFT_MODEL_DIR',str(tmp_path/'ignored'))
    assert default_model_root()==tmp_path/'models'
    manager=ModelManager();manager.mark_ready('clip-vit-b32')
    assert ModelManager().is_available('clip-vit-b32')
    assert ModelManager().root==tmp_path/'models'


@pytest.mark.skipif(EDITION!='Plus',reason='Plus model store only')
def test_unavailable_model_store_is_reported_without_crash(tmp_path,monkeypatch):
    from imagecraft.local_ai import ModelManager
    occupied=tmp_path/'not-a-folder';occupied.write_text('keep')
    manager=ModelManager(occupied)
    rows=manager.catalog()
    assert rows and all(row['storage_error'] and not row['can_download'] for row in rows)
    assert occupied.read_text()=='keep'
    monkeypatch.setattr('imagecraft.local_ai.shutil.disk_usage',lambda _: (_ for _ in ()).throw(PermissionError('denied')))
    assert all('unavailable' in row['storage_error'] for row in manager.catalog())


@pytest.mark.skipif(EDITION!='Plus',reason='Plus model store only')
def test_missing_checkpoint_has_actionable_inference_error(tmp_path):
    import numpy as np
    from imagecraft.local_ai import ModelManager,LocalAIRunner
    runner=LocalAIRunner(ModelManager(tmp_path/'missing'))
    with pytest.raises(RuntimeError,match='Download'):
        runner.run('clip-vit-b32',np.zeros((8,8,3),dtype=np.uint8),{},lambda:False)
