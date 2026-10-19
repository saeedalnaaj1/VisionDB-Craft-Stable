"""Pose schemas shared by annotation, geometry, and export code."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

COCO_17_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

COCO_17_SKELETON = [
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
]

MEDIAPIPE_33_NAMES = [
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
]

MEDIAPIPE_33_SKELETON = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 7),
    (0, 4),
    (4, 5),
    (5, 6),
    (6, 8),
    (9, 10),
    (11, 12),
    (11, 13),
    (13, 15),
    (15, 17),
    (15, 19),
    (15, 21),
    (17, 19),
    (12, 14),
    (14, 16),
    (16, 18),
    (16, 20),
    (16, 22),
    (18, 20),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (24, 26),
    (25, 27),
    (26, 28),
    (27, 29),
    (28, 30),
    (29, 31),
    (30, 32),
    (27, 31),
    (28, 32),
]


def _flip_index(names: list[str]) -> list[int]:
    """Return the YOLO flip-index mapping for a named symmetric skeleton."""
    by_name = {name: index for index, name in enumerate(names)}
    result: list[int] = []
    for index, name in enumerate(names):
        if name.startswith("left_"):
            result.append(by_name.get(f"right_{name[5:]}", index))
        elif name.startswith("right_"):
            result.append(by_name.get(f"left_{name[6:]}", index))
        elif name.endswith("_left"):
            result.append(by_name.get(f"{name[:-5]}_right", index))
        elif name.endswith("_right"):
            result.append(by_name.get(f"{name[:-6]}_left", index))
        else:
            result.append(index)
    return result


POSE_SCHEMAS: dict[str, dict[str, Any]] = {
    "coco_17": {
        "label": "COCO / YOLO human pose (17)",
        "names": COCO_17_NAMES,
        "skeleton": COCO_17_SKELETON,
        "flip_idx": _flip_index(COCO_17_NAMES),
    },
    "mediapipe_33": {
        "label": "MediaPipe body landmarks (33)",
        "names": MEDIAPIPE_33_NAMES,
        "skeleton": MEDIAPIPE_33_SKELETON,
        "flip_idx": _flip_index(MEDIAPIPE_33_NAMES),
    },
}


def pose_schema(schema_id: str) -> dict[str, Any]:
    """Return a defensive copy of a supported schema."""
    key = schema_id if schema_id in POSE_SCHEMAS else "coco_17"
    schema: dict[str, Any] = deepcopy(POSE_SCHEMAS[key])
    return schema


def normalize_keypoints(raw: Any, schema_id: str) -> list[dict[str, Any]]:
    """Normalize pose points to named x/y/z/visibility/presence dictionaries."""
    schema = pose_schema(schema_id)
    names = schema["names"]
    values = raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        value = values[index] if index < len(values) else {}
        if isinstance(value, dict):
            x = float(value.get("x", 0.0))
            y = float(value.get("y", 0.0))
            z = float(value.get("z", 0.0))
            raw_visibility = value.get("visibility", value.get("v", 0))
            visibility = int(raw_visibility) if raw_visibility is not None else 0
            presence = float(value.get("presence", 1.0 if visibility else 0.0))
        elif isinstance(value, (list, tuple)):
            x = float(value[0]) if len(value) > 0 else 0.0
            y = float(value[1]) if len(value) > 1 else 0.0
            visibility = int(value[2]) if len(value) > 2 else 2
            z = float(value[3]) if len(value) > 3 else 0.0
            presence = float(value[4]) if len(value) > 4 else (1.0 if visibility else 0.0)
        else:
            x = y = z = presence = 0.0
            visibility = 0
        visibility = max(0, min(2, visibility))
        if visibility == 0:
            x = y = z = presence = 0.0
        elif not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError(f"Keypoint {name} must stay inside the image")
        result.append(
            {
                "name": name,
                "x": x,
                "y": y,
                "z": z,
                "visibility": visibility,
                "presence": max(0.0, min(1.0, presence)),
            }
        )
    return result


def pose_bounds(
    keypoints: list[dict[str, Any]], padding: float = 0.02
) -> tuple[float, float, float, float]:
    """Return a non-zero normalized box around labelled keypoints."""
    visible = [point for point in keypoints if int(point.get("visibility", 0)) > 0]
    if not visible:
        raise ValueError("Place at least one pose keypoint")
    xs = [float(point["x"]) for point in visible]
    ys = [float(point["y"]) for point in visible]
    left = max(0.0, min(xs) - padding)
    top = max(0.0, min(ys) - padding)
    right = min(1.0, max(xs) + padding)
    bottom = min(1.0, max(ys) + padding)
    if right - left < 0.002:
        left = max(0.0, left - 0.001)
        right = min(1.0, right + 0.001)
    if bottom - top < 0.002:
        top = max(0.0, top - 0.001)
        bottom = min(1.0, bottom + 0.001)
    return ((left + right) / 2.0, (top + bottom) / 2.0, right - left, bottom - top)
