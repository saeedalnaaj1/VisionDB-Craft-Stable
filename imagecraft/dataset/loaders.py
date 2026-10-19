"""Dataset discovery and importers.

YOLO is the primary interactive format.  COCO and Pascal VOC importers are
also included so the same workbench can validate and convert common datasets.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import cv2
import yaml

from imagecraft.dataset.masks import decode_rle, mask_bbox, normalize_rle
from imagecraft.dataset.models import Annotation, DatasetProject, DatasetRecord
from imagecraft.dataset.pose import normalize_keypoints
from imagecraft.models.image_collection import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


def _looks_like_classification_dataset(root: Path) -> bool:
    """Recognize conventional split/class/image folder layouts."""
    split_roots = [root / name for name in ("train", "val", "test") if (root / name).is_dir()]
    if not split_roots or (root / "labels").is_dir() or (root / "annotations").is_dir():
        return False
    return any(
        child.is_dir()
        and any(path.suffix.lower() in SUPPORTED_EXTENSIONS for path in child.iterdir())
        for split_root in split_roots
        for child in split_root.iterdir()
    )


def load_dataset(root: Path) -> DatasetProject:
    """Auto-detect and load a YOLO, COCO, or Pascal VOC dataset."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Dataset folder does not exist: {root}")

    if _looks_like_classification_dataset(root):
        return load_classification_dataset(root)

    yolo_config = next(
        (path for name in ("data.yaml", "data.yml") if (path := root / name).is_file()),
        None,
    )
    if yolo_config is not None or (root / "labels").is_dir():
        return load_yolo_dataset(root, yolo_config)

    coco_jsons = (
        sorted((root / "annotations").glob("*.json")) if (root / "annotations").is_dir() else []
    )
    if coco_jsons:
        return load_coco_dataset(root, coco_jsons)

    if (root / "Annotations").is_dir() or any(root.rglob("*.xml")):
        return load_voc_dataset(root)

    # A YOLO dataset without data.yaml is common.  If an images directory or
    # image files exist, attempt the conventional images/labels relationship.
    if (root / "images").is_dir() or any(
        p.suffix.lower() in SUPPORTED_EXTENSIONS for p in root.iterdir() if p.is_file()
    ):
        return load_yolo_dataset(root, None)
    raise ValueError("No supported YOLO, COCO, or Pascal VOC dataset was detected")


def load_yolo_dataset(root: Path, config_path: Path | None = None) -> DatasetProject:
    config: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    if config_path is not None:
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            config = loaded if isinstance(loaded, dict) else {}
        except (OSError, yaml.YAMLError) as exc:
            issues.append(_issue("error", "invalid_config", f"Cannot read data.yaml: {exc}"))

    class_names = _class_names(config.get("names"))
    raw_kpt_shape = config.get("kpt_shape")
    pose_schema_id = ""
    keypoint_dims = 3
    if isinstance(raw_kpt_shape, list) and len(raw_kpt_shape) >= 2:
        try:
            point_count = int(raw_kpt_shape[0])
            keypoint_dims = int(raw_kpt_shape[1])
            pose_schema_id = {17: "coco_17", 33: "mediapipe_33"}.get(point_count, "")
            if not pose_schema_id:
                issues.append(
                    _issue(
                        "error",
                        "unsupported_pose_schema",
                        "VisionDB Craft currently supports 17 or 33 pose keypoints, "
                        f"found {point_count}",
                        config_path,
                    )
                )
        except (TypeError, ValueError):
            pose_schema_id = ""
    candidates = _yolo_image_candidates(root, config)
    records: list[DatasetRecord] = []
    max_class_id = -1

    for image_path, split in candidates:
        annotation_path = _yolo_label_path(root, image_path)
        annotations, parse_issues, seen_max = _read_yolo_labels(
            annotation_path, class_names, pose_schema_id, keypoint_dims
        )
        max_class_id = max(max_class_id, seen_max)
        width, height = _image_dimensions(image_path)
        if width <= 0 or height <= 0:
            parse_issues.append(
                _issue("error", "corrupt_image", "Image cannot be decoded", image_path)
            )
        records.append(
            DatasetRecord(
                image_path=image_path,
                annotation_path=annotation_path,
                split=split,
                annotations=annotations,
                width=width,
                height=height,
                parse_issues=parse_issues,
            )
        )

    if not class_names and max_class_id >= 0:
        class_names = [f"class_{idx}" for idx in range(max_class_id + 1)]
        for record in records:
            for ann in record.annotations:
                ann.label = class_names[ann.class_id]
    elif class_names:
        for record in records:
            for ann in record.annotations:
                if 0 <= ann.class_id < len(class_names):
                    ann.label = class_names[ann.class_id]

    if not records:
        raise ValueError("No supported images were found in the dataset")

    has_pose = any(
        ann.annotation_type == "pose" for record in records for ann in record.annotations
    )
    task_type = (
        "pose"
        if has_pose
        else "segmentation"
        if any(ann.polygon for record in records for ann in record.annotations)
        else "detection"
    )
    return DatasetProject(
        root=root,
        name=str(config.get("name") or root.name),
        source_format="yolo",
        class_names=class_names,
        records=records,
        config_path=config_path,
        imported_issues=issues,
        task_type=task_type,
    )


