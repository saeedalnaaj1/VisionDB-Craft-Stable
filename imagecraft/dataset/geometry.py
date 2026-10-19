"""Annotation geometry that mirrors VisionDB Craft's OpenCV pipelines."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy

import cv2
import numpy as np
import numpy.typing as npt

from imagecraft.dataset.masks import decode_rle, encode_rle, mask_bbox
from imagecraft.dataset.models import Annotation
from imagecraft.dataset.pose import pose_bounds, pose_schema
from imagecraft.models.transformation import (
    AugmentParams,
    TransformParams,
    _is_identity_perspective,
    resolve_crop_rect,
)


def resize_annotations(
    annotations: Iterable[Annotation],
    width: int | None = None,
    height: int | None = None,
) -> list[Annotation]:
    """Resize bitmap masks; normalized vector geometry remains unchanged."""
    result: list[Annotation] = []
    for ann in annotations:
        if ann.mask_rle and width and height and width > 0 and height > 0:
            mask = decode_rle(ann.mask_rle)
            resized = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
            box = mask_bbox(resized)
            if box is not None:
                result.append(
                    Annotation(
                        ann.class_id,
                        *box,
                        ann.label,
                        annotation_type="mask",
                        mask_rle=encode_rle(resized),
                        metadata=deepcopy(ann.metadata),
                    )
                )
            continue
        result.append(ann.copy())
    return result


def transform_annotations(
    annotations: Iterable[Annotation],
    params: TransformParams,
    width: int,
    height: int,
    min_visibility: float = 0.20,
) -> list[Annotation]:
    """Apply the transform panel's geometry to normalized bounding boxes."""
    matrix = np.eye(3, dtype=np.float64)

    if not _is_identity_perspective(params.src_points, width, height):
        dst = np.asarray([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
        perspective = cv2.getPerspectiveTransform(params.src_points, dst)
        matrix = perspective.astype(np.float64) @ matrix

    if params.translate_x or params.translate_y:
        translate = np.asarray(
            [[1, 0, params.translate_x], [0, 1, params.translate_y], [0, 0, 1]],
            dtype=np.float64,
        )
        matrix = translate @ matrix

    if params.rotation or params.scale != 100:
        affine = cv2.getRotationMatrix2D(
            (width / 2.0, height / 2.0), params.rotation, params.scale / 100.0
        )
        rotate = np.vstack([affine, [0, 0, 1]]).astype(np.float64)
        matrix = rotate @ matrix

    crop_x, crop_y, out_w, out_h = resolve_crop_rect(params, width, height)
    if (crop_x, crop_y, out_w, out_h) != (0, 0, width, height):
        crop = np.asarray([[1, 0, -crop_x], [0, 1, -crop_y], [0, 0, 1]], dtype=np.float64)
        matrix = crop @ matrix

    return _apply_matrix(annotations, matrix, width, height, out_w, out_h, min_visibility)


def augment_annotations(
    annotations: Iterable[Annotation],
    params: AugmentParams,
    width: int,
    height: int,
    min_visibility: float = 0.20,
) -> list[Annotation]:
    """Mirror every geometric stage in ``run_augment_pipeline``."""
    matrix = np.eye(3, dtype=np.float64)
    out_w, out_h = width, height

    if params.rotation or params.scale != 100:
        affine = cv2.getRotationMatrix2D(
            (out_w / 2.0, out_h / 2.0), params.rotation, params.scale / 100.0
        )
        matrix = np.vstack([affine, [0, 0, 1]]).astype(np.float64) @ matrix

    if params.translate:
        translate = np.asarray(
            [[1, 0, params.translate], [0, 1, params.translate], [0, 0, 1]],
            dtype=np.float64,
        )
        matrix = translate @ matrix

    if params.shear:
        tangent = float(np.tan(np.radians(params.shear)))
        shear = np.asarray([[1, tangent, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
        matrix = shear @ matrix
        out_w = width + int(abs(tangent) * height)

    if params.flip_vertical:
        vertical = np.asarray([[1, 0, 0], [0, -1, out_h], [0, 0, 1]], dtype=np.float64)
        matrix = vertical @ matrix
    if params.flip_horizontal:
        horizontal = np.asarray([[-1, 0, out_w], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
        matrix = horizontal @ matrix

    if params.padding_enabled:
        target_w = max(out_w, params.padding_width)
        target_h = max(out_h, params.padding_height)
        left = (target_w - out_w) // 2
        top = (target_h - out_h) // 2
        padding = np.asarray([[1, 0, left], [0, 1, top], [0, 0, 1]], dtype=np.float64)
        matrix = padding @ matrix
        out_w, out_h = target_w, target_h

    return _apply_matrix(
        annotations,
        matrix,
        width,
        height,
        out_w,
        out_h,
        min_visibility,
        flip_horizontal=params.flip_horizontal,
    )


def _apply_matrix(
    annotations: Iterable[Annotation],
    matrix: npt.NDArray[np.float64],
    in_w: int,
    in_h: int,
    out_w: int,
    out_h: int,
    min_visibility: float,
    *,
    flip_horizontal: bool = False,
) -> list[Annotation]:
    result: list[Annotation] = []
    if in_w <= 0 or in_h <= 0 or out_w <= 0 or out_h <= 0:
        return result

    for ann in annotations:
        if ann.annotation_type == "classification":
            result.append(ann.copy())
            continue
        if ann.annotation_type == "pose" and ann.keypoints:
            keypoints = deepcopy(ann.keypoints)
            for point in keypoints:
                if int(point.get("visibility", 0)) <= 0:
                    continue
                source = np.asarray(
                    [[[float(point["x"]) * in_w, float(point["y"]) * in_h]]],
                    dtype=np.float32,
                )
                transformed = cv2.perspectiveTransform(source, matrix.astype(np.float32))[0][0]
                normalized_x = float(transformed[0] / out_w)
                normalized_y = float(transformed[1] / out_h)
                if not 0.0 <= normalized_x <= 1.0 or not 0.0 <= normalized_y <= 1.0:
                    point.update({"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0, "presence": 0.0})
                else:
                    point["x"] = normalized_x
                    point["y"] = normalized_y
            if flip_horizontal:
                flip_idx = pose_schema(ann.pose_schema)["flip_idx"]
                keypoints = [deepcopy(keypoints[source]) for source in flip_idx]
                names = pose_schema(ann.pose_schema)["names"]
                for index, point in enumerate(keypoints):
                    point["name"] = names[index]
            if not any(int(point.get("visibility", 0)) > 0 for point in keypoints):
                continue
            if ann.pose_has_bbox:
                x1 = (ann.x_center - ann.width / 2.0) * in_w
                y1 = (ann.y_center - ann.height / 2.0) * in_h
                x2 = (ann.x_center + ann.width / 2.0) * in_w
                y2 = (ann.y_center + ann.height / 2.0) * in_h
                corners = np.asarray([[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]], dtype=np.float32)
                warped = cv2.perspectiveTransform(corners, matrix.astype(np.float32))[0]
                left = float(np.clip(warped[:, 0].min(), 0, out_w))
                top = float(np.clip(warped[:, 1].min(), 0, out_h))
                right = float(np.clip(warped[:, 0].max(), 0, out_w))
                bottom = float(np.clip(warped[:, 1].max(), 0, out_h))
                if right - left < 1.0 or bottom - top < 1.0:
                    continue
                pose_box = (
                    ((left + right) / 2.0) / out_w,
                    ((top + bottom) / 2.0) / out_h,
                    (right - left) / out_w,
                    (bottom - top) / out_h,
                )
            else:
                pose_box = pose_bounds(keypoints)
            result.append(
                Annotation(
                    ann.class_id,
                    *pose_box,
                    ann.label,
                    annotation_type="pose",
                    keypoints=keypoints,
                    pose_schema=ann.pose_schema,
                    pose_workflow=ann.pose_workflow,
                    pose_has_bbox=ann.pose_has_bbox,
                    metadata=deepcopy(ann.metadata),
                )
            )
            continue
        if ann.mask_rle:
            mask = decode_rle(ann.mask_rle)
            if mask.shape != (in_h, in_w):
                mask = np.asarray(
                    cv2.resize(mask, (in_w, in_h), interpolation=cv2.INTER_NEAREST),
                    dtype=np.uint8,
                )
            # Annotation matrices operate on image-edge coordinates (0..W),
            # while OpenCV warps address pixel centres (0..W-1).  Conjugating
            # by half a pixel keeps raster masks exactly aligned with cv2.flip,
            # resize and the image pipelines, without changing vector boxes.
            to_edges = np.asarray([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]], dtype=np.float64)
            to_centres = np.asarray([[1, 0, -0.5], [0, 1, -0.5], [0, 0, 1]], dtype=np.float64)
            pixel_matrix = to_centres @ matrix @ to_edges
            warped_mask = cv2.warpPerspective(
                mask,
                pixel_matrix,
                (out_w, out_h),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0.0,),
            )
            box = mask_bbox(warped_mask)
            if box is not None:
                result.append(
                    Annotation(
                        ann.class_id,
                        *box,
                        ann.label,
                        annotation_type="mask",
                        mask_rle=encode_rle(warped_mask),
                        metadata=deepcopy(ann.metadata),
                    )
                )
            continue
        if ann.polygon:
            points = np.asarray([[[x * in_w, y * in_h] for x, y in ann.polygon]], dtype=np.float32)
            warped_polygon = cv2.perspectiveTransform(points, matrix.astype(np.float32))[0]
            polygon = [
                (float(np.clip(x / out_w, 0, 1)), float(np.clip(y / out_h, 0, 1)))
                for x, y in warped_polygon
            ]
            if len(polygon) >= 3:
                xs, ys = zip(*polygon, strict=True)
                polygon_box = Annotation(
                    ann.class_id,
                    (min(xs) + max(xs)) / 2,
                    (min(ys) + max(ys)) / 2,
                    max(xs) - min(xs),
                    max(ys) - min(ys),
                    ann.label,
                    polygon,
                    "polygon",
                    metadata=deepcopy(ann.metadata),
                )
                if polygon_box.is_normalized:
                    result.append(polygon_box)
                    continue
        x1 = (ann.x_center - ann.width / 2.0) * in_w
        y1 = (ann.y_center - ann.height / 2.0) * in_h
        x2 = (ann.x_center + ann.width / 2.0) * in_w
        y2 = (ann.y_center + ann.height / 2.0) * in_h
        corners = np.asarray([[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]], dtype=np.float32)
        warped = cv2.perspectiveTransform(corners, matrix.astype(np.float32))[0]
        raw_x1, raw_y1 = warped.min(axis=0)
        raw_x2, raw_y2 = warped.max(axis=0)
        raw_area = max(0.0, float(raw_x2 - raw_x1)) * max(0.0, float(raw_y2 - raw_y1))
        if raw_area <= 1e-6:
            continue

        clipped_x1 = float(np.clip(raw_x1, 0, out_w))
        clipped_y1 = float(np.clip(raw_y1, 0, out_h))
        clipped_x2 = float(np.clip(raw_x2, 0, out_w))
        clipped_y2 = float(np.clip(raw_y2, 0, out_h))
        box_w = clipped_x2 - clipped_x1
        box_h = clipped_y2 - clipped_y1
        visible_area = max(0.0, box_w) * max(0.0, box_h)
        if box_w < 1.0 or box_h < 1.0 or visible_area / raw_area < min_visibility:
            continue

        result.append(
            Annotation(
                class_id=ann.class_id,
                label=ann.label,
                x_center=((clipped_x1 + clipped_x2) / 2.0) / out_w,
                y_center=((clipped_y1 + clipped_y2) / 2.0) / out_h,
                width=box_w / out_w,
                height=box_h / out_h,
                metadata=deepcopy(ann.metadata),
            )
        )
    return result
