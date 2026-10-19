"""Tests for the pure CV pipeline in ``imagecraft.models.transformation``."""

from __future__ import annotations

import numpy as np
import pytest

from imagecraft.models.transformation import (
    AugmentParams,
    TransformParams,
    apply_crop,
    apply_exposure,
    apply_flip,
    apply_gaussian_blur,
    apply_hsv,
    apply_noise,
    apply_oil_painting,
    apply_padding,
    apply_perspective,
    apply_rotate_scale,
    apply_salt_pepper,
    apply_sharpen,
    apply_shear,
    apply_softness,
    apply_translate,
    apply_white_balance,
    resize_image,
    run_augment_pipeline,
    run_transform_pipeline,
)

# ---------------------------------------------------------------------------
# Shape / identity guarantees
# ---------------------------------------------------------------------------


def test_identity_transform_preserves_image(image):
    # Identity requires the perspective points to match the actual image rect.
    h, w = image.shape[:2]
    params = TransformParams(tr_x=w, tr_y=0, br_x=w, br_y=h, bl_x=0, bl_y=h)
    out = run_transform_pipeline(image, params)
    assert out.shape == image.shape
    np.testing.assert_array_equal(out, image)


def test_identity_augment_preserves_image(image):
    out = run_augment_pipeline(image, AugmentParams())
    assert out.shape == image.shape
    np.testing.assert_array_equal(out, image)


def test_original_never_mutated(image):
    snapshot = image.copy()
    run_augment_pipeline(image, AugmentParams(sharpen=50, oil=40, exposure=1.0))
    np.testing.assert_array_equal(image, snapshot)


# ---------------------------------------------------------------------------
# Transform ops
# ---------------------------------------------------------------------------


def test_perspective_identity(image):
    out = apply_perspective(image, np.asarray(
        [[0, 0], [image.shape[1], 0], [image.shape[1], image.shape[0]], [0, image.shape[0]]],
        dtype=np.float32,
    ))
    assert out.shape == image.shape


def test_perspective_invalid_points_raises(image):
    bad = np.asarray([[0, 0], [0, 0], [1, 1], [2, 2]], dtype=np.float32)
    with pytest.raises(ValueError):
        apply_perspective(image, bad)


def test_translate_shifts_content(image):
    # The white square (cols 60-100) moves 10px right after a +10 translate.
    out = apply_translate(image, 10, 0)
    assert out.shape == image.shape
    assert np.all(out[50, 70] == 255)      # square's left edge now at col 70
    assert not np.all(out[50, 60] == 255)  # col 60 is no longer the square


def test_rotate_90_changes_shape_orientation(image):
    h, w = image.shape[:2]
    out = apply_rotate_scale(image, 90, 1.0)
    assert out.shape == (h, w, 3)  # canvas stays w×h


def test_crop_reduces_size(image):
    out = apply_crop(image, 10, 10, 50, 40)
    assert out.shape == (40, 50, 3)


def test_crop_clamped_to_bounds(image):
    h, w = image.shape[:2]
    out = apply_crop(image, w - 20, h - 20, 1000, 1000)
    assert out.shape == (20, 20, 3)


def test_crop_zero_size_clamped(image):
    # A zero-width rectangle is silently clamped up to the minimum edge rather
    # than rejected — required so a live crop drag across the opposite edge
    # never throws mid-gesture. clamp_crop_rect documents "never raises".
    out = apply_crop(image, 0, 0, 0, 10)
    assert out.shape == (10, 8, 3)


def test_crop_empty_image_raises(image):
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        apply_crop(empty, 0, 0, 5, 5)


# ---------------------------------------------------------------------------
# Augment ops
# ---------------------------------------------------------------------------


def test_white_balance_positive_brighter(image):
    out = apply_white_balance(image, 50)
    assert out.shape == image.shape
    assert float(out.mean()) > float(image.mean())


def test_white_balance_negative_darker(image):
    out = apply_white_balance(image, -50)
    assert float(out.mean()) < float(image.mean())


def test_hsv_shift_changes_colors(image):
    out = apply_hsv(image, 30, 0, 0)
    assert not np.array_equal(out, image)


def test_rotate_scale_image(image):
    out = apply_rotate_scale(image, 30, 0.8)
    assert out.shape == image.shape


def test_shear_widens_image(image):
    out = apply_shear(image, 20)
    assert out.shape[1] >= image.shape[1]


def test_noise_adds_difference(image):
    out = apply_noise(image, 40)
    assert not np.array_equal(out, image)


def test_noise_zero_is_identity(image):
    np.testing.assert_array_equal(apply_noise(image, 0), image)


def test_flip_vertical(image):
    out = apply_flip(image, vertical=True, horizontal=False)
    np.testing.assert_array_equal(out, image[::-1])


def test_flip_horizontal(image):
    out = apply_flip(image, vertical=False, horizontal=True)
    np.testing.assert_array_equal(out, image[:, ::-1])


