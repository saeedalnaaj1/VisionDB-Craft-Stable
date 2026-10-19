"""Pure image processing functions — no Qt dependency, fully testable.

Every function takes a numpy image array and returns a new numpy array.
Originals are never mutated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

ImageArray = npt.NDArray[np.uint8]


def _as_image(result: npt.NDArray[Any]) -> ImageArray:
    """Cast an OpenCV result to :data:`ImageArray`.

    OpenCV's type stubs declare results as ``ndarray[Any, dtype[...]]`` which
    mypy cannot reconcile with ``npt.NDArray[np.uint8]`` even though uint8
    input always yields uint8 output.
    """
    return cast(ImageArray, result)

# ---------------------------------------------------------------------------
# Parameter dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TransformParams:
    """Parameters for geometric image transformation.

    All values are in pixel or degree units as exposed by the UI sliders.
    Crop values are trim amounts — pixels removed from each edge.
    """

    # Perspective — 4 corners, each (x, y) in pixel coords
    tl_x: int = 0
    tl_y: int = 0
    tr_x: int = 1920
    tr_y: int = 0
    br_x: int = 1920
    br_y: int = 1080
    bl_x: int = 0
    bl_y: int = 1080

    translate_x: int = 0
    translate_y: int = 0
    scale: int = 100  # percentage, 100 = no scaling
    rotation: int = 0  # degrees
    crop_top: int = 0
    crop_bottom: int = 0
    crop_left: int = 0
    crop_right: int = 0

    # --- Free crop: absolute rectangle in post-transform image pixels ---
    # This is the authoritative crop when set.  ``-1`` on any field means
    # "unset", in which case the four trim values above are used instead.
    # Sending a rect avoids the lossy rect -> trims -> rect round trip that
    # desynchronised the overlay from the rendered result.
    crop_x: int = -1
    crop_y: int = -1
    crop_w: int = -1
    crop_h: int = -1

    @property
    def has_crop_rect(self) -> bool:
        """True when an explicit free-crop rectangle was supplied.

        Presence is decided by ``crop_w``/``crop_h`` alone: ``-1`` is the unset
        sentinel and ``0`` is meaningless.  Any other value — including a
        negative extent from a handle dragged past the opposite edge — is a
        real rectangle and is normalised by :func:`clamp_crop_rect`.  Origin
        fields are deliberately not part of this test so an off-canvas drag
        still takes the rect path instead of silently reverting to trims.
        """
        return self.crop_w not in (-1, 0) and self.crop_h not in (-1, 0)

    @property
    def src_points(self) -> npt.NDArray[np.float32]:
        """Four perspective source points as (4, 2) float32 array."""
        return np.asarray([
            [self.tl_x, self.tl_y],
            [self.tr_x, self.tr_y],
            [self.br_x, self.br_y],
            [self.bl_x, self.bl_y],
        ], dtype=np.float32)


@dataclass
class AugmentParams:
    """Parameters for image augmentation (color, geometric, noise, padding)."""

    white_balance: int = 0  # -100 .. 100
    hsv_hue: int = 0  # -180 .. 180
    hsv_saturation: int = 0  # -100 .. 100
    hsv_value: int = 0  # -100 .. 100
    rotation: int = 0  # -180 .. 180 degrees
    translate: int = 0  # -100 .. 100 px (applied to both axes)
    scale: int = 100  # 50 .. 150 percentage
    shear: int = 0  # -45 .. 45 degrees
    noise: int = 0  # 0 .. 100
    flip_vertical: bool = False
    flip_horizontal: bool = False
    padding_enabled: bool = False
    padding_width: int = 0
    padding_height: int = 0

    # --- New augmentations (v2 UI) — all default to "off" ---
    salt_pepper: int = 0          # 0..100 noise density
    gaussian_blur: int = 0        # 0..100 → blur kernel size
    softness: int = 0             # 0..100 edge-preserving smoothing
    sharpen: int = 0              # 0..100 unsharp-mask strength
    oil: int = 0                  # 0..100 oil-painting effect
    exposure: float = 0.0         # exposure in stops (-2..2)


# ---------------------------------------------------------------------------
# Full pipelines — called by the UI tabs
# ---------------------------------------------------------------------------


MIN_CROP_SIDE = 8
"""Smallest crop edge, in pixels.  Matches the floor pro editors enforce so a
stray click cannot collapse the selection to nothing."""


def run_transform_pipeline(img: ImageArray, params: TransformParams) -> ImageArray:
    """Apply the full transformation pipeline in order: perspective → translate
    → rotate+scale → crop.

    Each stage short-circuits at its identity value, so a pure free-crop costs
    one array slice instead of three full-frame warps.  The crop runs last and
    is expressed in the coordinate space of the *post-transform* image — which
    is exactly the image the user sees under the overlay.
    """
    h, w = img.shape[:2]

    if not _is_identity_perspective(params.src_points, w, h):
        img = apply_perspective(img, params.src_points)
    if params.translate_x or params.translate_y:
        img = apply_translate(img, params.translate_x, params.translate_y)
    if params.rotation or params.scale != 100:
        img = apply_rotate_scale(img, params.rotation, params.scale / 100.0)

    h, w = img.shape[:2]
    x, y, width, height = resolve_crop_rect(params, w, h)
    if (x, y, width, height) != (0, 0, w, h):
        img = apply_crop(img, x, y, width, height)
    return img


def resolve_crop_rect(
    params: TransformParams, width: int, height: int
) -> tuple[int, int, int, int]:
    """Resolve the effective crop rectangle for a *width* × *height* image.

    Prefers the absolute ``crop_x/y/w/h`` rectangle; falls back to the four
    edge trims.  The result is always a valid in-bounds rectangle.
    """
    if params.has_crop_rect:
        rect = (params.crop_x, params.crop_y, params.crop_w, params.crop_h)
    else:
        rect = (
            params.crop_left,
            params.crop_top,
            width - params.crop_left - params.crop_right,
            height - params.crop_top - params.crop_bottom,
        )
    return clamp_crop_rect(*rect, width, height)


def clamp_crop_rect(
    x: int, y: int, w: int, h: int, width: int, height: int
) -> tuple[int, int, int, int]:
    """Normalise and clamp a crop rectangle into a *width* × *height* image.

    Handles the three states a live drag can produce:

    * negative extents — the handle was dragged past the opposite edge, so the
      rectangle is flipped rather than rejected;
    * out-of-bounds origin — the rectangle is slid back inside the frame;
    * degenerate size — the rectangle is grown to :data:`MIN_CROP_SIDE`.

    Never raises.  A drag can always be resolved to *something* sensible,
    which is what keeps the overlay from snapping back mid-gesture.
    """
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))

    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h

    min_w = min(MIN_CROP_SIDE, width)
    min_h = min(MIN_CROP_SIDE, height)

    x = min(max(0, x), max(0, width - min_w))
    y = min(max(0, y), max(0, height - min_h))
    w = max(min_w, min(w, width - x))
    h = max(min_h, min(h, height - y))
    return x, y, w, h


def _is_identity_perspective(
    src_points: npt.NDArray[np.float32], width: int, height: int, tol: float = 0.5
) -> bool:
    """True when *src_points* should be treated as "no perspective change".

    Two cases qualify:

    1. The corners match the image rectangle exactly — a genuine identity.
    2. The corners form an axis-aligned rectangle anchored at the origin whose
       size differs from the image.  That only happens when the frontend is
       still holding corner values sized for a *previous* version of the image
       (e.g. before a crop was applied).  Warping to stale bounds stretched the
       frame and mirrored it through ``BORDER_REFLECT``; treating it as a
       no-op is both correct and what the user expects.

    A deliberately dragged quadrilateral fails both tests and still warps.
    """
    pts = np.asarray(src_points, dtype=np.float32)
    if pts.shape != (4, 2):
        return False
    expected = np.asarray(
        [[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32
    )
    if np.all(np.abs(pts - expected) <= tol):
        return True

    (tl_x, tl_y), (tr_x, tr_y), (br_x, br_y), (bl_x, bl_y) = pts
    axis_aligned = (
        abs(tl_x) <= tol
        and abs(tl_y) <= tol
        and abs(bl_x) <= tol
        and abs(tr_y) <= tol
        and abs(tr_x - br_x) <= tol
        and abs(bl_y - br_y) <= tol
    )
    if axis_aligned and br_x > tol and br_y > tol:
        logger.debug(
            "Ignoring stale perspective rect %gx%g on %dx%d image",
            br_x, br_y, width, height,
        )
        return True
    return False


def run_augment_pipeline(img: ImageArray, params: AugmentParams) -> ImageArray:
    """Apply the full augmentation pipeline in order."""
    img = apply_white_balance(img, params.white_balance)
    img = apply_hsv(img, params.hsv_hue, params.hsv_saturation, params.hsv_value)
    img = apply_rotate_scale(img, params.rotation, params.scale / 100.0)
    img = apply_translate(img, params.translate, params.translate)
    img = apply_shear(img, params.shear)
    img = apply_noise(img, params.noise)
    if params.flip_vertical:
        img = _as_image(cv2.flip(img, 0))
    if params.flip_horizontal:
        img = _as_image(cv2.flip(img, 1))
    if params.padding_enabled:
        img = apply_padding(img, params.padding_width, params.padding_height)

    # --- New augmentations (v2) — no-op at their default values ---
    img = apply_salt_pepper(img, params.salt_pepper)
    img = apply_gaussian_blur(img, params.gaussian_blur)
    img = apply_softness(img, params.softness)
    img = apply_sharpen(img, params.sharpen)
    img = apply_oil_painting(img, params.oil)
    img = apply_exposure(img, params.exposure)
    return img


# ---------------------------------------------------------------------------
# Individual operations
# ---------------------------------------------------------------------------


def apply_perspective(img: ImageArray, src_points: npt.NDArray[np.float32]) -> ImageArray:
    """Warp *img* so that *src_points* map to the image rectangle.

    Args:
        img: Input RGB image.
        src_points: (4, 2) float32 array of source corners in order
            [top-left, top-right, bottom-right, bottom-left].

    Returns:
        Warped image with same dimensions as input.

    Raises:
        ValueError: If *src_points* do not form a valid convex quadrilateral.
    """
    _validate_perspective_points(src_points)
    h, w = img.shape[:2]
    dst_points = np.asarray([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    try:
        matrix = cv2.getPerspectiveTransform(src_points, dst_points)
        return _as_image(cv2.warpPerspective(img, matrix, (w, h)))
    except cv2.error as exc:
        raise ValueError(f"Perspective transform failed: {exc}") from exc


#: Fill used for pixels pulled in from outside the frame by translate/rotate.
#: ``BORDER_REFLECT`` mirrored real image content into the empty margin, which
#: read as duplicated subject matter rather than as empty space.  Every major
#: editor shows a neutral fill here.  Set this back to ``cv2.BORDER_REFLECT``
#: if the mirrored behaviour is wanted.
BORDER_FILL_MODE = cv2.BORDER_CONSTANT
BORDER_FILL_VALUE = (0, 0, 0)


def apply_translate(img: ImageArray, dx: int, dy: int) -> ImageArray:
    """Translate *img* by (dx, dy) pixels, filling the vacated margin."""
    if dx == 0 and dy == 0:
        return img
    matrix = np.asarray([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
    h, w = img.shape[:2]
    return _as_image(cv2.warpAffine(
        img, matrix, (w, h),
        borderMode=BORDER_FILL_MODE, borderValue=BORDER_FILL_VALUE,
    ))


def apply_rotate_scale(img: ImageArray, angle: float, scale: float) -> ImageArray:
    """Rotate *img* by *angle* degrees and scale by *factor* around its centre."""
    if angle == 0 and scale == 1.0:
        return img
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, scale)
    return _as_image(cv2.warpAffine(
        img, matrix, (w, h),
        borderMode=BORDER_FILL_MODE, borderValue=BORDER_FILL_VALUE,
    ))


def apply_crop(
    img: ImageArray, x: int, y: int, width: int, height: int
) -> ImageArray:
    """Crop *img* to the region ``[y:y+h, x:x+w]``, clamped to image bounds.

    Returns an owned, C-contiguous copy — never a view.  A numpy slice aliases
    the parent buffer, which meant every crop kept the full pre-crop frame
    alive, undo snapshots shared memory with live state, and any subsequent
    in-place OpenCV call could write through into the original.

    Raises:
        ValueError: If the image is empty, so a crop is meaningless.
    """
    h, w = img.shape[:2]
    if w == 0 or h == 0:
        raise ValueError("Cannot crop an empty image")
    x, y, width, height = clamp_crop_rect(x, y, width, height, w, h)
    return _as_image(np.ascontiguousarray(img[y : y + height, x : x + width]))


def crop_free(img: ImageArray, points: npt.ArrayLike) -> ImageArray:
    """Crop to the axis-aligned bounding box of a set of (x, y) points.

    Accepts two or more points in any order — a drag only ever produces two
    meaningful corners, and requiring exactly four forced the caller to
    fabricate the other two.

    Args:
        img: Input RGB image.
        points: (N, 2) array-like of corner coordinates, N >= 2.

    Returns:
        Cropped image (an owned copy).

    Raises:
        ValueError: If *points* is not an (N, 2) array with N >= 2.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] < 2:
        raise ValueError(f"Expected at least 2 (x, y) points, got {pts.shape}")
    xs, ys = pts[:, 0], pts[:, 1]
    x = int(round(float(xs.min())))
    y = int(round(float(ys.min())))
    width = int(round(float(xs.max()))) - x
    height = int(round(float(ys.max()))) - y
    return apply_crop(img, x, y, width, height)


