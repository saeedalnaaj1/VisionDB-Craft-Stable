"""Contract tests: every engine method the web UI calls must exist and return
the shapes ``app.js`` expects. Guards against JS/Python drift."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from imagecraft.engine import BackendEngine
from tests.test_engine import FakeBridge, make_engine


def test_every_static_frontend_api_call_exists() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui" / "js"
    called: set[str] = set()
    for path in ui_root.rglob("*.js"):
        called.update(re.findall(r'call\("([a-z_]+)"', path.read_text(encoding="utf-8")))
    missing = sorted(name for name in called if not hasattr(BackendEngine, name))
    assert not missing, f"Frontend calls missing BackendEngine methods: {missing}"


def test_tutorial_dialog_stays_above_large_spotlights() -> None:
    """Step 8 spotlights the viewer, so the modal must not share its backdrop layer."""
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui"
    tutorial = (ui_root / "js" / "tutorial.js").read_text(encoding="utf-8")
    theme = (ui_root / "css" / "theme.css").read_text(encoding="utf-8")

    assert "document.body.append(backdrop, modal)" in tutorial
    assert "backdrop.append(modal)" not in tutorial
    assert re.search(r"\.tutorial-modal\s*\{[^}]*z-index:\s*1300", theme, re.DOTALL)


def test_annotation_refresh_preserves_zoom_and_pan() -> None:
    """Drawing annotations must not silently replace a custom viewport with 100%."""
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui" / "js"
    app = (ui_root / "app.js").read_text(encoding="utf-8")
    state = (ui_root / "state.js").read_text(encoding="utf-8")

    assert "const resetView = state.viewResetRequested" in app
    assert "preserveView: !resetView" in app
    assert "if (imageSwitched) state.viewResetRequested = true" in state

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for the pure viewport regression check")
    helper = (ui_root / "view_state.js").as_uri()
    script = f"""
      import {{ preservedImageView }} from {helper!r};
      for (const scale of [0.25, 0.5, 2, 4]) {{
        const before = {{
          scale, offsetX: -137.5, offsetY: 82.25, mode: "custom",
          naturalW: 1920, naturalH: 1080,
        }};
        const after = preservedImageView(true, before, {{ naturalW: 1920, naturalH: 1080 }});
        if (!after || after.scale !== scale || after.offsetX !== before.offsetX
            || after.offsetY !== before.offsetY || after.mode !== "custom") {{
          process.exit(1);
        }}
      }}
    """
    subprocess.run([node, "--input-type=module", "--eval", script], check=True)


def test_viewer_drawing_mode_can_be_started_and_stopped() -> None:
    """The W toggle depends on real viewer state, not button text or focus."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for the drawing-state regression check")
    viewer_module = (
        Path(__file__).parents[1] / "imagecraft" / "ui" / "js" / "viewer.js"
    ).as_uri()
    script = f"""
      import {{ Viewer }} from {viewer_module!r};
      const viewer = Object.create(Viewer.prototype);
      viewer.image = {{}};
      viewer.canvas = {{ style: {{}}, releasePointerCapture() {{}} }};
      viewer.annotationSelectionEnabled = true;
      viewer.annotationBrushSize = 24;
      viewer.annotationBrushErase = false;
      viewer.render = () => {{}};
      const transitions = [];
      viewer.onAnnotationModeChange = (active, kind) => transitions.push([active, kind]);
      if (!viewer.beginAnnotation("polygon", () => {{}})) process.exit(1);
      if (!viewer.isAnnotationDrawing() || viewer.annotationMode !== "polygon") process.exit(2);
      viewer.cancelAnnotation();
      if (viewer.isAnnotationDrawing() || viewer.annotationMode !== null) process.exit(3);
      const expected = [[true, "polygon"], [false, "polygon"]];
      if (JSON.stringify(transitions) !== JSON.stringify(expected)) {{
        process.exit(4);
      }}
      let poseGeometry = null;
      if (!viewer.beginAnnotation("pose", geometry => {{ poseGeometry = geometry; }}, {{
        poseSchema: "mediapipe_33", poseWorkflow: "bottom_up", poseHasBox: false,
        keypointNames: ["nose"], skeleton: [],
      }})) process.exit(5);
      viewer._posePoints.push({{
        name: "nose", x: 0.5, y: 0.25, z: 0, visibility: 2, presence: 1,
      }});
      if (!viewer.finishPose() || !poseGeometry || poseGeometry.pose_has_bbox !== false
          || poseGeometry.keypoints.length !== 1) process.exit(6);
    """
    subprocess.run([node, "--input-type=module", "--eval", script], check=True)