def load_classification_dataset(root: Path) -> DatasetProject:
    """Load a folder-per-class dataset (train/val/test/class/image)."""
    split_roots = [root / name for name in ("train", "val", "test") if (root / name).is_dir()]
    scan_roots = split_roots or [root]
    class_names = sorted(
        {
            directory.name
            for split_root in scan_roots
            for directory in split_root.iterdir()
            if directory.is_dir()
        }
    )
    class_ids = {name: index for index, name in enumerate(class_names)}
    records: list[DatasetRecord] = []
    for split_root in scan_roots:
        split = split_root.name if split_root != root else "unsplit"
        for class_name in class_names:
            class_dir = split_root / class_name
            if not class_dir.is_dir():
                continue
            for image_path in sorted(class_dir.iterdir()):
                if image_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                width, height = _image_dimensions(image_path)
                annotation = Annotation(
                    class_ids[class_name],
                    0.5,
                    0.5,
                    1.0,
                    1.0,
                    class_name,
                    annotation_type="classification",
                )
                records.append(
                    DatasetRecord(
                        image_path=image_path,
                        annotation_path=None,
                        split=split,
                        annotations=[annotation],
                        width=width,
                        height=height,
                    )
                )
    if not records:
        raise ValueError("No classification images were found")
    return DatasetProject(
        root=root,
        name=root.name,
        source_format="classification",
        class_names=class_names,
        records=records,
        task_type="classification",
    )


