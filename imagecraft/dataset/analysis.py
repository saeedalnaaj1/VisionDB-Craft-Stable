"""Dataset validation, statistics, duplicate detection and splitting."""

from __future__ import annotations

import hashlib
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import cv2

from imagecraft.dataset.models import Annotation, DatasetProject


class DatasetItemLike(Protocol):
    path: Path
    dataset_split: str
    annotation_path: Path | None
    is_generated: bool

    @property
    def is_modified(self) -> bool: ...

    @property
    def active(self) -> Any: ...

    @property
    def active_annotations(self) -> list[Annotation]: ...

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...


def validate_dataset(
    project: DatasetProject,
    items: Sequence[DatasetItemLike],
) -> dict[str, Any]:
    """Return a JSON-safe validation report without changing the dataset."""
    issues: list[dict[str, Any]] = list(project.imported_issues)
    for record in project.records:
        issues.extend(record.parse_issues)

    class_counts: Counter[int] = Counter()
    image_hashes: dict[str, list[DatasetItemLike]] = defaultdict(list)
    perceptual_hashes: list[tuple[DatasetItemLike, int]] = []
    known_label_paths = {
        item.annotation_path.resolve() for item in items if item.annotation_path is not None
    }

    for item in items:
        path = Path(item.path)
        if not path.is_file() and not item.is_generated:
            issues.append(_issue("error", "missing_image", "Image file is missing", path))
        seen_annotations: set[tuple[int, float, float, float, float]] = set()
        for index, ann in enumerate(item.active_annotations):
            class_counts[ann.class_id] += 1
            signature = (
                ann.class_id,
                round(ann.x_center, 7),
                round(ann.y_center, 7),
                round(ann.width, 7),
                round(ann.height, 7),
            )
            if signature in seen_annotations:
                issues.append(
                    _issue(
                        "warning",
                        "duplicate_annotation",
                        f"Object {index + 1} duplicates another bounding box",
                        path,
                    )
                )
            seen_annotations.add(signature)
            if ann.class_id < 0 or ann.class_id >= len(project.class_names):
                issues.append(
                    _issue(
                        "error",
                        "invalid_class_id",
                        f"Object {index + 1} uses class ID {ann.class_id}",
                        path,
                    )
                )
            if not ann.is_normalized:
                issues.append(
                    _issue(
                        "error",
                        "invalid_bbox",
                        f"Object {index + 1} has an out-of-range or zero-area box",
                        path,
                    )
                )
            elif ann.area < 0.0001:
                issues.append(
                    _issue(
                        "warning",
                        "tiny_bbox",
                        f"Object {index + 1} occupies less than 0.01% of the image",
                        path,
                    )
                )
        if item.is_modified or item.is_generated:
            image_hashes[_active_sha256(item)].append(item)
        elif path.is_file():
            try:
                digest = _sha256(path)
                image_hashes[digest].append(item)
                if len(perceptual_hashes) < 2500:
                    perceptual_hashes.append((item, _dhash(path)))
            except OSError:
                issues.append(_issue("error", "unreadable_image", "Image cannot be read", path))

    # Label files that have no corresponding image.
    labels_root = project.root / "labels"
    if labels_root.is_dir():
        for label_path in labels_root.rglob("*.txt"):
            if label_path.resolve() not in known_label_paths:
                issues.append(
                    _issue("warning", "orphan_label", "Label has no matching image", label_path)
                )

    for duplicates in image_hashes.values():
        if len(duplicates) < 2:
            continue
        paths = ", ".join(Path(item.path).name for item in duplicates[:4])
        splits = {item.dataset_split for item in duplicates}
        severity = "error" if len(splits) > 1 else "warning"
        code = "split_leakage" if len(splits) > 1 else "duplicate_image"
        message = (
            f"Identical image appears across splits: {paths}"
            if len(splits) > 1
            else f"Duplicate images: {paths}"
        )
        issues.append(_issue(severity, code, message, Path(duplicates[0].path)))

    # Catch resized/recompressed/lightly edited copies with different hashes.
    for index, (left, left_hash) in enumerate(perceptual_hashes):
        for right, right_hash in perceptual_hashes[index + 1:]:
            if (left_hash ^ right_hash).bit_count() <= 6:
                issues.append(
                    _issue(
                        "warning",
                        "near_duplicate_image",
                        "Images are visually very similar: "
                        f"{Path(left.path).name} and {Path(right.path).name}",
                        Path(left.path),
                    )
                )

    nonzero = [count for count in class_counts.values() if count > 0]
    if len(nonzero) > 1 and max(nonzero) / max(1, min(nonzero)) >= 10:
        issues.append(
            _issue(
                "warning",
                "class_imbalance",
                "The most frequent class has at least 10× more objects than "
                "the least frequent class",
            )
        )

    counts = Counter(issue["severity"] for issue in issues)
    score = max(0, 100 - counts["error"] * 8 - counts["warning"] * 2)
    return {
        "ok": counts["error"] == 0,
        "health_score": score,
        "summary": {
            "errors": counts["error"],
            "warnings": counts["warning"],
            "info": counts["info"],
            "total": len(issues),
        },
        "issues": issues,
    }