def test_w_shortcut_works_before_draw_button_focus() -> None:
    """W must work from selectors/checkboxes but never while typing class names."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for the shortcut-focus regression check")
    helper = (
        Path(__file__).parents[1] / "imagecraft" / "ui" / "js" / "annotation_interactions.js"
    ).as_uri()
    script = f"""
      import {{
        remapHiddenAnnotationIndices, shouldIgnoreAnnotationShortcut,
      }} from {helper!r};
      if (shouldIgnoreAnnotationShortcut({{ tagName: "SELECT" }}, "w")) process.exit(1);
      if (shouldIgnoreAnnotationShortcut({{ tagName: "INPUT", type: "checkbox" }}, "w")) {{
        process.exit(2);
      }}
      if (!shouldIgnoreAnnotationShortcut({{ tagName: "SELECT" }}, "b")) process.exit(3);
      if (!shouldIgnoreAnnotationShortcut({{ tagName: "INPUT", type: "text" }}, "w")) {{
        process.exit(4);
      }}
      if (!shouldIgnoreAnnotationShortcut({{ tagName: "TEXTAREA" }}, "w")) process.exit(5);
      if (shouldIgnoreAnnotationShortcut({{ tagName: "BUTTON" }}, "w")) process.exit(6);
      const remapped = remapHiddenAnnotationIndices(new Set([0, 2, 4]), 1);
      if (JSON.stringify(remapped) !== JSON.stringify([0, 1, 3])) process.exit(7);
    """
    subprocess.run([node, "--input-type=module", "--eval", script], check=True)


def test_startup_chooser_leaves_window_controls_accessible() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    theme = (ui_root / "css" / "theme.css").read_text(encoding="utf-8")
    titlebar = (ui_root / "js" / "titlebar.js").read_text(encoding="utf-8")

    assert re.search(
        r"\.mode-launcher\s*\{[^}]*inset:\s*var\(--titlebar-h\) 0 0;",
        theme,
        re.DOTALL,
    )
    assert re.search(r"\.titlebar\s*\{[^}]*z-index:\s*1700;", theme, re.DOTALL)
    assert 'class="drag-region pywebview-drag-region"' in html
    assert "one move call per mouse event" in titlebar
    for action in ("minimize_window", "toggle_maximize", "close_window"):
        assert f'call("{action}"' in titlebar


def test_sidebar_and_augmentation_safety_controls_are_present() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    sidebar = (ui_root / "js" / "sidebar.js").read_text(encoding="utf-8")
    augment = (ui_root / "js" / "panels" / "augment.js").read_text(encoding="utf-8")

    assert 'id="sidebar-resizer"' in html
    assert '"sidebar_width"' in sidebar
    assert "Keep settings after Apply" in augment
    assert '"imagecraft:augmentation-committed"' in augment
    assert "collectRecipeRanges" in augment
    transform = (ui_root / "js" / "panels" / "transform.js").read_text(encoding="utf-8")
    assert "Keep settings after Apply" in transform
    assert 'imagecraft:transform-committed' in transform


def test_protected_mode_switch_resumes_after_a_complete_export() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui" / "js"
    manager = (ui_root / "mode_manager.js").read_text(encoding="utf-8")
    app = (ui_root / "app.js").read_text(encoding="utf-8")
    export_panel = (ui_root / "panels" / "export.js").read_text(encoding="utf-8")

    assert "pendingModeAfterExport" in manager
    assert 'document.addEventListener("imagecraft:workspace-exported"' in manager
    assert "Export the complete workspace; VisionDB Craft will then open" in manager
    assert "commitPendingEditsForProject" in manager
    assert 'await call("apply", tool, params)' in manager
    assert "if (projectUi.active_tool) setActive(projectUi.active_tool)" in manager
    assert 'new CustomEvent("imagecraft:workspace-exported")' in app
    assert 'new CustomEvent("imagecraft:workspace-exported")' in export_panel


def test_protected_mode_switch_dialog_is_not_hidden_by_launcher() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui"
    manager = (ui_root / "js" / "mode_manager.js").read_text(encoding="utf-8")
    modal = (ui_root / "js" / "modal.js").read_text(encoding="utf-8")
    theme = (ui_root / "css" / "theme.css").read_text(encoding="utf-8")
    protected_flow = manager.split("if (pending && state.current) {", 1)[1].split(
        'if (choice === "export") {', 1
    )[0]

    assert protected_flow.index("if (fromLauncher) hideModeLauncher();") < (
        protected_flow.index("await modeTransitionChoice(mode)")
    )
    assert 'if (choice === "cancel" || !choice)' in protected_flow
    assert "if (fromLauncher) showModeLauncher();" in protected_flow
    assert 'backdrop.classList.add("mode-transition-backdrop")' in modal
    assert re.search(
        r"\.modal-backdrop\.mode-transition-backdrop\s*\{[^}]*z-index:\s*1650;",
        theme,
        re.DOTALL,
    )


def test_history_panel_exposes_state_jumping_and_readable_changes() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui" / "js"
    sidebar = (ui_root / "sidebar.js").read_text(encoding="utf-8")
    history = (ui_root / "panels" / "history.js").read_text(encoding="utf-8")

    assert 'id: "history", label: "History"' in sidebar
    assert 'call("jump_to_history", position)' in history
    assert "change.section" in history
    assert "change.label" in history
    assert "change.value" in history
    assert 'annotation: "Annotation"' in history
    assert 'return "Auto Annotate (BETA)"' in history


def test_annotation_panel_exposes_complete_workflow() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui" / "js"
    sidebar = (ui_root / "sidebar.js").read_text(encoding="utf-8")
    annotation = (ui_root / "panels" / "annotation.js").read_text(encoding="utf-8")
    export_panel = (ui_root / "panels" / "export.js").read_text(encoding="utf-8")
    assert 'id: "annotation", label: "Annotate"' in sidebar
    for feature in (
        "1 class mode", "Draw Box", "Draw Polygon",
        "Show annotations", "delete_annotation",
        "Segmentation — bitmap mask", "Finish Mask", "Erase from mask",
        "Pose Estimation — keypoints", "MediaPipe 33", "YOLO Pose / COCO 17",
        "Bottom-up", "Top-down", "Skip Keypoint", "update_pose_keypoint",
        "import_annotation_classes", "rename_annotation_class",
        "delete_annotation_class",
        "Delete all ${count} annotation(s) using this class",
        "Annotation log", "Show all", "Hide all", "annotation-log-summary",
        "changeAnnotationClass", "deleteAnnotation", "remapHiddenAfterDelete",
        "Select an annotation to move or resize it",
        "transform_annotation_geometry", "drag a landmark dot to refine it",
    ):
        assert feature in annotation
    for moved_feature in (
        "Auto-save working annotation files", "save_annotation_files",
        "choose_annotation_save_directory", "choose_annotation_export_directory",
        "Training dataset export", "YOLO Detection TXT",
        "COCO Instance Segmentation", "Pascal VOC XML", "PNG instance masks",
        "YOLO Pose TXT", "COCO Keypoints JSON", "MediaPipe 33-landmark JSON",
        "active-choice",
    ):
        assert moved_feature in export_panel
    assert 'call("export_annotations", format.value, scope.value, task.value)' in export_panel
    assert "Export annotations" not in annotation
    assert "Save locations" not in annotation
    assert "sidecar" not in annotation.lower()
    assert "LabelImg" not in annotation
    assert 'state.activeTool === "annotation"' in annotation
    assert 'state.activeTool === "auto_annotate"' in annotation
    assert 'shortcutKey === "w"' in annotation
    assert 'shortcutKey === "m"' in annotation
    assert "shouldIgnoreAnnotationShortcut" in annotation
    assert "ensureDrawingSurfaceReady" in annotation
    assert "event.target?.blur?.()" in annotation
    w_handler = annotation.split(
        'if (shortcutKey === "w") {', 1
    )[1].split('if (shortcutKey === "b") {', 1)[0]
    assert "startDrawing()" in w_handler
    assert 'mode.value = "bbox"' not in w_handler
    assert "isAnnotationDrawing()" in w_handler
    assert "stopDrawing()" in w_handler

    viewer = (ui_root / "viewer.js").read_text(encoding="utf-8")
    assert "isAnnotationDrawing()" in viewer
    assert "onAnnotationModeChange" in viewer
    assert "finishMask()" in viewer
    assert "decodeCocoCounts" in viewer
    assert '"bbox", "polygon", "mask", "pose"' in viewer
    assert "onAnnotationSelect" in viewer
    assert "onAnnotationTransform" in viewer
    assert "_annotationAtEvent" in viewer
    assert "_maskContains" in viewer
    assert "_annotationHandleAtEvent" in viewer
    assert "_beginAnnotationTransform" in viewer
    assert "_drawAnnotationHandles" in viewer
    assert "scalePolygonPoints" in viewer
    assert "pointInPolygon" in viewer
    assert "finishPose()" in viewer
    assert "skipPoseKeypoint()" in viewer
    assert "_poseKeypointAtEvent" in viewer
    tutorial = (ui_root / "tutorial.js").read_text(encoding="utf-8").replace("\\n", "\n")
    for lesson in (
        "Paint and edit bitmap masks",
        "Manage and import classes",
        "Export training annotations",
        "Select, move, resize, and delete",
    ):
        assert lesson in tutorial
    assert "eight\n      handles" in tutorial.replace("\\n", "\n")
    assert "does not\n      jump back to 100%" in tutorial
    assert "LabelImg" not in tutorial
    assert "sidecar" not in tutorial.lower()
    from imagecraft.edition import EDITION
    from tools.stage_edition import literal_array
    _, _, steps = literal_array((ui_root / "tutorial.js").read_text(), "STEPS")
    assert len(steps) == (22 if EDITION == "Stable" else 27)
    titles = [step["title"] for step in steps]
    assert titles.index("Choose an annotation task") < titles.index("Analyze and prepare datasets")
    if EDITION == "Plus":
        assert titles.index("Choose an annotation task") < titles.index("Choose an Auto Annotate BETA task")
        assert titles.index("Choose an Auto Annotate BETA task") < titles.index("Analyze and prepare datasets")
    dataset_panel = (ui_root / "panels" / "dataset.js").read_text(encoding="utf-8")
    assert '["mask", "PNG instance masks + JSON index"]' in dataset_panel


def test_keyboard_shortcuts_button_and_categorized_help_are_present() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    app = (ui_root / "js" / "app.js").read_text(encoding="utf-8")
    theme = (ui_root / "css" / "theme.css").read_text(encoding="utf-8")

    assert 'id="tb-shortcuts"' in html
    assert 'byId("tb-shortcuts").addEventListener("click", showKeyboardShortcuts)' in app
    for category in (
        "Files & projects", "Editing & history", "Viewer & navigation",
        "Panels", "Annotation panel", "Auto Annotate BETA panel", "Tutorial & dialogs",
    ):
        from imagecraft.edition import EDITION
        if category == "Auto Annotate BETA panel" and EDITION == "Stable":
            assert category not in app
        else:
            assert category in app
    from tools.stage_edition import literal_array
    _, _, groups = literal_array(app, "groups")
    shortcuts = [item for group in groups for item in group["items"]]
    for item in [
        ["W", "Start/stop the selected box, polygon, bitmap-mask, or pose tool"],
        ["B", "Draw a bounding box"], ["K", "Place pose keypoints"],
        ["Drag shape", "Move the selected annotation"],
        ["Drag handle", "Resize the selected annotation"],
        ["Delete / Backspace", "Delete the selected annotation"],
    ]:
        assert item in shortcuts
    assert ".shortcut-help" in theme


def test_discard_session_is_wired_and_describes_source_safety() -> None:
    ui_root = Path(__file__).parents[1] / "imagecraft" / "ui"
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    app = (ui_root / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="tb-discard-session"' in html
    assert 'id="mode-discard-session"' in html
    assert 'byId("tb-discard-session").addEventListener("click", discardSession)' in app
    assert 'byId("mode-discard-session").addEventListener("click", discardSession)' in app
    assert 'await call("discard_session")' in app
    assert 'byId("tb-discard-session").disabled = state.images.length === 0' in app
    assert "Source files will not be deleted" in app






@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    img = np.zeros((60, 100, 3), dtype=np.uint8)
    img[:, :50] = (200, 40, 40)
    img[:, 50:] = (40, 200, 40)
    path = tmp_path / "img.png"
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return path


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    for i in range(3):
        img = np.full((40, 40, 3), 30 + i * 20, dtype=np.uint8)
        cv2.imwrite(str(tmp_path / f"img{i}.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return tmp_path


def loaded_engine(image_file: Path, bridge: FakeBridge | None = None) -> BackendEngine:
    engine = make_engine(bridge or FakeBridge())
    engine._collection.load_single(image_file)  # load without a dialog
    return engine


def test_config_and_capabilities(image_file):
    engine = make_engine(FakeBridge(open_path=image_file))
    cfg = engine.get_config()
    assert "theme" in cfg and "sidebar_location" in cfg and "performance_mode" in cfg
    caps = engine.get_capabilities()
    assert caps["cv_version"] and caps["cores"] >= 1
    assert isinstance(caps["opencl"], bool)
    # Extended hardware fields consumed by the About dialog.
    assert isinstance(caps["opencl_in_use"], bool)
    assert isinstance(caps["cpu_name"], str) and caps["cpu_name"]
    assert isinstance(caps["gpu"], (dict, type(None)))
    assert caps["backend"] in ("GPU + CPU", "CPU only")

    ok = engine.set_config("performance_mode", "medium")
    assert ok.get("ok") is True
    assert engine.get_config()["performance_mode"] == "medium"


def test_get_app_info(image_file):
    engine = loaded_engine(image_file, FakeBridge())
    info = engine.get_app_info()
    assert set(info) == {"name", "edition", "version", "author"}
    from imagecraft.edition import APP_TITLE
    assert info["name"] == APP_TITLE
    assert info["version"] == "3.6.0"


def test_get_state_shapes(image_file):
    engine = loaded_engine(image_file, FakeBridge())
    s = engine.get_state()
    assert s["count"] == 1
    assert s["current_index"] == 0
    assert s["current_path"] == "img.png"
    assert isinstance(s["images"], list) and "name" in s["images"][0]
    assert set(s["history"]) == {"can_undo", "can_redo"}
    assert set(s["defaults"]) == {"transform", "augment"}
    assert s["dataset"] == {"active": False}


def test_preview_and_compare_shapes(image_file):
    engine = loaded_engine(image_file, FakeBridge())
    p = engine.preview("transform", {"rotation": 10})
    assert {"dataUrl", "w", "h", "latency_ms", "annotations", "classes"} <= set(p)
    c = engine.get_compare()
    assert c["original"].startswith("data:image/") and c["processed"].startswith("data:image/")
    gp = engine.get_preview()
    assert gp["w"] > 0 and gp["dataUrl"].startswith("data:image/")


def test_apply_undo_redo_reset_flow(image_file):
    engine = loaded_engine(image_file, FakeBridge())
    r = engine.apply("augment", {"white_balance": 40})
    assert r["history"] == {"can_undo": True, "can_redo": False}
    assert r["images"][0]["modified"] is True

    u = engine.undo()
    assert u["history"]["can_undo"] is False
    assert u["images"][0]["modified"] is False

    re = engine.redo()
    assert re["history"]["can_redo"] is False
    assert re["images"][0]["modified"] is True

    rc = engine.reset_current()
    assert rc["images"][0]["modified"] is False
    assert rc["history"] == {"can_undo": False, "can_redo": False}


def test_apply_all_reset_all_navigate(folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()
    assert engine.get_state()["count"] == 3

    r = engine.apply_all("augment", {"noise": 30})
    assert r["count"] == 3
    assert all(m["modified"] for m in r["images"])

    # Global undo reverts all images at once.
    u = engine.undo()
    assert all(not m["modified"] for m in u["images"])
    assert u["history"] == {"can_undo": False, "can_redo": True}

    # Redo re-applies to all.
    re = engine.redo()
    assert all(m["modified"] for m in re["images"])

    assert engine.navigate(1)["current_index"] == 1
    assert engine.navigate(-1)["current_index"] == 0

    rr = engine.reset_all()
    assert all(not m["modified"] for m in rr["images"])


def test_save_via_bridge(image_file, tmp_path):
    dest = tmp_path / "out.png"
    bridge = FakeBridge(open_path=image_file, save_path=str(dest))
    engine = loaded_engine(image_file, bridge)
    engine.apply("transform", {"scale": 120})
    res = engine.save_image()
    assert res["ok"] is True
    assert res["workspace_exported"] is True
    assert engine.get_state()["has_unsaved_work"] is False
    assert dest.is_file()


def test_resize_preview_and_apply(image_file):
    engine = loaded_engine(image_file, FakeBridge())
    p = engine.preview("resize", {"width": 50, "height": 40})
    assert {"dataUrl", "w", "h", "latency_ms", "annotations", "classes"} <= set(p)
    assert p["w"] == 50 and p["h"] == 40
    r = engine.apply("resize", {"width": 80, "height": 40})
    assert r["images"][0]["modified"] is True
    assert r["images"][0]["w"] == 80 and r["images"][0]["h"] == 40


def test_large_resize_is_not_silently_downscaled(image_file):
    engine = loaded_engine(image_file, FakeBridge())
    result = engine.apply("resize", {"width": 2200, "height": 1200})
    assert result["images"][0]["w"] == 2200
    assert result["images"][0]["h"] == 1200


def test_save_all_prefix_postfix(folder, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    bridge = FakeBridge(folder_path=str(dest))
    engine = make_engine(bridge)
    engine._collection.load_folder(folder)
    engine.apply_all("augment", {"noise": 10})  # mark every image modified
    res = engine.save_all("pre_", "_post")
    assert res["ok"] is True and res["saved"] == 3
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["pre_img0_post.png", "pre_img1_post.png", "pre_img2_post.png"]


def test_save_session_writes_unmodified_images(folder, tmp_path):
    dest = tmp_path / "session"
    dest.mkdir()
    bridge = FakeBridge(folder_path=str(dest))
    engine = make_engine(bridge)
    engine._collection.load_folder(folder)
    # No edits at all: save_session must still export every original.
    res = engine.save_session("pre_", "_post")
    assert res["ok"] is True and res["saved"] == 3 and res["total"] == 3
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["pre_img0_post.png", "pre_img1_post.png", "pre_img2_post.png"]


def test_window_and_progress_bridge_calls(folder):
    bridge = FakeBridge(folder_path=folder)
    engine = make_engine(bridge)
    engine.open_folder_dialog()
    for fn in (
        lambda: engine.move_window(0, 0),
        engine.minimize_window,
        engine.toggle_maximize,
        engine.close_window,
    ):
        assert fn() is None

    # Cancellation is exposed for the UI's stop button.
    assert callable(engine.cancel)

    # Batch operations push progress events through the bridge.
    bridge.events.clear()
    engine.apply_all("augment", {"noise": 20})
    assert any("backend:progress" in code for code in bridge.events)
    assert any("backend:operation-done" in code for code in bridge.events)
