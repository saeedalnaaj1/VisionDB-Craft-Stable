"""Application entry point — pywebview window bootstrap.

Creates a frameless native window that hosts the offline web UI
(``imagecraft/ui/index.html``) and wires the :class:`BackendEngine` as the
``js_api`` bridge.  All UI assets are local; the built-in HTTP server serves
them over ``127.0.0.1`` so ES modules and ``fetch`` work without the network.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import webview

from imagecraft.engine import BackendEngine, UIBridge
from imagecraft.logging_config import setup_logging
from imagecraft.settings import Settings
from imagecraft.edition import APP_TITLE

logger = logging.getLogger(__name__)

WINDOW_TITLE = APP_TITLE
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
WINDOW_MIN_SIZE = (900, 600)
UI_DIR = Path(__file__).resolve().parent / "ui"

# Dialog file-type filters (pywebview format: name + glob pattern).
IMAGE_FILE_TYPES = (
    "Image files (*.png;*.jpg;*.jpeg;*.bmp;*.tiff;*.tif)",
    "All files (*.*)",
)


class WindowBridge(UIBridge):
    """Adapter from the engine's ``UIBridge`` protocol to a pywebview window."""

    def __init__(self, window: webview.Window) -> None:
        self._window = window
        self._maximized = False

    # -- Events / JS -------------------------------------------------------

    def evaluate_js(self, code: str) -> None:
        self._window.evaluate_js(code)

    # -- Native dialogs ----------------------------------------------------

    def open_file_dialog(
        self, allow_multiple: bool = False, file_types: tuple[str, ...] = ()
    ) -> list[str] | None:
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=allow_multiple,
            file_types=file_types or IMAGE_FILE_TYPES,
        )
        return list(result) if result else None

    def open_folder_dialog(self) -> str | None:
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return self._first(result)

    def save_file_dialog(
        self, save_as: str, file_types: tuple[str, ...] = ()
    ) -> str | None:
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=save_as,
            file_types=file_types or IMAGE_FILE_TYPES,
        )
        return self._first(result)

    # -- Window control (frameless title bar) ------------------------------

    def move_window(self, x: int, y: int) -> None:
        self._window.move(int(x), int(y))

    def minimize_window(self) -> None:
        self._window.minimize()

    def toggle_maximize(self) -> None:
        # Track the state locally: pywebview's `window.state` is a dict-like
        # with a platform-dependent shape, so we keep our own flag.
        if self._maximized:
            self._window.restore()
            self._maximized = False
        else:
            self._window.maximize()
            self._maximized = True

    def close_window(self) -> None:
        self._window.destroy()

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _first(result: Sequence[str] | None) -> str | None:
        if not result:
            return None
        return str(result[0]) if isinstance(result, (list, tuple)) else str(result)


def main() -> int:
    """Bootstrap the application and enter the pywebview event loop."""
    setup_logging()
    settings = Settings()

    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_TITLE.replace(" ", "."))

    engine = BackendEngine(settings=settings)

    index_url = (UI_DIR / "index.html").as_uri()
    window = webview.create_window(
        WINDOW_TITLE,
        url=index_url,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN_SIZE,
        frameless=True,
        easy_drag=False,          # dragging handled by the JS title bar
        js_api=engine,
        background_color="#16171b",  # match dark theme root background
    )
    if window is None:
        logger.error("Failed to create application window")
        return 1

    # Wire the window into the engine only after it exists.
    engine.attach_bridge(WindowBridge(window))
    logger.info("VisionDB Craft starting — window=%s", window)

    webview.start(
        debug=False,
        http_server=True,         # serve local UI so ES modules/fetch work offline
        private_mode=True,
        icon=str(UI_DIR / "assets" / "visiondb-craft.ico"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