def apply_white_balance(img: ImageArray, value: int) -> ImageArray:
    """Adjust brightness.  Positive *value* adds brightness; negative reduces it.

    Args:
        img: Input RGB image.
        value: Slider value in [-100, 100].

    Returns:
        Adjusted image.
    """
    if value == 0:
        return img
    if value > 0:
        beta = value * 2.55  # map 0..100 → 0..255
        return _as_image(cv2.convertScaleAbs(img, alpha=1, beta=beta))
    else:
        factor = 1.0 + (value / 100.0)  # 1.0 → 0.0 as value goes -100
        return _as_image(cv2.convertScaleAbs(img, alpha=factor, beta=0))


def apply_hsv(img: ImageArray, h: int, s: int, v: int) -> ImageArray:
    """Adjust HSV channels.

    Args:
        img: Input RGB image.
        h: Hue shift in degrees [-180, 180].
        s: Saturation multiplier range [-100, 100] → factor [0.0, 2.0].
        v: Value multiplier range [-100, 100] → factor [0.0, 2.0].
    """
    if h == 0 and s == 0 and v == 0:
        return img
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + h) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + s / 100.0), 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * (1.0 + v / 100.0), 0, 255)
    return _as_image(cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB))


def apply_shear(img: ImageArray, angle_deg: int) -> ImageArray:
    """Apply horizontal shear by *angle_deg* degrees (-45 .. 45)."""
    if angle_deg == 0:
        return img
    rad = np.radians(angle_deg)
    tan_rad = np.tan(rad)
    h, w = img.shape[:2]
    new_width = w + int(abs(tan_rad) * h)
    matrix = np.asarray([[1, tan_rad, 0], [0, 1, 0]], dtype=np.float32)
    return _as_image(
        cv2.warpAffine(img, matrix, (new_width, h), borderMode=cv2.BORDER_REFLECT)
    )


