"""Tests for ``imagecraft.models.image_item.ImageItem``."""

from __future__ import annotations

import numpy as np
import pytest

from imagecraft.models.image_item import ImageItem


@pytest.fixture
def item(image) -> ImageItem:
    return ImageItem(path="dummy.png", original=image)


def test_active_is_original_when_unmodified(item, image):
    np.testing.assert_array_equal(item.active, image)
    assert not item.is_modified


def test_apply_sets_modified(item, image):
    modified = image.copy() + 10
    item.apply(modified)
    assert item.is_modified
    np.testing.assert_array_equal(item.active, modified)


def test_reset_returns_to_original(item, image):
    item.apply(image + 10)
    item.reset()
    assert not item.is_modified
    np.testing.assert_array_equal(item.active, image)


def test_invalid_array_shape_rejected():
    with pytest.raises(ValueError):
        ImageItem(path="x.png", original=np.zeros((10, 10), dtype=np.uint8))
