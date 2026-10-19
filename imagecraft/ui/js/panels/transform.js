// Transformation control panel — perspective, translation, rotation, scale, crop.
// Emits live previews via `ctx.preview("transform", collect)` and applies at full
// resolution via `ctx.apply`.

import { checkboxRow, sliderRow } from "../controls.js";
import { call } from "../api.js";
import { registerPendingApplyGuard, registerRefresher, onTabLeave } from "../sidebar.js";
import { applyBackendState, setEditParams, setState, state } from "../state.js";

// Free-crop rectangle, in *full-resolution (active image) pixels*, shipped to
// the backend as crop_x/y/w/h. It is set only while an accepted free-crop
// selection is being committed and lets TransformParams prefer the absolute
// rect over the four edge-trim sliders. The engine downscales these fields
// itself for the preview working copy, so the values here are full-res.
let pendingCropRect = null;

/** Build a collapsible `.panel` group and return { wrap, body }. */
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

export function buildTransformPanel(container, ctx) {
  container.innerHTML = "";

  /** Field name → slider row (order matters for `collect`). */
  const rows = new Map();
  const add = (body, key, label, min, max, step = 1) => {
    const r = sliderRow({ label, min, max, step, value: 0, onChange: () => ctx.onControlChanged("transform", collect) });
    rows.set(key, r);
    body.append(r.el);
    return r;
  };

  // Perspective corners (TL, TR, BR, BL × x,y).
  const persp = group("Perspective");
  for (const [key, label] of [
    ["tl_x", "Top-Left X"], ["tl_y", "Top-Left Y"],
    ["tr_x", "Top-Right X"], ["tr_y", "Top-Right Y"],
    ["br_x", "Bottom-Right X"], ["br_y", "Bottom-Right Y"],
    ["bl_x", "Bottom-Left X"], ["bl_y", "Bottom-Left Y"],
  ]) {
    add(persp.body, key, label, 0, 4000);
  }
  container.append(persp.wrap);

  // Geometric ops.
  const geo = group("Geometry");
  add(geo.body, "translate_x", "X Shift", -2000, 2000);
  add(geo.body, "translate_y", "Y Shift", -2000, 2000);
  add(geo.body, "rotation", "Rotation °", -360, 360, 1);
  add(geo.body, "scale", "Scale %", 10, 500, 1);
  container.append(geo.wrap);

  // Crop.
  const crop = group("Crop");
  add(crop.body, "crop_top", "Top", 0, 4000);
  add(crop.body, "crop_bottom", "Bottom", 0, 4000);
  add(crop.body, "crop_left", "Left", 0, 4000);
  add(crop.body, "crop_right", "Right", 0, 4000);

  // Crop control bar — shown when free crop is active.
  const cropBar = document.createElement("div");
  cropBar.className = "btn-row";
  cropBar.style.cssText = "margin-top:8px;display:none;";

  const cropResetBtn = document.createElement("button");
  cropResetBtn.textContent = "Reset";
  cropResetBtn.addEventListener("click", () => { if (ctx.viewer) ctx.viewer.resetCropRect(); });

  const cropAcceptBtn = document.createElement("button");
  cropAcceptBtn.className = "primary";
  cropAcceptBtn.textContent = "✓ Accept";
  cropAcceptBtn.addEventListener("click", () => {
    // Read the selection (in displayed-image pixels), convert it to full-res
    // active-image pixels and commit it as a real, undoable edit. The crop
    // therefore stays applied until the user undoes it manually.
    const v = ctx.viewer;
    const rImg = v && v.getCropRect();
    if (!rImg || !state.current || !v.naturalW || !v.naturalH) return;
    const aw = state.current.w, ah = state.current.h;
    const toFull = (px, naturalDim, fullDim) => Math.max(0, Math.round(px * fullDim / naturalDim));
    pendingCropRect = {
      x: toFull(rImg.x, v.naturalW, aw),
      y: toFull(rImg.y, v.naturalH, ah),
      w: toFull(rImg.w, v.naturalW, aw),
      h: toFull(rImg.h, v.naturalH, ah),
    };
    deactivateFreeCrop();
    Promise.resolve(applyTransform(false)).finally(() => { pendingCropRect = null; });
  });

  const cropCancelBtn = document.createElement("button");
  cropCancelBtn.textContent = "✕ Cancel";
  cropCancelBtn.addEventListener("click", () => { deactivateFreeCrop(); });

  cropBar.append(cropResetBtn, cropAcceptBtn, cropCancelBtn);

  // Free Crop toggle button
  const freeCropBtn = document.createElement("button");
  freeCropBtn.textContent = "Free Crop";
  freeCropBtn.style.cssText = "margin-top:6px;";
  let freeCropActive = false;

  function deactivateFreeCrop() {
    if (freeCropActive) {
      freeCropActive = false;
      freeCropBtn.textContent = "Free Crop";
      cropBar.style.display = "none";
      if (ctx.viewer) ctx.viewer.disableCropMode();
    }
  }
  // Switching tabs while a selection is open would leave the viewer frozen in
  // crop mode; cancel it so other panels keep working.
  onTabLeave("transform", deactivateFreeCrop);

  freeCropBtn.addEventListener("click", () => {
    if (!ctx.viewer || !state.current) return;
    if (freeCropActive) {
      deactivateFreeCrop();
    } else {
      if (!ctx.viewer.enableCropMode()) return;
      freeCropActive = true;
      freeCropBtn.textContent = "Crop Mode Active";
      cropBar.style.display = "flex";
    }
  });
  crop.body.append(freeCropBtn, cropBar);
  container.append(crop.wrap);

  const safety = group("Annotation safety");
  const annotationAware = checkboxRow({
    label: "Annotation-aware geometry (recommended)",
    checked: true,
    onChange: () => {
      updateSafety();
      ctx.onControlChanged("transform", collect);
    },
  });
  const safetyStatus = document.createElement("p");
  safetyStatus.className = "annotation-awareness-status";
  const practiceBtn = document.createElement("button");
  practiceBtn.textContent = "Open Transform Practice Image…";
  practiceBtn.addEventListener("click", async () => {
    if (state.current && !window.confirm("Open the built-in labelled practice image? Save any current work you need first.")) return;
    try {
      const payload = await call("open_transform_practice_image");
      if (!payload.ok) throw new Error(payload.message || "Could not open practice image");
      applyBackendState(payload, { resetControls: true });
      ctx.afterState?.();
      ctx.toast?.ok("Practice image opened", "Try rotation, perspective, scale, and crop");
    } catch (error) { ctx.toast?.err("Practice image failed", error.message); }
  });
  safety.body.append(annotationAware.el, safetyStatus, practiceBtn);
  container.append(safety.wrap);

  function updateSafety() {
    const labelled = (state.images || []).some(image => Number(image.annotations || 0) > 0);
    safetyStatus.classList.toggle("warning", labelled && !annotationAware.checked());
    safetyStatus.textContent = annotationAware.checked()
      ? "ON — boxes, polygons, and bitmap masks follow perspective, movement, rotation, scale, and crop."
      : labelled
        ? "WARNING — pixels will move while labels remain unchanged. Training labels may become invalid."
        : "OFF — no labels are currently present.";
  }

  // Actions.
  const actions = group("Actions");
  const btnRow = document.createElement("div");
  btnRow.className = "btn-row";
  const mkBtn = (text, fn, cls) => {
    const b = document.createElement("button");
    b.textContent = text;
    if (cls) b.className = cls;
    b.addEventListener("click", fn);
    btnRow.append(b);
    return b;
  };
  mkBtn("Apply", () => applyTransform(false), "primary");
  mkBtn("Apply to All", () => applyTransform(true));
  const reset = mkBtn("Reset sliders", () => resetValues());
  mkBtn("Preview", () => ctx.previewNow("transform", collect));
  const repeatApply = checkboxRow({
    label: "Keep settings after Apply (allow repeated stacking)",
    checked: false,
    onChange: (enabled) => setState({ repeatTransform: enabled }),
  });
  const repeatHint = document.createElement("p");
  repeatHint.className = "hint";
  repeatHint.textContent = "Off by default: applied transform values reset so an earlier transform is not accidentally applied again.";
  actions.body.append(btnRow, repeatApply.el, repeatHint);
  container.append(actions.wrap);

  function applyTransform(all) {
    const labelled = (state.images || []).some(image => Number(image.annotations || 0) > 0);
    if (labelled && !annotationAware.checked()
        && !window.confirm("Annotation-aware geometry is OFF. Continue and leave labels unchanged?")) {
      return;
    }
    return ctx.apply("transform", collect, all);
  }

  function collect() {
    const params = { annotation_aware: annotationAware.checked() };
    for (const [key, r] of rows) params[key] = Math.round(r.value());
    if (pendingCropRect) {
      // The absolute free-crop rect wins over the four trim sliders inside the
      // shared TransformParams (the engine prefers crop_x/y/w/h when set).
      params.crop_x = pendingCropRect.x;
      params.crop_y = pendingCropRect.y;
      params.crop_w = pendingCropRect.w;
      params.crop_h = pendingCropRect.h;
    }
    return params;
  }

  function resetValues() {
    setEditParams("transform", null);
    ctx.refresh();
  }
  document.addEventListener("imagecraft:transform-committed", resetValues);


  // ----------------------------------------------------------------
  // Refresh: ranges follow the current image; values follow defaults.
  // ----------------------------------------------------------------
  registerRefresher("transform", (s, info = {}) => {
    const w = s.current ? s.current.w : 1920;
    const h = s.current ? s.current.h : 1080;
    const d = s.defaults.transform || {};
    const enabled = !!s.current;

    const setRange = (key, min, max) => {
      const r = rows.get(key);
      if (!r) return;
      r.el.querySelector("input").min = min;
      r.el.querySelector("input").max = max;
    };

    // Perspective: X keys are even fields, Y keys are odd — set by name.
    for (const [key, r] of rows) {
      if (key.endsWith("_x")) setRange(key, 0, w);
      else if (key.endsWith("_y")) setRange(key, 0, h);
    }
    setRange("translate_x", -Math.floor(w / 2), Math.floor(w / 2));
    setRange("translate_y", -Math.floor(h / 2), Math.floor(h / 2));
    setRange("crop_top", 0, h);
    setRange("crop_bottom", 0, h);
    setRange("crop_left", 0, w);
    setRange("crop_right", 0, w);

    // Default fallbacks describe a full-frame identity transform.
    const fallback = {
      tl_x: 0, tl_y: 0, tr_x: w, tr_y: 0,
      br_x: w, br_y: h, bl_x: 0, bl_y: h,
      translate_x: 0, translate_y: 0, rotation: 0, scale: 100,
      crop_top: 0, crop_bottom: 0, crop_left: 0, crop_right: 0,
    };
    if (info.reset) {
      for (const [key, r] of rows) {
        const v = d[key] !== undefined ? d[key] : fallback[key];
        r.set(v);
        r.enable(enabled);
      }
    } else {
      for (const [key, r] of rows) r.enable(enabled);
    }
    if (!enabled || info.reset) deactivateFreeCrop();
    freeCropBtn.disabled = !enabled;
    reset.disabled = !enabled;
    repeatApply.set(!!state.repeatTransform);
    annotationAware.set(s.editParams?.transform?.annotation_aware !== false);
    updateSafety();
    practiceBtn.disabled = false;
  });
  registerPendingApplyGuard("transform", (params) => {
    const labelled = (state.images || []).some(image => Number(image.annotations || 0) > 0);
    return !labelled || params.annotation_aware !== false
      || window.confirm("Annotation-aware geometry is OFF. Apply the pending transform and leave labels unchanged?");
  });
}
