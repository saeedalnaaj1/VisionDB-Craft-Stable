"""Image collection — manages all loaded images with cursor-based navigation.

This is the **single source of truth** for image state. Both the Transformation
and Augmentation tabs share the same collection instance.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

import cv2

from imagecraft.dataset.models import DatasetRecord
from imagecraft.models.image_item import ImageArray, ImageItem

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")


class ImageCollection:
    """Ordered list of :class:`ImageItem` objects with navigation.

    Usage::

        collection = ImageCollection()
        collection.load_folder(Path("/images"))
        collection.next()
        item = collection.current
        item.apply(processed_array)
    """

    def __init__(self) -> None:
        self._images: list[ImageItem] = []
        self._cursor: int = -1  # -1 means empty

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total number of loaded images."""
        return len(self._images)

    @property
    def current_index(self) -> int:
        """Zero-based index of the active image (-1 when empty)."""
        return self._cursor

    @property
    def current(self) -> ImageItem | None:
        """The currently active :class:`ImageItem`, or ``None`` if empty."""
        if 0 <= self._cursor < len(self._images):
            return self._images[self._cursor]
        return None

    def get(self, index: int) -> ImageItem | None:
        """Return the image at *index*, or ``None`` if out of range."""
        if 0 <= index < len(self._images):
            return self._images[index]
        return None

    @property
    def is_empty(self) -> bool:
        return len(self._images) == 0

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_single(self, path: Path) -> None:
        """Replace the entire collection with a single image."""
        img = self._read_image(path)
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {path}")
        self._images = [ImageItem(path=path, original=img)]
        self._cursor = 0
        logger.info("Loaded single image: %s", path)

    def load_folder(
        self,
        directory: Path,
        progress_callback: Callable[[int, int, str], bool] | None = None,
    ) -> None:
        """Replace the collection with all supported images from *directory*.

        If *progress_callback* is given it is invoked as
        ``progress_callback(done, total, filename)`` before each image is read
        and may return ``False`` to abort loading early (cancellation).
        """
        paths = sorted(
            p
            for p in directory.iterdir()
            if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file()
        )
        if not paths:
            logger.warning("No supported images found in %s", directory)
            self._images = []
            self._cursor = -1
            return

        total = len(paths)
        self._images = []
        for idx, p in enumerate(paths):
            if progress_callback is not None and not progress_callback(idx + 1, total, p.name):
                break  # cancelled
            img = self._read_image(p)
            if img is not None:
                self._images.append(ImageItem(path=p, original=img))
        self._cursor = 0 if self._images else -1
        logger.info("Loaded %d images from %s", len(self._images), directory)

    def load_dataset_records(self, records: list[DatasetRecord]) -> None:
        """Load dataset metadata lazily so large projects do not fill RAM."""
        self._images = [
            ImageItem(
                path=record.image_path,
                original=None,
                original_annotations=record.annotations,
                annotation_path=record.annotation_path,
                dataset_split=record.split,
                original_split=record.split,
                source_width=record.width,
                source_height=record.height,
                lazy=True,
            )
            for record in records
        ]
        self._cursor = 0 if self._images else -1
        logger.info("Loaded %d dataset records lazily", len(self._images))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next(self) -> bool:
        """Move cursor forward. Returns ``False`` if already at the last image."""
        if self._cursor < len(self._images) - 1:
            self._cursor += 1
            return True
        return False

    def previous(self) -> bool:
        """Move cursor backward. Returns ``False`` if already at the first image."""
        if self._cursor > 0:
            self._cursor -= 1
            return True
        return False

    def go_to(self, index: int) -> bool:
        """Jump to a specific index. Clamps to valid range."""
        if not self._images:
            return False
        self._cursor = max(0, min(index, len(self._images) - 1))
        return True

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def reset_current(self) -> None:
        """Reset the current image to its original state."""
        item = self.current
        if item:
            item.reset()

    def reset_all(self) -> None:
        """Reset every image to its original state."""
        for item in self._images:
            item.reset()

    def clear(self) -> None:
        """Remove all images from the collection."""
        self._images.clear()
        self._cursor = -1

    def iter_all(self) -> list[tuple[int, ImageItem]]:
        """Return ``(index, ImageItem)`` pairs for every loaded image."""
        return list(enumerate(self._images))

    def append(self, item: ImageItem) -> None:
        """Append a generated dataset item without replacing the collection."""
        self._images.append(item)
        if self._cursor < 0:
            self._cursor = 0

    def restore(self, items: list[ImageItem], cursor: int = 0) -> None:
        """Replace the collection with already reconstructed project items."""
        self._images = list(items)
        if not self._images:
            self._cursor = -1
        else:
            self._cursor = max(0, min(int(cursor), len(self._images) - 1))

    def trim_cache(self, keep: int = 12) -> None:
        """Release lazy source pixels away from the cursor to bound memory use."""
        if keep < 1 or not self._images:
            return
        ranked = sorted(range(len(self._images)), key=lambda index: abs(index - self._cursor))
        keep_indices = set(ranked[:keep])
        for index, item in enumerate(self._images):
            if index not in keep_indices:
                item.release_source()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_image(path: Path) -> ImageArray | None:
        """Read an image from disk, converting BGR → RGB."""
        img = cv2.imread(str(path))
        if img is None:
            logger.warning("Failed to read image: %s", path)
            return None
        return cast(ImageArray, cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
