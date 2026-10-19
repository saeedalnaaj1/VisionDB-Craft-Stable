"""BackendEngine — the ``js_api`` bridge between the web UI and OpenCV.

Design notes
------------
* Every method is **synchronous** and JSON-safe (no numpy in return values).
  pywebview runs each ``js_api`` call on its own HTTP-server thread, so heavy
  operations never block the JS main thread; progress is pushed to the UI via
  ``bridge.evaluate_js`` dispatching ``CustomEvent('backend:...')`` events.
* The ``bridge`` is a small protocol (``UIBridge``) so the engine is fully
  testable headlessly with a fake bridge — the GUI window is only referenced
  through the bridge.
* Editing is **cumulative with history**: ``apply`` runs on the current active
  state and pushes an undo snapshot, so transformations and augmentations chain
  and are individually undoable.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import os
import platform
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import yaml


from imagecraft.dataset.analysis import assign_splits, dataset_statistics, validate_dataset
from imagecraft.dataset.exporters import export_dataset
from imagecraft.dataset.geometry import (
    augment_annotations,
    resize_annotations,
    transform_annotations,
)
from imagecraft.dataset.loaders import load_dataset
from imagecraft.dataset.masks import decode_rle, encode_rle, mask_bbox, normalize_rle
from imagecraft.dataset.models import Annotation, DatasetProject, DatasetRecord
from imagecraft.dataset.pose import normalize_keypoints, pose_bounds, pose_schema
from imagecraft.dataset.recipes import (
    RECIPE_FIELDS,
    recipe_catalog,
    sample_custom_recipe,
    sample_recipe,
)
from imagecraft.io import downscale, to_data_url
from imagecraft.edition import Features, EDITION, APP_TITLE, MODES
from imagecraft.models.image_collection import ImageCollection
from imagecraft.models.image_item import ImageItem
from imagecraft.models.transformation import (
    AugmentParams,
    ImageArray,
    TransformParams,
    resize_image,
    run_augment_pipeline,
    run_transform_pipeline,
)
from imagecraft.settings import Settings

logger = logging.getLogger(__name__)

MAX_PREVIEW_SIDE = 1920
MAX_OP_HISTORY = 20
PROJECT_FORMAT_VERSION = 1
WORKING_MODES = set(MODES)

HISTORY_FIELDS: dict[str, dict[str, tuple[str, str, str]]] = {
    "augment": {
        "white_balance": ("Color", "White balance", ""),
        "hsv_hue": ("Color", "Hue", "°"),
        "hsv_saturation": ("Color", "Saturation", ""),
        "hsv_value": ("Color", "Brightness", ""),
        "exposure": ("Color", "Exposure", " stops"),
        "gaussian_blur": ("Filters", "Blur", ""),
        "softness": ("Filters", "Softness", ""),
        "sharpen": ("Filters", "Sharpen", ""),
        "oil": ("Filters", "Oil paint", ""),
        "noise": ("Filters", "Noise", ""),
        "salt_pepper": ("Filters", "Salt & pepper", ""),
        "rotation": ("Geometry", "Rotation", "°"),
        "translate": ("Geometry", "Shift", " px"),
        "scale": ("Geometry", "Scale", "%"),
        "shear": ("Geometry", "Shear", "°"),
        "flip_vertical": ("Flip", "Flip up-down", ""),
        "flip_horizontal": ("Flip", "Flip left-right", ""),
        "padding_enabled": ("Padding", "Enabled", ""),
        "padding_width": ("Padding", "Width", " px"),
        "padding_height": ("Padding", "Height", " px"),
    },
    "transform": {
        "tl_x": ("Perspective", "Top-Left X", " px"),
        "tl_y": ("Perspective", "Top-Left Y", " px"),
        "tr_x": ("Perspective", "Top-Right X", " px"),
        "tr_y": ("Perspective", "Top-Right Y", " px"),
        "br_x": ("Perspective", "Bottom-Right X", " px"),
        "br_y": ("Perspective", "Bottom-Right Y", " px"),
        "bl_x": ("Perspective", "Bottom-Left X", " px"),
        "bl_y": ("Perspective", "Bottom-Left Y", " px"),
        "translate_x": ("Geometry", "X Shift", " px"),
        "translate_y": ("Geometry", "Y Shift", " px"),
        "rotation": ("Geometry", "Rotation", "°"),
        "scale": ("Geometry", "Scale", "%"),
        "crop_top": ("Crop", "Top", " px"),
        "crop_bottom": ("Crop", "Bottom", " px"),
        "crop_left": ("Crop", "Left", " px"),
        "crop_right": ("Crop", "Right", " px"),
        "crop_x": ("Free Crop", "X", " px"),
        "crop_y": ("Free Crop", "Y", " px"),
        "crop_w": ("Free Crop", "Width", " px"),
        "crop_h": ("Free Crop", "Height", " px"),
    },
    "resize": {
        "width": ("Dimensions", "Width", " px"),
        "height": ("Dimensions", "Height", " px"),
    },
    "annotation": {
        "action": ("Annotation", "Action", ""),
        "label": ("Annotation", "Class", ""),
        "annotation_type": ("Annotation", "Type", ""),
        "count": ("Auto Annotate", "Added", " annotations"),
        "needs_review": ("Auto Annotate", "Needs review", ""),
        "shapes": ("Auto Annotate", "Shapes", ""),
        "output_type": ("Auto Annotate", "Output", ""),
        "center_x": ("Bounds", "Center X", "%"),
        "center_y": ("Bounds", "Center Y", "%"),
        "width_percent": ("Bounds", "Width", "%"),
        "height_percent": ("Bounds", "Height", "%"),
    },
}


@dataclass
class OperationRecord:
    """One undoable operation touching one or more images."""

    kind: str
    params: dict[str, Any]
    target: str  # "current" | "all"
    image_indices: list[int]
    previous_states: dict[int, ImageArray | None]  # None == original/unmodified
    previous_annotations: dict[int, list[Annotation] | None] = field(default_factory=dict)
    resulting_states: dict[int, ImageArray | None] = field(default_factory=dict)
    resulting_annotations: dict[int, list[Annotation] | None] = field(default_factory=dict)
    changes: list[dict[str, str]] = field(default_factory=list)


PERFORMANCE_PREVIEW_SIZES: dict[str, int] = {
    "low": 720,
    "medium": 1920,
}


class UIBridge(Protocol):
    """Whatever the engine needs from the host window (swappable in tests)."""

    def evaluate_js(self, code: str) -> None: ...

    def open_file_dialog(
        self, allow_multiple: bool = False, file_types: tuple[str, ...] = ()
    ) -> list[str] | None: ...

    def open_folder_dialog(self) -> str | None: ...

    def save_file_dialog(self, save_as: str, file_types: tuple[str, ...] = ()) -> str | None: ...

    def move_window(self, x: int, y: int) -> None: ...

    def minimize_window(self) -> None: ...

    def toggle_maximize(self) -> None: ...

    def close_window(self) -> None: ...


class BackendEngine(Features):
    """All application logic exposed to the frontend as ``js_api``."""

    def __init__(
        self,
        bridge: UIBridge | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._bridge = bridge
        self._settings = settings if settings is not None else Settings()
        self._collection = ImageCollection()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._op_history: list[OperationRecord] = []
        self._op_redo: list[OperationRecord] = []
        self._history_base_truncated = False
        self._dataset: DatasetProject | None = None
        self._dataset_operations: list[dict[str, Any]] = []
        configured_classes = [
            str(value).strip()
            for value in self._settings.get("annotation_classes", [])
            if str(value).strip()
        ]
        # Migrate settings written by the first annotation build, which stored
        # an empty list and consequently left Draw Box permanently disabled.
        self._annotation_classes: list[str] = configured_classes or ["object"]
        self._auto_preview_candidates: list[dict[str, Any]] = []
        self._auto_preview_path: Path | None = None
        self._auto_preview_config: dict[str, Any] = {}
        self._initialize_features()
        self._ai_proposals: dict[str, list[dict[str, Any]]] = {}
        self._ai_task = "classification"
        self._ai_model = "clip-vit-b32"
        self._ai_config: dict[str, Any] = {}
        self._workspace_kind = "empty"
        self._working_mode = "transform"
        self._project_path: Path | None = None
        self._project_ui_state: dict[str, Any] = {}
        self._work_dirty = False
        self._practice_label = ""
        self._apply_performance_mode()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def attach_bridge(self, bridge: UIBridge | None) -> None:
        """Attach the host-window adapter (called after the window exists)."""
        self._bridge = bridge

    def _clear_history(self) -> None:
        """Reset the global undo/redo log."""
        self._op_history.clear()
        self._op_redo.clear()
        self._history_base_truncated = False
        self._clear_auto_preview()
        self._clear_ai_proposals()

    def _push_operation(
        self,
        kind: str,
        params: dict[str, Any],
        indices: list[int],
        previous_states: dict[int, ImageArray | None],
        previous_annotations: dict[int, list[Annotation] | None] | None = None,
    ) -> None:
        """Record one undoable operation."""
        target = "all" if len(indices) > 1 else "current"
        self._op_history.append(
            OperationRecord(
                kind=kind,
                params=dict(params),
                target=target,
                image_indices=list(indices),
                previous_states=previous_states,
                previous_annotations=previous_annotations or {},
                changes=self._describe_operation(kind, params, indices, previous_states),
            )
        )
        if len(self._op_history) > MAX_OP_HISTORY:
            self._op_history.pop(0)
            self._history_base_truncated = True
        self._op_redo.clear()
        self._clear_auto_preview()
        self._work_dirty = True

    def _describe_operation(
        self,
        kind: str,
        params: dict[str, Any],
        indices: list[int],
        previous_states: dict[int, ImageArray | None],
    ) -> list[dict[str, str]]:
        """Turn raw pipeline parameters into concise, user-facing history rows."""
        if not indices:
            return []
        item = self._collection.get(indices[0])
        before = previous_states.get(indices[0])
        if before is None and item is not None:
            try:
                before = item.source
            except FileNotFoundError:
                before = None
        height, width = before.shape[:2] if before is not None else (1080, 1920)

        if kind == "augment":
            defaults = _as_dict(AugmentParams())
        elif kind == "transform":
            defaults = {
                **_as_dict(TransformParams()),
                "tl_x": 0,
                "tl_y": 0,
                "tr_x": width,
                "tr_y": 0,
                "br_x": width,
                "br_y": height,
                "bl_x": 0,
                "bl_y": height,
            }
        else:
            defaults = {}

        labels = HISTORY_FIELDS.get(kind, {})
        changes: list[dict[str, str]] = []
        padding_enabled = bool(params.get("padding_enabled", False))
        for key, value in params.items():
            if key not in labels:
                continue
            if (
                kind == "augment"
                and key in {"padding_width", "padding_height"}
                and not padding_enabled
            ):
                continue
            if kind != "resize" and value == defaults.get(key):
                continue
            if key in {"crop_x", "crop_y", "crop_w", "crop_h"} and int(value) == -1:
                continue
            section, label, suffix = labels[key]
            if isinstance(value, bool):
                display = "On" if value else "Off"
            elif isinstance(value, float):
                display = f"{value:g}{suffix}"
            else:
                display = f"{value}{suffix}"
            changes.append({"section": section, "label": label, "value": display})
        return changes

    def _history_timeline(self) -> dict[str, Any]:
        records = [*self._op_history, *reversed(self._op_redo)]
        entries: list[dict[str, Any]] = []
        for index, operation in enumerate(records, start=1):
            first_item = (
                self._collection.get(operation.image_indices[0])
                if operation.image_indices
                else None
            )
            entries.append(
                {
                    "index": index,
                    "kind": operation.kind,
                    "target": operation.target,
                    "image_count": len(operation.image_indices),
                    "image_name": first_item.path.name if first_item is not None else "",
                    "changes": operation.changes,
                }
            )
        return {
            "position": len(self._op_history),
            "base_label": "Earlier state" if self._history_base_truncated else "Original",
            "truncated": self._history_base_truncated,
            "entries": entries,
        }

    # ------------------------------------------------------------------
    # Settings / capabilities
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        return self._settings.as_dict()

    def set_config(self, key: str, value: Any) -> dict[str, Any]:
        if key == "performance_mode":
            value = self._normalize_mode(str(value))
        self._settings.set(key, value)
        if key == "performance_mode":
            self._apply_performance_mode()
        return {"ok": True}

    def get_capabilities(self) -> dict[str, Any]:
        """Report the *real* detected hardware plus the active profile.

        Everything here is queried live from OpenCV/the OS, so the About
        dialog never has to invent a synthetic "GPU: available" line: if
        ``gpu`` is ``None`` there is genuinely no usable OpenCL device.
        """
        mode = self._normalize_mode(str(self._settings.get("performance_mode", "medium")))
        try:
            have_opencl = bool(cv2.ocl.haveOpenCL())
        except Exception:  # pragma: no cover - defensive
            have_opencl = False
        try:
            using_opencl = bool(cv2.ocl.useOpenCL())
        except Exception:  # pragma: no cover - defensive
            using_opencl = False
        try:
            threads = int(cv2.getNumThreads()) or (os.cpu_count() or 1)
        except Exception:  # pragma: no cover - defensive
            threads = os.cpu_count() or 1
        gpu = self._gpu_info() if have_opencl else None
        return {
            "cv_version": cv2.__version__,
            "opencl": have_opencl,
            "opencl_in_use": using_opencl,
            "cores": os.cpu_count() or 1,
            "threads": threads,
            "cpu_name": _cpu_name(),
            "gpu": gpu,
            "performance_mode": mode,
            "preview_max": self._resolve_preview_max(),
            "backend": "GPU + CPU" if using_opencl else "CPU only",
        }

    def _gpu_info(self) -> dict[str, Any] | None:
        """Describe the default OpenCL device, or ``None`` if unavailable."""
        try:
            device = cv2.ocl.Device.getDefault()
        except Exception:  # pragma: no cover - defensive
            return None
        if device is None:
            return None

        def call(method: str) -> str:
            try:
                return str(getattr(device, method)())
            except Exception:  # pragma: no cover - defensive
                return ""

        if call("available").lower() in ("", "false"):
            return None
        try:
            dtype = int(device.type())
        except Exception:  # pragma: no cover - defensive
            dtype = 0
        if dtype & cv2.ocl.DEVICE_TYPE_GPU:
            kind = "GPU"
        elif dtype & cv2.ocl.DEVICE_TYPE_CPU:
            kind = "CPU"
        else:
            kind = "Accelerator"
        return {
            "name": call("name"),
            "vendor": call("vendorName"),
            "driver": call("driverVersion"),
            "version": call("version") or call("OpenCLVersion"),
            "type": kind,
        }

    def get_app_info(self) -> dict[str, str]:
        """Return application metadata for the About dialog."""
        from imagecraft import __version__

        return {"name": APP_TITLE, "edition": EDITION, "version": __version__, "author": "Saeed Sameeh Abualnaaj"}

    # ------------------------------------------------------------------
    # Working modes and VisionDB Craft projects
    # ------------------------------------------------------------------

    def set_working_mode(self, mode: str) -> dict[str, Any]:
        """Change the focused workflow without destroying the open project."""
        normalized = str(mode).strip().lower()
        if normalized not in WORKING_MODES:
            return {"ok": False, "message": f"Unknown working mode: {mode}"}
        with self._lock:
            if self._working_mode == "auto_annotate" and normalized != "auto_annotate":
                self._clear_auto_preview()
            self._working_mode = normalized
            return {"ok": True, **self._state_payload()}

    def abandon_workspace(self, mode: str) -> dict[str, Any]:
        """Start an empty workflow after an explicit destructive UI choice."""
        normalized = str(mode).strip().lower()
        if normalized not in WORKING_MODES:
            return {"ok": False, "message": f"Unknown working mode: {mode}"}
        with self._lock:
            self._discard_workspace_state()
            self._working_mode = normalized
            return {"ok": True, **self._state_payload()}

    def discard_session(self) -> dict[str, Any]:
        """Unload current media and work without deleting any source files."""
        with self._lock:
            self._discard_workspace_state()
            return {"ok": True, **self._state_payload()}

    def _discard_workspace_state(self) -> None:
        """Return the workspace to its unloaded state while preserving its mode."""
        self._collection.clear()
        self._dataset = None
        self._dataset_operations = []
        self._workspace_kind = "empty"
        self._project_path = None
        self._project_ui_state = {}
        self._practice_label = ""
        self._work_dirty = False
        self._clear_history()

    def save_project(
        self,
        ui_state: dict[str, Any] | None = None,
        target_path: str = "",
    ) -> dict[str, Any]:
        """Save a complete, portable ``.imagecraft`` editing session."""
        if self._collection.is_empty:
            return {"ok": False, "message": "Open an image, folder, or dataset first"}
        destination = str(target_path).strip()
        if not destination:
            if self._bridge is None:
                return {"ok": False, "message": "No UI bridge available"}
            suggested = (
                str(self._project_path)
                if self._project_path is not None
                else str(Path.cwd() / "VisionDB Craft-project.imagecraft")
            )
            selected = self._bridge.save_file_dialog(
                save_as=suggested,
                file_types=("VisionDB Craft project (*.imagecraft)", "All files (*.*)"),
            )
            if not selected:
                return {"ok": False, "cancelled": True, "message": "Cancelled"}
            destination = selected
        target = Path(destination)
        if target.suffix.lower() != ".imagecraft":
            target = target.with_suffix(".imagecraft")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
            with (
                self._lock,
                zipfile.ZipFile(
                    staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                ) as archive,
            ):
                safe_ui = _json_safe(ui_state or {})
                manifest = self._project_manifest(archive, safe_ui)
                archive.writestr("project.json", json.dumps(manifest, indent=2))
            os.replace(staging, target)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            try:
                if "staging" in locals() and staging.exists():
                    staging.unlink()
            except OSError:
                pass
            return {"ok": False, "message": f"Could not save project: {exc}"}
        with self._lock:
            self._project_path = target
            self._project_ui_state = dict(safe_ui)
            self._work_dirty = False
            return {
                "ok": True,
                "path": str(target),
                "message": f"Project saved as {target.name}",
                **self._state_payload(),
            }

    def open_project_dialog(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"ok": False, "message": "No UI bridge available"}
        selected = self._bridge.open_file_dialog(
            file_types=("VisionDB Craft project (*.imagecraft)", "All files (*.*)"),
        )
        if not selected:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        return self.open_project_path(selected[0])

    def open_project_path(self, project_path: str) -> dict[str, Any]:
        """Restore media, annotations, history, detector preview, and UI state."""
        path = Path(project_path)
        try:
            with zipfile.ZipFile(path, "r") as archive:
                manifest = json.loads(archive.read("project.json").decode("utf-8"))
                if int(manifest.get("format_version", 0)) != PROJECT_FORMAT_VERSION:
                    raise ValueError("Unsupported VisionDB Craft project version")
                restored = self._restore_project(archive, manifest)
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            zipfile.BadZipFile,
        ) as exc:
            return {"ok": False, "message": f"Could not open project: {exc}"}
        with self._lock:
            self._collection.restore(restored["items"], int(manifest.get("current_index", 0)))
            self._working_mode = str(manifest.get("working_mode", "transform"))
            if self._working_mode not in WORKING_MODES:
                self._working_mode = "transform"
            self._workspace_kind = str(manifest.get("workspace_kind", "image_collection"))
            self._annotation_classes = [
                str(name) for name in manifest.get("annotation_classes", ["object"])
            ] or ["object"]
            self._dataset = restored["dataset"]
            self._dataset_operations = list(manifest.get("dataset_operations", []))
            self._op_history = restored["history"]
            self._op_redo = restored["redo"]
            self._history_base_truncated = bool(manifest.get("history_base_truncated", False))
            self._project_ui_state = dict(manifest.get("ui_state", {}))
            self._project_path = path
            self._practice_label = str(manifest.get("practice_label", ""))
            self._work_dirty = False
            self._clear_auto_preview()
            self._clear_ai_proposals()
            auto_preview = manifest.get("auto_preview")
            if isinstance(auto_preview, dict):
                image_index = int(auto_preview.get("image_index", -1))
                preview_item = self._collection.get(image_index)
                if preview_item is not None:
                    self._auto_preview_candidates = deepcopy(auto_preview.get("candidates", []))
                    self._auto_preview_config = deepcopy(auto_preview.get("config", {}))
                    self._auto_preview_path = preview_item.path.resolve()
            local_ai = manifest.get("local_ai")
            if isinstance(local_ai, dict):
                self._ai_task = str(local_ai.get("task", "classification"))
                self._ai_model = str(local_ai.get("model_id", "clip-vit-b32"))
                self._ai_config = deepcopy(local_ai.get("config", {}))
                for row in local_ai.get("proposals", []):
                    if not isinstance(row, dict):
                        continue
                    proposal_item = self._collection.get(int(row.get("image_index", -1)))
                    if proposal_item is not None:
                        self._ai_proposals[str(proposal_item.path.resolve())] = deepcopy(
                            row.get("candidates", [])
                        )
            missing = [
                str(item.path)
                for _, item in self._collection.iter_all()
                if not item.path.is_file() and not item.is_generated
            ]
            return {
                "ok": True,
                "path": str(path),
                "missing_media": missing,
                **self._state_payload(),
            }

    def relink_missing_media(self) -> dict[str, Any]:
        """Map missing source paths to files with matching names in a chosen folder."""
        if self._bridge is None:
            return {"ok": False, "message": "No UI bridge available"}
        selected = self._bridge.open_folder_dialog()
        if not selected:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        root = Path(selected)
        candidates: dict[str, list[Path]] = {}
        try:
            for candidate in root.rglob("*"):
                if candidate.is_file():
                    candidates.setdefault(candidate.name.casefold(), []).append(candidate)
        except OSError as exc:
            return {"ok": False, "message": f"Could not scan that folder: {exc}"}
        relinked = 0
        unresolved: list[str] = []
        with self._lock:
            for _, item in self._collection.iter_all():
                if item.path.is_file() or item.is_generated:
                    continue
                matches = candidates.get(item.path.name.casefold(), [])
                if matches:
                    item.path = matches[0]
                    relinked += 1
                else:
                    unresolved.append(str(item.path))
            if relinked:
                self._work_dirty = True
            return {
                "ok": True,
                "relinked": relinked,
                "unresolved": unresolved,
                **self._state_payload(),
            }

    # ------------------------------------------------------------------
    # Image loading / navigation
    # ------------------------------------------------------------------

    def open_image_dialog(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"error": "No UI bridge available"}
        paths = self._bridge.open_file_dialog(
            file_types=(
                "Image files (*.png;*.jpg;*.jpeg;*.bmp;*.tiff;*.tif)",
                "All files (*.*)",
            )
        )
        if not paths:
            return {"ok": False, "cancelled": True, "message": "No file selected"}
        return self._load_single(Path(paths[0]))

    def open_folder_dialog(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"error": "No UI bridge available"}
        directory = self._bridge.open_folder_dialog()
        if not directory:
            return {"ok": False, "cancelled": True, "message": "No folder selected"}
        path = Path(directory)
        if not _looks_like_labelled_dataset(path):
            return self._load_folder(path)
        try:
            project = load_dataset(path)
        except (OSError, ValueError):
            return self._load_folder(path)
        return {
            "ok": False,
            "requires_confirmation": "dataset_detected",
            "path": str(path),
            "dataset": project.as_summary(),
            "message": "This folder contains a supported labelled dataset.",
        }

    def open_dataset_dialog(self) -> dict[str, Any]:
        """Choose and load a classification, YOLO, COCO, or Pascal VOC project."""
        if self._bridge is None:
            return {"error": "No UI bridge available"}
        directory = self._bridge.open_folder_dialog()
        if not directory:
            return {"ok": False, "cancelled": True, "message": "No folder selected"}
        if not _looks_like_labelled_dataset(Path(directory)):
            return {
                "ok": False,
                "requires_confirmation": "no_dataset_detected",
                "path": str(directory),
                "message": (
                    "No supported classification, YOLO, COCO, or Pascal VOC dataset was detected"
                ),
            }
        try:
            project = load_dataset(Path(directory))
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "requires_confirmation": "no_dataset_detected",
                "path": str(directory),
                "message": str(exc),
            }
        return self._load_dataset_project(project)

    def open_folder_path(self, directory: str) -> dict[str, Any]:
        """Open a previously selected path explicitly as unlabelled images."""
        return self._load_folder(Path(directory))

    def open_dataset_path(self, directory: str) -> dict[str, Any]:
        """Open a previously selected path explicitly as a labelled dataset."""
        try:
            project = load_dataset(Path(directory))
        except (OSError, ValueError) as exc:
            return {"ok": False, "message": str(exc)}
        return self._load_dataset_project(project)

    def _load_dataset_project(self, project: DatasetProject) -> dict[str, Any]:
        with self._lock:
            self._dataset = project
            self._workspace_kind = "dataset"
            self._dataset_operations = []
            self._collection.load_dataset_records(project.records)
            self._load_annotation_sidecars()
            self._remember_recent_project(project.root)
            self._clear_history()
            self._project_path = None
            self._project_ui_state = {}
            self._practice_label = ""
            self._work_dirty = False
            return self._state_payload()

    # ------------------------------------------------------------------
    # Annotation workspace
    # ------------------------------------------------------------------

    def get_annotation_state(self) -> dict[str, Any]:
        with self._lock:
            return self._annotation_editor_payload()














    def open_augmentation_practice_image(self) -> dict[str, Any]:
        return self._open_geometry_practice_image("augment")

    def open_transform_practice_image(self) -> dict[str, Any]:
        return self._open_geometry_practice_image("transform")

    def _open_geometry_practice_image(self, mode: str) -> dict[str, Any]:
        """Open a labelled sheet that makes annotation synchronization visible."""
        width, height = 1100, 720
        image = np.full((height, width, 3), (235, 238, 244), dtype=np.uint8)
        cv2.rectangle(image, (85, 105), (390, 360), (55, 110, 215), -1, cv2.LINE_AA)
        triangle = np.asarray([[565, 355], [735, 95], [895, 355]], dtype=np.int32)
        cv2.fillPoly(image, [triangle], (225, 115, 45), cv2.LINE_AA)
        cv2.circle(image, (760, 555), 105, (60, 175, 110), -1, cv2.LINE_AA)
        for x in range(0, width, 100):
            cv2.line(image, (x, 0), (x, height), (205, 209, 218), 1)
        for y in range(0, height, 100):
            cv2.line(image, (0, y), (width, y), (205, 209, 218), 1)

        practice_dir = Path(tempfile.mkdtemp(prefix="VisionDB Craft-geometry-practice-"))
        path = practice_dir / f"{mode}_annotation_aware.png"
        if not cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)):
            return {"ok": False, "message": "Could not create the practice image"}
        payload = self._load_single(path)
        if payload.get("ok") is False:
            return payload
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.circle(mask, (760, 555), 105, (1.0,), -1)
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"ok": False, "message": "Could not open the practice image"}
            self._annotation_classes = ["rectangle", "triangle", "circle mask"]
            item.original_annotations = [
                Annotation(
                    0,
                    (85 + 390) / 2 / width,
                    (105 + 360) / 2 / height,
                    (390 - 85) / width,
                    (360 - 105) / height,
                    "rectangle",
                ),
                Annotation(
                    1,
                    (565 + 895) / 2 / width,
                    (95 + 355) / 2 / height,
                    (895 - 565) / width,
                    (355 - 95) / height,
                    "triangle",
                    [(x / width, y / height) for x, y in triangle.tolist()],
                    "polygon",
                ),
                Annotation(
                    2,
                    760 / width,
                    555 / height,
                    210 / width,
                    210 / height,
                    "circle mask",
                    annotation_type="mask",
                    mask_rle=encode_rle(mask),
                ),
            ]
            item.modified_annotations = None
            self._working_mode = mode if mode in {"transform", "augment"} else "augment"
            self._practice_label = f"{self._working_mode.title()} annotation-aware practice"
            self._work_dirty = False
            return {"ok": True, "practice": True, **self._state_payload()}







    def mark_annotation_reviewed(self, index: int) -> dict[str, Any]:
        """Clear the review flag on one Auto Annotate result without changing geometry."""
        with self._lock:
            item = self._collection.current
            if item is None or not 0 <= int(index) < len(item.active_annotations):
                return {"ok": False, "message": "Annotation was not found"}
            annotation = item.active_annotations[int(index)]
            auto_metadata = annotation.metadata.get("auto_annotate")
            if not isinstance(auto_metadata, dict) or not auto_metadata.get("needs_review"):
                return {"ok": False, "message": "This annotation is not awaiting review"}

            def mark_reviewed(annotations: list[Annotation]) -> None:
                metadata = annotations[int(index)].metadata.setdefault("auto_annotate", {})
                metadata["needs_review"] = False
                metadata["reviewed"] = True

            self._mutate_annotations("mark reviewed", {"label": annotation.label}, mark_reviewed)
            return {"ok": True, **self._state_payload()}

    def set_annotation_config(
        self, autosave: bool, one_class: bool, class_id: int = 0
    ) -> dict[str, Any]:
        self._settings.set("annotation_autosave", bool(autosave))
        self._settings.set("annotation_one_class", bool(one_class))
        self._settings.set("annotation_default_class", max(0, int(class_id)))
        return self.get_annotation_state()

    def set_annotation_autosave(self, enabled: bool) -> dict[str, Any]:
        """Update working-file autosave without changing drawing preferences."""
        self._settings.set("annotation_autosave", bool(enabled))
        if enabled:
            with self._lock:
                self._autosave_all_annotations(force=True)
        return {"ok": True, **self.get_annotation_state()}

    def add_annotation_class(self, name: str) -> dict[str, Any]:
        clean = str(name).strip()
        if not clean:
            return {"ok": False, "message": "Class name cannot be empty"}
        with self._lock:
            classes = self._active_annotation_classes()
            if clean not in classes:
                classes.append(clean)
                if self._dataset is None:
                    self._settings.set("annotation_classes", self._annotation_classes)
                item = self._collection.current
                if item is not None and self._settings.get("annotation_autosave", True):
                    self._write_annotation_sidecar(item)
            return {"ok": True, **self._annotation_editor_payload()}

    def import_annotation_classes(self) -> dict[str, Any]:
        """Merge class names from classes.txt, dataset YAML, or COCO JSON."""
        if self._bridge is None:
            return {"ok": False, "message": "No UI bridge available"}
        paths = self._bridge.open_file_dialog(
            allow_multiple=False,
            file_types=(
                "Class files (*.txt;*.yaml;*.yml;*.json)",
                "All files (*.*)",
            ),
        )
        if not paths:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        path = Path(paths[0])
        try:
            imported = _parse_annotation_class_file(path)
        except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
            return {"ok": False, "message": f"Could not import classes: {exc}"}
        if not imported:
            return {"ok": False, "message": "No class names were found in that file"}
        with self._lock:
            classes = self._active_annotation_classes()
            added = 0
            for name in imported:
                if name not in classes:
                    classes.append(name)
                    added += 1
            self._persist_annotation_classes()
            self._autosave_all_annotations()
            return {
                "ok": True,
                "added": added,
                "imported": len(imported),
                "path": str(path),
                **self._annotation_editor_payload(),
            }

    def rename_annotation_class(self, class_id: int, name: str) -> dict[str, Any]:
        clean = str(name).strip()
        if not clean:
            return {"ok": False, "message": "Class name cannot be empty"}
        with self._lock:
            classes = self._active_annotation_classes()
            class_id = int(class_id)
            if not 0 <= class_id < len(classes):
                return {"ok": False, "message": "Class was not found"}
            if clean in classes and classes[class_id] != clean:
                return {"ok": False, "message": "A class with that name already exists"}
            classes[class_id] = clean
            for annotations in self._annotation_storage_lists():
                for annotation in annotations:
                    if annotation.class_id == class_id:
                        annotation.label = clean
            self._persist_annotation_classes()
            self._autosave_all_annotations()
            return {"ok": True, **self._annotation_editor_payload()}

    def delete_annotation_class(
        self,
        class_id: int,
        reassign_to: int = -1,
        delete_annotations: bool = False,
    ) -> dict[str, Any]:
        """Delete a class and either reassign or remove every annotation using it."""
        with self._lock:
            classes = self._active_annotation_classes()
            class_id = int(class_id)
            reassign_to = int(reassign_to)
            delete_annotations = bool(delete_annotations)
            if not 0 <= class_id < len(classes):
                return {"ok": False, "message": "Class was not found"}
            if len(classes) <= 1:
                return {"ok": False, "message": "At least one class must remain"}
            usage = self._annotation_class_usage()[class_id]
            if (
                usage
                and not delete_annotations
                and (not 0 <= reassign_to < len(classes) or reassign_to == class_id)
            ):
                return {
                    "ok": False,
                    "requires_reassignment": True,
                    "usage": usage,
                    "message": f"This class is used by {usage} annotation(s)",
                    **self._annotation_editor_payload(),
                }

            replacement_id = (
                reassign_to if usage and not delete_annotations else (0 if class_id != 0 else 1)
            )
            replacement_name = classes[replacement_id]
            for annotations in self._annotation_storage_lists():
                if delete_annotations:
                    annotations[:] = [
                        annotation for annotation in annotations if annotation.class_id != class_id
                    ]
                for annotation in annotations:
                    if not delete_annotations and annotation.class_id == class_id:
                        annotation.class_id = replacement_id
                        annotation.label = replacement_name
                    if annotation.class_id > class_id:
                        annotation.class_id -= 1
            classes.pop(class_id)
            default_class = int(self._settings.get("annotation_default_class", 0))
            if default_class == class_id:
                default_class = max(0, replacement_id - int(replacement_id > class_id))
            elif default_class > class_id:
                default_class -= 1
            self._settings.set("annotation_default_class", min(default_class, len(classes) - 1))
            self._persist_annotation_classes()
            self._autosave_all_annotations()
            return {
                "ok": True,
                "reassigned": 0 if delete_annotations else usage,
                "deleted_annotations": usage if delete_annotations else 0,
                **self._annotation_editor_payload(),
            }

    def choose_annotation_save_directory(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"ok": False, "message": "No UI bridge available"}
        directory = self._bridge.open_folder_dialog()
        if not directory:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        path = Path(directory).resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "message": f"Cannot use that folder: {exc}"}
        with self._lock:
            self._settings.set("annotation_save_directory", str(path))
            self._autosave_all_annotations(force=True)
            return {"ok": True, **self._annotation_editor_payload()}

    def reset_annotation_save_directory(self) -> dict[str, Any]:
        self._settings.set("annotation_save_directory", "")
        return {"ok": True, **self.get_annotation_state()}

    def choose_annotation_export_directory(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"ok": False, "message": "No UI bridge available"}
        directory = self._bridge.open_folder_dialog()
        if not directory:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        path = Path(directory).resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "message": f"Cannot use that folder: {exc}"}
        self._settings.set("annotation_export_directory", str(path))
        return {"ok": True, **self.get_annotation_state()}

    def reset_annotation_export_directory(self) -> dict[str, Any]:
        self._settings.set("annotation_export_directory", "")
        return {"ok": True, **self.get_annotation_state()}

    def create_annotation(
        self, annotation_type: str, class_id: int, geometry: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"ok": False, "message": "No image is open"}
            classes = self._active_annotation_classes()
            class_id = int(class_id)
            if class_id < 0 or class_id >= len(classes):
                return {"ok": False, "message": "Choose a valid annotation class"}
            annotation_type = str(annotation_type).lower()
            geometry = geometry or {}
            try:
                annotation = self._annotation_from_geometry(
                    annotation_type, class_id, classes[class_id], geometry
                )
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}
            self._mutate_annotations(
                "create",
                {"annotation_type": annotation_type, "label": classes[class_id]},
                lambda annotations: annotations.append(annotation),
            )
            return {"ok": True, **self._state_payload()}

    def update_annotation(self, index: int, class_id: int) -> dict[str, Any]:
        with self._lock:
            item = self._collection.current
            classes = self._active_annotation_classes()
            if item is None or not 0 <= int(index) < len(item.active_annotations):
                return {"ok": False, "message": "Annotation was not found"}
            if not 0 <= int(class_id) < len(classes):
                return {"ok": False, "message": "Choose a valid class"}

            def change(annotations: list[Annotation]) -> None:
                annotations[int(index)].class_id = int(class_id)
                annotations[int(index)].label = classes[int(class_id)]

            self._mutate_annotations("reclassify", {"label": classes[int(class_id)]}, change)
            return {"ok": True, **self._state_payload()}

    def update_annotation_geometry(self, index: int, geometry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item = self._collection.current
            if item is None or not 0 <= int(index) < len(item.active_annotations):
                return {"ok": False, "message": "Annotation was not found"}
            original = item.active_annotations[int(index)]
            if original.annotation_type == "classification":
                return {"ok": False, "message": "Classification labels have no geometry"}
            try:
                replacement = self._annotation_from_geometry(
                    original.annotation_type, original.class_id, original.label, geometry
                )
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}
            self._mutate_annotations(
                "redraw",
                {"annotation_type": original.annotation_type, "label": original.label},
                lambda annotations: annotations.__setitem__(int(index), replacement),
            )
            return {"ok": True, **self._state_payload()}

    def transform_annotation_geometry(self, index: int, geometry: dict[str, Any]) -> dict[str, Any]:
        """Move or resize one spatial annotation inside the current image."""
        with self._lock:
            item = self._collection.current
            if item is None or not 0 <= int(index) < len(item.active_annotations):
                return {"ok": False, "message": "Annotation was not found"}
            original = item.active_annotations[int(index)]
            if original.annotation_type == "classification":
                return {
                    "ok": False,
                    "message": "Whole-image classifications cannot be moved or resized",
                }
            try:
                replacement = self._annotation_with_transformed_bounds(
                    original, geometry, item.width, item.height
                )
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}

            action = "move" if str(geometry.get("action", "")).lower() == "move" else "resize"
            self._mutate_annotations(
                action,
                {
                    "annotation_type": original.annotation_type,
                    "label": original.label,
                    "center_x": round(replacement.x_center * 100.0, 2),
                    "center_y": round(replacement.y_center * 100.0, 2),
                    "width_percent": round(replacement.width * 100.0, 2),
                    "height_percent": round(replacement.height * 100.0, 2),
                },
                lambda annotations: annotations.__setitem__(int(index), replacement),
            )
            return {"ok": True, **self._state_payload()}

    def delete_annotation(self, index: int) -> dict[str, Any]:
        with self._lock:
            item = self._collection.current
            if item is None or not 0 <= int(index) < len(item.active_annotations):
                return {"ok": False, "message": "Annotation was not found"}
            label = item.active_annotations[int(index)].label
            self._mutate_annotations(
                "delete", {"label": label}, lambda annotations: annotations.pop(int(index))
            )
            return {"ok": True, **self._state_payload()}

    def save_annotations(self) -> dict[str, Any]:
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"ok": False, "message": "No image is open"}
            path = self._write_annotation_sidecar(item)
            return {"ok": True, "path": str(path), **self._annotation_editor_payload()}

    def save_annotation_files(self, scope: str = "all") -> dict[str, Any]:
        """Write VisionDB Craft working annotation files for current or all images."""
        with self._lock:
            items = (
                [item for _, item in self._collection.iter_all()]
                if str(scope).lower() == "all"
                else [self._collection.current]
            )
            available = [item for item in items if item is not None]
            if not available:
                return {"ok": False, "message": "No images are open"}
            paths = [str(self._write_annotation_sidecar(item)) for item in available]
            return {
                "ok": True,
                "saved": len(paths),
                "paths": paths,
                **self._annotation_editor_payload(),
            }

    def export_annotations(
        self,
        target_format: str = "yolo",
        scope: str = "all",
        task: str = "auto",
    ) -> dict[str, Any]:
        """Export one coherent training task using only compatible geometry."""
        with self._lock:
            items = (
                [item for _, item in self._collection.iter_all()]
                if str(scope).lower() == "all"
                else [self._collection.current]
            )
            items = [item for item in items if item is not None]
            classes = list(self._active_annotation_classes())
            if not items or not classes:
                return {"ok": False, "message": "Open images and add at least one class"}

            counts = self._annotation_type_counts(items)
            available_tasks = {
                name
                for name, count in (
                    ("classification", counts["classification"]),
                    ("detection", counts["bbox"]),
                    ("segmentation", counts["polygon"] + counts["mask"]),
                    ("pose", counts["pose"]),
                )
                if count > 0
            }
            requested_task = str(task).strip().lower()
            if requested_task == "auto":
                requested_task = (
                    "pose"
                    if "pose" in available_tasks
                    else "segmentation"
                    if "segmentation" in available_tasks
                    else "detection"
                    if "detection" in available_tasks
                    else "classification"
                    if "classification" in available_tasks
                    else ""
                )
            if requested_task not in available_tasks:
                return {
                    "ok": False,
                    "message": "No annotations are available for the selected training task",
                }

            allowed_formats = {
                "classification": {"yolo"},
                "detection": {"yolo", "coco", "voc"},
                "segmentation": {"yolo", "coco", "mask"},
                "pose": {"yolo_pose", "coco_keypoints", "mediapipe"},
            }[requested_task]
            target = str(target_format).strip().lower()
            if target not in allowed_formats:
                readable = ", ".join(sorted(value.upper() for value in allowed_formats))
                return {
                    "ok": False,
                    "message": (
                        f"{target.upper()} is not valid for {requested_task}. "
                        f"Choose one of: {readable}"
                    ),
                }

            accepted_types = {
                "classification": {"classification"},
                "detection": {"bbox"},
                "segmentation": {"polygon", "mask"},
                "pose": {"pose"},
            }[requested_task]
            export_items: list[ImageItem] = []
            exported_annotations = 0
            excluded_annotations = 0
            for item in items:
                accepted = [
                    annotation.copy()
                    for annotation in item.active_annotations
                    if annotation.annotation_type in accepted_types
                ]
                exported_annotations += len(accepted)
                excluded_annotations += len(item.active_annotations) - len(accepted)
                export_items.append(
                    ImageItem(
                        path=item.path,
                        original=item.active.copy(),
                        original_annotations=accepted,
                        dataset_split=item.dataset_split,
                        original_split=item.original_split,
                        is_generated=item.is_generated,
                    )
                )

            try:
                root = Path(os.path.commonpath([str(item.path.parent) for item in items]))
            except ValueError:
                # Windows collections can span drives, which have no common path.
                root = items[0].path.parent
            project = DatasetProject(
                root=root,
                name=root.name or "annotations",
                source_format="imagecraft",
                class_names=classes,
                records=[],
                task_type=requested_task,
            )
            validation = validate_dataset(project, export_items)

        configured = str(self._settings.get("annotation_export_directory", "")).strip()
        directory: str | None
        if configured:
            directory = configured
        elif self._bridge is not None:
            directory = self._bridge.open_folder_dialog()
        else:
            return {"ok": False, "message": "No export directory is configured"}
        if not directory:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        try:
            result = export_dataset(
                project,
                export_items,
                Path(directory),
                target,
                validation,
                {
                    "annotation_workspace": True,
                    "scope": str(scope).lower(),
                    "training_task": requested_task,
                    "annotations_exported": exported_annotations,
                    "annotations_excluded_for_other_tasks": excluded_annotations,
                },
            )
            workspace_exported = str(scope).lower() == "all" or self._collection.count == 1
            if workspace_exported:
                self._work_dirty = False
            return {
                **result,
                "task": requested_task,
                "annotations_exported": exported_annotations,
                "annotations_excluded": excluded_annotations,
                "workspace_exported": workspace_exported,
            }
        except (OSError, ValueError) as exc:
            return {"ok": False, "message": str(exc)}


    def _active_annotation_classes(self) -> list[str]:
        if self._dataset is not None:
            if not self._dataset.class_names:
                self._dataset.class_names.append("object")
            return self._dataset.class_names
        if not self._annotation_classes:
            self._annotation_classes.append("object")
        return self._annotation_classes

    def _persist_annotation_classes(self) -> None:
        if self._dataset is None:
            self._settings.set("annotation_classes", list(self._annotation_classes))

    def _annotation_class_usage(self) -> list[int]:
        classes = self._active_annotation_classes()
        usage = [0 for _ in classes]
        for _, item in self._collection.iter_all():
            for annotation in item.active_annotations:
                if 0 <= annotation.class_id < len(usage):
                    usage[annotation.class_id] += 1
        return usage

    def _annotation_storage_lists(self) -> Iterable[list[Annotation]]:
        """Yield live and history annotation lists for safe class reindexing."""
        for _, item in self._collection.iter_all():
            yield item.original_annotations
            if item.modified_annotations is not None:
                yield item.modified_annotations
        for operation in [*self._op_history, *self._op_redo]:
            for mapping in (
                operation.previous_annotations,
                operation.resulting_annotations,
            ):
                for annotation_list in mapping.values():
                    if annotation_list is not None:
                        yield annotation_list

    def _autosave_all_annotations(self, *, force: bool = False) -> None:
        if not force and not self._settings.get("annotation_autosave", True):
            return
        for _, item in self._collection.iter_all():
            self._write_annotation_sidecar(item)

    def _annotation_from_geometry(
        self, annotation_type: str, class_id: int, label: str, geometry: dict[str, Any]
    ) -> Annotation:
        if annotation_type == "classification":
            annotation = Annotation(
                class_id,
                0.5,
                0.5,
                1.0,
                1.0,
                label,
                annotation_type="classification",
            )
        elif annotation_type == "polygon":
            raw = geometry.get("polygon", [])
            polygon = [(float(point[0]), float(point[1])) for point in raw]
            if len(polygon) < 3:
                raise ValueError("A polygon needs at least three points")
            xs, ys = zip(*polygon, strict=True)
            annotation = Annotation(
                class_id,
                (min(xs) + max(xs)) / 2,
                (min(ys) + max(ys)) / 2,
                max(xs) - min(xs),
                max(ys) - min(ys),
                label,
                polygon,
                "polygon",
            )
        elif annotation_type == "mask":
            raw_rle = geometry.get("mask_rle") or geometry.get("base_mask_rle")
            item = self._collection.current
            if raw_rle:
                mask = decode_rle(normalize_rle(raw_rle))
                if (
                    geometry.get("strokes")
                    and item is not None
                    and mask.shape != (item.height, item.width)
                ):
                    mask = np.asarray(
                        cv2.resize(
                            mask, (item.width, item.height), interpolation=cv2.INTER_NEAREST
                        ),
                        dtype=np.uint8,
                    )
            else:
                if item is None or item.width <= 0 or item.height <= 0:
                    raise ValueError("Open an image before painting a mask")
                mask = np.zeros((item.height, item.width), dtype=np.uint8)

            brush_size = max(1, min(512, int(geometry.get("brush_size", 24))))
            for raw_stroke in geometry.get("strokes", []):
                if isinstance(raw_stroke, dict):
                    raw_points = raw_stroke.get("points", [])
                    erase = bool(raw_stroke.get("erase", False))
                    stroke_size = max(1, min(512, int(raw_stroke.get("brush_size", brush_size))))
                else:
                    raw_points = raw_stroke
                    erase = False
                    stroke_size = brush_size
                points = [
                    (
                        int(round(float(point[0]) * max(mask.shape[1] - 1, 1))),
                        int(round(float(point[1]) * max(mask.shape[0] - 1, 1))),
                    )
                    for point in raw_points
                    if isinstance(point, (list, tuple)) and len(point) >= 2
                ]
                if not points:
                    continue
                color = (0.0,) if erase else (1.0,)
                if len(points) == 1:
                    cv2.circle(mask, points[0], max(1, stroke_size // 2), color, -1)
                else:
                    for start, end in zip(points, points[1:], strict=False):
                        cv2.line(mask, start, end, color, stroke_size, cv2.LINE_8)
                    cv2.circle(mask, points[0], max(1, stroke_size // 2), color, -1)
                    cv2.circle(mask, points[-1], max(1, stroke_size // 2), color, -1)
            box = mask_bbox(mask)
            if box is None:
                raise ValueError("Paint at least one visible mask area")
            annotation = Annotation(
                class_id, *box, label, annotation_type="mask", mask_rle=encode_rle(mask)
            )
        elif annotation_type == "pose":
            schema_id = str(geometry.get("pose_schema", "coco_17"))
            schema = pose_schema(schema_id)
            keypoints = normalize_keypoints(geometry.get("keypoints", []), schema_id)
            if not any(int(point["visibility"]) > 0 for point in keypoints):
                raise ValueError("Place at least one pose keypoint")
            workflow = str(geometry.get("pose_workflow", "top_down")).lower()
            if workflow not in {"top_down", "bottom_up"}:
                workflow = "top_down"
            has_bbox = bool(geometry.get("pose_has_bbox", workflow == "top_down"))
            if has_bbox:
                pose_box = (
                    float(geometry.get("x", 0)),
                    float(geometry.get("y", 0)),
                    float(geometry.get("w", 0)),
                    float(geometry.get("h", 0)),
                )
            else:
                pose_box = pose_bounds(keypoints)
            annotation = Annotation(
                class_id,
                *pose_box,
                label,
                annotation_type="pose",
                keypoints=keypoints,
                pose_schema=schema_id,
                pose_workflow=workflow,
                pose_has_bbox=has_bbox,
            )
            annotation.metadata["pose"] = {
                "schema_label": schema["label"],
                "keypoint_names": list(schema["names"]),
                "skeleton": [list(edge) for edge in schema["skeleton"]],
            }
        elif annotation_type == "bbox":
            annotation = Annotation(
                class_id,
                float(geometry.get("x", 0)),
                float(geometry.get("y", 0)),
                float(geometry.get("w", 0)),
                float(geometry.get("h", 0)),
                label,
                annotation_type="bbox",
            )
        else:
            raise ValueError("Unsupported annotation type")
        raw_metadata = geometry.get("metadata")
        if isinstance(raw_metadata, dict):
            annotation.metadata = deepcopy(raw_metadata)
        if not annotation.is_normalized:
            raise ValueError("Annotation must stay inside the image")
        return annotation

    def update_pose_keypoint(
        self,
        index: int,
        keypoint_index: int,
        x: float,
        y: float,
        visibility: int = 2,
    ) -> dict[str, Any]:
        """Move or change the visibility of one landmark in a pose annotation."""
        with self._lock:
            item = self._collection.current
            if item is None or not 0 <= int(index) < len(item.active_annotations):
                return {"ok": False, "message": "Pose annotation was not found"}
            original = item.active_annotations[int(index)]
            if original.annotation_type != "pose" or original.keypoints is None:
                return {"ok": False, "message": "The selected annotation is not a pose"}
            point_index = int(keypoint_index)
            if not 0 <= point_index < len(original.keypoints):
                return {"ok": False, "message": "Pose keypoint was not found"}
            visibility = max(0, min(2, int(visibility)))
            if visibility and not (0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0):
                return {"ok": False, "message": "Keypoint must stay inside the image"}

            replacement = original.copy()
            assert replacement.keypoints is not None
            point = replacement.keypoints[point_index]
            point["x"] = float(x) if visibility else 0.0
            point["y"] = float(y) if visibility else 0.0
            point["visibility"] = visibility
            point["presence"] = 1.0 if visibility else 0.0
            if not replacement.pose_has_bbox:
                bounds = pose_bounds(replacement.keypoints)
                (
                    replacement.x_center,
                    replacement.y_center,
                    replacement.width,
                    replacement.height,
                ) = bounds
            if not replacement.is_normalized:
                return {"ok": False, "message": "Pose must stay inside the image"}
            self._mutate_annotations(
                "move_keypoint",
                {
                    "annotation_type": "pose",
                    "label": original.label,
                    "keypoint": point.get("name", point_index),
                    "visibility": visibility,
                },
                lambda annotations: annotations.__setitem__(int(index), replacement),
            )
            return {"ok": True, **self._state_payload()}









    def _refresh_dataset_task_type(self) -> None:
        if self._dataset is None:
            return
        kinds = {
            annotation.annotation_type
            for _, item in self._collection.iter_all()
            for annotation in item.active_annotations
        }
        self._dataset.task_type = (
            "pose"
            if "pose" in kinds
            else "segmentation"
            if kinds & {"polygon", "mask"}
            else "detection"
            if "bbox" in kinds
            else "classification"
        )

    def _clear_auto_preview(self) -> None:
        self._auto_preview_candidates = []
        self._auto_preview_path = None
        self._auto_preview_config = {}

    def _current_ai_key(self) -> str:
        item = self._collection.current
        return str(item.path.resolve()) if item is not None else ""

    def _current_ai_proposals(self) -> list[dict[str, Any]]:
        return deepcopy(self._ai_proposals.get(self._current_ai_key(), []))

    def _clear_ai_proposals(self) -> None:
        self._ai_proposals.clear()
        self._ai_config = {}


    def _annotation_with_transformed_bounds(
        self,
        original: Annotation,
        geometry: dict[str, Any],
        image_width: int,
        image_height: int,
    ) -> Annotation:
        """Return *original* moved/scaled into a new normalized bounding frame."""
        try:
            center_x = float(geometry["x"])
            center_y = float(geometry["y"])
            width = float(geometry["w"])
            height = float(geometry["h"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Move/resize needs valid x, y, width and height values") from exc

        bounds = Annotation(
            original.class_id,
            center_x,
            center_y,
            width,
            height,
            original.label,
        )
        if not all(np.isfinite(value) for value in (center_x, center_y, width, height)):
            raise ValueError("Annotation bounds must contain finite numbers")
        if not bounds.is_normalized:
            raise ValueError("Annotation must stay inside the image")

        if original.annotation_type == "bbox":
            replacement = original.copy()
            replacement.x_center = center_x
            replacement.y_center = center_y
            replacement.width = width
            replacement.height = height
            return replacement

        source_left = original.x_center - original.width / 2.0
        source_top = original.y_center - original.height / 2.0
        target_left = center_x - width / 2.0
        target_top = center_y - height / 2.0

        if original.annotation_type == "pose" and original.keypoints:
            if original.width <= 0 or original.height <= 0:
                raise ValueError("Pose bounds are invalid")
            keypoints = deepcopy(original.keypoints)
            for point in keypoints:
                if int(point.get("visibility", 0)) <= 0:
                    continue
                point["x"] = min(
                    1.0,
                    max(
                        0.0,
                        target_left + ((float(point["x"]) - source_left) / original.width) * width,
                    ),
                )
                point["y"] = min(
                    1.0,
                    max(
                        0.0,
                        target_top + ((float(point["y"]) - source_top) / original.height) * height,
                    ),
                )
            replacement = original.copy()
            replacement.x_center = center_x
            replacement.y_center = center_y
            replacement.width = width
            replacement.height = height
            replacement.keypoints = keypoints
            return replacement

        if original.annotation_type == "polygon" and original.polygon:
            if original.width <= 0 or original.height <= 0:
                raise ValueError("Polygon bounds are invalid")
            polygon = [
                (
                    min(
                        1.0,
                        max(
                            0.0,
                            target_left + ((point_x - source_left) / original.width) * width,
                        ),
                    ),
                    min(
                        1.0,
                        max(
                            0.0,
                            target_top + ((point_y - source_top) / original.height) * height,
                        ),
                    ),
                )
                for point_x, point_y in original.polygon
            ]
            return self._annotation_from_geometry(
                "polygon",
                original.class_id,
                original.label,
                {"polygon": polygon, "metadata": original.metadata},
            )

        if original.annotation_type == "mask" and original.mask_rle:
            if image_width <= 0 or image_height <= 0:
                raise ValueError("Image dimensions are unavailable")
            mask = decode_rle(normalize_rle(original.mask_rle))
            if mask.shape != (image_height, image_width):
                mask = np.asarray(
                    cv2.resize(
                        mask,
                        (image_width, image_height),
                        interpolation=cv2.INTER_NEAREST,
                    ),
                    dtype=np.uint8,
                )
            source_y, source_x = np.nonzero(mask)
            if not len(source_x):
                raise ValueError("Bitmap mask is empty")
            crop = mask[
                int(source_y.min()) : int(source_y.max()) + 1,
                int(source_x.min()) : int(source_x.max()) + 1,
            ]
            left = max(0, min(image_width - 1, round(target_left * image_width)))
            top = max(0, min(image_height - 1, round(target_top * image_height)))
            right = max(left + 1, min(image_width, round((target_left + width) * image_width)))
            bottom = max(
                top + 1,
                min(image_height, round((target_top + height) * image_height)),
            )
            resized = np.asarray(
                cv2.resize(
                    crop,
                    (right - left, bottom - top),
                    interpolation=cv2.INTER_NEAREST,
                ),
                dtype=np.uint8,
            )
            if not resized.any():
                resized[(bottom - top) // 2, (right - left) // 2] = 1
            transformed = np.zeros((image_height, image_width), dtype=np.uint8)
            transformed[top:bottom, left:right] = resized
            return self._annotation_from_geometry(
                "mask",
                original.class_id,
                original.label,
                {"mask_rle": encode_rle(transformed), "metadata": original.metadata},
            )

        raise ValueError(f"Unsupported annotation type: {original.annotation_type}")

    def _mutate_annotations(self, action: str, details: dict[str, Any], mutation: Any) -> None:
        item = self._collection.current
        if item is None:
            return
        index = self._collection.current_index
        previous = (
            None
            if item.modified_annotations is None
            else [annotation.copy() for annotation in item.modified_annotations]
        )
        annotations = [annotation.copy() for annotation in item.active_annotations]
        mutation(annotations)
        item.modified_annotations = annotations
        self._refresh_dataset_task_type()
        params = {"action": action, **details}
        self._push_operation(
            "annotation",
            params,
            [index],
            {index: None if item.modified is None else item.modified.copy()},
            {index: previous},
        )
        if self._settings.get("annotation_autosave", True):
            self._write_annotation_sidecar(item)

    def _annotation_editor_payload(self) -> dict[str, Any]:
        item = self._collection.current
        classes = self._active_annotation_classes()
        all_items = [candidate for _, candidate in self._collection.iter_all()]
        kinds = {
            ann.annotation_type
            for _, collection_item in self._collection.iter_all()
            for ann in collection_item.active_annotations
        }
        task_type = (
            "pose"
            if "pose" in kinds
            else "segmentation"
            if kinds & {"polygon", "mask"}
            else "detection"
            if "bbox" in kinds
            else "classification"
            if "classification" in kinds
            else "unassigned"
        )
        return {
            "available": item is not None,
            "classes": list(classes),
            "annotations": self._annotation_payload(item.active_annotations) if item else [],
            "autosave": bool(self._settings.get("annotation_autosave", True)),
            "one_class": bool(self._settings.get("annotation_one_class", False)),
            "default_class": int(self._settings.get("annotation_default_class", 0)),
            "task_type": self._dataset.task_type if self._dataset else task_type,
            "class_usage": self._annotation_class_usage(),
            "save_directory": str(self._settings.get("annotation_save_directory", "")),
            "export_directory": str(self._settings.get("annotation_export_directory", "")),
            "type_counts_current": self._annotation_type_counts([item] if item else []),
            "type_counts_all": self._annotation_type_counts(all_items),
            "pose_schema_counts_current": self._pose_schema_counts([item] if item else []),
            "pose_schema_counts_all": self._pose_schema_counts(all_items),
            "pose_schemas": {
                schema_id: pose_schema(schema_id) for schema_id in ("mediapipe_33", "coco_17")
            },
        }

    @staticmethod
    def _annotation_type_counts(items: Iterable[ImageItem]) -> dict[str, int]:
        counts = {"classification": 0, "bbox": 0, "polygon": 0, "mask": 0, "pose": 0}
        for item in items:
            for annotation in item.active_annotations:
                if annotation.annotation_type in counts:
                    counts[annotation.annotation_type] += 1
        return counts

    @staticmethod
    def _pose_schema_counts(items: Iterable[ImageItem]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            for annotation in item.active_annotations:
                if annotation.annotation_type == "pose":
                    schema = annotation.pose_schema or "unknown"
                    counts[schema] = counts.get(schema, 0) + 1
        return counts

    def _annotation_sidecar_path(self, item: ImageItem) -> Path:
        configured = str(self._settings.get("annotation_save_directory", "")).strip()
        if configured:
            resolved = str(item.path.resolve())
            digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:12]
            safe_stem = (
                "".join(
                    character if character.isalnum() or character in "-_" else "_"
                    for character in item.path.stem
                ).strip("_")
                or "image"
            )
            return Path(configured) / f"{safe_stem}__{digest}.json"
        base = self._dataset.root if self._dataset is not None else item.path.parent
        try:
            relative = item.path.relative_to(base)
        except ValueError:
            relative = Path(item.path.name)
        return base / ".imagecraft" / "annotations" / relative.with_suffix(".json")

    def _write_annotation_sidecar(self, item: ImageItem) -> Path:
        path = self._annotation_sidecar_path(item)
        return self._write_annotation_file(item, path)

    def _write_annotation_file(self, item: ImageItem, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "image": str(item.path),
            "classes": self._active_annotation_classes(),
            "annotations": self._annotation_payload(item.active_annotations),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _load_annotation_sidecars(self) -> None:
        for _, item in self._collection.iter_all():
            paths = [self._annotation_sidecar_path(item)]
            available = [path for path in paths if path.is_file()]
            if not available:
                continue
            path = max(available, key=lambda candidate: candidate.stat().st_mtime)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                annotations = [
                    self._annotation_from_geometry(
                        str(row.get("type", "bbox")),
                        int(row.get("class_id", 0)),
                        str(row.get("label", "")),
                        row,
                    )
                    for row in payload.get("annotations", [])
                ]
                item.original_annotations = annotations
                if payload.get("classes"):
                    loaded_classes = [str(value) for value in payload["classes"]]
                    if self._dataset is None:
                        self._annotation_classes = loaded_classes
                    else:
                        for name in loaded_classes:
                            if name not in self._dataset.class_names:
                                self._dataset.class_names.append(name)
            except (OSError, ValueError, TypeError, KeyError):
                logger.warning("Could not load annotation sidecar %s", path)

    def get_recent_projects(self) -> dict[str, Any]:
        paths = [str(path) for path in self._settings.get("recent_projects", [])]
        return {"ok": True, "projects": [path for path in paths if Path(path).is_dir()]}

    def _remember_recent_project(self, path: Path) -> None:
        current = [str(path)]
        for value in self._settings.get("recent_projects", []):
            if str(value) != str(path):
                current.append(str(value))
        self._settings.set("recent_projects", current[:8])

    def export_fixed_dataset(self, target_format: str = "yolo") -> dict[str, Any]:
        """Export a cleaned copy; invalid annotations are omitted safely."""
        return self.export_current_dataset(target_format)

    def close_dataset(self) -> dict[str, Any]:
        """Close a dataset project and return to the normal empty editor."""
        with self._lock:
            self._dataset = None
            self._workspace_kind = "empty"
            self._dataset_operations = []
            self._collection.clear()
            self._clear_history()
            return self._state_payload()

    def validate_current_dataset(self) -> dict[str, Any]:
        with self._lock:
            if self._dataset is None:
                return {"ok": False, "message": "No dataset project is open"}
            items = [item for _, item in self._collection.iter_all()]
            return validate_dataset(self._dataset, items)

    def get_dataset_statistics(self) -> dict[str, Any]:
        with self._lock:
            if self._dataset is None:
                return {"ok": False, "message": "No dataset project is open"}
            items = [item for _, item in self._collection.iter_all()]
            return {"ok": True, **dataset_statistics(self._dataset, items)}

    def split_current_dataset(
        self,
        train_percent: float = 70,
        val_percent: float = 20,
        test_percent: float = 10,
        seed: int = 42,
    ) -> dict[str, Any]:
        with self._lock:
            if self._dataset is None:
                return {"ok": False, "message": "No dataset project is open"}
            values = [float(train_percent), float(val_percent), float(test_percent)]
            if any(value < 0 for value in values) or sum(values) <= 0:
                return {"ok": False, "message": "Split percentages must be non-negative"}
            items = [item for _, item in self._collection.iter_all()]
            counts = assign_splits(items, values[0], values[1], values[2], int(seed))
            self._dataset_operations.append(
                {
                    "operation": "split",
                    "train": values[0],
                    "val": values[1],
                    "test": values[2],
                    "seed": int(seed),
                }
            )
            self._work_dirty = True
            return {"ok": True, "counts": counts, "dataset": self._dataset_summary()}

    def get_augmentation_recipes(self) -> dict[str, Any]:
        return {"ok": True, "recipes": recipe_catalog(), "fields": RECIPE_FIELDS}

    def generate_variants(
        self,
        recipe_id: str,
        copies: int = 1,
        seed: int = 42,
        custom_ranges: dict[str, Any] | None = None,
        annotation_aware: bool = True,
    ) -> dict[str, Any]:
        """Generate deterministic variants, preserving annotations when present."""
        with self._lock:
            if self._collection.is_empty:
                return {"ok": False, "message": "No images are open"}
            source_items = list(self._collection.iter_all())
        if custom_ranges is not None and not custom_ranges:
            return {"ok": False, "message": "Enable at least one recipe transformation"}
        copies = max(1, min(int(copies), 10))
        generated = 0
        self._cancel.clear()
        total = len(source_items) * copies
        for source_index, (_, item) in enumerate(source_items):
            # Do not recursively augment variants from an earlier run.
            if item.is_generated:
                continue
            for copy_index in range(copies):
                if self._cancel.is_set():
                    break
                try:
                    params = (
                        sample_custom_recipe(custom_ranges, int(seed), source_index, copy_index)
                        if custom_ranges is not None
                        else sample_recipe(recipe_id, int(seed), source_index, copy_index)
                    )
                except ValueError as exc:
                    return {"ok": False, "message": str(exc)}
                augment = _as_dataclass(AugmentParams, params)
                # The random pixel-noise operators use NumPy's legacy global
                # generator. Seed it deterministically for reproducible files.
                np.random.seed(_stable_seed(int(seed), source_index, copy_index))
                try:
                    source_image = item.active
                except FileNotFoundError as exc:
                    logger.warning("Skipping unreadable dataset item: %s", exc)
                    continue
                result = run_augment_pipeline(source_image, augment)
                annotations = (
                    augment_annotations(
                        item.active_annotations,
                        augment,
                        source_image.shape[1],
                        source_image.shape[0],
                    )
                    if annotation_aware
                    else [annotation.copy() for annotation in item.active_annotations]
                )
                suffix = item.path.suffix or ".png"
                variant_path = item.path.with_name(
                    f"{item.path.stem}__{recipe_id}_{copy_index + 1}{suffix}"
                )
                variant = ImageItem(
                    path=variant_path,
                    original=result,
                    original_annotations=annotations,
                    dataset_split=item.dataset_split,
                    original_split=item.dataset_split,
                    is_generated=True,
                )
                with self._lock:
                    self._collection.append(variant)
                generated += 1
                self._emit_progress(
                    int(generated / max(total, 1) * 100), variant_path.name, "augment_dataset"
                )
            if self._cancel.is_set():
                break
        if self._dataset is not None:
            self._dataset_operations.append(
                {
                    "operation": "augmentation_recipe",
                    "recipe": recipe_id,
                    "copies": copies,
                    "seed": int(seed),
                    "generated": generated,
                    "ranges": custom_ranges,
                    "annotation_aware": bool(annotation_aware),
                }
            )
        cancelled = self._cancel.is_set()
        if generated:
            self._work_dirty = True
        self._emit_progress(100, "Done", "augment_dataset", cancelled=cancelled)
        self._emit("operation-done", {"operation": "augment_dataset", "cancelled": cancelled})
        with self._lock:
            return {
                **self._state_payload(),
                "ok": True,
                "generated": generated,
                "cancelled": cancelled,
            }

    def generate_dataset_variants(
        self, recipe_id: str, copies: int = 1, seed: int = 42
    ) -> dict[str, Any]:
        """Backward-compatible alias for the unified variant generator."""
        return self.generate_variants(recipe_id, copies, seed)

    def export_current_dataset(self, target_format: str = "yolo") -> dict[str, Any]:
        with self._lock:
            if self._dataset is None:
                return {"ok": False, "message": "No dataset project is open"}
            project = self._dataset
            items = [item for _, item in self._collection.iter_all()]
            validation = validate_dataset(project, items)
        configured = str(self._settings.get("annotation_export_directory", "")).strip()
        directory: str | None
        if configured:
            directory = configured
        elif self._bridge is not None:
            directory = self._bridge.open_folder_dialog()
        else:
            return {"ok": False, "message": "No export directory is configured"}
        if not directory:
            return {"ok": False, "cancelled": True, "message": "Cancelled"}
        try:
            result = export_dataset(
                project,
                items,
                Path(directory),
                target_format,
                validation,
                {"operations": list(self._dataset_operations)},
            )
            self._work_dirty = False
            return {**result, "workspace_exported": True}
        except (OSError, ValueError) as exc:
            return {"ok": False, "message": str(exc)}

    def get_images(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._image_metas()

    def navigate(self, delta: int) -> dict[str, Any]:
        """Move the cursor by *delta* (can be any magnitude; clamped at ends)."""
        with self._lock:
            direction = 1 if delta > 0 else (-1 if delta < 0 else 0)
            for _ in range(abs(delta)):
                if direction > 0:
                    if not self._collection.next():
                        break
                elif direction < 0:
                    if not self._collection.previous():
                        break
                else:
                    break
            self._collection.trim_cache()
            self._clear_auto_preview()
            return self._state_payload()

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return self._state_payload()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def get_preview(self, max_size: int | None = None) -> dict[str, Any]:
        """Base64 data URL of the current display image (downscaled).

        ``max_size`` defaults to the active performance profile's limit, so
        Low profile genuinely sends smaller previews to the UI.
        """
        if max_size is None:
            max_size = self._resolve_preview_max()
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"dataUrl": None, "w": 0, "h": 0}
            try:
                img = downscale(item.active, max_size)
            except FileNotFoundError as exc:
                return {"error": str(exc)}
            h, w = img.shape[:2]
            return {
                "dataUrl": to_data_url(img),
                "w": w,
                "h": h,
                "annotations": self._annotation_payload(item.active_annotations),
                "classes": self._dataset.class_names if self._dataset else [],
            }

    def get_compare(self, max_size: int | None = None) -> dict[str, Any]:
        """Original + processed images for the before/after comparison."""
        if max_size is None:
            max_size = self._resolve_preview_max()
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"original": None, "processed": None, "w": 0, "h": 0}
            orig = downscale(item.source, max_size)
            proc = downscale(item.active, max_size)
            h, w = proc.shape[:2]
            return {
                "original": to_data_url(orig),
                "processed": to_data_url(proc),
                "w": w,
                "h": h,
            }

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def preview(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        """Live preview of *params* against the current active image.

        Runs on a downscaled working copy (sized by the active performance
        mode) for responsiveness and reports the measured latency.
        """
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"error": "No image loaded"}
            t0 = time.perf_counter()
            working = downscale(item.active, self._resolve_preview_max())
            try:
                if kind == "transform":
                    transform_params = self._scaled_transform_params(item, params, working)
                    result = run_transform_pipeline(working, transform_params)
                    annotations = transform_annotations(
                        item.active_annotations,
                        transform_params,
                        working.shape[1],
                        working.shape[0],
                    )
                else:
                    result = self._run(kind, params, working)
                    annotations = self._annotations_after(
                        kind, params, item.active_annotations, working.shape[1], working.shape[0]
                    )
            except (ValueError, FileNotFoundError) as exc:
                return {"error": str(exc)}
            if max(result.shape[:2]) > self._resolve_preview_max():
                result = downscale(result, self._resolve_preview_max())
            latency_ms = (time.perf_counter() - t0) * 1000.0
            h, w = result.shape[:2]
            return {
                "dataUrl": to_data_url(result),
                "w": w,
                "h": h,
                "latency_ms": round(latency_ms),
                "annotations": self._annotation_payload(annotations),
                "classes": self._dataset.class_names if self._dataset else [],
            }

    def apply(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        """Apply *params* at full resolution and push an undo snapshot."""
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"error": "No image loaded"}
            idx = self._collection.current_index
            prev = None if item.modified is None else item.modified.copy()
            prev_annotations = (
                None
                if item.modified_annotations is None
                else [ann.copy() for ann in item.modified_annotations]
            )
            try:
                source = item.active
                source_annotations = [ann.copy() for ann in item.active_annotations]
                result = self._run(kind, params, source)
                annotations = self._annotations_after(
                    kind, params, source_annotations, source.shape[1], source.shape[0]
                )
            except (ValueError, FileNotFoundError) as exc:
                return {"error": str(exc)}
            item.apply(result, annotations)
            self._push_operation(
                kind,
                params,
                [idx],
                {idx: prev},
                {idx: prev_annotations},
            )
            if self._dataset is not None:
                self._dataset_operations.append(
                    {"operation": kind, "target": item.path.name, "params": dict(params)}
                )
            logger.info("Applied %s to %s", kind, item.path.name)
            return self._state_payload()

    def apply_all(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        """Apply the same params to every loaded image, with progress + cancel."""
        with self._lock:
            items = list(self._collection.iter_all())
        self._cancel.clear()
        applied = 0
        total = len(items)
        applied_entries: list[tuple[int, ImageArray | None, list[Annotation] | None]] = []
        for idx, (_, item) in enumerate(items):
            if self._cancel.is_set():
                break
            prev = None if item.modified is None else item.modified.copy()
            prev_annotations = (
                None
                if item.modified_annotations is None
                else [ann.copy() for ann in item.modified_annotations]
            )
            try:
                source = item.active
                source_annotations = [ann.copy() for ann in item.active_annotations]
                result = self._run(kind, params, source)
                annotations = self._annotations_after(
                    kind, params, source_annotations, source.shape[1], source.shape[0]
                )
            except (ValueError, FileNotFoundError) as exc:
                logger.warning("apply_all skipped %s: %s", item.path.name, exc)
                continue
            item.apply(result, annotations)
            applied += 1
            applied_entries.append((idx, prev, prev_annotations))
            self._emit_progress(
                int((idx + 1) / max(total, 1) * 100),
                f"{item.path.name}",
                "apply_all",
            )
        cancelled = self._cancel.is_set()
        self._emit_progress(100, "Done", "apply_all", cancelled=cancelled)
        self._emit("operation-done", {"operation": "apply_all", "cancelled": cancelled})
        with self._lock:
            if applied_entries:
                self._push_operation(
                    kind,
                    params,
                    [i for i, _, _ in applied_entries],
                    {i: previous for i, previous, _ in applied_entries},
                    {i: previous for i, _, previous in applied_entries},
                )
                if self._dataset is not None:
                    self._dataset_operations.append(
                        {"operation": kind, "target": "all", "params": dict(params)}
                    )
            return {**self._state_payload(), "applied": applied, "cancelled": cancelled}

    # ------------------------------------------------------------------
    # History / reset
    # ------------------------------------------------------------------

    def undo(self) -> dict[str, Any]:
        with self._lock:
            self._undo_one()
            return self._state_payload()

    def redo(self) -> dict[str, Any]:
        with self._lock:
            self._redo_one()
            return self._state_payload()

    def jump_to_history(self, position: int) -> dict[str, Any]:
        """Move directly to a visible history state using repeated undo/redo."""
        with self._lock:
            total = len(self._op_history) + len(self._op_redo)
            target = max(0, min(int(position), total))
            while len(self._op_history) > target:
                self._undo_one()
            while len(self._op_history) < target:
                self._redo_one()
            return self._state_payload()

    def _undo_one(self) -> None:
        if not self._op_history:
            return
        operation = self._op_history.pop()
        for index in operation.image_indices:
            item = self._collection.get(index)
            if item is not None:
                # Capture the exact state only while this operation sits on the
                # redo branch. This preserves random effects without doubling
                # every applied history snapshot in memory.
                operation.resulting_states[index] = (
                    None if item.modified is None else item.modified.copy()
                )
                operation.resulting_annotations[index] = (
                    None
                    if item.modified_annotations is None
                    else [annotation.copy() for annotation in item.modified_annotations]
                )
                item.modified = operation.previous_states.get(index)
                previous_annotations = operation.previous_annotations.get(index)
                item.modified_annotations = (
                    None
                    if previous_annotations is None
                    else [annotation.copy() for annotation in previous_annotations]
                )
        self._op_redo.append(operation)
        should_save_annotations = self._settings.get("annotation_autosave", True) or (
            operation.params.get("annotation_save_mode") == "immediate"
        )
        if operation.kind == "annotation" and should_save_annotations:
            for index in operation.image_indices:
                item = self._collection.get(index)
                if item is not None:
                    self._write_annotation_sidecar(item)

    def _redo_one(self) -> None:
        if not self._op_redo:
            return
        operation = self._op_redo.pop()
        for index in operation.image_indices:
            item = self._collection.get(index)
            if item is not None:
                if index in operation.resulting_states:
                    resulting_state = operation.resulting_states[index]
                    item.modified = None if resulting_state is None else resulting_state.copy()
                    resulting_annotations = operation.resulting_annotations.get(index)
                    item.modified_annotations = (
                        None
                        if resulting_annotations is None
                        else [annotation.copy() for annotation in resulting_annotations]
                    )
                else:  # Defensive fallback for legacy/in-memory records.
                    source = item.active
                    annotations = self._annotations_after(
                        operation.kind,
                        operation.params,
                        item.active_annotations,
                        source.shape[1],
                        source.shape[0],
                    )
                    item.apply(self._run(operation.kind, operation.params, source), annotations)
        operation.resulting_states.clear()
        operation.resulting_annotations.clear()
        self._op_history.append(operation)
        should_save_annotations = self._settings.get("annotation_autosave", True) or (
            operation.params.get("annotation_save_mode") == "immediate"
        )
        if operation.kind == "annotation" and should_save_annotations:
            for index in operation.image_indices:
                item = self._collection.get(index)
                if item is not None:
                    self._write_annotation_sidecar(item)

    def reset_current(self) -> dict[str, Any]:
        with self._lock:
            item = self._collection.current
            if item is None:
                return self._state_payload()
            item.reset()
            self._clear_history()
            if self._settings.get("annotation_autosave", True):
                self._write_annotation_sidecar(item)
            return self._state_payload()

    def reset_all(self) -> dict[str, Any]:
        with self._lock:
            self._collection.reset_all()
            self._clear_history()
            if self._settings.get("annotation_autosave", True):
                for _, item in self._collection.iter_all():
                    self._write_annotation_sidecar(item)
            return self._state_payload()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def save_image(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"error": "No UI bridge available"}
        with self._lock:
            item = self._collection.current
            if item is None:
                return {"error": "No image loaded"}
            img = item.active
            suggested = str(item.path.with_name(item.path.stem + "_edited.png"))
        path = self._bridge.save_file_dialog(
            save_as=suggested,
            file_types=(
                "Image files (*.png;*.jpg;*.jpeg;*.bmp;*.tiff)",
                "All files (*.*)",
            ),
        )
        if not path:
            return {"ok": False, "message": "Cancelled"}
        ok, message = self._write_image(img, Path(path))
        workspace_exported = bool(
            ok and self._collection.count == 1 and self._working_mode in {"transform", "augment"}
        )
        if workspace_exported:
            self._work_dirty = False
        return {
            "ok": ok,
            "message": message,
            "workspace_exported": workspace_exported,
        }

    def save_all(self, prefix: str = "", postfix: str = "") -> dict[str, Any]:
        """Save every modified image with *prefix*/*postfix* filename options."""
        if self._bridge is None:
            return {"error": "No UI bridge available"}
        with self._lock:
            modified = [(i, item) for i, item in self._collection.iter_all() if item.is_modified]
            if not modified:
                return {"ok": False, "message": "No modified images to save"}
        directory = self._bridge.open_folder_dialog()
        if not directory:
            return {"ok": False, "message": "Cancelled"}
        out_dir = Path(directory)
        self._cancel.clear()
        saved = 0
        total = len(modified)
        for idx, (_, item) in enumerate(modified):
            if self._cancel.is_set():
                break
            name = f"{prefix}{item.path.stem}{postfix}{item.path.suffix}"
            try:
                ok, message = self._write_image(item.active, out_dir / name)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("save_all failed for %s: %s", name, exc)
                ok = False
            if ok:
                saved += 1
            self._emit_progress(int((idx + 1) / max(total, 1) * 100), name, "save_all")
        cancelled = self._cancel.is_set()
        workspace_exported = bool(
            not cancelled and saved == total and self._working_mode in {"transform", "augment"}
        )
        if workspace_exported:
            self._work_dirty = False
        self._emit_progress(100, "Done", "save_all", cancelled=cancelled)
        self._emit("operation-done", {"operation": "save_all", "cancelled": cancelled})
        return {
            "ok": True,
            "saved": saved,
            "total": total,
            "cancelled": cancelled,
            "workspace_exported": workspace_exported,
            "message": f"Saved {saved} of {total} images",
        }

    def cancel(self) -> None:
        """Request cancellation of the current batch operation."""
        self._cancel.set()

    def save_session(self, prefix: str = "", postfix: str = "") -> dict[str, Any]:
        """Save **every** image in the session, edited or untouched alike.

        Unlike :meth:`save_all` (modified-only), this writes one file per
        loaded image using its current active state — the original pixels for
        unedited images.  The user picks the destination folder; ``prefix`` and
        ``postfix`` are filename options so originals can be preserved.
        """
        if self._bridge is None:
            return {"error": "No UI bridge available"}
        with self._lock:
            items = list(self._collection.iter_all())
            if not items:
                return {"ok": False, "message": "No images loaded"}
        directory = self._bridge.open_folder_dialog()
        if not directory:
            return {"ok": False, "message": "Cancelled"}
        out_dir = Path(directory)
        self._cancel.clear()
        saved = 0
        total = len(items)
        for idx, (_, item) in enumerate(items):
            if self._cancel.is_set():
                break
            name = f"{prefix}{item.path.stem}{postfix}{item.path.suffix}"
            try:
                ok, _ = self._write_image(item.active, out_dir / name)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("save_session failed for %s: %s", name, exc)
                ok = False
            if ok:
                saved += 1
            self._emit_progress(int((idx + 1) / max(total, 1) * 100), name, "save_session")
        cancelled = self._cancel.is_set()
        workspace_exported = bool(
            not cancelled and saved == total and self._working_mode in {"transform", "augment"}
        )
        if workspace_exported:
            self._work_dirty = False
        self._emit_progress(100, "Done", "save_session", cancelled=cancelled)
        self._emit("operation-done", {"operation": "save_session", "cancelled": cancelled})
        return {
            "ok": True,
            "saved": saved,
            "total": total,
            "cancelled": cancelled,
            "workspace_exported": workspace_exported,
            "message": f"Saved {saved} of {total} images",
        }

    # ------------------------------------------------------------------
    # Window control (delegated to the UI bridge)
    # ------------------------------------------------------------------

    def move_window(self, x: int, y: int) -> None:
        if self._bridge is not None:
            self._bridge.move_window(int(x), int(y))

    def minimize_window(self) -> None:
        if self._bridge is not None:
            self._bridge.minimize_window()

    def toggle_maximize(self) -> None:
        if self._bridge is not None:
            self._bridge.toggle_maximize()

    def close_window(self) -> None:
        if self._bridge is not None:
            self._bridge.close_window()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _project_manifest(
        self, archive: zipfile.ZipFile, ui_state: dict[str, Any]
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for index, item in self._collection.iter_all():
            original_name = f"media/{index:06d}/original.png"
            self._write_project_image(archive, original_name, item.source)
            modified_name: str | None = None
            if item.modified is not None:
                modified_name = f"media/{index:06d}/modified.png"
                self._write_project_image(archive, modified_name, item.modified)
            items.append(
                {
                    "path": str(item.path),
                    "original_image": original_name,
                    "modified_image": modified_name,
                    "original_annotations": [
                        annotation.as_dict() for annotation in item.original_annotations
                    ],
                    "modified_annotations": (
                        None
                        if item.modified_annotations is None
                        else [annotation.as_dict() for annotation in item.modified_annotations]
                    ),
                    "annotation_path": (
                        str(item.annotation_path) if item.annotation_path is not None else ""
                    ),
                    "dataset_split": item.dataset_split,
                    "original_split": item.original_split,
                    "source_width": item.source_width,
                    "source_height": item.source_height,
                    "is_generated": item.is_generated,
                }
            )

        dataset: dict[str, Any] | None = None
        if self._dataset is not None:
            dataset = {
                "root": str(self._dataset.root),
                "name": self._dataset.name,
                "source_format": self._dataset.source_format,
                "class_names": list(self._dataset.class_names),
                "config_path": (
                    str(self._dataset.config_path) if self._dataset.config_path is not None else ""
                ),
                "imported_issues": deepcopy(self._dataset.imported_issues),
                "task_type": self._dataset.task_type,
            }

        auto_preview: dict[str, Any] | None = None
        if self._auto_preview_path is not None and self._auto_preview_candidates:
            preview_index = next(
                (
                    index
                    for index, item in self._collection.iter_all()
                    if item.path.resolve() == self._auto_preview_path
                ),
                -1,
            )
            if preview_index >= 0:
                auto_preview = {
                    "image_index": preview_index,
                    "candidates": deepcopy(self._auto_preview_candidates),
                    "config": deepcopy(self._auto_preview_config),
                }

        ai_proposals: list[dict[str, Any]] = []
        for index, item in self._collection.iter_all():
            candidates = self._ai_proposals.get(str(item.path.resolve()), [])
            if candidates:
                ai_proposals.append({"image_index": index, "candidates": deepcopy(candidates)})

        return {
            "format": "ImageCraft Project",
            "format_version": PROJECT_FORMAT_VERSION,
            "working_mode": self._working_mode,
            "workspace_kind": self._workspace_kind,
            "current_index": self._collection.current_index,
            "annotation_classes": list(self._annotation_classes),
            "items": items,
            "dataset": dataset,
            "dataset_operations": deepcopy(self._dataset_operations),
            "history": [
                self._project_operation(archive, operation, f"history/{index:04d}")
                for index, operation in enumerate(self._op_history)
            ],
            "redo": [
                self._project_operation(archive, operation, f"redo/{index:04d}")
                for index, operation in enumerate(self._op_redo)
            ],
            "history_base_truncated": self._history_base_truncated,
            "auto_preview": auto_preview,
            "local_ai": {
                "task": self._ai_task,
                "model_id": self._ai_model,
                "config": deepcopy(self._ai_config),
                "proposals": ai_proposals,
            },
            "ui_state": ui_state,
            "practice_label": self._practice_label,
        }

    def _project_operation(
        self, archive: zipfile.ZipFile, operation: OperationRecord, prefix: str
    ) -> dict[str, Any]:
        def image_map(values: dict[int, ImageArray | None], map_name: str) -> dict[str, str | None]:
            encoded: dict[str, str | None] = {}
            for image_index, image in values.items():
                if image is None:
                    encoded[str(image_index)] = None
                    continue
                name = f"{prefix}/{map_name}/{image_index}.png"
                self._write_project_image(archive, name, image)
                encoded[str(image_index)] = name
            return encoded

        def annotation_map(
            values: dict[int, list[Annotation] | None],
        ) -> dict[str, list[dict[str, Any]] | None]:
            return {
                str(image_index): (
                    None
                    if annotations is None
                    else [annotation.as_dict() for annotation in annotations]
                )
                for image_index, annotations in values.items()
            }

        return {
            "kind": operation.kind,
            "params": _json_safe(operation.params),
            "target": operation.target,
            "image_indices": list(operation.image_indices),
            "previous_states": image_map(operation.previous_states, "previous"),
            "previous_annotations": annotation_map(operation.previous_annotations),
            "resulting_states": image_map(operation.resulting_states, "resulting"),
            "resulting_annotations": annotation_map(operation.resulting_annotations),
            "changes": deepcopy(operation.changes),
        }

    def _restore_project(
        self, archive: zipfile.ZipFile, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        rows = manifest.get("items")
        if not isinstance(rows, list) or not rows:
            raise ValueError("The project contains no images")
        items: list[ImageItem] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid image entry in project")
            original = self._read_project_image(archive, str(row["original_image"]))
            modified_ref = row.get("modified_image")
            modified = (
                self._read_project_image(archive, str(modified_ref)) if modified_ref else None
            )
            annotation_path = str(row.get("annotation_path", "")).strip()
            item = ImageItem(
                path=Path(str(row.get("path", "restored-image.png"))),
                original=original,
                original_annotations=self._project_annotations(row.get("original_annotations", [])),
                annotation_path=Path(annotation_path) if annotation_path else None,
                dataset_split=str(row.get("dataset_split", "unsplit")),
                original_split=str(row.get("original_split", "unsplit")),
                source_width=int(row.get("source_width") or original.shape[1]),
                source_height=int(row.get("source_height") or original.shape[0]),
                is_generated=bool(row.get("is_generated", False)),
            )
            item.modified = modified
            raw_modified_annotations = row.get("modified_annotations")
            item.modified_annotations = (
                None
                if raw_modified_annotations is None
                else self._project_annotations(raw_modified_annotations)
            )
            items.append(item)

        dataset_payload = manifest.get("dataset")
        dataset: DatasetProject | None = None
        if isinstance(dataset_payload, dict):
            config_value = str(dataset_payload.get("config_path", "")).strip()
            records = [
                DatasetRecord(
                    image_path=item.path,
                    annotation_path=item.annotation_path,
                    split=item.dataset_split,
                    annotations=[annotation.copy() for annotation in item.original_annotations],
                    width=item.source_width,
                    height=item.source_height,
                )
                for item in items
            ]
            dataset = DatasetProject(
                root=Path(str(dataset_payload.get("root", "."))),
                name=str(dataset_payload.get("name", "Restored project")),
                source_format=str(dataset_payload.get("source_format", "imagecraft")),
                class_names=[str(name) for name in dataset_payload.get("class_names", [])],
                records=records,
                config_path=Path(config_value) if config_value else None,
                imported_issues=list(dataset_payload.get("imported_issues", [])),
                task_type=str(dataset_payload.get("task_type", "detection")),
            )

        history = [
            self._restore_project_operation(archive, row)
            for row in manifest.get("history", [])
            if isinstance(row, dict)
        ]
        redo = [
            self._restore_project_operation(archive, row)
            for row in manifest.get("redo", [])
            if isinstance(row, dict)
        ]
        return {"items": items, "dataset": dataset, "history": history, "redo": redo}

    def _restore_project_operation(
        self, archive: zipfile.ZipFile, row: dict[str, Any]
    ) -> OperationRecord:
        def image_map(values: Any) -> dict[int, ImageArray | None]:
            if not isinstance(values, dict):
                return {}
            return {
                int(image_index): (
                    None if image_ref is None else self._read_project_image(archive, str(image_ref))
                )
                for image_index, image_ref in values.items()
            }

        def annotation_map(values: Any) -> dict[int, list[Annotation] | None]:
            if not isinstance(values, dict):
                return {}
            return {
                int(image_index): (
                    None if annotations is None else self._project_annotations(annotations)
                )
                for image_index, annotations in values.items()
            }

        return OperationRecord(
            kind=str(row.get("kind", "transform")),
            params=dict(row.get("params", {})),
            target=str(row.get("target", "current")),
            image_indices=[int(index) for index in row.get("image_indices", [])],
            previous_states=image_map(row.get("previous_states")),
            previous_annotations=annotation_map(row.get("previous_annotations")),
            resulting_states=image_map(row.get("resulting_states")),
            resulting_annotations=annotation_map(row.get("resulting_annotations")),
            changes=[dict(change) for change in row.get("changes", [])],
        )

    @staticmethod
    def _write_project_image(archive: zipfile.ZipFile, name: str, image: ImageArray) -> None:
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(".png", bgr)
        if not ok:
            raise ValueError(f"Could not encode project image {name}")
        archive.writestr(name, encoded.tobytes())

    @staticmethod
    def _read_project_image(archive: zipfile.ZipFile, name: str) -> ImageArray:
        encoded = np.frombuffer(archive.read(name), dtype=np.uint8)
        bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"Could not decode project image {name}")
        return np.asarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), dtype=np.uint8)

    @staticmethod
    def _project_annotations(raw: Any) -> list[Annotation]:
        if not isinstance(raw, list):
            return []
        annotations: list[Annotation] = []
        for value in raw:
            if not isinstance(value, dict):
                continue
            polygon_raw = value.get("polygon")
            polygon = (
                [(float(point[0]), float(point[1])) for point in polygon_raw]
                if isinstance(polygon_raw, list)
                else None
            )
            mask = value.get("mask_rle")
            keypoints = value.get("keypoints")
            metadata = value.get("metadata")
            annotations.append(
                Annotation(
                    class_id=int(value.get("class_id", 0)),
                    x_center=float(value.get("x", 0.5)),
                    y_center=float(value.get("y", 0.5)),
                    width=float(value.get("w", 1.0)),
                    height=float(value.get("h", 1.0)),
                    label=str(value.get("label", "")),
                    polygon=polygon,
                    annotation_type=str(value.get("type", "bbox")),
                    mask_rle=deepcopy(mask) if isinstance(mask, dict) else None,
                    keypoints=deepcopy(keypoints) if isinstance(keypoints, list) else None,
                    pose_schema=str(value.get("pose_schema", "")),
                    pose_workflow=str(value.get("pose_workflow", "")),
                    pose_has_bbox=bool(value.get("pose_has_bbox", False)),
                    metadata=deepcopy(metadata) if isinstance(metadata, dict) else {},
                )
            )
        return annotations

    def _load_single(self, path: Path) -> dict[str, Any]:
        try:
            self._collection.load_single(path)
        except FileNotFoundError as exc:
            return {"ok": False, "message": str(exc)}
        self._dataset = None
        self._load_annotation_sidecars()
        self._workspace_kind = "single"
        self._dataset_operations = []
        self._clear_history()
        self._project_path = None
        self._project_ui_state = {}
        self._practice_label = ""
        self._work_dirty = False
        return self._state_payload()

    def _load_folder(self, directory: Path) -> dict[str, Any]:
        self._cancel.clear()
        self._collection.load_folder(directory, progress_callback=self._folder_progress)
        if self._collection.is_empty:
            return {"ok": False, "message": "No supported images found"}
        self._dataset = None
        self._load_annotation_sidecars()
        self._workspace_kind = "image_collection"
        self._dataset_operations = []
        self._clear_history()
        self._project_path = None
        self._project_ui_state = {}
        self._practice_label = ""
        self._work_dirty = False
        return self._state_payload()

    def _folder_progress(self, done: int, total: int, name: str) -> bool:
        self._emit_progress(int(done / max(total, 1) * 100), name, "open_folder")
        return not self._cancel.is_set()

    def _preview_transform(
        self, item: Any, params: dict[str, Any], working: ImageArray
    ) -> ImageArray:
        """Build a TransformParams for the preview working copy.

        Frontend params are in *full-resolution* coordinates while the working
        copy is downscaled.  We start from image-aware identity defaults, merge
        caller-supplied values, then scale pixel-coordinate fields by the
        downscale factor so the preview is correct for any image size.
        """
        tp = self._scaled_transform_params(item, params, working)
        return run_transform_pipeline(working, tp)

    def _scaled_transform_params(
        self, item: Any, params: dict[str, Any], working: ImageArray
    ) -> TransformParams:
        """Scale full-resolution transform coordinates to a preview copy."""
        # Reference the ACTIVE image, not the on-disk original.  ``working`` is
        # downscaled from ``item.active``, so the scale factor has to be derived
        # from the same source.  Using ``item.width/height`` (original metadata)
        # made every preview after the first crop scale by the wrong ratio,
        # which is why the free-crop overlay rendered an unrelated region.
        oh, ow = item.active.shape[:2]
        wh, ww = working.shape[:2]
        kx = ww / max(1, ow)
        ky = wh / max(1, oh)

        # Image-aware identity defaults.
        base = {
            "tl_x": 0,
            "tl_y": 0,
            "tr_x": ow,
            "tr_y": 0,
            "br_x": ow,
            "br_y": oh,
            "bl_x": 0,
            "bl_y": oh,
            "translate_x": 0,
            "translate_y": 0,
            "rotation": 0,
            "scale": 100,
            "crop_top": 0,
            "crop_bottom": 0,
            "crop_left": 0,
            "crop_right": 0,
            "crop_x": -1,
            "crop_y": -1,
            "crop_w": -1,
            "crop_h": -1,
        }
        merged = {**base, **{key: val for key, val in params.items() if val is not None}}

        # Fields whose pixel values must be scaled to the working-copy size,
        # split by axis so a non-square rounding in ``downscale`` cannot drift.
        x_fields = {
            "tl_x",
            "tr_x",
            "br_x",
            "bl_x",
            "translate_x",
            "crop_left",
            "crop_right",
            "crop_x",
            "crop_w",
        }
        y_fields = {
            "tl_y",
            "tr_y",
            "br_y",
            "bl_y",
            "translate_y",
            "crop_top",
            "crop_bottom",
            "crop_y",
            "crop_h",
        }
        # Sentinel values (-1 == "no free-crop rect") must survive scaling.
        passthrough = {-1}

        defaults = TransformParams()
        scaled: dict[str, Any] = {}
        for model_field in dataclasses.fields(TransformParams):
            name = model_field.name
            value = merged.get(name, getattr(defaults, name))
            if name in x_fields or name in y_fields:
                if value in passthrough:
                    scaled[name] = int(value)
                else:
                    factor = kx if name in x_fields else ky
                    scaled[name] = int(round(value * factor))
            else:
                scaled[name] = value

        return TransformParams(**scaled)

    def _run(self, kind: str, params: dict[str, Any], img: ImageArray) -> ImageArray:
        """Dispatch a pipeline kind to the matching CV function."""
        if kind == "transform":
            tp = _as_dataclass(TransformParams, params)
            return run_transform_pipeline(img, tp)
        if kind == "augment":
            ap = _as_dataclass(AugmentParams, params)
            return run_augment_pipeline(img, ap)
        if kind == "resize":
            width = int(params.get("width", 0))
            height = int(params.get("height", 0))
            return resize_image(img, width, height)
        raise ValueError(f"Unknown pipeline kind: {kind}")

    def _annotations_after(
        self,
        kind: str,
        params: dict[str, Any],
        annotations: Iterable[Annotation],
        width: int,
        height: int,
    ) -> list[Annotation]:
        if kind in {"transform", "augment"} and params.get("annotation_aware", True) is False:
            return [annotation.copy() for annotation in annotations]
        if kind == "transform":
            return transform_annotations(
                annotations, _as_dataclass(TransformParams, params), width, height
            )
        if kind == "augment":
            return augment_annotations(
                annotations, _as_dataclass(AugmentParams, params), width, height
            )
        if kind == "resize":
            return resize_annotations(
                annotations,
                int(params.get("width", 0)),
                int(params.get("height", 0)),
            )
        raise ValueError(f"Unknown pipeline kind: {kind}")

    def _state_payload(self) -> dict[str, Any]:
        item = self._collection.current
        workspace: dict[str, Any] = {"kind": self._workspace_kind}
        if self._practice_label:
            workspace["practice"] = self._practice_label
        return {
            "images": self._image_metas(),
            "current_index": self._collection.current_index,
            "count": self._collection.count,
            "current_path": item.path.name if item else None,
            "defaults": self._defaults_for_current(),
            "history": {
                "can_undo": bool(self._op_history),
                "can_redo": bool(self._op_redo),
            },
            "history_timeline": self._history_timeline(),
            "dataset": self._dataset_summary(),
            "workspace": workspace,
            "annotation_editor": self._annotation_editor_payload(),
            "working_mode": self._working_mode,
            "has_unsaved_work": self._work_dirty,
            "project": {
                "path": str(self._project_path) if self._project_path is not None else None,
                "name": self._project_path.name if self._project_path is not None else None,
                "ui_state": deepcopy(self._project_ui_state),
            },
            "auto_annotate_preview": {
                "candidates": deepcopy(self._auto_preview_candidates),
                "config": deepcopy(self._auto_preview_config),
            },
            "local_ai": {
                "task": self._ai_task,
                "model_id": self._ai_model,
                "config": deepcopy(self._ai_config),
                "proposals": self._current_ai_proposals(),
                "proposal_images": sum(bool(values) for values in self._ai_proposals.values()),
                "job": self._feature_job_snapshot(),
            },
        }

    def _image_metas(self) -> list[dict[str, Any]]:
        metas = []
        for _, item in self._collection.iter_all():
            metas.append(
                {
                    "path": str(item.path),
                    "name": item.path.name,
                    # ``w``/``h`` describe the image currently on canvas.  The
                    # free-crop overlay maps its rectangle against these, so they
                    # must track ``active`` rather than the on-disk original.
                    "w": item.width,
                    "h": item.height,
                    "orig_w": item.source_width,
                    "orig_h": item.source_height,
                    "modified": item.is_modified,
                    "annotations": len(item.active_annotations),
                    "split": item.dataset_split,
                    "generated": item.is_generated,
                }
            )
        return metas

    def _dataset_summary(self) -> dict[str, Any]:
        if self._dataset is None:
            return {"active": False}
        summary = self._dataset.as_summary()
        split_counts: dict[str, int] = {}
        generated = 0
        for _, item in self._collection.iter_all():
            split_counts[item.dataset_split] = split_counts.get(item.dataset_split, 0) + 1
            generated += int(item.is_generated)
        summary.update(
            {
                "image_count": self._collection.count,
                "splits": split_counts,
                "generated": generated,
            }
        )
        return summary

    @staticmethod
    def _annotation_payload(annotations: Iterable[Annotation]) -> list[dict[str, Any]]:
        result = []
        for index, annotation in enumerate(annotations):
            row = annotation.as_dict()
            row["id"] = index
            result.append(row)
        return result

    def _defaults_for_current(self) -> dict[str, Any]:
        item = self._collection.current
        if item is None:
            return {"transform": _as_dict(TransformParams()), "augment": _as_dict(AugmentParams())}
        # Derive from the ACTIVE image.  Using the original dimensions left the
        # perspective corners describing a rectangle larger than the current
        # image after any crop, so the next preview warped the frame out to
        # stale bounds and mirrored it into the margin.
        h, w = item.height, item.width
        # crop defaults are all 0 (no trimming); the free-crop rect is unset
        tp = TransformParams(
            tr_x=w,
            tr_y=0,
            br_x=w,
            br_y=h,
            bl_x=0,
            bl_y=h,
        )
        return {"transform": _as_dict(tp), "augment": _as_dict(AugmentParams())}

    # ------------------------------------------------------------------
    # Performance profiles
    # ------------------------------------------------------------------

    def _normalize_mode(self, mode: str) -> str:
        """Normalize legacy/unknown mode names to a supported value."""
        if mode == "low":
            return "low"
        return "medium"

    def _apply_performance_mode(self) -> None:
        """Configure OpenCL and thread count based on the current performance mode."""
        mode = self._normalize_mode(self._settings.get("performance_mode", "medium"))
        try:
            if mode == "low":
                # CPU only, single-threaded, small previews.
                cv2.ocl.setUseOpenCL(False)
                cv2.setNumThreads(1)
            else:
                # GPU (OpenCL) when available and OpenCV's full thread pool.
                # NB: setNumThreads(0) *disables* threading; -1 restores the
                # system default (all logical cores).
                cv2.ocl.setUseOpenCL(bool(cv2.ocl.haveOpenCL()))
                cv2.setNumThreads(-1)
        except Exception:  # pragma: no cover - OpenCL API absent on some builds
            cv2.setNumThreads(-1)

    def _resolve_preview_max(self) -> int:
        mode = self._normalize_mode(str(self._settings.get("performance_mode", "medium")))
        return PERFORMANCE_PREVIEW_SIZES.get(mode, MAX_PREVIEW_SIDE)

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._bridge is None:
            return
        code = (
            "window.dispatchEvent(new CustomEvent("
            f"'backend:{event}', {{detail: {json.dumps(payload)}}}))"
        )
        try:
            self._bridge.evaluate_js(code)
        except Exception:  # pragma: no cover - defensive
            logger.warning("Failed to emit backend:%s event", event)

    def _emit_progress(
        self, percent: int, message: str, operation: str, cancelled: bool = False
    ) -> None:
        self._emit(
            "progress",
            {
                "operation": operation,
                "percent": min(100, max(0, int(percent))),
                "message": message,
                "cancelled": cancelled,
            },
        )

    @staticmethod
    def _write_image(img: ImageArray, path: Path) -> tuple[bool, str]:
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        ok = cv2.imwrite(str(path), bgr)
        return (True, f"Saved to {path.name}") if ok else (False, f"Failed to save {path.name}")


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    """Recursively convert NumPy/scalar values to portable JSON values."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def _parse_annotation_class_file(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".txt":
        raw_names: Any = [line.strip() for line in text.splitlines() if line.strip()]
    elif suffix == ".json":
        raw_names = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        raw_names = yaml.safe_load(text)
    else:
        raise ValueError("Choose a .txt, .yaml, .yml, or .json class file")

    if isinstance(raw_names, dict):
        if isinstance(raw_names.get("categories"), list):
            categories = [
                row
                for row in raw_names["categories"]
                if isinstance(row, dict) and str(row.get("name", "")).strip()
            ]
            categories.sort(key=lambda row: int(row.get("id", 0)))
            raw_names = [row["name"] for row in categories]
        else:
            raw_names = raw_names.get("names", raw_names.get("classes", []))
    if isinstance(raw_names, dict):

        def sort_key(value: Any) -> tuple[int, str]:
            try:
                return (0, f"{int(value):012d}")
            except (TypeError, ValueError):
                return (1, str(value))

        raw_names = [raw_names[key] for key in sorted(raw_names, key=sort_key)]
    if not isinstance(raw_names, list):
        raise ValueError("The file does not contain a class-name list")

    names: list[str] = []
    for value in raw_names:
        name = str(value).strip()
        if name and name not in names:
            names.append(name)
    return names


def _looks_like_labelled_dataset(root: Path) -> bool:
    """Detect explicit annotation structure without treating plain images as YOLO."""
    if any((root / name).is_file() for name in ("data.yaml", "data.yml", "classes.txt")):
        return True
    if (root / "labels").is_dir() or (root / "Annotations").is_dir():
        return True
    annotations = root / "annotations"
    if annotations.is_dir() and any(annotations.glob("*.json")):
        return True
    for split in ("train", "val", "test"):
        split_root = root / split
        if split_root.is_dir() and any(
            child.is_dir()
            and any(
                path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
                for path in child.iterdir()
            )
            for child in split_root.iterdir()
        ):
            return True
    return any(root.rglob("*.xml"))


def _cpu_name() -> str:
    """Best-effort human-readable CPU model name (cross-platform)."""
    if platform.system() == "Windows":  # pragma: no cover - platform specific
        try:
            import winreg

            key = winreg.OpenKey(  # type: ignore[attr-defined]
                winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            name, _ = winreg.QueryValueEx(  # type: ignore[attr-defined]
                key, "ProcessorNameString"
            )
            winreg.CloseKey(key)  # type: ignore[attr-defined]
            if name:
                return str(name).strip()
        except Exception:
            pass
    name = platform.processor() or platform.machine()
    return name.strip() or "Unknown CPU"


def _as_dataclass(cls: type[Any], data: dict[str, Any]) -> Any:
    """Build a dataclass instance from a JSON dict, ignoring unknown keys."""
    known = {f.name for f in dataclasses.fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs)


def _as_dict(obj: Any) -> dict[str, Any]:
    """JSON-safe dict of a dataclass instance."""
    return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}


def _stable_seed(seed: int, item_index: int, copy_index: int) -> int:
    """Create a reproducible uint32 seed without Python's salted ``hash``."""
    sequence = np.random.SeedSequence([seed, item_index, copy_index])
    return int(sequence.generate_state(1, dtype=np.uint32)[0])
