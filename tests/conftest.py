"""Shared pytest fixtures for the VisionDB Craft backend."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

ImageArray = npt.NDArray[np.uint8]


@pytest.fixture
def image() -> ImageArray:
    """A 100×160 RGB image with distinct regions and edges."""
    img = np.zeros((100, 160, 3), dtype=np.uint8)
    # Left half red, right half green — a clear vertical edge.
    img[:, :80] = (200, 30, 30)
    img[:, 80:] = (30, 200, 30)
    # A white square in the middle to give texture.
    img[30:70, 60:100] = (255, 255, 255)
    return img


@pytest.fixture
def small_image() -> ImageArray:
    """A tiny 8×8 image, useful for fast op tests."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (8, 8, 3), dtype=np.uint8)