def dataset_statistics(project: DatasetProject, items: Sequence[DatasetItemLike]) -> dict[str, Any]:
    class_counts: Counter[int] = Counter()
    split_images: Counter[str] = Counter()
    split_objects: Counter[str] = Counter()
    widths: list[int] = []
    heights: list[int] = []
    box_areas: list[float] = []
    empty_images = 0

    for item in items:
        split_images[item.dataset_split] += 1
        widths.append(item.width)
        heights.append(item.height)
        annotations = item.active_annotations
        if not annotations:
            empty_images += 1
        for ann in annotations:
            class_counts[ann.class_id] += 1
            split_objects[item.dataset_split] += 1
            box_areas.append(ann.area)

    classes = []
    for class_id, name in enumerate(project.class_names):
        classes.append({"id": class_id, "name": name, "objects": class_counts[class_id]})
    return {
        "project": project.as_summary(),
        "images": len(items),
        "objects": sum(class_counts.values()),
        "class_count": len(project.class_names),
        "empty_images": empty_images,
        "classes": classes,
        "splits": {
            split: {"images": count, "objects": split_objects[split]}
            for split, count in sorted(split_images.items())
        },
        "dimensions": {
            "min_width": min(widths, default=0),
            "max_width": max(widths, default=0),
            "min_height": min(heights, default=0),
            "max_height": max(heights, default=0),
            "average_width": round(sum(widths) / len(widths), 1) if widths else 0,
            "average_height": round(sum(heights) / len(heights), 1) if heights else 0,
        },
        "boxes": {
            "average_area_percent": round(
                (sum(box_areas) / len(box_areas) * 100.0) if box_areas else 0.0, 3
            ),
            "tiny_count": sum(area < 0.0001 for area in box_areas),
        },
    }


def assign_splits(
    items: Sequence[DatasetItemLike],
    train: float,
    val: float,
    test: float,
    seed: int,
) -> dict[str, int]:
    """Deterministically assign class-aware train/val/test splits in place."""
    total_ratio = train + val + test
    if total_ratio <= 0:
        raise ValueError("Split percentages must add up to more than zero")
    ratios = {
        "train": train / total_ratio,
        "val": val / total_ratio,
        "test": test / total_ratio,
    }
    split_names = [name for name, ratio in ratios.items() if ratio > 0]
    total = len(items)
    capacities = {name: int(total * ratios[name]) for name in split_names}
    while sum(capacities.values()) < total:
        name = max(split_names, key=lambda split: ratios[split] - capacities[split] / max(total, 1))
        capacities[name] += 1

    global_classes = Counter(ann.class_id for item in items for ann in item.active_annotations)
    targets = {
        split: {class_id: count * ratios[split] for class_id, count in global_classes.items()}
        for split in split_names
    }
    assigned_classes: dict[str, Counter[int]] = {split: Counter() for split in split_names}
    assigned_counts: Counter[str] = Counter()

    rng = random.Random(seed)
    ordered = list(items)
    rng.shuffle(ordered)
    ordered.sort(
        key=lambda item: min(
            (global_classes[ann.class_id] for ann in item.active_annotations),
            default=10**9,
        )
    )

    for item in ordered:
        item_classes = Counter(ann.class_id for ann in item.active_annotations)
        available = [
            split for split in split_names if assigned_counts[split] < capacities[split]
        ] or split_names

        def score(split: str, classes: Counter[int] = item_classes) -> float:
            capacity_left = capacities[split] - assigned_counts[split]
            class_need = sum(
                max(0.0, targets[split].get(class_id, 0.0) - assigned_classes[split][class_id])
                * count
                for class_id, count in classes.items()
            )
            return class_need + capacity_left / max(1, total)

        chosen = max(available, key=score)
        item.dataset_split = chosen
        assigned_counts[chosen] += 1
        assigned_classes[chosen].update(item_classes)
    return dict(assigned_counts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _active_sha256(item: DatasetItemLike) -> str:
    digest = hashlib.sha256()
    digest.update(f"{item.width}x{item.height}:".encode("ascii"))
    digest.update(item.active.tobytes())
    return digest.hexdigest()


def _dhash(path: Path) -> int:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise OSError(f"Cannot read image: {path}")
    small = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in bits.flat:
        value = (value << 1) | int(bit)
    return value


def _issue(severity: str, code: str, message: str, path: Path | None = None) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": str(path) if path else "",
    }