def test_padding_reaches_target(image):
    out = apply_padding(image, 300, 200)
    assert out.shape == (200, 300, 3)
    assert np.all(out[0, :, :] == 255)  # top border white


def test_padding_smaller_target_unchanged(image):
    np.testing.assert_array_equal(apply_padding(image, 10, 10), image)


# ---------------------------------------------------------------------------
# New v2 augmentations
# ---------------------------------------------------------------------------


def test_salt_pepper_changes_pixels(image):
    out = apply_salt_pepper(image, 60)
    assert out.shape == image.shape
    diff = np.count_nonzero(np.any(out != image, axis=2))
    assert 0 < diff < image.shape[0] * image.shape[1] // 4


def test_salt_pepper_zero_is_identity(image):
    np.testing.assert_array_equal(apply_salt_pepper(image, 0), image)


def test_gaussian_blur_smooths(image):
    # Row 10 is outside the white square, so cols 79/80 are the red→green edge.
    out = apply_gaussian_blur(image, 40)
    edge_strength = np.abs(image[10, 79].astype(int) - image[10, 80].astype(int)).sum()
    edge_strength_out = np.abs(out[10, 79].astype(int) - out[10, 80].astype(int)).sum()
    assert edge_strength_out < edge_strength  # edge softened


def test_gaussian_blur_zero_is_identity(image):
    np.testing.assert_array_equal(apply_gaussian_blur(image, 0), image)


def test_softness_smooths_noise(small_image):
    out = apply_softness(small_image, 50)
    assert out.shape == small_image.shape
    assert not np.array_equal(out, small_image)
    assert float(out.var()) < float(small_image.var())  # noise smoothed


def test_sharpen_increases_edge_contrast(image):
    out = apply_sharpen(image, 80)
    edge = np.abs(image[:, 79] - image[:, 80]).sum()
    edge_out = np.abs(out[:, 79] - out[:, 80]).sum()
    assert edge_out >= edge


def test_oil_painting_smoothes_flat_regions(image):
    out = apply_oil_painting(image, 60)
    assert out.shape == image.shape
    # Flat white square should stay near-white and lose high-frequency detail.
    assert float(out[30:70, 60:100].mean()) > 200


def test_oil_painting_zero_is_identity(image):
    np.testing.assert_array_equal(apply_oil_painting(image, 0), image)


def test_exposure_positive_brighter(image):
    out = apply_exposure(image, 1.0)
    assert float(out.mean()) > float(image.mean())


def test_exposure_negative_darker(image):
    out = apply_exposure(image, -1.0)
    assert float(out.mean()) < float(image.mean())


def test_exposure_zero_is_identity(image):
    np.testing.assert_array_equal(apply_exposure(image, 0.0), image)


def test_resize_changes_size(image):
    out = resize_image(image, 80, 50)
    assert out.shape == (50, 80, 3)


def test_resize_invalid_raises(image):
    with pytest.raises(ValueError):
        resize_image(image, 0, 100)


def test_pipeline_applies_new_augmentations(image):
    params = AugmentParams(
        salt_pepper=20, gaussian_blur=20, softness=30,
        sharpen=30, oil=20, exposure=0.5,
    )
    out = run_augment_pipeline(image, params)
    assert out.shape == image.shape
    assert not np.array_equal(out, image)


def test_pipeline_crop_trims(image):
    """Crop trims pixels from each edge of the post-transform image."""
    from imagecraft.models.transformation import TransformParams, run_transform_pipeline
    params = TransformParams(crop_left=10, crop_right=20, crop_top=10, crop_bottom=10)
    result = run_transform_pipeline(image, params)
    assert result.shape == (80, 130, 3)  # (100-10-10, 160-10-20, 3)


def test_pipeline_crop_zero_trims_identity(image):
    from imagecraft.models.transformation import TransformParams, run_transform_pipeline
    # Perspective points must match the image rect for the pre-crop steps to be
    # identity (TransformParams defaults are for a 1920x1080 canvas).
    h, w = image.shape[:2]
    params = TransformParams(tr_x=w, tr_y=0, br_x=w, br_y=h, bl_x=0, bl_y=h)
    result = run_transform_pipeline(image, params)
    np.testing.assert_array_equal(result, image)


def test_crop_free_points(image):
    from imagecraft.models.transformation import crop_free
    result = crop_free(image, [[10, 10], [140, 10], [140, 90], [10, 90]])
    assert result.shape == (80, 130, 3)


def test_crop_free_accepts_two_or_more_points(image):
    from imagecraft.models.transformation import crop_free
    # A drag only ever produces two meaningful corners; crop_free builds the
    # axis-aligned bounding box from two or more points in any order.
    result = crop_free(image, [[10, 10], [140, 90]])
    assert result.shape == (80, 130, 3)


def test_crop_free_single_point_raises(image):
    from imagecraft.models.transformation import crop_free
    with pytest.raises(ValueError):
        crop_free(image, [[10, 10]])