def load_coco_dataset(root: Path, json_paths: list[Path] | None = None) -> DatasetProject:
    json_paths = json_paths or sorted((root / "annotations").glob("*.json"))
    records_by_path: dict[Path, DatasetRecord] = {}
    category_names: dict[int, str] = {}
    category_pose_schemas: dict[int, str] = {}
    issues: list[dict[str, Any]] = []

    for json_path in json_paths:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(_issue("error", "invalid_coco", f"Cannot read {json_path.name}: {exc}"))
            continue
        split = _split_from_name(json_path.stem)
        categories = payload.get("categories", [])
        for category in categories:
            try:
                category_id = int(category["id"])
                category_names[category_id] = str(category["name"])
                keypoint_names = category.get("keypoints")
                if isinstance(keypoint_names, list):
                    schema_id = {17: "coco_17", 33: "mediapipe_33"}.get(len(keypoint_names))
                    if schema_id:
                        category_pose_schemas[category_id] = schema_id
            except (KeyError, TypeError, ValueError):
                continue
        image_rows = {int(row["id"]): row for row in payload.get("images", []) if "id" in row}
        anns_by_image: dict[int, list[dict[str, Any]]] = {}
        for row in payload.get("annotations", []):
            try:
                anns_by_image.setdefault(int(row["image_id"]), []).append(row)
            except (KeyError, TypeError, ValueError):
                continue
        sorted_category_ids = sorted(category_names)
        category_to_index = {
            category_id: idx for idx, category_id in enumerate(sorted_category_ids)
        }

        for image_id, row in image_rows.items():
            image_path = _resolve_coco_image(root, str(row.get("file_name", "")), split)
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
            if width <= 0 or height <= 0:
                width, height = _image_dimensions(image_path)
            annotations: list[Annotation] = []
            parse_issues: list[dict[str, Any]] = []
            for ann_row in anns_by_image.get(image_id, []):
                category_id = int(ann_row.get("category_id", -1))
                class_id = category_to_index.get(category_id, -1)
                polygon: list[tuple[float, float]] | None = None
                mask_rle: dict[str, Any] | None = None
                segmentation = ann_row.get("segmentation")
                if isinstance(segmentation, dict):
                    try:
                        mask_rle = normalize_rle(segmentation)
                        mask = decode_rle(mask_rle)
                        if width <= 0 or height <= 0:
                            height, width = mask.shape
                    except (TypeError, ValueError) as exc:
                        parse_issues.append(
                            _issue(
                                "error",
                                "invalid_mask_rle",
                                f"Invalid COCO mask RLE: {exc}",
                                image_path,
                            )
                        )
                        continue
                elif (
                    isinstance(segmentation, list)
                    and segmentation
                    and isinstance(segmentation[0], list)
                ):
                    coords = segmentation[0]
                    if len(coords) >= 6 and len(coords) % 2 == 0:
                        polygon = [
                            (
                                float(coords[i]) / max(width, 1),
                                float(coords[i + 1]) / max(height, 1),
                            )
                            for i in range(0, len(coords), 2)
                        ]

                bbox = ann_row.get("bbox")
                if isinstance(bbox, list) and len(bbox) >= 4 and width > 0 and height > 0:
                    x, y, box_w, box_h = (float(v) for v in bbox[:4])
                    normalized_box = (
                        (x + box_w / 2.0) / max(width, 1),
                        (y + box_h / 2.0) / max(height, 1),
                        box_w / max(width, 1),
                        box_h / max(height, 1),
                    )
                elif mask_rle is not None:
                    derived_box = mask_bbox(decode_rle(mask_rle))
                    if derived_box is None:
                        parse_issues.append(
                            _issue("error", "empty_mask", "COCO mask is empty", image_path)
                        )
                        continue
                    normalized_box = derived_box
                else:
                    parse_issues.append(
                        _issue("error", "invalid_bbox", "Invalid COCO bbox", image_path)
                    )
                    continue
                raw_keypoints = ann_row.get("keypoints")
                pose_schema_id = category_pose_schemas.get(category_id, "")
                if (
                    pose_schema_id
                    and isinstance(raw_keypoints, list)
                    and len(raw_keypoints) % 3 == 0
                ):
                    pose_points = [
                        {
                            "x": float(raw_keypoints[index]) / max(width, 1),
                            "y": float(raw_keypoints[index + 1]) / max(height, 1),
                            "visibility": int(raw_keypoints[index + 2]),
                            "z": 0.0,
                            "presence": 1.0 if int(raw_keypoints[index + 2]) else 0.0,
                        }
                        for index in range(0, len(raw_keypoints), 3)
                    ]
                    annotations.append(
                        Annotation(
                            class_id=class_id,
                            label=category_names.get(category_id, f"class_{class_id}"),
                            x_center=normalized_box[0],
                            y_center=normalized_box[1],
                            width=normalized_box[2],
                            height=normalized_box[3],
                            annotation_type="pose",
                            keypoints=normalize_keypoints(pose_points, pose_schema_id),
                            pose_schema=pose_schema_id,
                            pose_workflow="top_down",
                            pose_has_bbox=True,
                        )
                    )
                    continue
                annotations.append(
                    Annotation(
                        class_id=class_id,
                        label=category_names.get(category_id, f"class_{class_id}"),
                        x_center=normalized_box[0],
                        y_center=normalized_box[1],
                        width=normalized_box[2],
                        height=normalized_box[3],
                        polygon=polygon,
                        annotation_type=(
                            "mask" if mask_rle is not None else "polygon" if polygon else "bbox"
                        ),
                        mask_rle=mask_rle,
                    )
                )
            records_by_path[image_path] = DatasetRecord(
                image_path=image_path,
                annotation_path=json_path,
                split=split,
                annotations=annotations,
                width=width,
                height=height,
                parse_issues=parse_issues,
            )

    class_names = [category_names[key] for key in sorted(category_names)]
    if not records_by_path:
        raise ValueError("No usable COCO image records were found")
    task_type = (
        "pose"
        if any(
            ann.annotation_type == "pose"
            for record in records_by_path.values()
            for ann in record.annotations
        )
        else "segmentation"
        if any(
            ann.polygon or ann.mask_rle
            for record in records_by_path.values()
            for ann in record.annotations
        )
        else "detection"
    )
    return DatasetProject(
        root=root,
        name=root.name,
        source_format="coco",
        class_names=class_names,
        records=list(records_by_path.values()),
        config_path=json_paths[0] if json_paths else None,
        imported_issues=issues,
        task_type=task_type,
    )


