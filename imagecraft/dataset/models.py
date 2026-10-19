"""Format-neutral dataset models used by importers, validators and exporters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass
class Annotation:
    """One classification, box, segmentation, or pose annotation."""

    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float
    label: str = ""
    polygon: list[tuple[float, float]] | None = None
    annotation_type: str = "bbox"
    mask_rle: dict[str, Any] | None = None
    keypoints: list[dict[str, Any]] | None = None
    pose_schema: str = ""
    pose_workflow: str = ""
    pose_has_bbox: bool = False
    # VisionDB Craft-only provenance/review information. Standard YOLO, COCO, VOC
    # and mask exporters intentionally ignore this field, so training labels
    # remain fully compatible with third-party tooling.
    metadata: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> Annotation:
        return replace(
            self,
            polygon=list(self.polygon) if self.polygon else None,
            mask_rle=deepcopy(self.mask_rle),
            keypoints=deepcopy(self.keypoints),
            metadata=deepcopy(self.metadata),
        )

    def as_dict(self) -> dict[str, Any]:
        result = {
            "class_id": self.class_id,
            "label": self.label or f"class_{self.class_id}",
            "x": self.x_center,
            "y": self.y_center,
            "w": self.width,
            "h": self.height,
            "type": self.annotation_type,
        }
        if self.polygon:
            result["polygon"] = [[x, y] for x, y in self.polygon]
        if self.mask_rle:
            result["mask_rle"] = deepcopy(self.mask_rle)
        if self.keypoints is not None:
            result["keypoints"] = deepcopy(self.keypoints)
            result["pose_schema"] = self.pose_schema
            result["pose_workflow"] = self.pose_workflow
            result["pose_has_bbox"] = self.pose_has_bbox
        if self.metadata:
            result["metadata"] = deepcopy(self.metadata)
        return result

    def to_yolo(self) -> str:
        if self.annotation_type == "classification":
            return str(self.class_id)
        if self.annotation_type == "pose":
            points = " ".join(
                f"{float(point['x']):.8f} {float(point['y']):.8f} {int(point.get('visibility', 0))}"
                for point in (self.keypoints or [])
            )
            return (
                f"{self.class_id} {self.x_center:.8f} {self.y_center:.8f} "
                f"{self.width:.8f} {self.height:.8f} {points}"
            ).rstrip()
        if self.polygon and len(self.polygon) >= 3:
            points = " ".join(f"{x:.8f} {y:.8f}" for x, y in self.polygon)
            return f"{self.class_id} {points}"
        return (
            f"{self.class_id} {self.x_center:.8f} {self.y_center:.8f} "
            f"{self.width:.8f} {self.height:.8f}"
        )

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def is_normalized(self) -> bool:
        if self.annotation_type == "classification":
            return self.class_id >= 0
        if self.annotation_type == "pose":
            visible = [
                point for point in (self.keypoints or []) if int(point.get("visibility", 0)) > 0
            ]
            if not visible or any(
                not 0.0 <= float(point.get(axis, -1.0)) <= 1.0
                for point in visible
                for axis in ("x", "y")
            ):
                return False
        return (
            0.0 <= self.x_center <= 1.0
            and 0.0 <= self.y_center <= 1.0
            and 0.0 < self.width <= 1.0
            and 0.0 < self.height <= 1.0
            and self.x_center - self.width / 2.0 >= -1e-6
            and self.y_center - self.height / 2.0 >= -1e-6
            and self.x_center + self.width / 2.0 <= 1.0 + 1e-6
            and self.y_center + self.height / 2.0 <= 1.0 + 1e-6
        )


@dataclass
class DatasetRecord:
    """One source image and its annotation/metadata relationship."""

    image_path: Path
    annotation_path: Path | None
    split: str = "unsplit"
    annotations: list[Annotation] = field(default_factory=list)
    width: int = 0
    height: int = 0
    parse_issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DatasetProject:
    """A loaded dataset project independent of any on-screen UI state."""

    root: Path
    name: str
    source_format: str
    class_names: list[str]
    records: list[DatasetRecord]
    config_path: Path | None = None
    imported_issues: list[dict[str, Any]] = field(default_factory=list)
    task_type: str = "detection"

    def as_summary(self) -> dict[str, Any]:
        split_counts: dict[str, int] = {}
        pose_schemas: set[str] = set()
        for record in self.records:
            split_counts[record.split] = split_counts.get(record.split, 0) + 1
            pose_schemas.update(
                annotation.pose_schema
                for annotation in record.annotations
                if annotation.annotation_type == "pose" and annotation.pose_schema
            )
        return {
            "active": True,
            "name": self.name,
            "root": str(self.root),
            "format": self.source_format,
            "classes": list(self.class_names),
            "image_count": len(self.records),
            "splits": split_counts,
            "task_type": self.task_type,
            "pose_schemas": sorted(pose_schemas),
        }