def apply_noise(img: ImageArray, level: int) -> ImageArray:
    """Add uniform random noise in range [0, *level*]."""
    if level <= 0:
        return img
    noise = np.random.randint(0, level, img.shape, dtype=np.uint8)
    return _as_image(cv2.add(img, noise))


def apply_flip(img: ImageArray, vertical: bool, horizontal: bool) -> ImageArray:
    """Flip image.  ``flip(0)`` = vertical, ``flip(1)`` = horizontal."""
    if vertical:
        img = _as_image(cv2.flip(img, 0))
    if horizontal:
        img = _as_image(cv2.flip(img, 1))
    return img


def apply_padding(
    img: ImageArray,
    target_w: int,
    target_h: int,
    color: tuple[int, int, int] = (255, 255, 255),
) -> ImageArray:
    """Pad *img* to reach *target_w* × *target_h* (centered, white border).

    If the target dimensions are smaller than or equal to the image, the
    image is returned unchanged.
    """
    h, w = img.shape[:2]
    pad_w = max(target_w - w, 0)
    pad_h = max(target_h - h, 0)
    if pad_w == 0 and pad_h == 0:
        return img

    left = pad_w // 2
    right = pad_w - left
    top = pad_h // 2
    bottom = pad_h - top
    return _as_image(cv2.copyMakeBorder(
        img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color
    ))


