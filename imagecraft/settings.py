"""Edition-isolated per-user settings; legacy ImageCraft settings are read as defaults.

VISIONDB_CRAFT_CONFIG changes the base directory. The edition name is appended.
Legacy IMAGECRAFT_CONFIG is accepted without overwriting its settings file.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from imagecraft.paths import config_root, legacy_settings

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "theme": "dark",               # "dark" | "light"
    "sidebar_location": "right",   # "left" | "right" | "bottom"
    "sidebar_collapsed": False,
    "sidebar_width": 380,
    "performance_mode": "medium",  # "low" | "medium" (displayed as "High" | "Low" in UI)
    "live_preview": True,
    "export_prefix": "",
    "export_postfix": "",
    "last_directory": "",
    "recent_projects": [],
    "annotation_autosave": True,
    "annotation_one_class": False,
    "annotation_default_class": 0,
    "annotation_classes": ["object"],
    "annotation_save_directory": "",
    "annotation_export_directory": "",
}


class Settings:
    """Simple JSON-backed settings store with immediate persistence."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else self._default_path()
        self._data: dict[str, Any] = dict(DEFAULTS)
        if path is None and not self._path.exists() and legacy_settings().is_file():
            try:
                legacy = json.loads(legacy_settings().read_text(encoding="utf-8"))
                if isinstance(legacy, dict):
                    self._data.update({k: v for k, v in legacy.items() if k in DEFAULTS})
            except (OSError, ValueError):
                pass
        self.load()

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self.save()

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        try:
            if self._path.is_file():
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (OSError, ValueError) as exc:
            logger.warning("Failed to read settings from %s: %s", self._path, exc)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Failed to write settings to %s: %s", self._path, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_path() -> Path:
        return config_root() / "settings.json"
