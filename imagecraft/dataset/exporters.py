"""Safe, source-preserving dataset exporters and format converters."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import yaml

from imagecraft import __version__
from imagecraft.dataset.masks import annotation_mask, decode_rle, encode_rle, mask_to_polygons
from imagecraft.dataset.models import Annotation, DatasetProject
from imagecraft.dataset.pose import pose_schema
from imagecraft.models.image_item import ImageArray


class ExportItem(Protocol):
    path: Path
    dataset_split: str
    is_generated: bool

    @property
    def active(self) -> ImageArray: ...

    @property
    def active_annotations(self) -> list[Annotation]: ...

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...


def export_dataset(
    project: DatasetProject,
    items: Sequence[ExportItem],
    parent: Path,
    target_format: str,
    validation: dict[str, Any],
    manifest_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export to a new uniquely named directory; never overwrite the source."""
    target_format = target_format.lower()
    if target_format not in {
        "yolo",
        "coco",
        "voc",
        "mask",
        "yolo_pose",
        "coco_keypoints",
        "mediapipe",
    }:
        raise ValueError(f"Unsupported export format: {target_format}")
    allowed_formats = {
        "classification": {"yolo"},
        "detection": {"yolo", "coco", "voc"},
        "segmentation": {"yolo", "coco", "mask"},
        "pose": {"yolo_pose", "coco_keypoints", "mediapipe"},
    }.get(project.task_type)
    if allowed_formats is not None and target_format not in allowed_formats:
        readable = ", ".join(sorted(value.upper() for value in allowed_formats))
        raise ValueError(
            f"{target_format.upper()} is not valid for {project.task_type}. "
            f"Choose one of: {readable}"
        )
    parent = parent.resolve()
    source_root = project.root.resolve()
    if parent == source_root or source_root in parent.parents:
        raise ValueError("Choose a destination outside the source dataset folder")
    parent.mkdir(parents=True, exist_ok=True)
    output = _unique_directory(parent, f"{_safe_name(project.name)}_imagecraft_{target_format}")
    output.mkdir(parents=True)

    try:
        if target_format == "yolo_pose":
            exported = _export_yolo_pose(project, items, output)
        elif target_format == "coco_keypoints":
            exported = _export_coco_keypoints(project, items, output)
        elif target_format == "mediapipe":
            exported = _export_mediapipe_pose(project, items, output)
        elif target_format == "yolo":
            exported = (
                _export_yolo_classification(project, items, output)
                if project.task_type == "classification"
                else _export_yolo(project, items, output)
            )
        elif target_format == "coco":
            exported = _export_coco(project, items, output)
        elif target_format == "voc":
            exported = _export_voc(project, items, output)
        else:
            exported = _export_masks(project, items, output)

        manifest: dict[str, Any] = {
            "application": "VisionDB Craft",
            "application_version": __version__,
            "exported_at": datetime.now(UTC).isoformat(),
            "source_root": str(project.root),
            "source_format": project.source_format,
            "target_format": target_format,
            "images": exported,
            "classes": project.class_names,
            "task_type": project.task_type,
            "source_preserved": True,
        }
        if manifest_extra:
            manifest.update(manifest_extra)
        (output / "imagecraft_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        (output / "imagecraft_validation_report.json").write_text(
            json.dumps(validation, indent=2), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return {"ok": True, "path": str(output), "saved": exported, "format": target_format}


def _export_yolo(project: DatasetProject, items: Sequence[ExportItem], output: Path) -> int:
    names_by_split: dict[str, set[str]] = defaultdict(set)
    saved = 0
    present_splits: set[str] = set()
    for item in items:
        split = _clean_split(item.dataset_split)
        present_splits.add(split)
        image_dir = output / "images" / split
        label_dir = output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        filename = _unique_filename(Path(item.path).name, names_by_split[split])
        if not _write_item(item, image_dir / filename):
            continue
        label_path = label_dir / Path(filename).with_suffix(".txt").name
        accepted_types = {"polygon", "mask"} if project.task_type == "segmentation" else {"bbox"}
        annotations = [
            ann
            for ann in _clean_annotations(project, item)
            if ann.annotation_type in accepted_types
        ]
        lines = [line for annotation in annotations for line in _annotation_yolo_lines(annotation)]
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        saved += 1
    config: dict[str, Any] = {"path": ".", "names": project.class_names}
    for split in sorted(present_splits):
        config[split] = f"images/{split}"
    (output / "data.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return saved


def _export_yolo_classification(
    project: DatasetProject, items: Sequence[ExportItem], output: Path
) -> int:
    saved = 0
    used_by_folder: dict[str, set[str]] = defaultdict(set)
    for item in items:
        labels = [
            ann
            for ann in item.active_annotations
            if ann.annotation_type == "classification"
            and 0 <= ann.class_id < len(project.class_names)
        ]
        if not labels:
            continue
        label = labels[0]
        split = _clean_split(item.dataset_split)
        folder = output / split / _safe_name(project.class_names[label.class_id])
        folder.mkdir(parents=True, exist_ok=True)
        filename = _unique_filename(Path(item.path).name, used_by_folder[str(folder)])
        if _write_item(item, folder / filename):
            saved += 1
    (output / "classes.txt").write_text("\n".join(project.class_names) + "\n", encoding="utf-8")
    return saved


def _pose_annotations(project: DatasetProject, item: ExportItem) -> list[Annotation]:
    return [
        annotation
        for annotation in _clean_annotations(project, item)
        if annotation.annotation_type == "pose" and annotation.keypoints
    ]


def _export_yolo_pose(project: DatasetProject, items: Sequence[ExportItem], output: Path) -> int:
    """Export Ultralytics YOLO pose rows plus the required dataset YAML."""
    poses = [annotation for item in items for annotation in _pose_annotations(project, item)]
    if not poses:
        raise ValueError("No pose annotations are available")
    schemas = {annotation.pose_schema for annotation in poses}
    if len(schemas) != 1:
        raise ValueError(
            "YOLO Pose requires one keypoint schema per dataset. "
            "Export MediaPipe 33 and COCO 17 annotations separately."
        )
    schema_id = next(iter(schemas))
    schema = pose_schema(schema_id)
    point_count = len(schema["names"])
    if any(len(annotation.keypoints or []) != point_count for annotation in poses):
        raise ValueError("Every YOLO Pose instance must contain the same ordered keypoint count")

    names_by_split: dict[str, set[str]] = defaultdict(set)
    present_splits: set[str] = set()
    saved = 0
    for item in items:
        split = _clean_split(item.dataset_split)
        present_splits.add(split)
        image_dir = output / "images" / split
        label_dir = output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        filename = _unique_filename(Path(item.path).name, names_by_split[split])
        if not _write_item(item, image_dir / filename):
            continue
        lines = [annotation.to_yolo() for annotation in _pose_annotations(project, item)]
        (label_dir / Path(filename).with_suffix(".txt").name).write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        saved += 1

    config: dict[str, Any] = {
        "path": ".",
        "kpt_shape": [point_count, 3],
        "flip_idx": schema["flip_idx"],
        "names": dict(enumerate(project.class_names)),
        "kpt_names": {index: list(schema["names"]) for index in range(len(project.class_names))},
    }
    for split in sorted(present_splits):
        config[split] = f"images/{split}"
    (output / "data.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return saved


def _export_coco_keypoints(
    project: DatasetProject, items: Sequence[ExportItem], output: Path
) -> int:
    """Export COCO keypoint instances with per-category keypoint metadata."""
    poses = [annotation for item in items for annotation in _pose_annotations(project, item)]
    if not poses:
        raise ValueError("No pose annotations are available")
    schema_by_class: dict[int, str] = {}
    for annotation in poses:
        previous = schema_by_class.setdefault(annotation.class_id, annotation.pose_schema)
        if previous != annotation.pose_schema:
            raise ValueError("A COCO category cannot use multiple keypoint schemas")
    fallback_schema = poses[0].pose_schema
    categories = []
    for class_id, name in enumerate(project.class_names):
        schema = pose_schema(schema_by_class.get(class_id, fallback_schema))
        categories.append(
            {
                "id": class_id + 1,
                "name": name,
                "supercategory": "object",
                "keypoints": list(schema["names"]),
                "skeleton": [[start + 1, end + 1] for start, end in schema["skeleton"]],
            }
        )

    grouped: dict[str, list[ExportItem]] = defaultdict(list)
    for item in items:
        grouped[_clean_split(item.dataset_split)].append(item)
    annotation_dir = output / "annotations"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for split, split_items in grouped.items():
        image_dir = output / "images" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        images: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        annotation_id = 1
        for image_id, item in enumerate(split_items, start=1):
            filename = _unique_filename(Path(item.path).name, used)
            if not _write_item(item, image_dir / filename):
                continue
            images.append(
                {
                    "id": image_id,
                    "file_name": filename,
                    "width": item.width,
                    "height": item.height,
                }
            )
            for annotation in _pose_annotations(project, item):
                left = (annotation.x_center - annotation.width / 2.0) * item.width
                top = (annotation.y_center - annotation.height / 2.0) * item.height
                width = annotation.width * item.width
                height = annotation.height * item.height
                points = annotation.keypoints or []
                keypoints = [
                    coordinate
                    for point in points
                    for coordinate in (
                        round(float(point["x"]) * item.width, 3)
                        if int(point.get("visibility", 0))
                        else 0,
                        round(float(point["y"]) * item.height, 3)
                        if int(point.get("visibility", 0))
                        else 0,
                        int(point.get("visibility", 0)),
                    )
                ]
                annotations.append(
                    {
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": annotation.class_id + 1,
                        "bbox": [round(left, 3), round(top, 3), round(width, 3), round(height, 3)],
                        "area": round(width * height, 3),
                        "iscrowd": 0,
                        "keypoints": keypoints,
                        "num_keypoints": sum(
                            int(point.get("visibility", 0)) > 0 for point in points
                        ),
                    }
                )
                annotation_id += 1
            saved += 1
        payload = {"images": images, "annotations": annotations, "categories": categories}
        (annotation_dir / f"person_keypoints_{split}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    return saved


def _export_mediapipe_pose(
    project: DatasetProject, items: Sequence[ExportItem], output: Path
) -> int:
    """Export normalized 33-landmark records matching MediaPipe landmark fields."""
    poses = [annotation for item in items for annotation in _pose_annotations(project, item)]
    if not poses:
        raise ValueError("No pose annotations are available")
    if any(annotation.pose_schema != "mediapipe_33" for annotation in poses):
        raise ValueError("MediaPipe JSON export requires the MediaPipe 33-landmark schema")
    grouped: dict[str, list[ExportItem]] = defaultdict(list)
    for item in items:
        grouped[_clean_split(item.dataset_split)].append(item)
    annotation_dir = output / "annotations"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for split, split_items in grouped.items():
        image_dir = output / "images" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        records: list[dict[str, Any]] = []
        for item in split_items:
            filename = _unique_filename(Path(item.path).name, used)
            if not _write_item(item, image_dir / filename):
                continue
            instances = []
            for annotation in _pose_annotations(project, item):
                instances.append(
                    {
                        "class_id": annotation.class_id,
                        "class_name": project.class_names[annotation.class_id],
                        "normalized_landmarks": [
                            {
                                "x": float(point["x"]),
                                "y": float(point["y"]),
                                "z": float(point.get("z", 0.0)),
                                "visibility": float(point.get("visibility", 0)) / 2.0,
                                "presence": float(point.get("presence", 0.0)),
                            }
                            for point in (annotation.keypoints or [])
                        ],
                    }
                )
            records.append(
                {
                    "image": f"images/{split}/{filename}",
                    "width": item.width,
                    "height": item.height,
                    "poses": instances,
                }
            )
            saved += 1
        (annotation_dir / f"mediapipe_pose_{split}.json").write_text(
            json.dumps(
                {
                    "schema": "mediapipe_pose_landmarker_33",
                    "landmark_names": pose_schema("mediapipe_33")["names"],
                    "images": records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return saved


def _export_coco(project: DatasetProject, items: Sequence[ExportItem], output: Path) -> int:
    grouped: dict[str, list[ExportItem]] = defaultdict(list)
    for item in items:
        grouped[_clean_split(item.dataset_split)].append(item)
    categories = [
        {"id": class_id + 1, "name": name, "supercategory": "object"}
        for class_id, name in enumerate(project.class_names)
    ]
    annotation_dir = output / "annotations"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for split, split_items in grouped.items():
        image_dir = output / "images" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        images: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        annotation_id = 1
        for image_id, item in enumerate(split_items, start=1):
            filename = _unique_filename(Path(item.path).name, used)
            if not _write_item(item, image_dir / filename):
                continue
            images.append(
                {"id": image_id, "file_name": filename, "width": item.width, "height": item.height}
            )
            accepted_types = (
                {"polygon", "mask"} if project.task_type == "segmentation" else {"bbox"}
            )
            for ann in _clean_annotations(project, item):
                if ann.annotation_type not in accepted_types:
                    continue
                x = (ann.x_center - ann.width / 2.0) * item.width
                y = (ann.y_center - ann.height / 2.0) * item.height
                box_w = ann.width * item.width
                box_h = ann.height * item.height
                row: dict[str, Any] = {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": ann.class_id + 1,
                    "bbox": [round(x, 3), round(y, 3), round(box_w, 3), round(box_h, 3)],
                    "area": round(box_w * box_h, 3),
                    "iscrowd": 0,
                }
                if ann.mask_rle:
                    mask = annotation_mask(ann, item.width, item.height)
                    if mask is not None:
                        row["segmentation"] = encode_rle(mask)
                        row["area"] = int(np.count_nonzero(mask))
                elif ann.polygon:
                    pixel_polygon = [
                        (point[0] * item.width, point[1] * item.height) for point in ann.polygon
                    ]
                    row["segmentation"] = [
                        [coordinate for point in pixel_polygon for coordinate in point]
                    ]
                    row["area"] = round(
                        float(cv2.contourArea(np.asarray(pixel_polygon, dtype=np.float32))),
                        3,
                    )
                annotations.append(row)
                annotation_id += 1
            saved += 1
        payload = {"images": images, "annotations": annotations, "categories": categories}
        (annotation_dir / f"instances_{split}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    return saved


def _export_masks(project: DatasetProject, items: Sequence[ExportItem], output: Path) -> int:
    """Export one lossless PNG mask per annotation plus an explicit index."""
    used_images: dict[str, set[str]] = defaultdict(set)
    index_rows: list[dict[str, Any]] = []
    saved = 0
    for item in items:
        split = _clean_split(item.dataset_split)
        image_dir = output / "images" / split
        mask_dir = output / "masks" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        mask_dir.mkdir(parents=True, exist_ok=True)
        filename = _unique_filename(Path(item.path).name, used_images[split])
        if not _write_item(item, image_dir / filename):
            continue
        annotations = [
            annotation
            for annotation in _clean_annotations(project, item)
            if annotation.annotation_type in {"polygon", "mask"}
        ]
        for ann_index, ann in enumerate(annotations, start=1):
            mask = annotation_mask(ann, item.width, item.height)
            if mask is None or not mask.any():
                continue
            mask_name = f"{Path(filename).stem}__{ann_index:04d}__class_{ann.class_id}.png"
            if not cv2.imwrite(str(mask_dir / mask_name), mask.astype(np.uint8) * 255):
                continue
            index_rows.append(
                {
                    "image": f"images/{split}/{filename}",
                    "mask": f"masks/{split}/{mask_name}",
                    "class_id": ann.class_id,
                    "class_name": project.class_names[ann.class_id],
                    "annotation_type": ann.annotation_type,
                }
            )
        saved += 1
    (output / "classes.txt").write_text("\n".join(project.class_names) + "\n", encoding="utf-8")
    (output / "mask_index.json").write_text(
        json.dumps({"classes": project.class_names, "instances": index_rows}, indent=2),
        encoding="utf-8",
    )
    return saved


def _export_voc(project: DatasetProject, items: Sequence[ExportItem], output: Path) -> int:
    image_root = output / "JPEGImages"
    annotation_root = output / "Annotations"
    split_root = output / "ImageSets" / "Main"
    image_root.mkdir(parents=True, exist_ok=True)
    annotation_root.mkdir(parents=True, exist_ok=True)
    split_root.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    split_stems: dict[str, list[str]] = defaultdict(list)
    saved = 0

    for item in items:
        filename = _unique_filename(Path(item.path).name, used)
        if not _write_item(item, image_root / filename):
            continue
        stem = Path(filename).stem
        split = _clean_split(item.dataset_split)
        split_stems[split].append(stem)
        root = ET.Element("annotation")
        ET.SubElement(root, "folder").text = "JPEGImages"
        ET.SubElement(root, "filename").text = filename
        size = ET.SubElement(root, "size")
        ET.SubElement(size, "width").text = str(item.width)
        ET.SubElement(size, "height").text = str(item.height)
        ET.SubElement(size, "depth").text = "3"
        for ann in _clean_annotations(project, item):
            if ann.annotation_type != "bbox":
                continue
            obj = ET.SubElement(root, "object")
            ET.SubElement(obj, "name").text = ann.label or project.class_names[ann.class_id]
            ET.SubElement(obj, "pose").text = "Unspecified"
            ET.SubElement(obj, "truncated").text = "0"
            ET.SubElement(obj, "difficult").text = "0"
            box = ET.SubElement(obj, "bndbox")
            x1 = round((ann.x_center - ann.width / 2.0) * item.width)
            y1 = round((ann.y_center - ann.height / 2.0) * item.height)
            x2 = round((ann.x_center + ann.width / 2.0) * item.width)
            y2 = round((ann.y_center + ann.height / 2.0) * item.height)
            for key, value in (("xmin", x1), ("ymin", y1), ("xmax", x2), ("ymax", y2)):
                ET.SubElement(box, key).text = str(value)
        ET.ElementTree(root).write(
            annotation_root / f"{stem}.xml", encoding="utf-8", xml_declaration=True
        )
        saved += 1

    for split, stems in split_stems.items():
        (split_root / f"{split}.txt").write_text("\n".join(stems) + "\n", encoding="utf-8")
    (output / "classes.txt").write_text("\n".join(project.class_names) + "\n", encoding="utf-8")
    return saved


def _write_image(image: ImageArray, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    return bool(cv2.imwrite(str(path), bgr))


def _write_item(item: ExportItem, path: Path) -> bool:
    try:
        return _write_image(item.active, path)
    except (OSError, FileNotFoundError, ValueError):
        return False


def _clean_annotations(project: DatasetProject, item: ExportItem) -> list[Annotation]:
    """Omit annotations that validation identified as unsafe to export."""
    return [
        annotation
        for annotation in item.active_annotations
        if 0 <= annotation.class_id < len(project.class_names) and annotation.is_normalized
    ]


def _annotation_yolo_lines(annotation: Annotation) -> list[str]:
    if not annotation.mask_rle:
        return [annotation.to_yolo()]
    try:
        polygons = mask_to_polygons(decode_rle(annotation.mask_rle))
    except ValueError:
        return []
    return [
        f"{annotation.class_id} " + " ".join(f"{x:.8f} {y:.8f}" for x, y in polygon)
        for polygon in polygons
        if len(polygon) >= 3
    ]


def _unique_directory(parent: Path, base: str) -> Path:
    candidate = parent / base
    number = 2
    while candidate.exists():
        candidate = parent / f"{base}_{number}"
        number += 1
    return candidate


def _unique_filename(filename: str, used: set[str]) -> str:
    path = Path(filename)
    suffix = path.suffix if path.suffix else ".png"
    candidate = f"{_safe_name(path.stem)}{suffix.lower()}"
    number = 2
    while candidate.lower() in used:
        candidate = f"{_safe_name(path.stem)}_{number}{suffix.lower()}"
        number += 1
    used.add(candidate.lower())
    return candidate


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return cleaned.strip("_") or "dataset"


def _clean_split(value: str) -> str:
    return value if value in {"train", "val", "test"} else "unsplit"
