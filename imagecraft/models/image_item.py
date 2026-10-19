"""Image item model — a single image and its processing state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from imagecraft.dataset.models import Annotation

logger = logging.getLogger(__name__)

ImageArray = npt.NDArray[np.uint8]
"""Type alias for a uint8 RGB image array (H × W × 3)."""


@dataclass
class ImageItem:
    """Represents one loaded image with its original data and any modifications.

    The ``original`` array is **never mutated** — all transforms and augmentations
    write to ``modified``, so the user can always reset back to the original.

    Undo/redo history is managed centrally by :class:`~imagecraft.engine.BackendEngine`,
    not per-image.

    Attributes:
        path: Filesystem path to the image file.
        original: The source RGB pixels, or ``None`` until first use for a
            lazily loaded dataset item.
        modified: The latest transformed/augmented version, or ``None`` if unchanged.
        original_annotations: Source bounding boxes in normalized coordinates.
        modified_annotations: Bounding boxes matching ``modified``.
        dataset_split: Current train/val/test assignment.
        zoom: Current zoom level for display (1.0 = 100%).
        lines: Horizontal line Y-positions drawn on the image (transform tab only).
    """

    path: Path
    original: ImageArray | None
    modified: ImageArray | None = None
    zoom: float = 1.0
    lines: list[int] = field(default_factory=list)
    original_annotations: list[Annotation] = field(default_factory=list)
    modified_annotations: list[Annotation] | None = None
    annotation_path: Path | None = None
    dataset_split: str = "unsplit"
    original_split: str = "unsplit"
    source_width: int = 0
    source_height: int = 0
    lazy: bool = False
    is_generated: bool = False

    def __post_init__(self) -> None:
        """Sanity-check the image array."""
        self.path = Path(self.path)
        if self.annotation_path is not None:
            self.annotation_path = Path(self.annotation_path)
        if self.original is not None:
            if len(self.original.shape) != 3 or self.original.shape[2] != 3:
                raise ValueError(f"Expected an H×W×3 RGB array, got {self.original.shape}")
            self.source_height, self.source_width = self.original.shape[:2]
        elif not self.lazy:
            raise ValueError("An image array is required unless lazy loading is enabled")
        self.original_annotations = [ann.copy() for ann in self.original_annotations]
        if self.original_split == "unsplit":
            self.original_split = self.dataset_split

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active(self) -> ImageArray:
        """Return the image to display: modified if available, else original."""
        if self.modified is not None:
            return self.modified
        return self._ensure_original()

    @property
    def source(self) -> ImageArray:
        """Return the original source pixels, loading them on demand."""
        return self._ensure_original()

    @property
    def active_annotations(self) -> list[Annotation]:
        """Current annotations, following the active image's geometry."""
        source = (
            self.modified_annotations
            if self.modified_annotations is not None
            else self.original_annotations
        )
        return source

    @property
    def is_modified(self) -> bool:
        """Whether this image has been transformed or augmented."""
        return self.modified is not None

    @property
    def height(self) -> int:
        if self.modified is not None:
            return int(self.modified.shape[0])
        return int(self.source_height)

    @property
    def width(self) -> int:
        if self.modified is not None:
            return int(self.modified.shape[1])
        return int(self.source_width)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def apply(self, result: ImageArray, annotations: list[Annotation] | None = None) -> None:
        """Store a processing result as the new modified image."""
        self.modified = result
        current = self.active_annotations if annotations is None else annotations
        self.modified_annotations = [ann.copy() for ann in current]

    def reset(self) -> None:
        """Discard modifications, zoom, and lines."""
        self.modified = None
        self.modified_annotations = None
        self.zoom = 1.0
        self.lines.clear()

    def release_source(self) -> None:
        """Release a lazily loaded, unmodified source image from memory."""
        if self.lazy and self.modified is None:
            self.original = None

    def _ensure_original(self) -> ImageArray:
        if self.original is None:
            bgr = cv2.imread(str(self.path))
            if bgr is None:
                raise FileNotFoundError(f"Cannot read image: {self.path}")
            self.original = np.asarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), dtype=np.uint8)
            self.source_height, self.source_width = self.original.shape[:2]
        return self.original
