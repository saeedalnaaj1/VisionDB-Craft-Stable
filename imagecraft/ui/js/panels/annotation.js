// Modern annotation workspace: classification, boxes, segmentation, pose,
// class management, visibility, and autosave.

import { call } from "../api.js";
import {
  remapHiddenAnnotationIndices,
  shouldIgnoreAnnotationShortcut,
} from "../annotation_interactions.js";
import { checkboxRow } from "../controls.js";
import { onTabLeave, registerRefresher } from "../sidebar.js";
import { applyBackendState, state } from "../state.js";

function group(title) {
  const wrap = document.createElement("div");
  wrap.className = "panel";
  const head = document.createElement("div");
  head.className = "panel-title";
  head.textContent = title;
  const body = document.createElement("div");
  body.className = "panel-body";
  head.addEventListener("click", () => wrap.classList.toggle("collapsed"));
  wrap.append(head, body);
  return { wrap, body };
}

function button(label, action, primary = false) {
  const element = document.createElement("button");
  element.textContent = label;
  if (primary) element.className = "primary";
  element.addEventListener("click", action);
  return element;
}

export function buildAnnotationPanel(container, ctx) {
  container.innerHTML = "";
  let hidden = new Set();
  let selected = -1;
  let lastPath = null;

  const create = group("Create annotation");
  const taskStatus = document.createElement("div");
  taskStatus.className = "annotation-task-status";
  const mode = document.createElement("select");
  mode.className = "dataset-wide-input";
  for (const [value, label] of [
    ["bbox", "Object Detection — box"],
    ["polygon", "Segmentation — polygon"],
    ["mask", "Segmentation — bitmap mask"],
    ["pose", "Pose Estimation — keypoints"],
    ["classification", "Classification — whole image"],
  ]) {
    const option = document.createElement("option");
    option.value = value; option.textContent = label; mode.append(option);
  }
  const classSelect = document.createElement("select");
  classSelect.className = "dataset-wide-input";
  const drawBtn = button("Draw Box", startDrawing, true);
  const finishBtn = button("Finish Polygon", () => {
    if (mode.value === "mask") ctx.viewer?.finishMask();
    else if (mode.value === "pose") ctx.viewer?.finishPose();
    else ctx.viewer?.finishPolygon();
  });
  const cancelBtn = button("Cancel Drawing", () => {
    stopDrawing();
  });
  finishBtn.hidden = true; cancelBtn.hidden = true;
  const drawHint = document.createElement("p");
  drawHint.className = "hint";
  drawHint.textContent = "Boxes: drag. Polygons: click edges. Masks: paint strokes. Poses: follow each named landmark prompt.";
  const drawingStatus = document.createElement("div");
  drawingStatus.className = "annotation-drawing-status";
  drawingStatus.hidden = true;
  const brushControls = document.createElement("div");
  brushControls.className = "annotation-brush-controls";
  const brushLabel = document.createElement("label");
  brushLabel.textContent = "Brush size";
  const brushSize = document.createElement("input");
  brushSize.type = "range"; brushSize.min = "2"; brushSize.max = "160"; brushSize.value = "24";
  const brushValue = document.createElement("span");
  brushValue.textContent = "24 px";
  const eraseMask = checkboxRow({
    label: "Erase from mask", checked: false,
    onChange: (erase) => ctx.viewer?.setMaskBrush(Number(brushSize.value), erase),
  });
  brushSize.addEventListener("input", () => {
    brushValue.textContent = `${brushSize.value} px`;
    ctx.viewer?.setMaskBrush(Number(brushSize.value), eraseMask.checked());
  });
  brushControls.append(brushLabel, brushSize, brushValue, eraseMask.el);
  brushControls.hidden = true;
  const poseControls = document.createElement("div");
  poseControls.className = "annotation-pose-controls";
  const poseWorkflowLabel = document.createElement("label");
  poseWorkflowLabel.textContent = "Pose workflow";
  const poseWorkflow = document.createElement("select");
  poseWorkflow.className = "dataset-wide-input";
  poseWorkflow.innerHTML = [
    '<option value="bottom_up">Bottom-up · MediaPipe 33 · keypoints only</option>',
    '<option value="top_down">Top-down · YOLO Pose / COCO 17 · box + keypoints</option>',
  ].join("");
  const poseExplanation = document.createElement("p");
  poseExplanation.className = "hint";
  const poseActions = document.createElement("div");
  poseActions.className = "btn-row";
  const skipPoseBtn = button("Skip Keypoint", () => ctx.viewer?.skipPoseKeypoint());
  const undoPoseBtn = button("Undo Point", () => ctx.viewer?.undoPoseKeypoint());
  skipPoseBtn.disabled = true;
  undoPoseBtn.disabled = true;
  poseActions.append(skipPoseBtn, undoPoseBtn);
  poseControls.append(poseWorkflowLabel, poseWorkflow, poseExplanation, poseActions);
  poseControls.hidden = true;
  poseWorkflow.addEventListener("change", updateDrawLabel);
  mode.addEventListener("change", updateDrawLabel);
  classSelect.addEventListener("change", () => { if (oneClass.checked()) saveConfig(); });
  create.body.append(
    taskStatus, mode, classSelect, brushControls, poseControls, drawBtn,
    drawingStatus, finishBtn, cancelBtn, drawHint,
  );
  container.append(create.wrap);

  const classes = group("Classes");
  const classRow = document.createElement("div");
  classRow.className = "btn-row annotation-class-row";
  const className = document.createElement("input");
  className.placeholder = "New class name";
  const addClassBtn = button("Add Class", async () => {
    try {
      const result = await call("add_annotation_class", className.value);
      if (!result.ok) throw new Error(result.message || "Could not add class");
      className.value = "";
      await reloadState();
    } catch (error) { ctx.toast?.err("Class failed", error.message); }
  });
  className.addEventListener("keydown", (event) => {
    if (event.key === "Enter") addClassBtn.click();
  });
  classRow.append(className, addClassBtn);
  const classTools = document.createElement("div");
  classTools.className = "btn-row";
  const importClassesBtn = button("Import TXT / YAML / COCO…", async () => {
    try {
      const result = await call("import_annotation_classes");
      if (result.cancelled) return;
      if (!result.ok) throw new Error(result.message || "Could not import classes");
      ctx.toast?.ok("Classes imported", `${result.added} new · ${result.imported} read`);
      await reloadState();
    } catch (error) { ctx.toast?.err("Import failed", error.message); }
  });
  classTools.append(importClassesBtn);
  const classList = document.createElement("div");
  classList.className = "annotation-class-list";
  classes.body.append(classRow, classTools, classList);
  container.append(classes.wrap);

  const workflow = group("Workflow");
  const oneClass = checkboxRow({
    label: "1 class mode", checked: false, onChange: saveConfig,
  });
  const showAll = checkboxRow({
    label: "Show annotations", checked: true,
    onChange: (visible) => ctx.viewer?.setAnnotationVisibility(visible),
  });
  const saveHint = document.createElement("p");
  saveHint.className = "hint";
  saveHint.textContent = "Annotation saving, file locations, and training-dataset formats are managed together in Export.";
  workflow.body.append(oneClass.el, showAll.el, saveHint);
  container.append(workflow.wrap);

  const objects = group("Annotation log");
  const objectToolbar = document.createElement("div");
  objectToolbar.className = "annotation-log-toolbar";
  const objectSummary = document.createElement("span");
  objectSummary.className = "annotation-log-summary";
  const objectVisibilityActions = document.createElement("div");
  objectVisibilityActions.className = "annotation-log-visibility-actions";
  const showAllObjectsBtn = button("Show all", () => {
    hidden = new Set();
    ctx.viewer?.setHiddenAnnotations([]);
    render(state);
  });
  const hideAllObjectsBtn = button("Hide all", () => {
    const annotations = state.annotationEditor?.annotations || [];
    hidden = new Set(annotations.map((_, index) => index));
    ctx.viewer?.setHiddenAnnotations([...hidden]);
    render(state);
  });
  objectVisibilityActions.append(showAllObjectsBtn, hideAllObjectsBtn);
  objectToolbar.append(objectSummary, objectVisibilityActions);
  const objectList = document.createElement("div");
  objectList.className = "annotation-list";
  objectList.setAttribute("role", "listbox");
  objectList.setAttribute("aria-label", "Annotations on the current image");
  const objectHint = document.createElement("p");
  objectHint.className = "hint";
  objectHint.textContent = "Select an annotation to move or resize it. For a pose, drag a landmark dot to refine it. Delete removes the selection.";
  const objectActions = document.createElement("div");
  objectActions.className = "btn-row";
  const redrawBtn = button("Redraw Selected", () => {
    const annotation = state.annotationEditor?.annotations?.[selected];
    if (!annotation || annotation.type === "classification") return;
    const selectedIndex = selected;
    if (annotation.type === "pose") {
      poseWorkflow.value = annotation.pose_workflow === "bottom_up" ? "bottom_up" : "top_down";
    }
    const poseConfig = currentPoseConfig(annotation);
    const started = ctx.viewer?.beginAnnotation(annotation.type, async (geometry) => {
      drawingStatus.hidden = true;
      finishBtn.hidden = true; cancelBtn.hidden = true;
      const result = await call("update_annotation_geometry", selectedIndex, geometry);
      if (result.ok) { applyBackendState(result); ctx.afterState?.(); }
    }, {
      brushSize: Number(brushSize.value), erase: eraseMask.checked(),
      baseMaskRle: annotation.mask_rle || null,
      ...poseConfig,
    });
    if (started) {
      mode.value = annotation.type;
      updateDrawLabel();
      drawingStatus.hidden = false;
      drawingStatus.textContent = annotation.type === "mask"
        ? "MASK EDIT ACTIVE — paint or erase, then Finish Mask"
        : annotation.type === "pose" ? "POSE REDRAW ACTIVE — follow the named keypoints"
        : annotation.type === "bbox" ? "DRAWING ACTIVE — drag a replacement box"
          : "DRAWING ACTIVE — click replacement polygon points";
      finishBtn.hidden = !["polygon", "mask", "pose"].includes(annotation.type);
      cancelBtn.hidden = false;
    }
  });
  const deleteSelectedBtn = button("Delete Selected", async () => {
    if (selected < 0) return;
    await deleteAnnotation(selected);
  });
  const reviewSelectedBtn = button("Mark Reviewed", async () => {
    if (selected < 0) return;
    try {
      const result = await call("mark_annotation_reviewed", selected);
      if (!result.ok) throw new Error(result.message || "Could not update review status");
      applyBackendState(result);
      ctx.afterState?.();
      ctx.toast?.ok("Review completed", "The warning marker was removed");
    } catch (error) { ctx.toast?.err("Review failed", error.message); }
  });
  objectActions.append(redrawBtn, reviewSelectedBtn, deleteSelectedBtn);
  objects.body.append(objectToolbar, objectHint, objectActions, objectList);
  container.append(objects.wrap);

  if (ctx.viewer) {
    ctx.viewer.onAnnotationModeChange = (active, kind) => {
      drawingStatus.hidden = !active;
      finishBtn.hidden = !active || !["polygon", "mask", "pose"].includes(kind);
      cancelBtn.hidden = !active;
      if (!active) {
        skipPoseBtn.disabled = true;
        undoPoseBtn.disabled = true;
        return;
      }
      drawingStatus.textContent = kind === "bbox"
        ? "DRAWING ACTIVE — press W again to stop, or drag a box"
        : kind === "mask" ? "MASK PAINT ACTIVE — press W again to stop, or paint then finish"
          : kind === "pose" ? "POSE ACTIVE — follow the landmark prompt"
          : "DRAWING ACTIVE — press W again to stop, or click polygon points";
    };
    ctx.viewer.onPoseProgress = (progress) => {
      if (progress.stage === "bbox") {
        drawingStatus.textContent = "POSE · STEP 1 — drag a box around the object";
      } else {
        drawingStatus.textContent = `POSE · ${progress.index + 1}/${progress.total} — place ${String(progress.name).replaceAll("_", " ")} · Shift+click = occluded`;
      }
      skipPoseBtn.disabled = progress.stage !== "keypoints";
      undoPoseBtn.disabled = progress.index <= 0;
    };
    ctx.viewer.onPoseKeypointTransform = async (annotationIndex, pointIndex, x, y) => {
      try {
        const result = await call(
          "update_pose_keypoint", annotationIndex, pointIndex, x, y, 2,
        );
        if (!result.ok) throw new Error(result.message || "Could not move keypoint");
        applyBackendState(result);
        ctx.viewer?.setAnnotations(result.annotation_editor?.annotations || []);
        ctx.viewer?.selectAnnotation(annotationIndex);
        ctx.afterState?.();
        return true;
      } catch (error) {
        ctx.toast?.err("Keypoint edit failed", error.message);
        return false;
      }
    };
    ctx.viewer.onAnnotationSelect = (index) => {
      if (!["annotation", "auto_annotate"].includes(state.activeTool)) return false;
      selected = Number(index);
      if (state.activeTool === "auto_annotate") {
        ctx.viewer?.selectAutoAnnotation(-1);
        document.dispatchEvent(new CustomEvent("imagecraft:committed-annotation-selected"));
      }
      render(state);
      return true;
    };
    ctx.viewer.onAnnotationTransform = async (index, bounds, action) => {
      if (!["annotation", "auto_annotate"].includes(state.activeTool)) return false;
      try {
        const result = await call("transform_annotation_geometry", index, {
          ...bounds,
          action,
        });
        if (!result.ok) throw new Error(result.message || "Could not update annotation");
        applyBackendState(result);
        ctx.viewer?.setAnnotations(result.annotation_editor?.annotations || []);
        ctx.viewer?.selectAnnotation(index);
        ctx.afterState?.();
        ctx.toast?.ok(
          action === "move" ? "Annotation moved" : "Annotation resized",
          "Undo is available with Ctrl+Z",
        );
        return true;
      } catch (error) {
        ctx.viewer?.cancelAnnotationTransform();
        ctx.toast?.err("Annotation edit failed", error.message);
        return false;
      }
    };
  }

  async function saveConfig() {
    try {
      await call(
        "set_annotation_config", state.annotationEditor?.autosave !== false, oneClass.checked(),
        Number(classSelect.value || 0),
      );
    } catch (error) { ctx.toast?.err("Setting failed", error.message); }
  }

  async function reloadState() {
    const payload = await call("get_state");
    applyBackendState(payload);
    ctx.afterState?.();
  }

  async function commit(kind, geometry = {}) {
    try {
      const result = await call("create_annotation", kind, Number(classSelect.value), geometry);
      if (!result.ok) throw new Error(result.message || "Annotation failed");
      applyBackendState(result);
      ctx.afterState?.();
      ctx.toast?.ok(
        "Annotation added",
        state.annotationEditor?.autosave !== false
          ? "Working annotation file saved automatically"
          : "Use Export to save working annotation files",
      );
    } catch (error) { ctx.toast?.err("Annotation failed", error.message); }
  }

  async function ensureDrawingSurfaceReady() {
    if (ctx.viewer?.hasImage?.()) return true;
    if (!state.current || !ctx.viewer) return false;
    try {
      const preview = await call("get_preview");
      if (!preview?.dataUrl) return false;
      ctx.viewer.setAnnotations(preview.annotations || []);
      await ctx.viewer.setImage(preview.dataUrl, { preserveView: true });
      return ctx.viewer.hasImage();
    } catch (error) {
      ctx.toast?.err("Drawing unavailable", error.message);
      return false;
    }
  }

  function remapHiddenAfterDelete(deletedIndex) {
    hidden = new Set(remapHiddenAnnotationIndices(hidden, deletedIndex));
  }

  async function changeAnnotationClass(index, classId, control) {
    const previousClass = Number(
      state.annotationEditor?.annotations?.[index]?.class_id ?? control.value,
    );
    control.disabled = true;
    try {
      const result = await call("update_annotation", index, classId);
      if (!result.ok) throw new Error(result.message || "Could not change annotation class");
      selected = index;
      applyBackendState(result);
      ctx.viewer?.setAnnotations(result.annotation_editor?.annotations || []);
      ctx.viewer?.selectAnnotation(index);
      ctx.afterState?.();
      ctx.toast?.ok("Class changed", `Annotation ${index + 1} was reassigned`);
    } catch (error) {
      control.value = String(previousClass);
      ctx.toast?.err("Class change failed", error.message);
    } finally {
      control.disabled = false;
    }
  }

  async function deleteAnnotation(index) {
    try {
      const result = await call("delete_annotation", index);
      if (!result.ok) throw new Error(result.message || "Could not delete annotation");
      remapHiddenAfterDelete(index);
      if (selected === index) selected = -1;
      else if (selected > index) selected -= 1;
      applyBackendState(result);
      ctx.viewer?.setAnnotations(result.annotation_editor?.annotations || []);
      ctx.viewer?.setHiddenAnnotations([...hidden]);
      ctx.viewer?.selectAnnotation(selected);
      ctx.afterState?.();
      ctx.toast?.ok("Annotation deleted", "Undo is available with Ctrl+Z");
      return true;
    } catch (error) {
      ctx.toast?.err("Delete failed", error.message);
      return false;
    }
  }

  function currentPoseConfig(annotation = null) {
    const bottomUp = (annotation?.pose_workflow || poseWorkflow.value) === "bottom_up";
    const schemaId = annotation?.pose_schema || (bottomUp ? "mediapipe_33" : "coco_17");
    const schema = state.annotationEditor?.pose_schemas?.[schemaId] || {};
    return {
      poseWorkflow: bottomUp ? "bottom_up" : "top_down",
      poseSchema: schemaId,
      poseHasBox: !bottomUp,
      keypointNames: schema.names || [],
      skeleton: schema.skeleton || [],
    };
  }

  async function startDrawing() {
    if (!state.current) {
      ctx.toast?.err("Drawing unavailable", "Open an image before starting an annotation");
      return;
    }
    if (!classSelect.options.length) {
      try {
        const added = await call("add_annotation_class", "object");
        if (!added.ok) throw new Error(added.message || "Could not create default class");
        const payload = await call("get_state");
        applyBackendState(payload);
        render(state);
      } catch (error) {
        ctx.toast?.err("Class setup failed", error.message);
        return;
      }
    }
    if (!classSelect.options.length) {
      ctx.toast?.err("Class setup failed", "No annotation class is available");
      return;
    }
    const kind = mode.value;
    if (kind === "classification") { commit(kind); return; }
    if (!await ensureDrawingSurfaceReady()) {
      ctx.toast?.err("Drawing unavailable", "The current image is not ready yet");
      return;
    }
    const started = ctx.viewer?.beginAnnotation(kind, (geometry) => {
      drawingStatus.hidden = true;
      finishBtn.hidden = true; cancelBtn.hidden = true;
      commit(kind, geometry);
    }, {
      brushSize: Number(brushSize.value),
      erase: eraseMask.checked(),
      ...(kind === "pose" ? currentPoseConfig() : {}),
    });
    if (started) {
      ctx.toast?.ok(
        "Drawing mode active",
        kind === "bbox" ? "Drag over the object"
          : kind === "mask" ? "Paint the object, then click Finish Mask"
            : kind === "pose" ? "Follow the landmark names; Shift+click marks occluded"
            : "Click polygon edge points",
      );
    } else {
      ctx.toast?.err("Drawing unavailable", "Could not start the selected annotation tool");
    }
  }

  function stopDrawing() {
    ctx.viewer?.cancelAnnotation();
    ctx.viewer?.cancelAnnotationTransform();
    drawingStatus.hidden = true;
    finishBtn.hidden = true;
    cancelBtn.hidden = true;
  }

  function updateDrawLabel() {
    drawBtn.textContent = mode.value === "classification"
      ? "Add Classification"
      : mode.value === "bbox" ? "Draw Box"
        : mode.value === "mask" ? "Paint Mask"
          : mode.value === "pose" ? "Place Pose Keypoints" : "Draw Polygon";
    finishBtn.textContent = mode.value === "mask" ? "Finish Mask"
      : mode.value === "pose" ? "Finish Pose" : "Finish Polygon";
    brushControls.hidden = mode.value !== "mask";
    poseControls.hidden = mode.value !== "pose";
    poseExplanation.textContent = poseWorkflow.value === "bottom_up"
      ? "Place the 33 MediaPipe landmarks directly. No object box is displayed."
      : "Draw the object box first, then place the 17 COCO/YOLO landmarks in order.";
    ctx.viewer?.setMaskBrush(Number(brushSize.value), eraseMask.checked());
  }

  function render(current) {
    ctx.viewer?.setAnnotationSelectionEnabled(
      state.activeTool === "annotation" || state.activeTool === "auto_annotate",
    );
    const editor = current.annotationEditor || {};
    taskStatus.textContent = `Project task: ${String(editor.task_type || "unassigned").replaceAll("_", " ")}`;
    if (current.currentPath !== lastPath) {
      lastPath = current.currentPath;
      hidden = new Set();
      selected = -1;
      ctx.viewer?.selectAnnotation(-1);
    }
    const currentClass = classSelect.value;
    classSelect.innerHTML = "";
    for (const [index, name] of (editor.classes || []).entries()) {
      const option = document.createElement("option");
      option.value = String(index); option.textContent = `${index}: ${name}`;
      classSelect.append(option);
    }
    classList.innerHTML = "";
    for (const [index, name] of (editor.classes || []).entries()) {
      const row = document.createElement("div");
      row.className = "annotation-class-manager-row";
      const id = document.createElement("span");
      id.textContent = String(index);
      const nameInput = document.createElement("input");
      nameInput.value = name;
      nameInput.title = `Rename class ${index}`;
      const count = Number(editor.class_usage?.[index] || 0);
      const usage = document.createElement("small");
      usage.textContent = `${count} used`;
      const reassign = document.createElement("select");
      reassign.className = "annotation-class-reassign";
      reassign.title = "Choose what happens to annotations when this class is deleted";
      for (const [targetId, targetName] of (editor.classes || []).entries()) {
        if (targetId === index) continue;
        const option = document.createElement("option");
        option.value = `move:${targetId}`;
        option.textContent = `Move all ${count} annotation(s) to ${targetId}: ${targetName}`;
        reassign.append(option);
      }
      const deleteAll = document.createElement("option");
      deleteAll.value = "delete";
      deleteAll.textContent = `Delete all ${count} annotation(s) using this class`;
      reassign.append(deleteAll);
      reassign.addEventListener("change", () => {
        reassign.classList.toggle("danger-choice", reassign.value === "delete");
      });
      reassign.hidden = count <= 0;
      const rename = button("Save", async () => {
        try {
          const result = await call("rename_annotation_class", index, nameInput.value);
          if (!result.ok) throw new Error(result.message || "Could not rename class");
          await reloadState();
        } catch (error) { ctx.toast?.err("Rename failed", error.message); }
      });
      nameInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") rename.click();
      });
      const remove = button("Delete", async () => {
        const names = editor.classes || [];
        const deleteUsedAnnotations = count > 0 && reassign.value === "delete";
        const target = count > 0 && reassign.value.startsWith("move:")
          ? Number(reassign.value.slice(5)) : -1;
        if (count > 0 && !deleteUsedAnnotations && (!Number.isInteger(target) || target < 0)) {
          ctx.toast?.err("Class in use", "Choose where to move its annotations, or delete them all");
          return;
        }
        if (count > 0) {
          const message = deleteUsedAnnotations
            ? `Delete “${name}” and permanently remove all ${count} annotation(s) using it?`
            : `Move all ${count} annotation(s) from “${name}” to “${names[target]}”, then delete the class?`;
          if (!window.confirm(message)) return;
        }
        try {
          const result = await call(
            "delete_annotation_class",
            index,
            count > 0 ? target : -1,
            deleteUsedAnnotations,
          );
          if (!result.ok) throw new Error(result.message || "Could not delete class");
          selected = -1;
          ctx.toast?.ok(
            "Class deleted",
            deleteUsedAnnotations
              ? `${result.deleted_annotations || count} annotation(s) removed`
              : `${result.reassigned || 0} annotation(s) moved`,
          );
          await reloadState();
        } catch (error) { ctx.toast?.err("Delete failed", error.message); }
      });
      remove.disabled = (editor.classes || []).length <= 1;
      row.append(id, nameInput, usage, rename, remove, reassign);
      classList.append(row);
    }
    const preferred = editor.one_class ? editor.default_class : Number(currentClass || 0);
    if (preferred < classSelect.options.length) classSelect.value = String(preferred);
    classSelect.disabled = !editor.available || !(editor.classes || []).length;
    mode.disabled = !editor.available;
    drawBtn.disabled = !editor.available || !(editor.classes || []).length;
    oneClass.set(!!editor.one_class);

    objectList.innerHTML = "";
    const annotations = editor.annotations || [];
    if (selected >= annotations.length) {
      selected = -1;
      ctx.viewer?.selectAnnotation(-1);
    }
    const selectedAnnotation = annotations[selected];
    redrawBtn.textContent = selectedAnnotation?.type === "mask"
      ? "Edit Selected Mask"
      : selectedAnnotation?.type === "pose" ? "Redraw Selected Pose" : "Redraw Selected";
    redrawBtn.disabled = !selectedAnnotation || selectedAnnotation.type === "classification";
    deleteSelectedBtn.disabled = !selectedAnnotation;
    const selectedNeedsReview = !!selectedAnnotation?.metadata?.auto_annotate?.needs_review;
    reviewSelectedBtn.hidden = !selectedNeedsReview;
    reviewSelectedBtn.disabled = !selectedNeedsReview;
    const visibleCount = annotations.length - hidden.size;
    objectSummary.textContent = `${annotations.length} annotation${annotations.length === 1 ? "" : "s"} · ${Math.max(0, visibleCount)} visible`;
    showAllObjectsBtn.disabled = !annotations.length || hidden.size === 0;
    hideAllObjectsBtn.disabled = !annotations.length || hidden.size >= annotations.length;
    if (!annotations.length) {
      const empty = document.createElement("p");
      empty.className = "hint"; empty.textContent = "No annotations on this image.";
      objectList.append(empty);
    }
    for (const [index, annotation] of annotations.entries()) {
      const row = document.createElement("div");
      const needsReview = !!annotation?.metadata?.auto_annotate?.needs_review;
      const isHidden = hidden.has(index);
      row.className = `annotation-row${selected === index ? " selected" : ""}${needsReview ? " needs-review" : ""}${isHidden ? " is-hidden" : ""}`;
      row.dataset.annotationIndex = String(index);
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", selected === index ? "true" : "false");
      if (needsReview) row.title = "Auto Annotate BETA marked this result as Needs review";
      const visible = document.createElement("input");
      visible.type = "checkbox"; visible.checked = !isHidden;
      visible.className = "annotation-visibility-toggle";
      visible.title = "Show or hide annotation";
      visible.setAttribute("aria-label", `${isHidden ? "Show" : "Hide"} annotation ${index + 1}`);
      visible.addEventListener("change", () => {
        if (visible.checked) hidden.delete(index); else hidden.add(index);
        ctx.viewer?.setHiddenAnnotations([...hidden]);
        render(state);
      });
      const type = document.createElement("span");
      type.className = "annotation-type";
      const typeName = annotation.type === "classification" ? "CLASS"
        : annotation.type === "polygon" ? "POLY"
          : annotation.type === "mask" ? "MASK"
            : annotation.type === "pose" ? "POSE" : "BOX";
      type.textContent = `#${index + 1} ${needsReview ? "REVIEW" : typeName}`;
      const label = document.createElement("select");
      label.className = "annotation-class-select";
      label.title = `Change class for annotation ${index + 1}`;
      label.setAttribute("aria-label", `Class for annotation ${index + 1}`);
      for (const [classId, name] of (editor.classes || []).entries()) {
        const option = document.createElement("option");
        option.value = String(classId); option.textContent = name; label.append(option);
      }
      label.value = String(annotation.class_id);
      label.addEventListener("change", async () => {
        await changeAnnotationClass(index, Number(label.value), label);
      });
      const remove = button("×", async () => {
        await deleteAnnotation(index);
      });
      remove.className = "annotation-delete-button";
      remove.title = "Delete annotation";
      remove.setAttribute("aria-label", `Delete annotation ${index + 1}`);
      row.addEventListener("click", (event) => {
        if (["INPUT", "SELECT", "BUTTON"].includes(event.target.tagName)) return;
        selected = index; ctx.viewer?.selectAnnotation(index); render(state);
      });
      row.append(visible, type, label, remove);
      objectList.append(row);
    }
    ctx.viewer?.setHiddenAnnotations([...hidden]);
  }

  document.addEventListener("keydown", (event) => {
    const shortcutKey = event.key.toLowerCase();
    if (shouldIgnoreAnnotationShortcut(event.target, shortcutKey)) return;
    const annotationWorkspace = state.activeTool === "annotation";
    const autoWorkspace = state.activeTool === "auto_annotate";
    if (!annotationWorkspace && !autoWorkspace) return;
    // In Auto Annotate BETA, Delete rejects a selected proposal first. The
    // proposal panel owns that transient action; committed annotations still
    // use this normal deletion path.
    if (autoWorkspace && Number(ctx.viewer?.selectedAutoAnnotation) >= 0) return;
    if (!annotationWorkspace && !(event.key === "Delete" || event.key === "Backspace")) return;
    if (shortcutKey === "w") {
      event.preventDefault();
      event.target?.blur?.();
      if (ctx.viewer?.isAnnotationDrawing()) {
        stopDrawing();
        ctx.toast?.ok("Drawing stopped", "Press W to start the selected drawing tool again");
      } else if (["bbox", "polygon", "mask", "pose"].includes(mode.value)) {
        updateDrawLabel(); startDrawing();
      }
    }
    if (shortcutKey === "b") {
      event.preventDefault();
      mode.value = "bbox"; updateDrawLabel(); startDrawing();
    }
    if (shortcutKey === "p") { event.preventDefault(); mode.value = "polygon"; updateDrawLabel(); startDrawing(); }
    if (shortcutKey === "m") { event.preventDefault(); mode.value = "mask"; updateDrawLabel(); startDrawing(); }
    if (shortcutKey === "k") { event.preventDefault(); mode.value = "pose"; updateDrawLabel(); startDrawing(); }
    if (shortcutKey === "c") { event.preventDefault(); mode.value = "classification"; updateDrawLabel(); startDrawing(); }
    if (event.key === "Escape") {
      ctx.viewer?.cancelAnnotation();
      ctx.viewer?.cancelAnnotationTransform();
      drawingStatus.hidden = true; finishBtn.hidden = true; cancelBtn.hidden = true;
    }
    if (event.key === "Enter") {
      if (mode.value === "mask") ctx.viewer?.finishMask();
      else if (mode.value === "pose") ctx.viewer?.finishPose();
      else ctx.viewer?.finishPolygon();
    }
    if ((event.key === "Delete" || event.key === "Backspace") && selected >= 0) {
      event.preventDefault();
      deleteAnnotation(selected);
    }
  });

  registerRefresher("annotation", render);
  onTabLeave("annotation", () => {
    selected = -1;
    ctx.viewer?.setAnnotationSelectionEnabled(false);
    ctx.viewer?.selectAnnotation(-1);
    stopDrawing();
  });
  updateDrawLabel();
}
