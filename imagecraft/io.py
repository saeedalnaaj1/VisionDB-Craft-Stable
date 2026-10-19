"""Image <-> wire helpers: base64 data URLs and preview downscaling."""

from __future__ import annotations

import base64
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from imagecraft.models.transformation import ImageArray


def encode_base64(img: ImageArray, fmt: str = "png") -> str:
    """Encode an RGB array as a base64 string (raw, no data-URL prefix)."""
    ok, buf = cv2.imencode("." + fmt, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError(f"Failed to encode image as {fmt}")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def to_data_url(img: ImageArray, fmt: str = "png") -> str:
    """Encode an RGB array as a ``data:image/...;base64,...`` URL."""
    return f"data:image/{fmt};base64,{encode_base64(img, fmt)}"


def downscale(img: ImageArray, max_size: int) -> ImageArray:
    """Shrink *img* so its longest side is at most *max_size* (no upscale).

    Uses area interpolation for quality.  Returns the original array when it
    already fits, so callers can rely on identity for small images.
    """
    h, w = img.shape[:2]
    scale = min(1.0, max_size / max(h, w))
    if scale >= 1.0:
        return img
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    return cast(ImageArray, cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA))


def decode_from_bytes(data: bytes) -> ImageArray:
    """Decode raw bytes into an RGB image array.

    Raises:
        ValueError: If the bytes are not a decodable image.
    """
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Cannot decode image bytes (unsupported or corrupt data)")
    return cast(ImageArray, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def bgr_to_rgb(img: npt.NDArray[np.uint8]) -> ImageArray:
    """Convert a BGR OpenCV array to RGB (view-safe: returns a new array)."""
    return cast(ImageArray, cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
