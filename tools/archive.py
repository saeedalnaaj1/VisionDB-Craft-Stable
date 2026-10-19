"""Produce deterministic ZIP entries with a single top-level application folder."""
import sys
import zipfile
from pathlib import Path


def archive(folder: Path, output: Path):
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
            info=zipfile.ZipInfo(str(p.relative_to(folder.parent)).replace('\\','/'),date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,p.read_bytes())

if __name__=='__main__':archive(Path(sys.argv[1]),Path(sys.argv[2]))