def apply_salt_pepper(img: ImageArray, amount: int = 0) -> ImageArray:
    """Add salt-and-pepper noise.  *amount* (0..100) scales the pixel density.

    Approximately ``amount/100 * 5%`` of pixels are set to white or black.
    """
    if amount <= 0:
        return img
    density = amount / 100.0 * 0.05
    out = img.copy()
    num_salt = int(np.ceil(density * img.size))
    if num_salt > 0:
        coords = [np.random.randint(0, n, num_salt) for n in img.shape[:2]]
        out[coords[0], coords[1], :] = 255
    num_pepper = int(np.ceil(density * img.size / 2.0))
    if num_pepper > 0:
        coords = [np.random.randint(0, n, num_pepper) for n in img.shape[:2]]
        out[coords[0], coords[1], :] = 0
    return _as_image(out)


def apply_gaussian_blur(img: ImageArray, amount: int = 0) -> ImageArray:
    """Apply a Gaussian blur.  *amount* (0..100) maps to kernel size 1..31."""
    if amount <= 0:
        return img
    k = max(1, int(round(amount / 100.0 * 30))) | 1  # ensure odd 1..31
    if k < 3:
        return img
    sigma = 0.5 + amount / 100.0 * 4.0
    return _as_image(cv2.GaussianBlur(img, (k, k), sigma))


