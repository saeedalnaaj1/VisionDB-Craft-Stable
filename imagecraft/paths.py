"""Writable user data lives outside both installation folders."""
from __future__ import annotations
import os
from pathlib import Path


def config_root() -> Path:
    from imagecraft.edition import EDITION
    override = os.environ.get("VISIONDB_CRAFT_CONFIG") or os.environ.get("IMAGECRAFT_CONFIG")
    if override:
        return Path(override).expanduser() / EDITION.lower()
    base = Path(os.environ.get("APPDATA", os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))))
    return base / "VisionDB-Craft" / EDITION.lower()


def legacy_settings() -> Path:
    override = os.environ.get("IMAGECRAFT_CONFIG")
    if override:
        return Path(override).expanduser() / "settings.json"
    if os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "ImageCraft" / "settings.json"
    return Path.home() / ".imagecraft" / "settings.json"


def application_root() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def model_root() -> Path:
    # Portable storage: never silently place new downloads in AppData.
    return application_root() / "models"
