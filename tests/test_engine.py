"""Headless tests for ``imagecraft.engine.BackendEngine`` using a fake bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from imagecraft.dataset.masks import decode_rle
from imagecraft.engine import BackendEngine
from imagecraft.settings import Settings


class FakeBridge:
    """Records evaluate_js calls and returns canned dialog answers."""

    def __init__(
        self,
        open_path: Path | None = None,
        folder_path: Path | None = None,
        save_path: Path | None = None,
    ) -> None:
        self.open_path = str(open_path) if open_path else None
        self.folder_path = str(folder_path) if folder_path else None
        self.save_path = str(save_path) if save_path else None
        self.events: list[str] = []

    def evaluate_js(self, code: str) -> None:
        self.events.append(code)

    def open_file_dialog(self, allow_multiple: bool = False, file_types: tuple[str, ...] = ()):
        return [self.open_path] if self.open_path else None

    def open_folder_dialog(self) -> str | None:
        return self.folder_path

    def save_file_dialog(self, save_as: str, file_types: tuple[str, ...] = ()):
        return self.save_path

    def move_window(self, x: int, y: int) -> None: ...
    def minimize_window(self) -> None: ...
    def toggle_maximize(self) -> None: ...
    def close_window(self) -> None: ...


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    img = np.zeros((80, 120, 3), dtype=np.uint8)
    img[:, :60] = (200, 40, 40)
    img[:, 60:] = (40, 200, 40)
    img[20:60, 40:80] = (255, 255, 255)
    single = tmp_path / "single"
    single.mkdir(exist_ok=True)
    path = single / "sample.png"
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return path


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    for i in range(3):
        img = np.full((40, 40, 3), 30 + i * 20, dtype=np.uint8)
        cv2.imwrite(str(tmp_path / f"img{i}.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return tmp_path


def make_engine(bridge: FakeBridge) -> BackendEngine:
    settings = Settings(path=Path("/nonexistent/settings.json"))
    engine = BackendEngine(bridge=bridge, settings=settings)
    return engine


def test_open_image_dialog_loads_and_defaults_match_dims(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    state = engine.open_image_dialog()

    assert state.get("ok", True) is not False
    assert state["count"] == 1
    assert state["current_path"] == "sample.png"
    d = state["defaults"]["transform"]
    assert d["tr_x"] == 120 and d["br_y"] == 80
    assert d["crop_top"] == 0 and d["crop_bottom"] == 0
    assert d["crop_left"] == 0 and d["crop_right"] == 0


def test_cancelled_openers_preserve_the_complete_current_workspace(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()
    engine.create_annotation("bbox", 0, {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2})
    before = engine.get_state()

    bridge.open_path = None
    bridge.folder_path = None
    assert engine.open_image_dialog()["cancelled"] is True
    assert engine.open_folder_dialog()["cancelled"] is True
    after = engine.get_state()

    assert after["current_path"] == before["current_path"]
    assert after["images"] == before["images"]
    assert after["history_timeline"] == before["history_timeline"]
    assert after["annotation_editor"] == before["annotation_editor"]


def test_discard_session_unloads_work_without_deleting_source(image_file: Path) -> None:
    engine = make_engine(FakeBridge(open_path=image_file))
    engine.open_image_dialog()
    engine.set_working_mode("annotate")
    engine.create_annotation("bbox", 0, {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2})

    discarded = engine.discard_session()

    assert discarded["ok"] is True
    assert discarded["count"] == 0
    assert discarded["images"] == []
    assert discarded["current_path"] is None
    assert discarded["workspace"] == {"kind": "empty"}
    assert discarded["working_mode"] == "annotate"
    assert discarded["history"] == {"can_undo": False, "can_redo": False}
    assert discarded["history_timeline"]["entries"] == []
    assert discarded["project"]["path"] is None
    assert discarded["auto_annotate_preview"]["candidates"] == []
    assert discarded["has_unsaved_work"] is False
    assert image_file.is_file()


def test_portable_project_round_trip_restores_history_ui_and_embedded_media(
    image_file: Path, tmp_path: Path
) -> None:
    settings = Settings(path=tmp_path / "project-settings.json")
    settings.set("annotation_autosave", False)
    engine = BackendEngine(bridge=FakeBridge(open_path=image_file), settings=settings)
    engine.open_image_dialog()
    engine.set_working_mode("annotate")
    engine.create_annotation("bbox", 0, {"x": 0.4, "y": 0.5, "w": 0.25, "h": 0.3})
    engine.apply("resize", {"width": 60, "height": 40})
    project_path = tmp_path / "resume.imagecraft"
    ui_state = {
        "active_tool": "annotation",
        "viewer": {
            "scale": 2.0,
            "offsetX": -123.5,
            "offsetY": 44.25,
            "mode": "custom",
            "naturalW": 60,
            "naturalH": 40,
        },
    }

    saved = engine.save_project(ui_state, str(project_path))
    assert saved["ok"] is True
    assert project_path.is_file()
    assert saved["has_unsaved_work"] is False

    # A project is portable: embedded media still opens if the source moved.
    image_file.unlink()
    restored_engine = BackendEngine(settings=Settings(path=tmp_path / "restored.json"))
    restored = restored_engine.open_project_path(str(project_path))

    assert restored["ok"] is True
    assert restored["working_mode"] == "annotate"
    assert restored["missing_media"] == [str(image_file)]
    assert restored["project"]["ui_state"] == ui_state
    assert restored["images"][0]["w"] == 60
    assert restored["images"][0]["h"] == 40
    assert restored["images"][0]["annotations"] == 1
    assert restored_engine.get_preview()["dataUrl"].startswith("data:image/")

    undo_resize = restored_engine.undo()
    assert (undo_resize["images"][0]["w"], undo_resize["images"][0]["h"]) == (120, 80)
    assert undo_resize["images"][0]["annotations"] == 1
    undo_annotation = restored_engine.undo()
    assert undo_annotation["images"][0]["annotations"] == 0
    assert restored_engine.redo()["images"][0]["annotations"] == 1
    redo_resize = restored_engine.redo()
    assert (redo_resize["images"][0]["w"], redo_resize["images"][0]["h"]) == (60, 40)


def test_annotation_aware_practice_covers_box_polygon_and_rle_mask(tmp_path: Path) -> None:
    settings = Settings(path=tmp_path / "awareness-settings.json")
    settings.set("annotation_autosave", False)
    engine = BackendEngine(settings=settings)
    opened = engine.open_transform_practice_image()
    original = opened["annotation_editor"]["annotations"]

    assert opened["working_mode"] == "transform"
    assert [annotation["type"] for annotation in original] == ["bbox", "polygon", "mask"]
    assert decode_rle(original[2]["mask_rle"]).any()

    transformed = engine.apply(
        "transform",
        {"rotation": 17, "translate_x": 20, "translate_y": -10, "annotation_aware": True},
    )["annotation_editor"]["annotations"]
    assert transformed != original
    assert [annotation["type"] for annotation in transformed] == ["bbox", "polygon", "mask"]
    assert decode_rle(transformed[2]["mask_rle"]).any()

    engine.undo()
    unchanged = engine.apply(
        "augment", {"flip_horizontal": True, "annotation_aware": False}
    )["annotation_editor"]["annotations"]
    assert unchanged == original


def test_annotation_workspace_creates_autosaves_and_undoes(image_file, tmp_path):
    settings = Settings(path=tmp_path / "annotation-settings.json")
    settings.set("annotation_classes", [])  # migrate the broken first-release setting
    engine = BackendEngine(bridge=FakeBridge(open_path=image_file), settings=settings)
    opened = engine.open_image_dialog()
    assert opened["annotation_editor"]["classes"] == ["object"]
    added_class = engine.add_annotation_class("vehicle")
    assert added_class["ok"] is True

    box = engine.create_annotation("bbox", 0, {"x": 0.5, "y": 0.5, "w": 0.4, "h": 0.3})
    assert box["annotation_editor"]["annotations"][0]["type"] == "bbox"
    polygon = engine.create_annotation(
        "polygon", 0, {"polygon": [[0.1, 0.1], [0.5, 0.1], [0.3, 0.5]]}
    )
    assert polygon["annotation_editor"]["annotations"][1]["type"] == "polygon"
    classification = engine.create_annotation("classification", 0, {})
    assert len(classification["annotation_editor"]["annotations"]) == 3
    redrawn = engine.update_annotation_geometry(
        0, {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}
    )
    assert redrawn["annotation_editor"]["annotations"][0]["w"] == 0.2

    sidecar = image_file.parent / ".imagecraft" / "annotations" / "sample.json"
    assert sidecar.is_file()
    deleted = engine.delete_annotation(1)
    assert len(deleted["annotation_editor"]["annotations"]) == 2
    restored = engine.undo()
    assert len(restored["annotation_editor"]["annotations"]) == 3


def test_annotation_log_reclassifies_and_deletes_with_history(image_file, tmp_path):
    settings = Settings(path=tmp_path / "annotation-log-settings.json")
    engine = BackendEngine(bridge=FakeBridge(open_path=image_file), settings=settings)
    engine.open_image_dialog()
    engine.add_annotation_class("vehicle")
    engine.create_annotation("bbox", 0, {"x": 0.5, "y": 0.5, "w": 0.4, "h": 0.3})

    changed = engine.update_annotation(0, 1)
    assert changed["ok"] is True
    assert changed["annotation_editor"]["annotations"][0]["class_id"] == 1
    assert changed["annotation_editor"]["annotations"][0]["label"] == "vehicle"
    assert engine.undo()["annotation_editor"]["annotations"][0]["class_id"] == 0
    assert engine.redo()["annotation_editor"]["annotations"][0]["class_id"] == 1

    deleted = engine.delete_annotation(0)
    assert deleted["annotation_editor"]["annotations"] == []
    assert len(engine.undo()["annotation_editor"]["annotations"]) == 1


def test_annotations_can_be_moved_and_resized_with_undo(image_file, tmp_path):
    settings = Settings(path=tmp_path / "annotation-transform-settings.json")
    engine = BackendEngine(bridge=FakeBridge(open_path=image_file), settings=settings)
    engine.open_image_dialog()

    engine.create_annotation("bbox", 0, {"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2})
    moved = engine.transform_annotation_geometry(
        0, {"x": 0.6, "y": 0.65, "w": 0.2, "h": 0.2, "action": "move"}
    )
    moved_box = moved["annotation_editor"]["annotations"][0]
    assert (moved_box["x"], moved_box["y"], moved_box["w"], moved_box["h"]) == pytest.approx(
        (0.6, 0.65, 0.2, 0.2)
    )
    assert moved["history_timeline"]["entries"][-1]["changes"][0]["value"] == "move"

    undone = engine.undo()
    original_box = undone["annotation_editor"]["annotations"][0]
    assert (original_box["x"], original_box["y"]) == pytest.approx((0.3, 0.3))
    engine.redo()

    engine.create_annotation(
        "polygon", 0, {"polygon": [[0.1, 0.1], [0.3, 0.1], [0.2, 0.3]]}
    )
    resized_polygon = engine.transform_annotation_geometry(
        1, {"x": 0.6, "y": 0.6, "w": 0.4, "h": 0.2, "action": "resize"}
    )["annotation_editor"]["annotations"][1]
    np.testing.assert_allclose(
        np.asarray(resized_polygon["polygon"]),
        np.asarray([[0.4, 0.5], [0.8, 0.5], [0.6, 0.7]]),
    )

    engine.create_annotation(
        "mask",
        0,
        {
            "brush_size": 10,
            "strokes": [{"points": [[0.15, 0.2], [0.3, 0.35]], "erase": False}],
        },
    )
    moved_mask = engine.transform_annotation_geometry(
        2, {"x": 0.75, "y": 0.7, "w": 0.2, "h": 0.25, "action": "resize"}
    )["annotation_editor"]["annotations"][2]
    assert moved_mask["type"] == "mask"
    assert decode_rle(moved_mask["mask_rle"]).any()
    assert (moved_mask["x"], moved_mask["y"]) == pytest.approx((0.75, 0.7), abs=0.02)
    assert (moved_mask["w"], moved_mask["h"]) == pytest.approx((0.2, 0.25), abs=0.03)

    engine.create_annotation("classification", 0)
    refused = engine.transform_annotation_geometry(
        3, {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5, "action": "resize"}
    )
    assert refused["ok"] is False
    assert "classifications" in refused["message"]

    outside = engine.transform_annotation_geometry(
        0, {"x": 0.95, "y": 0.5, "w": 0.2, "h": 0.2, "action": "move"}
    )
    assert outside["ok"] is False


def test_mask_brush_class_management_import_and_custom_locations(image_file, tmp_path):
    settings = Settings(path=tmp_path / "annotation-settings.json")
    bridge = FakeBridge(open_path=image_file)
    engine = BackendEngine(bridge=bridge, settings=settings)
    engine.open_image_dialog()

    painted = engine.create_annotation(
        "mask",
        0,
        {
            "brush_size": 12,
            "strokes": [
                {"points": [[0.2, 0.2], [0.8, 0.8]], "erase": False},
                {"points": [[0.5, 0.5]], "erase": True},
            ],
        },
    )
    row = painted["annotation_editor"]["annotations"][0]
    assert row["type"] == "mask"
    mask = decode_rle(row["mask_rle"])
    assert mask.shape == (80, 120) and mask.any()
    edited = engine.update_annotation_geometry(
        0,
        {
            "base_mask_rle": row["mask_rle"],
            "strokes": [{"points": [[0.3, 0.3], [0.7, 0.7]], "erase": True,
                         "brush_size": 18}],
        },
    )
    edited_mask = decode_rle(edited["annotation_editor"]["annotations"][0]["mask_rle"])
    assert edited_mask.sum() < mask.sum()

    engine.add_annotation_class("vehicle")
    engine.create_annotation("bbox", 1, {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2})
    renamed = engine.rename_annotation_class(1, "car")
    assert renamed["classes"] == ["object", "car"]
    refused = engine.delete_annotation_class(1)
    assert refused["requires_reassignment"] is True
    deleted = engine.delete_annotation_class(1, 0)
    assert deleted["classes"] == ["object"]
    assert all(annotation["class_id"] == 0 for annotation in deleted["annotations"])

    class_file = tmp_path / "classes.yaml"
    class_file.write_text("names: [person, bicycle]\n", encoding="utf-8")
    bridge.open_path = str(class_file)
    imported = engine.import_annotation_classes()
    assert imported["added"] == 2
    assert imported["classes"] == ["object", "person", "bicycle"]

    txt_file = tmp_path / "classes.txt"
    txt_file.write_text("cat\ndog\nperson\n", encoding="utf-8")
    bridge.open_path = str(txt_file)
    imported_txt = engine.import_annotation_classes()
    assert imported_txt["added"] == 2
    assert imported_txt["classes"] == ["object", "person", "bicycle", "cat", "dog"]

    sidecar_dir = tmp_path / "central-sidecars"
    bridge.folder_path = str(sidecar_dir)
    selected = engine.choose_annotation_save_directory()
    assert selected["save_directory"] == str(sidecar_dir.resolve())
    saved = engine.save_annotations()
    assert Path(saved["path"]).parent == sidecar_dir.resolve()
    assert Path(saved["path"]).is_file()

    export_dir = tmp_path / "annotation-exports"
    bridge.folder_path = str(export_dir)
    selected_export = engine.choose_annotation_export_directory()
    assert selected_export["export_directory"] == str(export_dir.resolve())
    exported = engine.export_annotations("coco")
    assert exported["ok"] is True
    assert Path(exported["path"]).parent == export_dir.resolve()


def test_annotation_export_enforces_task_compatible_formats_and_filters(
    image_file: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "smart-exports"
    settings = Settings(path=tmp_path / "smart-export-settings.json")
    settings.set("annotation_export_directory", str(destination))
    settings.set("annotation_autosave", False)
    engine = BackendEngine(bridge=FakeBridge(open_path=image_file), settings=settings)
    engine.open_image_dialog()
    engine.create_annotation("bbox", 0, {"x": 0.25, "y": 0.3, "w": 0.2, "h": 0.2})
    engine.create_annotation(
        "polygon", 0, {"polygon": [[0.5, 0.2], [0.8, 0.2], [0.7, 0.6]]}
    )
    engine.create_annotation("classification", 0, {})

    editor = engine.get_state()["annotation_editor"]
    assert editor["type_counts_all"] == {
        "classification": 1,
        "bbox": 1,
        "polygon": 1,
        "mask": 0,
        "pose": 0,
    }

    invalid_detection = engine.export_annotations("mask", "all", "detection")
    assert invalid_detection["ok"] is False
    assert "not valid for detection" in invalid_detection["message"]
    invalid_segmentation = engine.export_annotations("voc", "all", "segmentation")
    assert invalid_segmentation["ok"] is False
    assert "not valid for segmentation" in invalid_segmentation["message"]

    detection = engine.export_annotations("coco", "all", "detection")
    detection_json = next((Path(detection["path"]) / "annotations").glob("*.json"))
    detection_rows = json.loads(detection_json.read_text(encoding="utf-8"))["annotations"]
    assert detection["annotations_exported"] == 1
    assert detection["annotations_excluded"] == 2
    assert len(detection_rows) == 1 and "segmentation" not in detection_rows[0]

    segmentation = engine.export_annotations("coco", "all", "segmentation")
    segmentation_json = next((Path(segmentation["path"]) / "annotations").glob("*.json"))
    segmentation_rows = json.loads(
        segmentation_json.read_text(encoding="utf-8")
    )["annotations"]
    assert segmentation["annotations_exported"] == 1
    assert len(segmentation_rows) == 1 and segmentation_rows[0]["segmentation"]
    assert segmentation_rows[0]["area"] == pytest.approx(576.0)

    classification = engine.export_annotations("yolo", "all", "classification")
    class_images = list(Path(classification["path"]).glob("*/*/*"))
    assert classification["annotations_exported"] == 1
    assert any(path.name == image_file.name for path in class_images)


def test_class_deletion_can_remove_its_annotations_without_history_resurrection(
    image_file, tmp_path
):
    settings = Settings(path=tmp_path / "delete-class-settings.json")
    engine = BackendEngine(bridge=FakeBridge(open_path=image_file), settings=settings)
    engine.open_image_dialog()
    engine.add_annotation_class("cat")
    engine.add_annotation_class("dog")
    engine.create_annotation(
        "bbox", 1, {"x": 0.25, "y": 0.25, "w": 0.2, "h": 0.2}
    )
    engine.create_annotation(
        "bbox", 2, {"x": 0.75, "y": 0.75, "w": 0.2, "h": 0.2}
    )
    engine.create_annotation("classification", 1)

    deleted = engine.delete_annotation_class(1, -1, True)

    assert deleted["ok"] is True
    assert deleted["deleted_annotations"] == 2
    assert deleted["reassigned"] == 0
    assert deleted["classes"] == ["object", "dog"]
    assert [(row["class_id"], row["label"]) for row in deleted["annotations"]] == [
        (1, "dog")
    ]

    # Class deletion also scrubs undo/redo snapshots, so an ordinary undo cannot
    # bring back annotations whose class no longer exists.
    undone = engine.undo()
    assert all(row["label"] != "cat" for row in undone["annotation_editor"]["annotations"])
    assert all(
        annotation.class_id < 2
        for annotations in engine._annotation_storage_lists()
        for annotation in annotations
    )


def test_open_folder_dialog_loads_all(image_file, folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    state = engine.open_folder_dialog()
    assert state["count"] == 3
    assert len(state["images"]) == 3
    assert state["workspace"] == {"kind": "image_collection"}


def test_seeded_variants_also_work_for_unlabelled_image_folder(folder):
    engine = make_engine(FakeBridge(folder_path=folder))
    engine.open_folder_dialog()

    generated = engine.generate_variants("balanced", 1, 42)

    assert generated["ok"] is True
    assert generated["generated"] == 3
    assert generated["count"] == 6
    assert generated["dataset"] == {"active": False}
    assert all(row["annotations"] == 0 for row in generated["images"])


def test_user_configured_seeded_recipe_generates_variants(folder):
    engine = make_engine(FakeBridge(folder_path=folder))
    engine.open_folder_dialog()
    catalog = engine.get_augmentation_recipes()

    generated = engine.generate_variants(
        "custom",
        1,
        123,
        {"rotation": [-3, 3], "noise": [2, 5]},
    )

    assert catalog["recipes"] and catalog["fields"]
    assert generated["ok"] is True
    assert generated["generated"] == 3
    assert generated["count"] == 6


def test_preview_transform_returns_data_url(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    result = engine.preview("transform", {"scale": 80, "rotation": 15})
    assert "error" not in result
    assert result["dataUrl"].startswith("data:image/png;base64,")
    assert result["latency_ms"] >= 0
    assert not result["dataUrl"].endswith(",")


def test_apply_transform_marks_modified_and_history(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    before = engine.get_state()
    assert before["history"] == {"can_undo": False, "can_redo": False}

    state = engine.apply("transform", {"rotation": 90, "scale": 100})
    assert state["images"][0]["modified"] is True
    assert state["history"]["can_undo"] is True

    # Undo returns to original.
    state = engine.undo()
    assert state["images"][0]["modified"] is False
    assert state["history"]["can_redo"] is True

    # Redo re-applies.
    state = engine.redo()
    assert state["images"][0]["modified"] is True


def test_apply_is_cumulative_with_history(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    engine.apply("augment", {"white_balance": 30})
    engine.apply("augment", {"sharpen": 50})
    state = engine.get_state()
    assert state["history"]["can_undo"] is True

    engine.undo()
    state = engine.get_state()
    assert state["images"][0]["modified"] is True  # one edit still applied


def test_history_timeline_describes_values_and_jumps_between_states(image_file):
    engine = make_engine(FakeBridge(open_path=image_file))
    engine.open_image_dialog()

    first = engine.apply("augment", {"white_balance": 56})
    transform = first["defaults"]["transform"]
    transform["tl_x"] = 55
    second = engine.apply("transform", transform)

    timeline = second["history_timeline"]
    assert timeline["position"] == 2
    assert timeline["base_label"] == "Original"
    assert timeline["entries"][0]["changes"] == [
        {"section": "Color", "label": "White balance", "value": "56"}
    ]
    assert {
        "section": "Perspective",
        "label": "Top-Left X",
        "value": "55 px",
    } in timeline["entries"][1]["changes"]

    original = engine.jump_to_history(0)
    assert original["history_timeline"]["position"] == 0
    assert original["images"][0]["modified"] is False
    assert original["history"]["can_redo"] is True

    first_state = engine.jump_to_history(1)
    assert first_state["history_timeline"]["position"] == 1
    assert first_state["history"]["can_undo"] is True
    assert first_state["history"]["can_redo"] is True

    latest = engine.jump_to_history(2)
    assert latest["history_timeline"]["position"] == 2
    assert latest["history"]["can_redo"] is False


def test_history_redo_restores_exact_random_augmentation(image_file):
    engine = make_engine(FakeBridge(open_path=image_file))
    engine.open_image_dialog()
    engine.apply("augment", {"noise": 25})
    expected = engine._collection.current.active.copy()

    engine.jump_to_history(0)
    engine.jump_to_history(1)

    assert np.array_equal(engine._collection.current.active, expected)


def test_apply_resize_changes_dims(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    state = engine.apply("resize", {"width": 60, "height": 40})
    meta = state["images"][0]
    assert (meta["w"], meta["h"]) == (60, 40)


def test_new_augment_fields_are_applied(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    result = engine.preview("augment", {
        "salt_pepper": 30, "gaussian_blur": 20, "softness": 20,
        "sharpen": 20, "oil": 10, "exposure": 0.5,
    })
    assert "error" not in result
    assert result["dataUrl"].startswith("data:image")


def test_unknown_params_are_ignored(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()
    result = engine.preview("transform", {"rotation": 30, "bogus_key": 123})
    assert "error" not in result


def test_apply_all_reports_progress_and_can_cancel(image_file, folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()

    # Cancel immediately after the first progress event.
    original_emit = engine._emit_progress
    def cancel_after_emit(percent, message, operation, cancelled=False):
        original_emit(percent, message, operation, cancelled)
        engine.cancel()
    engine._emit_progress = cancel_after_emit  # type: ignore[method-assign]

    state = engine.apply_all("augment", {"exposure": 0.5})
    assert state["cancelled"] is True
    assert state["applied"] < 3  # cancelled mid-batch


def test_apply_all_no_cancel_applies_everything(image_file, folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()

    state = engine.apply_all("augment", {"exposure": 0.5})
    assert state["cancelled"] is False
    assert state["applied"] == 3


def test_get_compare_returns_both_images(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    engine.apply("augment", {"exposure": 1.0})
    result = engine.get_compare(max_size=200)
    assert result["original"].startswith("data:image")
    assert result["processed"].startswith("data:image")
    assert result["w"] > 0 and result["h"] > 0


def test_save_all_respects_prefix_postfix(image_file, folder, tmp_path):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()
    engine.apply_all("augment", {"exposure": 0.5})

    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    bridge.folder_path = str(out_dir)

    result = engine.save_all(prefix="a_", postfix="_b")
    assert result["ok"] is True
    assert result["saved"] == 3
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["a_img0_b.png", "a_img1_b.png", "a_img2_b.png"]


def test_save_session_saves_every_image_even_unedited(folder, tmp_path):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()
    # Edit only the first image; the rest must still be written.
    engine.apply("augment", {"exposure": 0.5})

    out_dir = tmp_path / "session_out"
    out_dir.mkdir()
    bridge.folder_path = str(out_dir)
    bridge.events.clear()

    result = engine.save_session(prefix="s_", postfix="_x")
    assert result["ok"] is True
    assert result["saved"] == 3
    assert result["total"] == 3
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["s_img0_x.png", "s_img1_x.png", "s_img2_x.png"]
    assert any("save_session" in code for code in bridge.events)


def test_save_session_empty_collection_is_rejected(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    result = engine.save_session()
    assert result["ok"] is False
    assert "No images" in result["message"]


def test_save_image_with_bridge(image_file, tmp_path):
    bridge = FakeBridge(open_path=image_file, save_path=str(tmp_path / "out.png"))
    engine = make_engine(bridge)
    engine.open_image_dialog()
    engine.apply("augment", {"exposure": 0.5})

    result = engine.save_image()
    assert result["ok"] is True
    assert (tmp_path / "out.png").is_file()


def test_capabilities_and_config_roundtrip(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    caps = engine.get_capabilities()
    assert caps["cv_version"]
    assert caps["cores"] >= 1
    assert isinstance(caps["opencl"], bool)

    engine.set_config("performance_mode", "medium")
    assert engine.get_config()["performance_mode"] == "medium"


def test_performance_mode_controls_preview_max(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    engine.set_config("performance_mode", "low")
    assert engine._resolve_preview_max() == 720
    engine.set_config("performance_mode", "medium")
    assert engine._resolve_preview_max() == 1920
    # Legacy values normalize to medium
    engine.set_config("performance_mode", "high")
    assert engine._resolve_preview_max() == 1920
    engine.set_config("performance_mode", "auto")
    assert engine._resolve_preview_max() == 1920


def test_capabilities_report_real_hardware(image_file):
    engine = make_engine(FakeBridge(open_path=image_file))
    caps = engine.get_capabilities()
    for key in (
        "opencl_in_use",
        "threads",
        "cpu_name",
        "gpu",
        "performance_mode",
        "preview_max",
        "backend",
    ):
        assert key in caps
    assert isinstance(caps["opencl_in_use"], bool)
    assert isinstance(caps["threads"], int) and caps["threads"] >= 1
    assert caps["cpu_name"]
    assert caps["backend"] in ("GPU + CPU", "CPU only")
    assert caps["preview_max"] == 1920
    if caps["gpu"] is not None:
        assert caps["gpu"]["name"]
        assert caps["gpu"]["type"] in ("GPU", "CPU", "Accelerator")


def test_low_profile_is_cpu_only_single_thread(image_file):
    engine = make_engine(FakeBridge(open_path=image_file))
    engine.set_config("performance_mode", "low")
    caps = engine.get_capabilities()
    assert caps["threads"] == 1
    assert caps["opencl_in_use"] is False
    assert caps["preview_max"] == 720

    engine.set_config("performance_mode", "medium")
    caps = engine.get_capabilities()
    assert caps["opencl_in_use"] == caps["opencl"]
    assert caps["preview_max"] == 1920
    # High profile must restore parallel threads (not collapse to one).
    if (os.cpu_count() or 1) > 1:
        assert caps["threads"] > 1


def test_get_preview_honors_performance_profile(tmp_path):
    big = np.full((800, 1000, 3), 128, dtype=np.uint8)
    path = tmp_path / "big.png"
    cv2.imwrite(str(path), cv2.cvtColor(big, cv2.COLOR_RGB2BGR))
    engine = make_engine(FakeBridge(open_path=path))
    engine.open_image_dialog()

    engine.set_config("performance_mode", "low")
    low = engine.get_preview()
    assert low["w"] <= 720 and low["h"] <= 720

    engine.set_config("performance_mode", "medium")
    full = engine.get_preview()
    assert full["w"] == 1000

    # An explicit cap still wins over the profile.
    capped = engine.get_preview(max_size=100)
    assert capped["w"] == 100


def test_navigate_between_images(image_file, folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()
    assert engine.get_state()["current_index"] == 0

    state = engine.navigate(1)
    assert state["current_index"] == 1
    state = engine.navigate(-1)
    assert state["current_index"] == 0
    # Past the end stays clamped.
    engine.navigate(5)
    assert engine.get_state()["current_index"] == 2


def test_reset_image_and_all(image_file, folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()

    engine.apply_all("augment", {"exposure": 0.5})
    assert all(m["modified"] for m in engine.get_images())

    engine.reset_all()
    assert not any(m["modified"] for m in engine.get_images())


def test_window_control_delegates_without_crash():
    bridge = FakeBridge()
    engine = make_engine(bridge)
    engine.move_window(10, 20)
    engine.minimize_window()
    engine.toggle_maximize()
    engine.close_window()


@pytest.fixture
def large_image_file(tmp_path: Path) -> Path:
    img = np.full((2400, 3200, 3), 30, dtype=np.uint8)
    img[200:2200, 200:3000] = (200, 100, 50)
    single = tmp_path / "large"
    single.mkdir(exist_ok=True)
    path = single / "large.png"
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return path


def _data_url_to_image(data_url: str):
    import base64
    header, b64 = data_url.split(",", 1)
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def test_preview_transform_identity_on_large_image(large_image_file):
    bridge = FakeBridge(open_path=large_image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    result = engine.preview("transform", {})
    assert "error" not in result
    img = _data_url_to_image(result["dataUrl"])
    h, w = img.shape[:2]
    # Preview downscales to at most 1920 on the long side; aspect ratio ~4:3.
    assert w > 1800 and h > 1300
    # Nearly all pixels should be non-black (identity transform).
    nonblack = np.count_nonzero(img.sum(axis=2))
    frac = nonblack / (w * h)
    assert frac > 0.95


def test_preview_transform_rotation_on_large_image(large_image_file):
    bridge = FakeBridge(open_path=large_image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    result = engine.preview("transform", {"rotation": 30})
    assert "error" not in result
    img = _data_url_to_image(result["dataUrl"])
    h, w = img.shape[:2]
    assert w > 1800 and h > 1300
    nonblack = np.count_nonzero(img.sum(axis=2))
    frac = nonblack / (w * h)
    assert frac > 0.78  # rotation crops corners but most content is still present.


def test_preview_transform_with_bogus_key_on_large_image(large_image_file):
    bridge = FakeBridge(open_path=large_image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    result = engine.preview("transform", {"rotation": 15, "bogus_key": 999})
    assert "error" not in result
    assert result["dataUrl"].startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# Global (batch) undo/redo tests
# ---------------------------------------------------------------------------


def test_apply_all_then_undo_reverts_everything(image_file, folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()

    state = engine.apply_all("augment", {"exposure": 0.5})
    assert state["applied"] == 3
    assert all(m["modified"] for m in state["images"])

    # Single undo should revert ALL images.
    state = engine.undo()
    assert all(not m["modified"] for m in state["images"])
    assert state["history"]["can_undo"] is False
    assert state["history"]["can_redo"] is True

    # Redo should re-apply to ALL.
    state = engine.redo()
    assert all(m["modified"] for m in state["images"])


def test_undo_is_global_across_navigation(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    engine.apply("augment", {"white_balance": 30})
    engine.navigate(1)  # stays at 0 (only one image)
    state = engine.undo()
    assert state["images"][0]["modified"] is False


def test_new_apply_clears_redo_tail(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    engine.apply("augment", {"white_balance": 30})
    engine.undo()
    assert engine.get_state()["history"]["can_redo"] is True

    # New apply should clear redo.
    state = engine.apply("augment", {"sharpen": 50})
    assert state["history"]["can_redo"] is False
    assert state["history_timeline"]["position"] == 1
    assert len(state["history_timeline"]["entries"]) == 1
    assert state["history_timeline"]["entries"][0]["changes"][0]["label"] == "Sharpen"


def test_history_log_capped(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    from imagecraft.engine import MAX_OP_HISTORY

    for i in range(MAX_OP_HISTORY + 5):
        engine.apply("augment", {"white_balance": i})
    assert len(engine._op_history) == MAX_OP_HISTORY
    timeline = engine.get_state()["history_timeline"]
    assert timeline["truncated"] is True
    assert timeline["base_label"] == "Earlier state"


def test_loading_new_collection_clears_history(image_file):
    bridge = FakeBridge(open_path=image_file)
    engine = make_engine(bridge)
    engine.open_image_dialog()

    engine.apply("augment", {"white_balance": 30})
    assert engine.get_state()["history"]["can_undo"] is True

    engine._collection.load_single(image_file)
    engine._clear_history()
    state = engine.get_state()
    assert state["history"]["can_undo"] is False
    assert state["history"]["can_redo"] is False