def load_voc_dataset(root: Path) -> DatasetProject:
    xml_paths = (
        sorted((root / "Annotations").glob("*.xml"))
        if (root / "Annotations").is_dir()
        else sorted(root.rglob("*.xml"))
    )
    pending: list[
        tuple[
            Path,
            str,
            int,
            int,
            list[tuple[str, tuple[float, float, float, float]]],
            list[dict[str, Any]],
        ]
    ] = []
    labels: set[str] = set()
    issues: list[dict[str, Any]] = []
    split_by_stem: dict[str, str] = {}
    split_root = root / "ImageSets" / "Main"
    for split in ("train", "val", "test"):
        split_file = split_root / f"{split}.txt"
        if not split_file.is_file():
            continue
        try:
            for line in split_file.read_text(encoding="utf-8").splitlines():
                # VOC classification sets may add a trailing presence flag.
                columns = line.split()
                if columns:
                    split_by_stem[columns[0]] = split
        except OSError as exc:
            issues.append(_issue("warning", "unreadable_split", str(exc), split_file))

    for xml_path in xml_paths:
        parse_issues: list[dict[str, Any]] = []
        try:
            tree = ET.parse(xml_path)
            node = tree.getroot()
        except (OSError, ET.ParseError) as exc:
            issues.append(_issue("error", "invalid_voc", f"Cannot read {xml_path.name}: {exc}"))
            continue
        filename = node.findtext("filename") or f"{xml_path.stem}.jpg"
        image_path = _resolve_voc_image(root, filename)
        width = int(node.findtext("size/width") or 0)
        height = int(node.findtext("size/height") or 0)
        if width <= 0 or height <= 0:
            width, height = _image_dimensions(image_path)
        boxes: list[tuple[str, tuple[float, float, float, float]]] = []
        for obj in node.findall("object"):
            label = (obj.findtext("name") or "unknown").strip()
            box = obj.find("bndbox")
            if box is None:
                parse_issues.append(
                    _issue("error", "invalid_bbox", "VOC object has no bndbox", xml_path)
                )
                continue
            try:
                coords = (
                    float(box.findtext("xmin") or 0),
                    float(box.findtext("ymin") or 0),
                    float(box.findtext("xmax") or 0),
                    float(box.findtext("ymax") or 0),
                )
            except ValueError:
                parse_issues.append(
                    _issue("error", "invalid_bbox", "VOC bbox is not numeric", xml_path)
                )
                continue
            labels.add(label)
            boxes.append((label, coords))
        split = split_by_stem.get(xml_path.stem, _split_from_path(xml_path))
        pending.append((image_path, split, width, height, boxes, parse_issues))

    class_names: list[str] = []
    classes_path = root / "classes.txt"
    if classes_path.is_file():
        try:
            class_names = [
                line.strip()
                for line in classes_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError as exc:
            issues.append(_issue("warning", "unreadable_classes", str(exc), classes_path))
    class_names.extend(sorted(label for label in labels if label not in class_names))
    class_ids = {name: idx for idx, name in enumerate(class_names)}
    records: list[DatasetRecord] = []
    for image_path, split, width, height, boxes, parse_issues in pending:
        annotations: list[Annotation] = []
        for label, (x1, y1, x2, y2) in boxes:
            box_w, box_h = x2 - x1, y2 - y1
            annotations.append(
                Annotation(
                    class_id=class_ids[label],
                    label=label,
                    x_center=(x1 + x2) / 2.0 / max(width, 1),
                    y_center=(y1 + y2) / 2.0 / max(height, 1),
                    width=box_w / max(width, 1),
                    height=box_h / max(height, 1),
                )
            )
        records.append(
            DatasetRecord(image_path, None, split, annotations, width, height, parse_issues)
        )
    if not records:
        raise ValueError("No usable Pascal VOC records were found")
    return DatasetProject(root, root.name, "voc", class_names, records, None, issues)


def _yolo_image_candidates(root: Path, config: dict[str, Any]) -> list[tuple[Path, str]]:
    found: dict[Path, str] = {}
    dataset_base = root
    configured_path = config.get("path")
    if isinstance(configured_path, str) and configured_path.strip():
        candidate = Path(configured_path)
        dataset_base = candidate if candidate.is_absolute() else (root / candidate).resolve()

    for split in ("train", "val", "test"):
        entries = config.get(split)
        if isinstance(entries, str):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue
            source = Path(entry)
            source = source if source.is_absolute() else dataset_base / source
            if source.is_dir():
                for path in _images_under(source):
                    found[path.resolve()] = split
            elif source.is_file() and source.suffix.lower() == ".txt":
                try:
                    lines = source.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                for line in lines:
                    path = Path(line.strip())
                    path = path if path.is_absolute() else dataset_base / path
                    if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                        found[path.resolve()] = split

    if not found:
        image_root = root / "images"
        search_root = image_root if image_root.is_dir() else root
        for path in _images_under(search_root):
            found[path.resolve()] = _split_from_path(path)
    return sorted(found.items(), key=lambda pair: str(pair[0]).lower())


def _images_under(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _yolo_label_path(root: Path, image_path: Path) -> Path:
    parts = list(image_path.parts)
    lowered = [part.lower() for part in parts]
    if "images" in lowered:
        index = len(lowered) - 1 - lowered[::-1].index("images")
        parts[index] = "labels"
        return Path(*parts).with_suffix(".txt")
    direct = root / "labels" / image_path.relative_to(root).with_suffix(".txt")
    if direct.exists():
        return direct
    return image_path.with_suffix(".txt")


def _read_yolo_labels(
    path: Path,
    class_names: list[str],
    pose_schema_id: str = "",
    keypoint_dims: int = 3,
) -> tuple[list[Annotation], list[dict[str, Any]], int]:
    annotations: list[Annotation] = []
    issues: list[dict[str, Any]] = []
    max_class_id = -1
    if not path.is_file():
        issues.append(_issue("warning", "missing_label", "No label file", path))
        return annotations, issues, max_class_id
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        issues.append(_issue("error", "unreadable_label", str(exc), path))
        return annotations, issues, max_class_id
    if not [line for line in lines if line.strip()]:
        issues.append(_issue("info", "empty_label", "Label file contains no objects", path))
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split()
        pose_point_count = {"coco_17": 17, "mediapipe_33": 33}.get(pose_schema_id, 0)
        expected_pose_values = 4 + pose_point_count * keypoint_dims
        is_pose_row = bool(pose_point_count and len(parts) - 1 == expected_pose_values)
        if not is_pose_row and len(parts) != 5 and (len(parts) < 7 or len(parts[1:]) % 2 != 0):
            issues.append(
                _issue(
                    "error",
                    "invalid_label_row",
                    f"Line {line_number}: expected YOLO box or polygon values, found {len(parts)}",
                    path,
                )
            )
            continue
        try:
            class_id = int(parts[0])
            values = [float(value) for value in parts[1:]]
        except ValueError:
            issues.append(
                _issue("error", "invalid_label_row", f"Line {line_number}: non-numeric value", path)
            )
            continue
        max_class_id = max(max_class_id, class_id)
        label = class_names[class_id] if 0 <= class_id < len(class_names) else f"class_{class_id}"
        if is_pose_row:
            points = []
            raw_points = values[4:]
            for index in range(0, len(raw_points), keypoint_dims):
                visibility = int(raw_points[index + 2]) if keypoint_dims >= 3 else 2
                points.append(
                    {
                        "x": raw_points[index],
                        "y": raw_points[index + 1],
                        "z": 0.0,
                        "visibility": visibility,
                        "presence": 1.0 if visibility else 0.0,
                    }
                )
            annotations.append(
                Annotation(
                    class_id,
                    values[0],
                    values[1],
                    values[2],
                    values[3],
                    label,
                    annotation_type="pose",
                    keypoints=normalize_keypoints(points, pose_schema_id),
                    pose_schema=pose_schema_id,
                    pose_workflow="top_down",
                    pose_has_bbox=True,
                )
            )
        elif len(values) == 4:
            annotations.append(
                Annotation(class_id, values[0], values[1], values[2], values[3], label)
            )
        else:
            polygon = list(zip(values[::2], values[1::2], strict=True))
            xs, ys = zip(*polygon, strict=True)
            annotations.append(
                Annotation(
                    class_id,
                    (min(xs) + max(xs)) / 2,
                    (min(ys) + max(ys)) / 2,
                    max(xs) - min(xs),
                    max(ys) - min(ys),
                    label,
                    polygon,
                    "polygon",
                )
            )
    return annotations, issues, max_class_id


def _class_names(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(value) for value in raw]
    if isinstance(raw, dict):
        pairs: list[tuple[int, str]] = []
        for key, value in raw.items():
            try:
                pairs.append((int(key), str(value)))
            except (TypeError, ValueError):
                continue
        if not pairs:
            return []
        maximum = max(key for key, _ in pairs)
        result = [f"class_{idx}" for idx in range(maximum + 1)]
        for key, value in pairs:
            result[key] = value
        return result
    return []


def _image_dimensions(path: Path) -> tuple[int, int]:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim < 2:
        return 0, 0
    return int(image.shape[1]), int(image.shape[0])


def _split_from_path(path: Path) -> str:
    lowered = [part.lower() for part in path.parts]
    for split, aliases in {
        "train": {"train", "training"},
        "val": {"val", "valid", "validation"},
        "test": {"test", "testing"},
    }.items():
        if any(alias in lowered for alias in aliases):
            return split
    return "unsplit"


def _split_from_name(name: str) -> str:
    lower = name.lower()
    if "train" in lower:
        return "train"
    if "val" in lower or "valid" in lower:
        return "val"
    if "test" in lower:
        return "test"
    return "unsplit"


def _resolve_coco_image(root: Path, filename: str, split: str) -> Path:
    candidates = [root / filename, root / "images" / filename, root / "images" / split / filename]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _resolve_voc_image(root: Path, filename: str) -> Path:
    candidates = [root / "JPEGImages" / filename, root / "images" / filename, root / filename]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _issue(severity: str, code: str, message: str, path: Path | None = None) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": str(path) if path else "",
    }
