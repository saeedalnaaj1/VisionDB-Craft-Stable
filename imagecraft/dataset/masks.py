"""Bitmap mask helpers with dependency-free COCO RLE support.

COCO stores masks in column-major (Fortran) order and permits either an
uncompressed list of run lengths or the compact ASCII representation used by
``pycocotools``.  Keeping the codec here avoids making that compiled package a
runtime requirement on Windows while remaining interoperable with COCO tools.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

MaskArray = npt.NDArray[np.uint8]


def encode_rle(mask: npt.ArrayLike, *, compressed: bool = True) -> dict[str, Any]:
    """Encode a two-dimensional binary mask as a COCO RLE dictionary."""
    binary = np.asarray(mask, dtype=np.uint8)
    if binary.ndim != 2:
        raise ValueError("A bitmap mask must be a two-dimensional array")
    binary = (binary > 0).astype(np.uint8)
    flat = binary.ravel(order="F")
    counts: list[int] = []
    previous = 0
    run = 0
    for value in flat:
        current = int(value)
        if current == previous:
            run += 1
        else:
            counts.append(run)
            run = 1
            previous = current
    counts.append(run)
    encoded: str | list[int] = _compress_counts(counts) if compressed else counts
    return {"size": [int(binary.shape[0]), int(binary.shape[1])], "counts": encoded}


def decode_rle(rle: dict[str, Any]) -> MaskArray:
    """Decode compressed or uncompressed COCO RLE into a uint8 0/1 mask."""
    if not isinstance(rle, dict):
        raise ValueError("Mask RLE must be an object")
    size = rle.get("size")
    if not isinstance(size, Sequence) or isinstance(size, (str, bytes)) or len(size) != 2:
        raise ValueError("Mask RLE needs a [height, width] size")
    height, width = int(size[0]), int(size[1])
    if height <= 0 or width <= 0:
        raise ValueError("Mask RLE dimensions must be positive")
    raw_counts = rle.get("counts")
    if isinstance(raw_counts, bytes):
        raw_counts = raw_counts.decode("ascii")
    if isinstance(raw_counts, str):
        counts = _decompress_counts(raw_counts)
    elif isinstance(raw_counts, Sequence):
        counts = [int(value) for value in raw_counts]
    else:
        raise ValueError("Mask RLE counts must be a string or list")
    if any(value < 0 for value in counts):
        raise ValueError("Mask RLE contains a negative run length")

    total = height * width
    if sum(counts) != total:
        raise ValueError("Mask RLE run lengths do not match its dimensions")
    flat = np.zeros(total, dtype=np.uint8)
    cursor = 0
    foreground = False
    for run in counts:
        end = cursor + run
        if foreground and run:
            flat[cursor:end] = 1
        cursor = end
        foreground = not foreground
    return np.ascontiguousarray(
        flat.reshape((height, width), order="F"), dtype=np.uint8
    )


def normalize_rle(rle: dict[str, Any], *, compressed: bool = True) -> dict[str, Any]:
    """Validate and return a JSON-safe canonical RLE dictionary."""
    return encode_rle(decode_rle(rle), compressed=compressed)


def mask_bbox(mask: npt.ArrayLike) -> tuple[float, float, float, float] | None:
    """Return a normalized ``(x_center, y_center, width, height)`` mask box."""
    binary = np.asarray(mask)
    if binary.ndim != 2 or binary.size == 0:
        return None
    ys, xs = np.nonzero(binary)
    if not len(xs):
        return None
    height, width = binary.shape
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    return (
        ((x1 + x2) / 2.0) / width,
        ((y1 + y2) / 2.0) / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    )


def mask_to_polygons(mask: npt.ArrayLike) -> list[list[tuple[float, float]]]:
    """Trace external mask contours as normalized polygons for YOLO export."""
    binary = (np.asarray(mask, dtype=np.uint8) > 0).astype(np.uint8)
    if binary.ndim != 2 or not binary.any():
        return []
    height, width = binary.shape
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons: list[list[tuple[float, float]]] = []
    for contour in contours:
        points = contour.reshape(-1, 2)
        if len(points) < 3:
            continue
        polygon = [
            (float(x) / max(width, 1), float(y) / max(height, 1))
            for x, y in points
        ]
        polygons.append(polygon)
    return polygons


def annotation_mask(
    annotation: Any,
    width: int,
    height: int,
) -> MaskArray | None:
    """Rasterize a mask, polygon, or box annotation at the requested size."""
    if width <= 0 or height <= 0:
        return None
    if getattr(annotation, "mask_rle", None):
        mask = decode_rle(annotation.mask_rle)
        if mask.shape != (height, width):
            mask = np.asarray(
                cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST),
                dtype=np.uint8,
            )
        return (mask > 0).astype(np.uint8)

    mask = np.zeros((height, width), dtype=np.uint8)
    polygon = getattr(annotation, "polygon", None)
    if polygon and len(polygon) >= 3:
        points = np.asarray(
            [[round(x * width), round(y * height)] for x, y in polygon], dtype=np.int32
        )
        cv2.fillPoly(mask, [points], (1.0,))
        return mask
    if getattr(annotation, "annotation_type", "bbox") == "classification":
        return None
    x1 = round((annotation.x_center - annotation.width / 2.0) * width)
    y1 = round((annotation.y_center - annotation.height / 2.0) * height)
    x2 = round((annotation.x_center + annotation.width / 2.0) * width)
    y2 = round((annotation.y_center + annotation.height / 2.0) * height)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    mask[y1:y2, x1:x2] = 1
    return mask


def _compress_counts(counts: Sequence[int]) -> str:
    chars: list[str] = []
    for index, original in enumerate(counts):
        value = int(original)
        if index > 2:
            value -= int(counts[index - 2])
        more = True
        while more:
            char = value & 0x1F
            value >>= 5
            more = value != (-1 if char & 0x10 else 0)
            if more:
                char |= 0x20
            chars.append(chr(char + 48))
    return "".join(chars)


def _decompress_counts(value: str) -> list[int]:
    counts: list[int] = []
    position = 0
    while position < len(value):
        result = 0
        shift = 0
        more = True
        char = 0
        while more:
            if position >= len(value):
                raise ValueError("Mask RLE counts string is truncated")
            char = ord(value[position]) - 48
            position += 1
            if char < 0 or char > 0x3F:
                raise ValueError("Mask RLE counts string contains an invalid character")
            result |= (char & 0x1F) << (5 * shift)
            more = bool(char & 0x20)
            shift += 1
        if char & 0x10:
            result |= -1 << (5 * shift)
        if len(counts) > 2:
            result += counts[-2]
        counts.append(result)
    return counts
