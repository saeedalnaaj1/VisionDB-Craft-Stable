// Export panel — filename prefix/postfix options and batch saving.
// "Save Modified" delegates to `save_all(prefix, postfix)`;
// "Save All" delegates to `save_session(prefix, postfix)` (every image).

import { call } from "../api.js";
import { registerRefresher } from "../sidebar.js";
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

export function buildExportPanel(container, ctx) {
  container.innerHTML = "";

  const naming = group("Filename options");
  const body = naming.body;

  const mkTextRow = (label, placeholder) => {
    const row = document.createElement("label");
    row.className = "ctrl";
    const span = document.createElement("span");
    span.className = "lbl";
    span.textContent = label;
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = placeholder;
    row.append(span, input);
    body.append(row);
    return input;
  };
  const prefix = mkTextRow("Prefix", "batch_");
  const postfix = mkTextRow("Postfix", "_v2");
  const example = document.createElement("p");
  example.className = "hint";
  example.style.cssText = "font-size:var(--fs-xs);color:var(--text-3);margin:2px 0 0;";
  body.append(example);
  container.append(naming.wrap);

  const updateExample = () => {
    example.textContent = `e.g. ${prefix.value || "photo"}${postfix.value || ""}.png`;
  };
  prefix.addEventListener("input", updateExample);
  postfix.addEventListener("input", updateExample);
  updateExample();

  const actions = group("Save");
  const btnRow = document.createElement("div");
  btnRow.className = "btn-row";

  const runSave = async (btn, method, okTitle, failTitle, okMsg) => {
    btn.disabled = true;
    try {
      const res = await call(method, prefix.value.trim(), postfix.value.trim());
      if (ctx.toast) {
        if (res.ok) ctx.toast.ok(okTitle, res.message || okMsg);
        else ctx.toast.err(failTitle, res.message || okMsg);
      }
      if (res.ok && res.workspace_exported) {
        document.dispatchEvent(new CustomEvent("imagecraft:workspace-exported"));
      }
    } catch (e) {
      if (ctx.toast) ctx.toast.err(failTitle, e.message);
    } finally {
      btn.disabled = false;
    }
  };

  const saveOneBtn = document.createElement("button");
  saveOneBtn.textContent = "Save Current Image";
  saveOneBtn.addEventListener("click", async () => {
    try {
      const res = await call("save_image");
      if (ctx.toast) {
        if (res.ok) ctx.toast.ok("Saved", res.message || "Image saved");
        else ctx.toast.err("Save", res.message || "No image saved");
      }
      if (res.ok && res.workspace_exported) {
        document.dispatchEvent(new CustomEvent("imagecraft:workspace-exported"));
      }
    } catch (e) {
      if (ctx.toast) ctx.toast.err("Save failed", e.message);
    }
  });

  const saveModifiedBtn = document.createElement("button");
  saveModifiedBtn.textContent = "Save Modified";
  saveModifiedBtn.addEventListener("click", () =>
    runSave(saveModifiedBtn, "save_all", "Saved modified", "Save modified", "No modified images"));

  const saveSessionBtn = document.createElement("button");
  saveSessionBtn.className = "primary";
  saveSessionBtn.textContent = "Save All";
  saveSessionBtn.addEventListener("click", () =>
    runSave(saveSessionBtn, "save_session", "Saved all", "Save all", "No images to save"));

  btnRow.append(saveOneBtn, saveModifiedBtn, saveSessionBtn);
  actions.body.append(btnRow);
  container.append(actions.wrap);

  const annotationFiles = group("Working annotation files");
  const autosaveRow = document.createElement("label");
  autosaveRow.className = "check-row";
  const autosave = document.createElement("input");
  autosave.type = "checkbox";
  const autosaveText = document.createElement("span");
  autosaveText.textContent = "Auto-save working annotation files";
  autosaveRow.append(autosave, autosaveText);
  const annotationPath = document.createElement("div");
  annotationPath.className = "annotation-path";
  const annotationFileActions = document.createElement("div");
  annotationFileActions.className = "btn-row";
  const saveCurrentAnnotations = document.createElement("button");
  saveCurrentAnnotations.textContent = "Save Current";
  const saveAllAnnotations = document.createElement("button");
  saveAllAnnotations.textContent = "Save All";
  const chooseAnnotationFolder = document.createElement("button");
  chooseAnnotationFolder.textContent = "Choose Folder…";
  const saveBesideImages = document.createElement("button");
  saveBesideImages.textContent = "Save Beside Images";
  annotationFileActions.append(
    saveCurrentAnnotations, saveAllAnnotations, chooseAnnotationFolder, saveBesideImages,
  );
  const annotationFileHint = document.createElement("p");
  annotationFileHint.className = "hint";
  annotationFileHint.textContent = "Working files preserve editable boxes, polygons, masks, classes, and review metadata. They are separate from model-training exports.";
  annotationFiles.body.append(
    autosaveRow, annotationPath, annotationFileActions, annotationFileHint,
  );
  container.append(annotationFiles.wrap);

  async function refreshBackendState() {
    const payload = await call("get_state");
    applyBackendState(payload);
    ctx.afterState?.();
  }

  autosave.addEventListener("change", async () => {
    try {
      const result = await call("set_annotation_autosave", autosave.checked);
      if (!result.ok) throw new Error(result.message || "Could not update autosave");
      await refreshBackendState();
    } catch (error) { ctx.toast?.err("Autosave failed", error.message); }
  });

  const saveWorkingFiles = async (requestedScope) => {
    try {
      const result = await call("save_annotation_files", requestedScope);
      if (!result.ok) throw new Error(result.message || "Annotation files were not saved");
      ctx.toast?.ok("Working files saved", `${result.saved} annotation file(s) written`);
      await refreshBackendState();
    } catch (error) { ctx.toast?.err("Save failed", error.message); }
  };
  saveCurrentAnnotations.addEventListener("click", () => saveWorkingFiles("current"));
  saveAllAnnotations.addEventListener("click", () => saveWorkingFiles("all"));

  const chooseDirectory = async (method) => {
    try {
      const result = await call(method);
      if (result.cancelled) return;
      if (!result.ok) throw new Error(result.message || "Could not change folder");
      await refreshBackendState();
    } catch (error) { ctx.toast?.err("Folder failed", error.message); }
  };
  chooseAnnotationFolder.addEventListener(
    "click", () => chooseDirectory("choose_annotation_save_directory"),
  );
  saveBesideImages.addEventListener(
    "click", () => chooseDirectory("reset_annotation_save_directory"),
  );

  const annotations = group("Training dataset export");
  const modeStatus = document.createElement("div");
  modeStatus.className = "auto-preview-status";
  const scopeRow = document.createElement("label");
  scopeRow.className = "auto-control-row";
  const scopeLabel = document.createElement("span");
  scopeLabel.textContent = "Images";
  const scope = document.createElement("select");
  scope.innerHTML = '<option value="current">Current image</option><option value="all" selected>All open images</option>';
  scopeRow.append(scopeLabel, scope);
  const taskRow = document.createElement("label");
  taskRow.className = "auto-control-row";
  const taskLabel = document.createElement("span");
  taskLabel.textContent = "Training task";
  const task = document.createElement("select");
  taskRow.append(taskLabel, task);
  const formatRow = document.createElement("label");
  formatRow.className = "auto-control-row";
  const formatLabel = document.createElement("span");
  formatLabel.textContent = "Format";
  const format = document.createElement("select");
  formatRow.append(formatLabel, format);
  const exportAnnotations = document.createElement("button");
  exportAnnotations.className = "primary";
  exportAnnotations.textContent = "Export Annotations";
  exportAnnotations.addEventListener("click", async () => {
    exportAnnotations.disabled = true;
    try {
      const res = await call("export_annotations", format.value, scope.value, task.value);
      if (!res.ok) {
        if (!res.cancelled) throw new Error(res.message || "Could not export annotations");
        return;
      }
      const excluded = Number(res.annotations_excluded || 0);
      ctx.toast?.ok(
        "Training dataset exported",
        `${res.saved} image(s) · ${res.format.toUpperCase()}${excluded ? ` · ${excluded} other-task annotation(s) excluded` : ""}`,
      );
      if (res.workspace_exported) {
        document.dispatchEvent(new CustomEvent("imagecraft:workspace-exported"));
      }
    } catch (error) {
      ctx.toast?.err("Export failed", error.message);
    } finally {
      exportAnnotations.disabled = !state.current;
    }
  });
  const exportHint = document.createElement("p");
  exportHint.className = "hint";
  const destinationStatus = document.createElement("div");
  destinationStatus.className = "annotation-path";
  const destinationActions = document.createElement("div");
  destinationActions.className = "btn-row";
  const chooseExportFolder = document.createElement("button");
  chooseExportFolder.textContent = "Choose Export Folder…";
  const askEveryTime = document.createElement("button");
  askEveryTime.textContent = "Ask Every Time";
  destinationActions.append(chooseExportFolder, askEveryTime);
  chooseExportFolder.addEventListener(
    "click", () => chooseDirectory("choose_annotation_export_directory"),
  );
  askEveryTime.addEventListener(
    "click", () => chooseDirectory("reset_annotation_export_directory"),
  );
  annotations.body.append(
    modeStatus, scopeRow, taskRow, formatRow, exportHint,
    destinationStatus, destinationActions, exportAnnotations,
  );
  container.append(annotations.wrap);

  function refreshAnnotationFormats() {
    const editor = state.annotationEditor || {};
    const counts = scope.value === "current"
      ? editor.type_counts_current || {}
      : editor.type_counts_all || {};
    const taskOptions = [];
    if (Number(counts.mask || 0) + Number(counts.polygon || 0) > 0) {
      taskOptions.push(["segmentation", "Instance segmentation — polygons and masks"]);
    }
    if (Number(counts.bbox || 0) > 0) {
      taskOptions.push(["detection", "Object detection — bounding boxes"]);
    }
    if (Number(counts.classification || 0) > 0) {
      taskOptions.push(["classification", "Image classification — whole-image labels"]);
    }
    if (Number(counts.pose || 0) > 0) {
      taskOptions.unshift(["pose", "Pose estimation — boxes and/or ordered keypoints"]);
    }
    const previousTask = task.value;
    task.innerHTML = "";
    for (const [value, label] of taskOptions) {
      const option = document.createElement("option");
      option.value = value; option.textContent = label; task.append(option);
    }
    if ([...task.options].some(option => option.value === previousTask)) {
      task.value = previousTask;
    }

    const formats = {
      detection: [
        ["yolo", "YOLO Detection TXT — recommended for YOLO detectors"],
        ["coco", "COCO Instances JSON — broad framework support"],
        ["voc", "Pascal VOC XML — classic bounding-box format"],
      ],
      segmentation: [
        ["coco", "COCO Instance Segmentation — recommended; preserves masks"],
        ["yolo", "YOLO Segmentation TXT — polygons; masks are traced"],
        ["mask", "PNG instance masks + JSON index — lossless raster masks"],
      ],
      classification: [
        ["yolo", "Class folders — YOLO Classification / torchvision compatible"],
      ],
      pose: [],
    };
    const poseSchemas = scope.value === "current"
      ? editor.pose_schema_counts_current || {}
      : editor.pose_schema_counts_all || {};
    const schemaNames = Object.keys(poseSchemas).filter(name => Number(poseSchemas[name]) > 0);
    if (schemaNames.length === 1) {
      formats.pose.push([
        "yolo_pose",
        "YOLO Pose TXT + data.yaml — recommended for Ultralytics pose training",
      ]);
    }
    formats.pose.push([
      "coco_keypoints",
      "COCO Keypoints JSON — standard instance keypoints with boxes and skeleton",
    ]);
    if (schemaNames.length === 1 && schemaNames[0] === "mediapipe_33") {
      formats.pose.push([
        "mediapipe",
        "MediaPipe 33-landmark JSON — normalized landmarks without required boxes",
      ]);
    }
    const options = formats[task.value] || [];
    const previous = format.value;
    format.innerHTML = "";
    for (const [value, label] of options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      format.append(option);
    }
    if ([...format.options].some(option => option.value === previous)) format.value = previous;
    const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
    modeStatus.textContent = total
      ? `Found ${counts.bbox || 0} box(es), ${counts.polygon || 0} polygon(s), ${counts.mask || 0} mask(s), ${counts.pose || 0} pose instance(s), and ${counts.classification || 0} classification label(s). Only formats valid for the selected task are shown.`
      : "No committed annotations are available in this image scope.";
    const taskCount = task.value === "segmentation"
      ? Number(counts.polygon || 0) + Number(counts.mask || 0)
      : task.value === "detection" ? Number(counts.bbox || 0)
        : task.value === "pose" ? Number(counts.pose || 0)
        : Number(counts.classification || 0);
    const excluded = Math.max(0, total - taskCount);
    exportHint.textContent = task.value === "pose" && schemaNames.length > 1
      ? `This scope mixes pose schemas. COCO Keypoints is the safe combined format; export each schema separately for YOLO Pose.${excluded ? ` ${excluded} annotation(s) from other tasks will be excluded.` : ""}`
      : format.value === "yolo" && task.value === "segmentation"
      && Number(counts.mask || 0) > 0
      ? `Bitmap masks will be traced into YOLO polygons. Choose COCO or PNG masks for lossless mask geometry.${excluded ? ` ${excluded} annotation(s) from other tasks will be excluded.` : ""}`
      : `A new source-preserving dataset folder will be created.${excluded ? ` ${excluded} annotation(s) from other tasks will be excluded.` : ""}`;
    task.disabled = taskOptions.length === 0;
    format.disabled = options.length === 0;
    exportAnnotations.disabled = !state.current || options.length === 0;
  }

  scope.addEventListener("change", refreshAnnotationFormats);
  task.addEventListener("change", refreshAnnotationFormats);
  format.addEventListener("change", refreshAnnotationFormats);

  registerRefresher("export", (s) => {
    const hasImage = !!s.current;
    const hasModified = (s.images || []).some((i) => i.modified);
    saveOneBtn.disabled = !hasImage;
    saveModifiedBtn.disabled = !hasImage || !hasModified;
    saveSessionBtn.disabled = (s.images || []).length === 0;
    prefix.disabled = !hasImage;
    postfix.disabled = !hasImage;
    annotationFiles.wrap.hidden = !hasImage;
    annotations.wrap.hidden = !hasImage;
    autosave.checked = s.annotationEditor?.autosave !== false;
    saveCurrentAnnotations.disabled = !hasImage;
    saveAllAnnotations.disabled = !hasImage;
    const customAnnotationFolder = !!s.annotationEditor?.save_directory;
    annotationPath.textContent = customAnnotationFolder
      ? `Working files: ${s.annotationEditor.save_directory}`
      : "Working files: beside each image";
    chooseAnnotationFolder.classList.toggle("active-choice", customAnnotationFolder);
    saveBesideImages.classList.toggle("active-choice", !customAnnotationFolder);
    const customExportFolder = !!s.annotationEditor?.export_directory;
    destinationStatus.textContent = customExportFolder
      ? `Training exports: ${s.annotationEditor.export_directory}`
      : "Training exports: ask for a destination each time";
    chooseExportFolder.classList.toggle("active-choice", customExportFolder);
    askEveryTime.classList.toggle("active-choice", !customExportFolder);
    scope.disabled = !hasImage || (s.images || []).length <= 1;
    refreshAnnotationFormats();
  });
}
