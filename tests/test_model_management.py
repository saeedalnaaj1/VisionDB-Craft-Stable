import pytest
from imagecraft.edition import EDITION
pytestmark=pytest.mark.skipif(EDITION!="Plus",reason="AI only in Plus")

def test_download_does_not_require_inference_libraries(tmp_path,monkeypatch):
    from imagecraft.local_ai import ModelManager
    monkeypatch.setattr("imagecraft.local_ai.importlib.util.find_spec",lambda name: None)
    manager=ModelManager(tmp_path)
    sam=next(x for x in manager.catalog() if x["id"]=="mobile-sam-vit-t")
    assert sam["missing_dependencies"]
    assert sam["download_dependencies"]==[]
    assert sam["can_download"]

def test_delete_model_preserves_other_files_and_rejects_escape(tmp_path):
    from imagecraft.local_ai import ModelManager
    manager=ModelManager(tmp_path/"models")
    manager.mark_ready("clip-vit-b32")
    other=tmp_path/"keep.txt";other.write_text("keep")
    assert manager.delete("clip-vit-b32")["ok"]
    assert not manager.is_available("clip-vit-b32")
    assert other.read_text()=="keep"
    with pytest.raises(ValueError):manager.delete("../keep.txt")
    manager.root.mkdir(exist_ok=True)
    manager.path("clip-vit-b32").symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError):manager.delete("clip-vit-b32")


def test_pose_download_stays_portable_without_inference_runtime(tmp_path,monkeypatch):
    import io,zipfile
    from imagecraft.local_ai import ModelManager,MODELS
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,"w") as archive:archive.writestr("nested/model.onnx",b"checkpoint")
    payload=memory.getvalue()
    monkeypatch.setattr("imagecraft.local_ai.importlib.util.find_spec",lambda name: None)
    monkeypatch.setattr("imagecraft.local_ai.urllib.request.urlopen",lambda *a,**k:io.BytesIO(payload))
    manager=ModelManager(tmp_path/"models")
    model=next(m for m in MODELS if m.download_kind=="runtime")
    manager.download(model.id,lambda *a:None,lambda:False)
    assert manager.is_available(model.id)
    assert (manager.path(model.id)/"detector.onnx").read_bytes()==b"checkpoint"
    assert (manager.path(model.id)/"pose.onnx").read_bytes()==b"checkpoint"
    assert not list(manager.path(model.id).glob("*.part"))
