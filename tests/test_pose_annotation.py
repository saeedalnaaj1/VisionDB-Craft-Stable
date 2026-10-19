"""Pose annotation, geometry, import, and export regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from imagecraft.dataset.analysis import validate_dataset
from imagecraft.dataset.exporters import export_dataset
from imagecraft.dataset.geometry import augment_annotations
from imagecraft.dataset.loaders import load_dataset
from imagecraft.dataset.models import Annotation, DatasetProject
from imagecraft.dataset.pose import normalize_keypoints, pose_schema
from imagecraft.engine import BackendEngine
from imagecraft.models.image_item import ImageItem
from imagecraft.models.transformation import AugmentParams
from imagecraft.settings import Settings
from tests.test_engine import FakeBridge


def _image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.zeros((100, 200, 3), dtype=np.uint8))
    return path


def _points(schema_id: str, placements: dict[int, tuple[float, float, int]]) -> list[dict]:
    raw: list[dict] = []
    count = len(pose_schema(schema_id)["names"])
    for index in range(count):
        x, y, visibility = placements.get(index, (0.0, 0.0, 0))
        raw.append(
            {
                "x": x,
                "y": y,
                "z": 0.0,
                "visibility": visibility,
                "presence": 1.0 if visibility else 0.0,
            }
        )
    return normalize_keypoints(raw, schema_id)


def test_engine_pose_creation_keypoint_edit_history_and_roundtrip(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "person.png")
    settings = Settings(path=tmp_path / "settings.json")
    settings.set("annotation_autosave", False)
    engine = BackendEngine(bridge=FakeBridge(open_path=image_path), settings=settings)
    engine.open_image_dialog()

    created = engine.create_annotation(
        "pose",
        0,
        {
            "pose_schema": "mediapipe_33",
            "pose_workflow": "bottom_up",
            "pose_has_bbox": False,
            "keypoints": _points("mediapipe_33", {0: (0.4, 0.2, 2), 11: (0.3, 0.5, 1)}),
        },
    )
    assert created["ok"] is True
    pose = created["annotation_editor"]["annotations"][0]
    assert pose["type"] == "pose"
    assert pose["pose_has_bbox"] is False
    assert len(pose["keypoints"]) == 33
    assert created["annotation_editor"]["type_counts_current"]["pose"] == 1

    moved = engine.update_pose_keypoint(0, 0, 0.6, 0.25, 2)
    assert moved["ok"] is True
    assert moved["annotation_editor"]["annotations"][0]["keypoints"][0]["x"] == 0.6
    assert moved["history_timeline"]["entries"][-1]["changes"][0]["value"] == "move_keypoint"
    undone = engine.undo()
    assert undone["annotation_editor"]["annotations"][0]["keypoints"][0]["x"] == 0.4
    redone = engine.redo()
    assert redone["annotation_editor"]["annotations"][0]["keypoints"][0]["x"] == 0.6

    project_path = tmp_path / "pose.imagecraft"
    saved = engine.save_project({"active_mode": "annotate"}, str(project_path))
    assert saved["ok"] is True
    reopened = BackendEngine(settings=Settings(path=tmp_path / "settings-2.json"))
    assert reopened.open_project_path(str(project_path))["ok"] is True
    restored = reopened.get_state()["annotation_editor"]["annotations"][0]
    assert restored["pose_schema"] == "mediapipe_33"
    assert restored["keypoints"][11]["visibility"] == 1


def test_pose_horizontal_flip_swaps_left_and_right_semantics() -> None:
    annotation = Annotation(
        0,
        0.5,
        0.5,
        0.8,
        0.8,
        "person",
        annotation_type="pose",
        keypoints=_points("coco_17", {9: (0.1, 0.5, 2), 10: (0.7, 0.5, 2)}),
        pose_schema="coco_17",
        pose_workflow="top_down",
        pose_has_bbox=True,
    )
    flipped = augment_annotations([annotation], AugmentParams(flip_horizontal=True), 200, 100)[0]
    assert flipped.keypoints is not None
    assert flipped.keypoints[9]["name"] == "left_wrist"
    assert abs(float(flipped.keypoints[9]["x"]) - 0.3) < 1e-6
    assert abs(float(flipped.keypoints[10]["x"]) - 0.9) < 1e-6


def test_pose_exports_and_imports_yolo_coco_and_mediapipe(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "source" / "person.png")
    coco_pose = Annotation(
        0,
        0.5,
        0.5,
        0.6,
        0.8,
        "person",
        annotation_type="pose",
        keypoints=_points("coco_17", {0: (0.5, 0.2, 2), 9: (0.3, 0.55, 1)}),
        pose_schema="coco_17",
        pose_workflow="top_down",
        pose_has_bbox=True,
    )
    pixels = np.zeros((100, 200, 3), dtype=np.uint8)
    item = ImageItem(image_path, pixels, original_annotations=[coco_pose], dataset_split="train")
    project = DatasetProject(
        root=image_path.parent,
        name="pose",
        source_format="imagecraft",
        class_names=["person"],
        records=[],
        task_type="pose",
    )
    validation = validate_dataset(project, [item])

    yolo = export_dataset(project, [item], tmp_path / "exports", "yolo_pose", validation)
    yolo_root = Path(yolo["path"])
    config = yaml.safe_load((yolo_root / "data.yaml").read_text(encoding="utf-8"))
    assert config["kpt_shape"] == [17, 3]
    assert config["flip_idx"][1:3] == [2, 1]
    label = next((yolo_root / "labels").rglob("*.txt")).read_text(encoding="utf-8")
    assert len(label.split()) == 1 + 4 + 17 * 3
    imported_yolo = load_dataset(yolo_root)
    assert imported_yolo.task_type == "pose"
    assert imported_yolo.records[0].annotations[0].pose_schema == "coco_17"

    coco = export_dataset(project, [item], tmp_path / "exports", "coco_keypoints", validation)
    coco_root = Path(coco["path"])
    coco_payload = json.loads(
        next((coco_root / "annotations").glob("*.json")).read_text(encoding="utf-8")
    )
    assert len(coco_payload["categories"][0]["keypoints"]) == 17
    assert coco_payload["annotations"][0]["num_keypoints"] == 2
    assert len(coco_payload["annotations"][0]["keypoints"]) == 51
    imported_coco = load_dataset(coco_root)
    assert imported_coco.task_type == "pose"
    assert imported_coco.records[0].annotations[0].annotation_type == "pose"

    media_pose = Annotation(
        0,
        0.5,
        0.5,
        0.2,
        0.4,
        "person",
        annotation_type="pose",
        keypoints=_points("mediapipe_33", {0: (0.5, 0.2, 2), 11: (0.4, 0.45, 2)}),
        pose_schema="mediapipe_33",
        pose_workflow="bottom_up",
        pose_has_bbox=False,
    )
    media_item = ImageItem(
        image_path, pixels, original_annotations=[media_pose], dataset_split="train"
    )
    media = export_dataset(
        project,
        [media_item],
        tmp_path / "exports",
        "mediapipe",
        validate_dataset(project, [media_item]),
    )
    media_payload = json.loads(
        next((Path(media["path"]) / "annotations").glob("*.json")).read_text(encoding="utf-8")
    )
    landmarks = media_payload["images"][0]["poses"][0]["normalized_landmarks"]
    assert len(landmarks) == 33
    assert landmarks[0]["visibility"] == 1.0


def test_backend_rejects_non_pose_export_format(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "person.png")
    destination = tmp_path / "exports"
    settings = Settings(path=tmp_path / "settings.json")
    settings.set("annotation_export_directory", str(destination))
    settings.set("annotation_autosave", False)
    engine = BackendEngine(bridge=FakeBridge(open_path=image_path), settings=settings)
    engine.open_image_dialog()
    engine.create_annotation(
        "pose",
        0,
        {
            "pose_schema": "coco_17",
            "pose_workflow": "top_down",
            "pose_has_bbox": True,
            "x": 0.5,
            "y": 0.5,
            "w": 0.6,
            "h": 0.8,
            "keypoints": _points("coco_17", {0: (0.5, 0.2, 2)}),
        },
    )
    invalid = engine.export_annotations("voc", "all", "pose")
    assert invalid["ok"] is False
    assert "not valid for pose" in invalid["message"]
