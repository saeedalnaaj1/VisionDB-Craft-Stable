"""Frozen executable entry point and headless release smoke test."""
from __future__ import annotations
import json
import sys
from pathlib import Path


def main() -> int:
    if '--self-test' in sys.argv:
        from imagecraft.edition import APP_TITLE, EDITION, MODES
        from imagecraft.engine import BackendEngine
        from imagecraft.settings import Settings
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            engine = BackendEngine(settings=Settings(Path(directory)/'settings.json'))
            assert engine.get_app_info()['name'] == APP_TITLE
            assert engine.get_state()['count'] == 0
            for mode in MODES:
                assert engine.set_working_mode(mode)['ok']
            if EDITION == 'Stable':
                assert not hasattr(engine,'download_local_ai_model')
                assert not hasattr(engine,'preview_auto_annotations')
                assert not any(m in sys.modules for m in ('imagecraft.local_ai','imagecraft.plus_features','torch','transformers'))
            else:
                assert engine.get_local_ai_state()['ok']
                assert engine.get_auto_annotate_state()['ok']
            ui = Path(__import__('imagecraft').__file__).resolve().parent/'ui'
            for name in ('index.html','js/app.js','assets/visiondb-craft.ico','assets/visiondb-craft-logo.svg'):
                assert (ui/name).is_file(), name
            report={'ok':True,'edition':EDITION,'modes':MODES,'ui_resources':True}
        if '--report' in sys.argv:
            Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps(report,indent=2))
        else:
            print(json.dumps(report))
        return 0
    from imagecraft.main import main as start
    return start()

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        error=traceback.format_exc()
        try:
            from imagecraft.paths import config_root
            path=config_root()/'startup-error.log';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(error)
            message=f'VisionDB Craft could not start.\n\nDetails: {path}\n\n{error[-1800:]}'
        except Exception:
            message=error
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'VisionDB Craft startup error',0x10)
        else:
            print(message,file=sys.stderr)
        raise SystemExit(1)
