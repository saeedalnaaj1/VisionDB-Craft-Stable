"""Dataset loading, geometry, validation, splitting, recipes and export tests."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from imagecraft.dataset.analysis import assign_splits, dataset_statistics, validate_dataset
from imagecraft.dataset.exporters import export_dataset
from imagecraft.dataset.geometry import (
    augment_annotations,
    resize_annotations,
    transform_annotations,
)
from imagecraft.dataset.loaders import load_dataset
from imagecraft.dataset.masks import decode_rle, encode_rle
from imagecraft.dataset.models import Annotation
from imagecraft.dataset.recipes import sample_custom_recipe, sample_recipe
from imagecraft.engine import BackendEngine
from imagecraft.models.image_item import ImageItem
from imagecraft.models.transformation import AugmentParams, TransformParams
from imagecraft.settings import Settings
from tests.test_engine import FakeBridge


def make_yolo_dataset(root: Path) -> Path:
    for split in ("train", "val"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[25:75, 50:150] = (255, 255, 255)
    cv2.imwrite(str(root / "images" / "train" / "one.jpg"), image)
    second_image = image.copy()
    second_image[0:10, 0:10] = (50, 100, 150)
    cv2.imwrite(str(root / "images" / "val" / "two.jpg"), second_image)
    (root / "labels" / "train" / "one.txt").write_text("0 0.5 0.5 0.5 0.5\n", encoding="utf-8")
    (root / "labels" / "val" / "two.txt").write_text("1 0.25 0.25 0.2 0.2\n", encoding="utf-8")
    (root / "data.yaml").write_text(
        yaml.safe_dump(
            {
                "path": ".",
                "train": "images/train",
                "val": "images/val",
                "names": ["person", "vehicle"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root


def test_load_yolo_dataset(tmp_path: Path) -> None:
    project = load_dataset(make_yolo_dataset(tmp_path / "dataset"))
    assert project.source_format == "yolo"
    assert project.class_names == ["person", "vehicle"]
    assert len(project.records) == 2
    assert {record.split for record in project.records} == {"train", "val"}
    assert project.records[0].width == 200
    assert project.records[0].annotations[0].label in {"person", "vehicle"}


def test_load_classification_and_yolo_polygon_datasets(tmp_path: Path) -> None:
    classification = tmp_path / "classification"
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    for name in ("cat", "dog"):
        folder = classification / "train" / name
        folder.mkdir(parents=True)
        cv2.imwrite(str(folder / f"{name}.jpg"), image)
    project = load_dataset(classification)
    assert project.task_type == "classification"
    assert project.class_names == ["cat", "dog"]
    assert all(
        record.annotations[0].annotation_type == "classification"
        for record in project.records
    )

    segmentation = make_yolo_dataset(tmp_path / "segmentation")
    (segmentation / "labels" / "train" / "one.txt").write_text(
        "0 0.1 0.1 0.8 0.1 0.8 0.8 0.1 0.8\n", encoding="utf-8"
    )
    polygon_project = load_dataset(segmentation)
    assert polygon_project.task_type == "segmentation"
    assert polygon_project.records[0].annotations[0].polygon is not None

    items = [
        ImageItem(
            record.image_path, None, original_annotations=record.annotations,
            dataset_split=record.split, source_width=record.width,
            source_height=record.height, lazy=True,
        )
        for record in project.records
    ]
    exported = export_dataset(
        project, items, tmp_path / "classification-export", "yolo",
        validate_dataset(project, items),
    )
    output = Path(exported["path"])
    assert (output / "train" / "cat" / "cat.jpg").is_file()
    assert (output / "train" / "dog" / "dog.jpg").is_file()


def test_annotation_geometry_crop_flip_and_padding() -> None:
    annotation = Annotation(0, 0.5, 0.5, 0.4, 0.4, "object")
    cropped = transform_annotations(
        [annotation],
        TransformParams(
            tr_x=200,
            br_x=200,
            br_y=100,
            bl_y=100,
            crop_x=50,
            crop_y=0,
            crop_w=100,
            crop_h=100,
        ),
        200,
        100,
    )
    assert len(cropped) == 1
    assert abs(cropped[0].x_center - 0.5) < 1e-6
    assert abs(cropped[0].width - 0.8) < 1e-6

    flipped = augment_annotations(
        [Annotation(0, 0.25, 0.5, 0.2, 0.2)],
        AugmentParams(
            flip_horizontal=True, padding_enabled=True, padding_width=300, padding_height=100
        ),
        200,
        100,
    )
    assert len(flipped) == 1
    assert abs(flipped[0].x_center - (200 / 300 * 0.75 + 50 / 300)) < 1e-6


def test_coco_rle_roundtrip_and_mask_geometry() -> None:
    mask = np.zeros((30, 40), dtype=np.uint8)
    mask[5:20, 8:32] = 1
    mask[10:15, 14:18] = 0
    for compressed in (False, True):
        encoded = encode_rle(mask, compressed=compressed)
        assert np.array_equal(decode_rle(encoded), mask)

    annotation = Annotation(
        0, 0.5, 0.4166667, 0.6, 0.5, "object",
        annotation_type="mask", mask_rle=encode_rle(mask),
    )
    resized = resize_annotations([annotation], 80, 60)
    assert decode_rle(resized[0].mask_rle).shape == (60, 80)
    flipped = augment_annotations(
        [annotation], AugmentParams(flip_horizontal=True), 40, 30
    )
    flipped_mask = decode_rle(flipped[0].mask_rle)
    assert np.array_equal(flipped_mask, np.fliplr(mask))


def test_load_and_export_coco_rle_mask(tmp_path: Path) -> None:
    root = tmp_path / "coco-mask"
    (root / "annotations").mkdir(parents=True)
    (root / "images" / "train").mkdir(parents=True)
    image = np.zeros((24, 32, 3), dtype=np.uint8)
    cv2.imwrite(str(root / "images" / "train" / "one.png"), image)
    mask = np.zeros((24, 32), dtype=np.uint8)
    mask[4:18, 7:25] = 1
    payload = {
        "images": [{"id": 1, "file_name": "one.png", "width": 32, "height": 24}],
        "categories": [{"id": 3, "name": "thing"}],
        "annotations": [{
            "id": 1, "image_id": 1, "category_id": 3,
            "bbox": [7, 4, 18, 14], "segmentation": encode_rle(mask),
            "area": int(mask.sum()), "iscrowd": 0,
        }],
    }
    (root / "annotations" / "instances_train.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    project = load_dataset(root)
    annotation = project.records[0].annotations[0]
    assert project.task_type == "segmentation"
    assert annotation.annotation_type == "mask"
    assert np.array_equal(decode_rle(annotation.mask_rle), mask)

    record = project.records[0]
    item = ImageItem(
        record.image_path, None, original_annotations=record.annotations,
        dataset_split=record.split, source_width=record.width,
        source_height=record.height, lazy=True,
    )
    validation = validate_dataset(project, [item])
    coco = export_dataset(project, [item], tmp_path / "exports-coco", "coco", validation)
    exported_json = next((Path(coco["path"]) / "annotations").glob("*.json"))
    exported_payload = json.loads(exported_json.read_text(encoding="utf-8"))
    exported_rle = exported_payload["annotations"][0]["segmentation"]
    assert np.array_equal(decode_rle(exported_rle), mask)

    png = export_dataset(project, [item], tmp_path / "exports-png", "mask", validation)
    png_root = Path(png["path"])
    mask_path = next((png_root / "masks").rglob("*.png"))
    exported_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal((exported_mask > 0).astype(np.uint8), mask)


def test_engine_dataset_flow_preserves_annotations(tmp_path: Path) -> None:
    root = make_yolo_dataset(tmp_path / "dataset")
    bridge = FakeBridge(folder_path=root)
    engine = BackendEngine(bridge=bridge, settings=Settings(path=tmp_path / "settings.json"))
    state = engine.open_dataset_dialog()
    assert state["dataset"]["active"] is True
    assert state["count"] == 2
    assert state["images"][0]["annotations"] == 1
    assert state["workspace"] == {"kind": "dataset"}
    preview = engine.get_preview()
    assert len(preview["annotations"]) == 1

    applied = engine.apply("resize", {"width": 100, "height": 50})
    assert applied["images"][0]["w"] == 100
    assert applied["images"][0]["annotations"] == 1
    engine.undo()
    assert engine.get_state()["images"][0]["w"] == 200

    cropped = engine.apply(
        "transform",
        {
            "tr_x": 200,
            "br_x": 200,
            "br_y": 100,
            "bl_y": 100,
            "crop_x": 50,
            "crop_y": 0,
            "crop_w": 100,
            "crop_h": 100,
        },
    )
    assert cropped["images"][0]["w"] == 100
    assert abs(engine.get_preview()["annotations"][0]["w"] - 1.0) < 1e-6
    engine.undo()
    assert abs(engine.get_preview()["annotations"][0]["w"] - 0.5) < 1e-6
    engine.redo()
    assert abs(engine.get_preview()["annotations"][0]["w"] - 1.0) < 1e-6


def test_wrong_folder_opener_warns_before_ignoring_dataset_labels(tmp_path: Path) -> None:
    root = make_yolo_dataset(tmp_path / "dataset")
    engine = BackendEngine(
        bridge=FakeBridge(folder_path=root),
        settings=Settings(path=tmp_path / "settings.json"),
    )

    result = engine.open_folder_dialog()

    assert result["requires_confirmation"] == "dataset_detected"
    assert result["dataset"]["format"] == "yolo"
    assert engine.get_state()["count"] == 0


def test_engine_splits_and_generates_annotated_variants(tmp_path: Path) -> None:
    root = make_yolo_dataset(tmp_path / "dataset")
    engine = BackendEngine(
        bridge=FakeBridge(folder_path=root),
        settings=Settings(path=tmp_path / "settings.json"),
    )
    engine.open_dataset_dialog()
    split = engine.split_current_dataset(50, 50, 0, 7)
    assert split["ok"] is True
    assert sum(split["counts"].values()) == 2
    generated = engine.generate_dataset_variants("balanced", 1, 99)
    assert generated["ok"] is True
    assert generated["generated"] == 2
    assert generated["count"] == 4
    generated_rows = [row for row in generated["images"] if row["generated"]]
    assert len(generated_rows) == 2
    assert all(row["annotations"] == 1 for row in generated_rows)


def test_corrupt_dataset_item_is_reported_without_blocking_project_open(
    tmp_path: Path,
) -> None:
    root = tmp_path / "corrupt"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "images" / "train" / "broken.jpg").write_bytes(b"not an image")
    (root / "labels" / "train" / "broken.txt").write_text("", encoding="utf-8")
    (root / "data.yaml").write_text("train: images/train\nnames: [object]\n", encoding="utf-8")
    engine = BackendEngine(
        bridge=FakeBridge(folder_path=root),
        settings=Settings(path=tmp_path / "settings.json"),
    )
    state = engine.open_dataset_dialog()
    assert state["dataset"]["active"] is True
    assert "error" in engine.get_preview()
    report = engine.validate_current_dataset()
    assert any(issue["code"] == "corrupt_image" for issue in report["issues"])


def test_validation_statistics_and_deterministic_split(tmp_path: Path) -> None:
    project = load_dataset(make_yolo_dataset(tmp_path / "dataset"))
    items = [
        ImageItem(
            record.image_path,
            None,
            original_annotations=record.annotations,
            annotation_path=record.annotation_path,
            dataset_split=record.split,
            source_width=record.width,
            source_height=record.height,
            lazy=True,
        )
        for record in project.records
    ]
    report = validate_dataset(project, items)
    stats = dataset_statistics(project, items)
    assert report["summary"]["errors"] == 0
    assert stats["images"] == 2 and stats["objects"] == 2
    first = assign_splits(items, 0.5, 0.5, 0.0, 123)
    assignments = [item.dataset_split for item in items]
    second = assign_splits(items, 0.5, 0.5, 0.0, 123)
    assert first == second == {"train": 1, "val": 1}
    assert assignments == [item.dataset_split for item in items]


def test_recipes_are_reproducible() -> None:
    first = sample_recipe("balanced", 42, 3, 1)
    second = sample_recipe("balanced", 42, 3, 1)
    different = sample_recipe("balanced", 43, 3, 1)
    assert first == second
    assert first != different


def test_custom_recipe_ranges_are_reproducible_and_validated() -> None:
    ranges = {
        "rotation": [-8, 8],
        "exposure": [-0.5, 0.25],
        "flip_horizontal_probability": 50,
    }
    first = sample_custom_recipe(ranges, 77, 2, 4)
    second = sample_custom_recipe(ranges, 77, 2, 4)

    assert first == second
    assert -8 <= first["rotation"] <= 8
    assert -0.5 <= first["exposure"] <= 0.25
    assert isinstance(first["flip_horizontal"], bool)


def test_safe_export_yolo_coco_and_voc(tmp_path: Path) -> None:
    source = make_yolo_dataset(tmp_path / "source")
    project = load_dataset(source)
    items = [
        ImageItem(
            record.image_path,
            None,
            original_annotations=record.annotations,
            annotation_path=record.annotation_path,
            dataset_split=record.split,
            source_width=record.width,
            source_height=record.height,
            lazy=True,
        )
        for record in project.records
    ]
    report = validate_dataset(project, items)
    destination = tmp_path / "exports"
    for target_format in ("yolo", "coco", "voc"):
        result = export_dataset(project, items, destination, target_format, report)
        output = Path(result["path"])
        assert output.is_dir()
        assert result["saved"] == 2
        manifest = json.loads((output / "imagecraft_manifest.json").read_text(encoding="utf-8"))
        assert manifest["target_format"] == target_format
        assert manifest["application_version"] == "3.6.0"
        assert manifest["source_preserved"] is True
        reopened = load_dataset(output)
        assert reopened.source_format == target_format
        assert len(reopened.records) == 2
        assert reopened.class_names == ["person", "vehicle"]
        assert {record.split for record in reopened.records} == {"train", "val"}
    assert (source / "data.yaml").is_file()


def test_exporter_rejects_formats_that_cannot_represent_the_task(tmp_path: Path) -> None:
    source = make_yolo_dataset(tmp_path / "source-seg")
    project = load_dataset(source)
    project.task_type = "segmentation"
    items = [
        ImageItem(
            record.image_path,
            None,
            original_annotations=record.annotations,
            dataset_split=record.split,
            source_width=record.width,
            source_height=record.height,
            lazy=True,
        )
        for record in project.records
    ]
    with pytest.raises(ValueError, match="VOC is not valid for segmentation"):
        export_dataset(project, items, tmp_path / "invalid", "voc", {})