def apply_softness(img: ImageArray, amount: int = 0) -> ImageArray:
    """Edge-preserving smoothing (bilateral filter) for a soft skin-like look."""
    if amount <= 0:
        return img
    d = max(5, int(round(amount / 100.0 * 20)) | 1)
    return _as_image(cv2.bilateralFilter(img, d, 75, 75))


def apply_sharpen(img: ImageArray, amount: int = 0) -> ImageArray:
    """Unsharp-mask sharpening.  *amount* (0..100) scales the strength."""
    if amount <= 0:
        return img
    strength = amount / 100.0
    blurred = cv2.GaussianBlur(img, (0, 0), 1.5)
    sharpened = cv2.addWeighted(img, 1.0 + strength, blurred, -strength, 0)
    return _as_image(np.clip(sharpened, 0, 255).astype(np.uint8))


def apply_oil_painting(img: ImageArray, amount: int = 0) -> ImageArray:
    """Oil-painting effect (manual implementation — ``opencv-python`` lacks
    ``cv2.xphoto.oilPainting``).

    Quantizes luminance into a few levels, then for every pixel picks the most
    frequent level in its neighbourhood and averages the colour of pixels that
    share that level.  Uses :func:`cv2.boxFilter` so it vectorises over the
    whole image.
    """
    if amount <= 0:
        return img
    size = max(3, int(round(amount / 100.0 * 10)) | 1)
    levels = max(4, int(round(amount / 100.0 * 8)) + 4)
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    quant = (gray.astype(np.int32) * levels // 256)
    area = float(size * size)

    # Pass 1: find the dominant quantized level in each window.
    mode_map = np.zeros((h, w), dtype=np.uint8)
    mode_count = np.zeros((h, w), dtype=np.float32)
    for k in range(levels):
        count = cv2.boxFilter((quant == k).astype(np.float32), -1, (size, size)) * area
        better = count > mode_count
        mode_count[better] = count[better]
        mode_map[better] = k

    # Pass 2: average the colour of pixels sharing the dominant level.
    result = np.zeros((h, w, 3), dtype=np.float32)
    for k in range(levels):
        mask_k = (mode_map == k).astype(np.float32)
        if not mask_k.any():
            continue
        contrib = (quant == k).astype(np.float32)
        counts_k = cv2.boxFilter(contrib, -1, (size, size)) * area
        safe_counts = np.where(counts_k > 0, counts_k, 1.0)
        for c in range(3):
            weighted = cv2.boxFilter(
                img[:, :, c].astype(np.float32) * contrib, -1, (size, size)
            ) * area
            avg = np.divide(weighted, safe_counts)
            result[:, :, c] += avg * mask_k
    return _as_image(np.clip(result, 0, 255).astype(np.uint8))


def apply_exposure(img: ImageArray, stops: float = 0.0) -> ImageArray:
    """Adjust exposure by *stops* (each stop doubles/halves brightness)."""
    if stops == 0:
        return img
    factor = 2.0 ** stops
    lut = np.clip(np.arange(256, dtype=np.float32) * factor, 0, 255).astype(np.uint8)
    return _as_image(cv2.LUT(img, lut))


def resize_image(
    img: ImageArray, width: int, height: int,
    interpolation: int = cv2.INTER_LANCZOS4,
) -> ImageArray:
    """Resize *img* to *width* × *height* pixels.

    Raises:
        ValueError: If either dimension is non-positive.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid resize dimensions: {width}×{height}")
    return _as_image(cv2.resize(img, (width, height), interpolation=interpolation))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_perspective_points(points: npt.NDArray[np.float32]) -> None:
    """Raise :class:`ValueError` if *points* is not a valid convex quadrilateral."""
    if points.shape != (4, 2):
        raise ValueError(f"Expected (4, 2) points, got {points.shape}")
    if len(np.unique(points, axis=0)) != 4:
        raise ValueError("Perspective points must be unique")
    try:
        hull = cv2.convexHull(points.astype(np.float32))
    except cv2.error as exc:
        raise ValueError(f"Cannot compute convex hull of points: {exc}") from exc
    if hull is not None and len(hull) != 4:
        raise ValueError(
            "Perspective points must form a convex quadrilateral "
            "(points may be collinear or self-intersecting)"
        )
