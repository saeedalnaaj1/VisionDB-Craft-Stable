// Canvas-based image viewer: fit-to-window, cursor-anchored wheel zoom,
// drag-to-pan with edge clamping, double-click to fit.
// Crop overlay is DOM-based (positioned over the canvas) — no coordinate
// conversion during drag, just like Windows Photos.

import { setState } from "./state.js";
import { preservedImageView } from "./view_state.js";

const MIN_SCALE = 0.05;
const MAX_SCALE = 16;
const WHEEL_STEP = 1.15;

export class Viewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.image = null;
    this.naturalW = 0;
    this.naturalH = 0;
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.mode = "fit";
    this.onChange = null;
    this.onAnnotationSelect = null;
    this.onAnnotationTransform = null;
    this.onPoseKeypointTransform = null;
    this.onPoseProgress = null;
    this.onAutoAnnotationSelect = null;
    this.pointPromptMode = false;
    this.pointPromptCallback = null;
    this.annotations = [];
    this.autoAnnotations = [];
    this.showAnnotations = true;
    this.hiddenAnnotations = new Set();
    this.selectedAnnotation = -1;
    this.annotationSelectionEnabled = false;
    this.autoAnnotationSelectionEnabled = false;
    this.selectedAutoAnnotation = -1;
    this._annotationTransform = null;
    this.annotationMode = null;
    this.annotationCallback = null;
    this.onAnnotationModeChange = null;
    this._annotationDraft = null;
    this._polygonPoints = [];
    this._maskStrokes = [];
    this._maskActiveStroke = null;
    this._maskBaseRle = null;
    this.annotationBrushSize = 24;
    this.annotationBrushErase = false;
    this._maskCache = new Map();
    this._maskDraftCanvas = null;
    this._poseOptions = null;
    this._poseStage = null;
    this._poseBox = null;
    this._posePoints = [];
    this._posePointTransform = null;

    // Crop — DOM overlay. The selection rectangle is stored in *displayed
    // image pixel coordinates* (this._cropRectImg) and converted to CSS
    // pixels only for drawing, using the current view transform. Keeping the
    // source in image space means the overlay stays glued to the picture even
    // if the canvas re-renders, resizes or zooms — the old CSS-space rect
    // drifted against a moving image, which is the "jumps somewhere else" bug.
    this.cropMode = false;
    this._cropRectImg = null; // { x, y, w, h } in displayed-image pixels
    this._cropOverlay = document.getElementById("crop-overlay");
    this._cropRect = document.getElementById("crop-rect");
    this._cropDrag = null; // { kind, startX, startY, startRect (image px) }

    const host = canvas.parentElement;
    this._ro = new ResizeObserver(() => this.render());
    if (host) this._ro.observe(host);

    canvas.style.touchAction = "none";
    canvas.addEventListener("wheel", (e) => this._onWheel(e), { passive: false });
    canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    canvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
    canvas.addEventListener("pointerleave", (e) => this._onPointerUp(e));
    canvas.addEventListener("pointercancel", (e) => this._onPointerUp(e));
    canvas.addEventListener("dblclick", (e) => {
      if (this.annotationMode === "polygon") {
        e.preventDefault();
        this.finishPolygon();
      } else if (!this.cropMode) this.fit();
    });
    canvas.addEventListener("contextmenu", (e) => {
      if (this.annotationMode || this.pointPromptMode || this._annotationTransform) {
        e.preventDefault();
        this.cancelAnnotation();
        this.cancelPointPrompt();
        this.cancelAnnotationTransform();
      }
    });
    this._pointer = null;

    // Wire crop handle drag
    this._initCropHandles();
  }

  // ------------------------------------------------------------------
  // Coordinate helpers (for the image, not the crop)
  // ------------------------------------------------------------------

  _cssToImg(cssX, cssY) {
    return [(cssX - this.offsetX) / this.scale, (cssY - this.offsetY) / this.scale];
  }

  _imgToCss(ix, iy) {
    return [this.offsetX + ix * this.scale, this.offsetY + iy * this.scale];
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  async setImage(dataUrl, opts = {}) {
    const previous = this.getViewState();

    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        // While a crop selection is active the displayed picture is frozen so
        // the selection stays aligned with exactly what the user is looking at
        // (a debounced preview firing mid-drag used to swap the underlying
        // image, which desynced the overlay from the picture).
        if (this.cropMode) { resolve(); return; }
        this.image = img;
        this.naturalW = img.naturalWidth;
        this.naturalH = img.naturalHeight;
        const preserved = preservedImageView(!!opts.preserveView, previous, {
          naturalW: this.naturalW,
          naturalH: this.naturalH,
        });
        if (preserved) {
          this.scale = preserved.scale;
          this.offsetX = preserved.offsetX;
          this.offsetY = preserved.offsetY;
          this.mode = preserved.mode;
          this._clampOffsets();
        } else if (!this.cropMode) {
          this.fit();
        }
        this.render();
        resolve();
      };
      img.onerror = () => reject(new Error("Failed to decode image"));
      img.src = dataUrl;
    });
  }

  getViewState() {
    return {
      scale: this.scale,
      offsetX: this.offsetX,
      offsetY: this.offsetY,
      mode: this.mode,
      naturalW: this.naturalW,
      naturalH: this.naturalH,
    };
  }

  restoreViewState(view) {
    if (!this.image || !view) return false;
    if (view.mode === "fit") {
      this.fit();
      return true;
    }
    const restored = preservedImageView(true, view, {
      naturalW: this.naturalW,
      naturalH: this.naturalH,
    });
    if (!restored) return false;
    this.scale = restored.scale;
    this.offsetX = restored.offsetX;
    this.offsetY = restored.offsetY;
    this.mode = restored.mode;
    this._clampOffsets();
    this.render();
    return true;
  }

  clear() {
    this.image = null;
    this.naturalW = 0;
    this.naturalH = 0;
    this.autoAnnotations = [];
    this.selectedAutoAnnotation = -1;
    this.cancelPointPrompt();
    this.fit();
  }
  fit() { this.mode = "fit"; this.render(); }

  setAnnotations(annotations) {
    this.annotations = Array.isArray(annotations) ? annotations : [];
    this._annotationTransform = null;
    this._posePointTransform = null;
    if (this.image) this.render();
  }

  hasImage() {
    return !!this.image;
  }

  setAutoAnnotationPreview(candidates) {
    this.autoAnnotations = Array.isArray(candidates) ? candidates : [];
    if (this.selectedAutoAnnotation >= this.autoAnnotations.length) {
      this.selectedAutoAnnotation = -1;
    }
    this.render();
  }

  clearAutoAnnotationPreview() {
    this.autoAnnotations = [];
    this.selectedAutoAnnotation = -1;
    this.autoAnnotationSelectionEnabled = false;
    this.render();
  }

  setAutoAnnotationSelectionEnabled(enabled) {
    this.autoAnnotationSelectionEnabled = !!enabled;
    if (!enabled) this.selectedAutoAnnotation = -1;
    this.render();
  }

  selectAutoAnnotation(index) {
    this.selectedAutoAnnotation = Number(index);
    this.render();
  }

  setAnnotationVisibility(visible) {
    this.showAnnotations = !!visible;
    this.render();
  }

  setHiddenAnnotations(indices) {
    this.hiddenAnnotations = new Set(indices || []);
    this.render();
  }

  selectAnnotation(index) {
    const next = Number(index);
    if (next !== this.selectedAnnotation) this._annotationTransform = null;
    this.selectedAnnotation = next;
    this.render();
  }

  setAnnotationSelectionEnabled(enabled) {
    this.annotationSelectionEnabled = !!enabled;
    if (!this.annotationSelectionEnabled) this._annotationTransform = null;
    this.render();
  }

  cancelAnnotationTransform() {
    const active = this._annotationTransform;
    this._annotationTransform = null;
    if (active?.id != null) {
      try { this.canvas.releasePointerCapture(active.id); } catch (_) { /* not captured */ }
    }
    this.render();
  }

  beginAnnotation(kind, callback, options = {}) {
    if (!this.image || !["bbox", "polygon", "mask", "pose"].includes(kind)) return false;
    this.annotationMode = kind;
    this.annotationCallback = callback;
    this._annotationDraft = null;
    this._polygonPoints = [];
    this._maskStrokes = [];
    this._maskActiveStroke = null;
    this._maskBaseRle = options.baseMaskRle || null;
    this._maskDraftCanvas = null;
    this._poseOptions = kind === "pose" ? {
      schema: options.poseSchema || "coco_17",
      workflow: options.poseWorkflow || "top_down",
      names: Array.isArray(options.keypointNames) ? options.keypointNames : [],
      skeleton: Array.isArray(options.skeleton) ? options.skeleton : [],
      hasBox: options.poseHasBox !== false,
    } : null;
    this._poseStage = kind === "pose" && this._poseOptions.hasBox ? "bbox" : "keypoints";
    this._poseBox = options.poseBox || null;
    this._posePoints = [];
    this.setMaskBrush(options.brushSize ?? this.annotationBrushSize, options.erase ?? false);
    this.canvas.style.cursor = "crosshair";
    this.onAnnotationModeChange?.(true, kind);
    if (kind === "pose") this._emitPoseProgress();
    this.render();
    return true;
  }

  beginPointPrompt(callback) {
    if (!this.image) return false;
    this.cancelAnnotation();
    this.pointPromptMode = true;
    this.pointPromptCallback = callback;
    this.canvas.style.cursor = "crosshair";
    this.render();
    return true;
  }

  cancelPointPrompt() {
    const active = this.pointPromptMode;
    this.pointPromptMode = false;
    this.pointPromptCallback = null;
    if (active && this.image) this.render();
  }

  isAnnotationDrawing() {
    return this.annotationMode !== null;
  }

  finishPolygon() {
    if (this.annotationMode !== "polygon" || this._polygonPoints.length < 3) return false;
    const points = [...this._polygonPoints];
    const callback = this.annotationCallback;
    this.cancelAnnotation();
    if (callback) callback({ polygon: points });
    return true;
  }

  setMaskBrush(size, erase = this.annotationBrushErase) {
    this.annotationBrushSize = clamp(Math.round(Number(size) || 24), 1, 512);
    this.annotationBrushErase = !!erase;
  }

  finishMask() {
    if (this.annotationMode !== "mask") return false;
    if (!this._maskStrokes.length && !this._maskBaseRle) return false;
    const geometry = {
      strokes: this._maskStrokes.map((stroke) => ({
        points: stroke.points.map((point) => [...point]),
        erase: !!stroke.erase,
        brush_size: stroke.brushSize,
      })),
      brush_size: this.annotationBrushSize,
    };
    if (this._maskBaseRle) geometry.base_mask_rle = this._maskBaseRle;
    const callback = this.annotationCallback;
    this.cancelAnnotation();
    if (callback) callback(geometry);
    return true;
  }

  skipPoseKeypoint() {
    if (this.annotationMode !== "pose" || this._poseStage !== "keypoints") return false;
    const total = this._poseOptions?.names?.length || 0;
    if (this._posePoints.length >= total) return false;
    const name = this._poseOptions.names[this._posePoints.length] || `point_${this._posePoints.length}`;
    this._posePoints.push({ name, x: 0, y: 0, z: 0, visibility: 0, presence: 0 });
    if (this._posePoints.length >= total) return this.finishPose();
    this._emitPoseProgress();
    this.render();
    return true;
  }

  undoPoseKeypoint() {
    if (this.annotationMode !== "pose" || !this._posePoints.length) return false;
    this._posePoints.pop();
    this._emitPoseProgress();
    this.render();
    return true;
  }

  finishPose() {
    if (this.annotationMode !== "pose") return false;
    const total = this._poseOptions?.names?.length || 0;
    if (!this._posePoints.some(point => Number(point.visibility) > 0)) return false;
    while (this._posePoints.length < total) {
      const index = this._posePoints.length;
      this._posePoints.push({
        name: this._poseOptions.names[index] || `point_${index}`,
        x: 0, y: 0, z: 0, visibility: 0, presence: 0,
      });
    }
    const geometry = {
      keypoints: this._posePoints.map(point => ({ ...point })),
      pose_schema: this._poseOptions.schema,
      pose_workflow: this._poseOptions.workflow,
      pose_has_bbox: !!this._poseOptions.hasBox,
      ...(this._poseBox || {}),
    };
    const callback = this.annotationCallback;
    this.cancelAnnotation();
    if (callback) callback(geometry);
    return true;
  }

  _emitPoseProgress() {
    if (this.annotationMode !== "pose") return;
    const index = this._posePoints.length;
    const names = this._poseOptions?.names || [];
    this.onPoseProgress?.({
      stage: this._poseStage,
      index,
      total: names.length,
      name: names[index] || "Complete",
      placed: this._posePoints.filter(point => Number(point.visibility) > 0).length,
    });
  }

  cancelAnnotation() {
    const previousMode = this.annotationMode;
    this.annotationMode = null;
    this.annotationCallback = null;
    this._annotationDraft = null;
    this._polygonPoints = [];
    this._maskStrokes = [];
    this._maskActiveStroke = null;
    this._maskBaseRle = null;
    this._maskDraftCanvas = null;
    this._poseOptions = null;
    this._poseStage = null;
    this._poseBox = null;
    this._posePoints = [];
    this.canvas.style.cursor = this.annotationSelectionEnabled ? "pointer" : "grab";
    if (previousMode !== null) this.onAnnotationModeChange?.(false, previousMode);
    this.render();
  }

  _eventToNormalized(e) {
    const point = this._eventToNormalizedClamped(e);
    if (!point || point[2] < 0 || point[2] > this.naturalW
      || point[3] < 0 || point[3] > this.naturalH) return null;
    return [point[0], point[1]];
  }

  _eventToNormalizedClamped(e) {
    const rect = this.canvas.getBoundingClientRect();
    const [x, y] = this._cssToImg(e.clientX - rect.left, e.clientY - rect.top);
    if (!this.naturalW || !this.naturalH) return null;
    return [
      clamp(x / this.naturalW, 0, 1),
      clamp(y / this.naturalH, 0, 1),
      x,
      y,
    ];
  }

  _annotationAtEvent(e) {
    if (!this.showAnnotations) return -1;
    const point = this._eventToNormalized(e);
    if (!point) return -1;
    const [nx, ny] = point;
    const imageX = nx * this.naturalW;
    const imageY = ny * this.naturalH;
    const scale = Math.max(this.scale, 0.0001);
    const hits = [];

    for (const [index, annotation] of this.annotations.entries()) {
      if (this.hiddenAnnotations.has(index)) continue;
      let inside = false;
      let area = 1;

      if (annotation.type === "classification") {
        const label = String(annotation.label || `class_${annotation.class_id ?? 0}`);
        const labelY = 8 + index * 24;
        const labelWidth = Math.max(80 / scale, label.length * 8 / scale);
        inside = imageX >= 8 && imageX <= 8 + labelWidth
          && imageY >= labelY && imageY <= labelY + 20 / scale;
        area = 0;
      } else {
        const width = Number(annotation.w);
        const height = Number(annotation.h);
        const left = Number(annotation.x) - width / 2;
        const top = Number(annotation.y) - height / 2;
        const inBounds = [left, top, width, height].every(Number.isFinite)
          && width > 0 && height > 0
          && nx >= left && nx <= left + width
          && ny >= top && ny <= top + height;
        area = Math.abs(width * height);

        if (annotation.type === "mask" && annotation.mask_rle) {
          const maskHit = this._maskContains(annotation.mask_rle, nx, ny);
          inside = maskHit === null ? inBounds : maskHit;
        } else if (Array.isArray(annotation.polygon) && annotation.polygon.length >= 3) {
          inside = pointInPolygon(nx, ny, annotation.polygon);
        } else {
          inside = inBounds;
        }
      }

      if (inside) hits.push({ index, area });
    }

    hits.sort((left, right) => left.area - right.area || right.index - left.index);
    return hits[0]?.index ?? -1;
  }

  _autoAnnotationAtEvent(e) {
    const point = this._eventToNormalized(e);
    if (!point) return -1;
    const [nx, ny] = point;
    const hits = [];
    for (const [index, candidate] of this.autoAnnotations.entries()) {
      const box = candidate?.bbox || {};
      const width = Number(box.w), height = Number(box.h);
      const left = Number(box.x) - width / 2;
      const top = Number(box.y) - height / 2;
      const insideBox = [left, top, width, height].every(Number.isFinite)
        && width > 0 && height > 0
        && nx >= left && nx <= left + width
        && ny >= top && ny <= top + height;
      const polygon = Array.isArray(candidate?.polygon) ? candidate.polygon : [];
      const inside = polygon.length >= 3 ? pointInPolygon(nx, ny, polygon) : insideBox;
      if (inside) hits.push({ index, area: Math.abs(width * height) });
    }
    hits.sort((left, right) => left.area - right.area || right.index - left.index);
    return hits[0]?.index ?? -1;
  }

  _maskContains(rle, nx, ny) {
    const size = Array.isArray(rle?.size) ? rle.size : [];
    const height = Number(size[0]);
    const width = Number(size[1]);
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
      return null;
    }
    let counts;
    try { counts = decodeCocoCounts(rle.counts); } catch (_) { return null; }
    const x = clamp(Math.floor(nx * width), 0, width - 1);
    const y = clamp(Math.floor(ny * height), 0, height - 1);
    const target = x * height + y;
    let cursor = 0;
    let foreground = false;
    for (const run of counts) {
      const end = cursor + run;
      if (target >= cursor && target < end) return foreground;
      cursor = end;
      foreground = !foreground;
    }
    return null;
  }

  _annotationHandleAtEvent(e, index = this.selectedAnnotation) {
    if (!this.annotationSelectionEnabled || !this.showAnnotations) return null;
    const annotation = this.annotations[index];
    if (!annotation || annotation.type === "classification" || this.hiddenAnnotations.has(index)) {
      return null;
    }
    const bounds = this._annotationTransform?.index === index
      ? this._annotationTransform.rect
      : annotationBounds(annotation);
    if (!bounds) return null;
    const canvasRect = this.canvas.getBoundingClientRect();
    const pointerX = e.clientX - canvasRect.left;
    const pointerY = e.clientY - canvasRect.top;
    let nearest = null;
    let distance = 11;
    for (const [handle, point] of Object.entries(annotationHandles(bounds))) {
      const [handleX, handleY] = this._imgToCss(
        point[0] * this.naturalW,
        point[1] * this.naturalH,
      );
      const candidate = Math.hypot(pointerX - handleX, pointerY - handleY);
      if (candidate <= distance) {
        nearest = handle;
        distance = candidate;
      }
    }
    return nearest;
  }

  _beginAnnotationTransform(e, index, handle = "move") {
    const annotation = this.annotations[index];
    const bounds = annotationBounds(annotation);
    const point = this._eventToNormalizedClamped(e);
    if (!annotation || !bounds || !point || annotation.type === "classification") return false;
    this._annotationTransform = {
      id: e.pointerId,
      index,
      kind: handle === "move" ? "move" : "resize",
      handle,
      start: [point[0], point[1]],
      startClientX: e.clientX,
      startClientY: e.clientY,
      original: { ...bounds },
      rect: { ...bounds },
      moved: false,
      pending: false,
    };
    this.canvas.setPointerCapture(e.pointerId);
    this.canvas.style.cursor = annotationCursor(handle);
    this.render();
    return true;
  }

  _poseKeypointAtEvent(e, index = this.selectedAnnotation) {
    const annotation = this.annotations[index];
    if (!annotation || annotation.type !== "pose" || !Array.isArray(annotation.keypoints)) {
      return -1;
    }
    const canvasRect = this.canvas.getBoundingClientRect();
    const pointerX = e.clientX - canvasRect.left;
    const pointerY = e.clientY - canvasRect.top;
    let nearest = -1;
    let distance = 12;
    for (const [pointIndex, point] of annotation.keypoints.entries()) {
      if (Number(point.visibility) <= 0) continue;
      const [pointX, pointY] = this._imgToCss(
        Number(point.x) * this.naturalW,
        Number(point.y) * this.naturalH,
      );
      const candidate = Math.hypot(pointerX - pointX, pointerY - pointY);
      if (candidate <= distance) { nearest = pointIndex; distance = candidate; }
    }
    return nearest;
  }

  _beginPoseKeypointTransform(e, annotationIndex, pointIndex) {
    const point = this._eventToNormalizedClamped(e);
    if (!point) return false;
    this._posePointTransform = {
      id: e.pointerId,
      annotationIndex,
      pointIndex,
      point: [point[0], point[1]],
      moved: false,
      pending: false,
    };
    this.canvas.setPointerCapture(e.pointerId);
    this.canvas.style.cursor = "move";
    this.render();
    return true;
  }

  _updatePoseKeypointTransform(e) {
    const active = this._posePointTransform;
    if (!active || active.pending || active.id !== e.pointerId) return false;
    const point = this._eventToNormalizedClamped(e);
    if (!point) return false;
    active.point = [point[0], point[1]];
    active.moved = true;
    this.render();
    return true;
  }

  _updateAnnotationTransform(e) {
    const active = this._annotationTransform;
    if (!active || active.pending || active.id !== e.pointerId) return false;
    const point = this._eventToNormalizedClamped(e);
    if (!point) return false;
    const [nx, ny] = point;
    const totalDistance = Math.hypot(
      e.clientX - active.startClientX,
      e.clientY - active.startClientY,
    );
    if (!active.moved && totalDistance <= 3) return true;
    active.moved = true;

    const source = active.original;
    let { left, top, right, bottom } = source;
    if (active.kind === "move") {
      const width = right - left;
      const height = bottom - top;
      left = clamp(source.left + nx - active.start[0], 0, 1 - width);
      top = clamp(source.top + ny - active.start[1], 0, 1 - height);
      right = left + width;
      bottom = top + height;
    } else {
      const minWidth = Math.max(0.002, 3 / Math.max(this.naturalW, 1));
      const minHeight = Math.max(0.002, 3 / Math.max(this.naturalH, 1));
      if (active.handle.includes("w")) left = clamp(nx, 0, right - minWidth);
      if (active.handle.includes("e")) right = clamp(nx, left + minWidth, 1);
      if (active.handle.includes("n")) top = clamp(ny, 0, bottom - minHeight);
      if (active.handle.includes("s")) bottom = clamp(ny, top + minHeight, 1);
    }
    active.rect = { left, top, right, bottom };
    this.canvas.style.cursor = annotationCursor(active.handle);
    this.render();
    return true;
  }

  _annotationTransformGeometry(active = this._annotationTransform) {
    if (!active) return null;
    const { left, top, right, bottom } = active.rect;
    return {
      x: (left + right) / 2,
      y: (top + bottom) / 2,
      w: right - left,
      h: bottom - top,
    };
  }

  zoomBy(f) {
    this._zoomTo(clamp(this.scale * f, MIN_SCALE, MAX_SCALE),
      this.canvas.clientWidth / 2, this.canvas.clientHeight / 2);
  }

  setZoomAbsolute(z) {
    this._zoomTo(clamp(z, MIN_SCALE, MAX_SCALE),
      this.canvas.clientWidth / 2, this.canvas.clientHeight / 2);
  }

  zoomPercent() { return Math.round(this.scale * 100); }

  // ------------------------------------------------------------------
  // Crop mode — DOM overlay, selection kept in image pixel space
  // ------------------------------------------------------------------

  enableCropMode() {
    if (!this.image || !this.naturalW || !this.naturalH) return false;
    this.cropMode = true;
    this.mode = "custom"; // freeze scale/offset so nothing re-fits mid-gesture
    // Start with the WHOLE picture selected — the user pulls the corners
    // inward to choose the crop region, like every photo editor.
    this._cropRectImg = { x: 0, y: 0, w: this.naturalW, h: this.naturalH };
    this._cropOverlay.hidden = false;
    this._syncCropOverlay();
    return true;
  }

  disableCropMode() {
    this.cropMode = false;
    this._cropRectImg = null;
    this._cropDrag = null;
    this._cropOverlay.hidden = true;
    this.mode = "fit";
    this.render();
  }

  resetCropRect() {
    if (!this.cropMode || !this.naturalW || !this.naturalH) return;
    this._cropRectImg = { x: 0, y: 0, w: this.naturalW, h: this.naturalH };
    this._syncCropOverlay();
  }

  /** Current selection in displayed-image pixels, or null when inactive. */
  getCropRect() {
    return this.cropMode && this._cropRectImg ? { ...this._cropRectImg } : null;
  }

  _setCropCSS(left, top, width, height) {
    const el = this._cropRect;
    el.style.left = left + "px";
    el.style.top = top + "px";
    el.style.width = width + "px";
    el.style.height = height + "px";
  }

  /** Reposition the DOM rect from the image-space selection + view transform. */
  _syncCropOverlay() {
    if (!this.cropMode || !this._cropRectImg) return;
    const { x, y, w, h } = this._cropRectImg;
    this._setCropCSS(
      Math.round(this.offsetX + x * this.scale),
      Math.round(this.offsetY + y * this.scale),
      Math.max(0, Math.round(w * this.scale)),
      Math.max(0, Math.round(h * this.scale)),
    );
  }

  /** Clamp the image-space selection to the picture, flipping past-the-edge drags. */
  _clampCropImg() {
    const r = this._cropRectImg;
    if (!r) return;
    const W = this.naturalW, H = this.naturalH;
    const minW = Math.min(8, W), minH = Math.min(8, H);
    let { x, y, w, h } = r;
    // Handle dragged across the opposite edge → flip instead of reject.
    if (w < 0) { x += w; w = -w; }
    if (h < 0) { y += h; h = -h; }
    // Slide back inside the picture.
    x = clamp(x, 0, Math.max(0, W - minW));
    y = clamp(y, 0, Math.max(0, H - minH));
    // Enforce minimum size and never exceed the remaining room.
    w = clamp(w, minW, W - x);
    h = clamp(h, minH, H - y);
    this._cropRectImg = {
      x: Math.round(x), y: Math.round(y),
      w: Math.round(w), h: Math.round(h),
    };
  }

  // ---- Handle drag wiring ----

  _initCropHandles() {
    const rect = this._cropRect;
    const overlay = this._cropOverlay;

    // Click on the darkened overlay background (outside the rect) — ignore.
    overlay.addEventListener("pointerdown", (e) => {
      if (e.target === overlay) { e.preventDefault(); return; }
    });

    // Click on crop rect body → move.
    rect.addEventListener("pointerdown", (e) => {
      if (e.target !== rect) return; // handle clicks go to handle
      if (!this.cropMode || !this._cropRectImg) return;
      e.preventDefault();
      e.stopPropagation();
      this._cropDrag = {
        kind: "move",
        startX: e.clientX,
        startY: e.clientY,
        startRect: { ...this._cropRectImg },
      };
      rect.setPointerCapture(e.pointerId);
      rect.style.cursor = "grabbing";
    });

    // Click on handle → resize.
    for (const handle of this._cropOverlay.querySelectorAll(".crop-handle")) {
      handle.addEventListener("pointerdown", (e) => {
        if (!this.cropMode || !this._cropRectImg) return;
        e.preventDefault();
        e.stopPropagation();
        this._cropDrag = {
          kind: handle.dataset.handle,
          startX: e.clientX,
          startY: e.clientY,
          startRect: { ...this._cropRectImg },
        };
        rect.setPointerCapture(e.pointerId);
      });
    }

    // Pointer move — on the rect (which has capture).
    rect.addEventListener("pointermove", (e) => {
      if (!this.cropMode || !this._cropDrag || !this._cropRectImg) return;
      e.preventDefault();
      // Convert the CSS-pixel drag delta into displayed-image pixels using the
      // frozen scale, so the selection edits in the same space it is stored.
      const s = this._cropDrag.startRect;
      const dx = (e.clientX - this._cropDrag.startX) / this.scale;
      const dy = (e.clientY - this._cropDrag.startY) / this.scale;

      let { x, y, w, h } = s;
      switch (this._cropDrag.kind) {
        case "nw": x = s.x + dx; y = s.y + dy; w = s.w - dx; h = s.h - dy; break;
        case "ne": y = s.y + dy; w = s.w + dx; h = s.h - dy; break;
        case "sw": x = s.x + dx; w = s.w - dx; h = s.h + dy; break;
        case "se": w = s.w + dx; h = s.h + dy; break;
        case "n":  y = s.y + dy; h = s.h - dy; break;
        case "s":  h = s.h + dy; break;
        case "w":  x = s.x + dx; w = s.w - dx; break;
        case "e":  w = s.w + dx; break;
        case "move": x = s.x + dx; y = s.y + dy; break;
      }
      this._cropRectImg = { x, y, w, h };
      this._clampCropImg();
      this._syncCropOverlay();
    });

    // Pointer up.
    rect.addEventListener("pointerup", () => {
      if (this._cropDrag) {
        this._cropDrag = null;
        rect.style.cursor = "move";
      }
    });
  }

  // ------------------------------------------------------------------
  // Pan / zoom interactions (on the canvas)
  // ------------------------------------------------------------------

  _onWheel(e) {
    if (!this.image) return;
    e.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    const factor = e.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP;
    this._zoomTo(clamp(this.scale * factor, MIN_SCALE, MAX_SCALE),
      e.clientX - rect.left, e.clientY - rect.top);
  }

  _onPointerDown(e) {
    if (!this.image || e.button !== 0 || this.cropMode) return;
    if (this.pointPromptMode) {
      const point = this._eventToNormalized(e);
      if (!point) return;
      const callback = this.pointPromptCallback;
      this.pointPromptMode = false;
      this.pointPromptCallback = null;
      callback?.({ x: point[0], y: point[1] });
      this.render();
      e.preventDefault();
      return;
    }
    if (this.annotationMode) {
      const point = this._eventToNormalized(e);
      if (!point) return;
      if (this.annotationMode === "pose") {
        if (this._poseStage === "bbox") {
          this._annotationDraft = { start: point, end: point };
          this.canvas.setPointerCapture(e.pointerId);
        } else {
          const index = this._posePoints.length;
          const total = this._poseOptions?.names?.length || 0;
          if (index < total) {
            this._posePoints.push({
              name: this._poseOptions.names[index] || `point_${index}`,
              x: point[0], y: point[1], z: 0,
              visibility: e.shiftKey ? 1 : 2, presence: 1,
            });
            if (this._posePoints.length >= total) {
              this.finishPose();
              e.preventDefault();
              return;
            }
            this._emitPoseProgress();
          }
        }
      } else if (this.annotationMode === "polygon") {
        const last = this._polygonPoints.at(-1);
        if (!last || Math.hypot(point[0] - last[0], point[1] - last[1]) > 0.002) {
          this._polygonPoints.push(point);
        }
      } else if (this.annotationMode === "mask") {
        const stroke = {
          points: [point], erase: this.annotationBrushErase,
          brushSize: this.annotationBrushSize,
        };
        this._maskStrokes.push(stroke);
        this._maskActiveStroke = { id: e.pointerId, stroke };
        this.canvas.setPointerCapture(e.pointerId);
      } else {
        this._annotationDraft = { start: point, end: point };
        this.canvas.setPointerCapture(e.pointerId);
      }
      this.render();
      e.preventDefault();
      return;
    }
    if (this._annotationTransform?.pending) return;
    if (this.autoAnnotationSelectionEnabled && this.autoAnnotations.length) {
      const hit = this._autoAnnotationAtEvent(e);
      if (hit >= 0) {
        const accepted = this.onAutoAnnotationSelect
          ? this.onAutoAnnotationSelect(hit) !== false
          : true;
        if (accepted) this.selectAutoAnnotation(hit);
        e.preventDefault();
        return;
      }
    }
    if (this.annotationSelectionEnabled && this.showAnnotations) {
      const posePoint = this._poseKeypointAtEvent(e);
      if (posePoint >= 0 && this._beginPoseKeypointTransform(
        e, this.selectedAnnotation, posePoint,
      )) {
        e.preventDefault();
        return;
      }
      const handle = this._annotationHandleAtEvent(e);
      if (handle && this._beginAnnotationTransform(e, this.selectedAnnotation, handle)) {
        e.preventDefault();
        return;
      }
      const hit = this._annotationAtEvent(e);
      if (hit >= 0) {
        const accepted = this.onAnnotationSelect
          ? this.onAnnotationSelect(hit) !== false
          : true;
        if (accepted) {
          this.selectedAnnotation = hit;
          if (this.annotations[hit]?.type !== "classification") {
            this._beginAnnotationTransform(e, hit, "move");
          } else {
            this.render();
          }
          e.preventDefault();
          return;
        }
      }
    }
    this._pointer = {
      id: e.pointerId,
      x: e.clientX,
      y: e.clientY,
      startX: e.clientX,
      startY: e.clientY,
      moved: false,
    };
    this.canvas.setPointerCapture(e.pointerId);
    this.canvas.style.cursor = "grabbing";
    e.preventDefault();
  }

  _onPointerMove(e) {
    if ((this.annotationMode === "bbox"
      || (this.annotationMode === "pose" && this._poseStage === "bbox"))
      && this._annotationDraft) {
      const point = this._eventToNormalized(e);
      if (point) this._annotationDraft.end = point;
      this.render();
      return;
    }
    if (
      this.annotationMode === "mask"
      && this._maskActiveStroke
      && e.pointerId === this._maskActiveStroke.id
    ) {
      const point = this._eventToNormalized(e);
      const points = this._maskActiveStroke.stroke.points;
      const last = points.at(-1);
      if (point && (!last || Math.hypot(point[0] - last[0], point[1] - last[1]) > 0.001)) {
        points.push(point);
      }
      this.render();
      return;
    }
    if (this._updateAnnotationTransform(e)) {
      e.preventDefault();
      return;
    }
    if (this._updatePoseKeypointTransform(e)) {
      e.preventDefault();
      return;
    }
    if ((this.annotationSelectionEnabled || this.autoAnnotationSelectionEnabled)
      && !this._pointer && !this._annotationTransform) {
      const handle = this._annotationHandleAtEvent(e);
      this.canvas.style.cursor = handle ? annotationCursor(handle) : "pointer";
    }
    if (this.cropMode || !this._pointer || e.pointerId !== this._pointer.id) return;
    const totalDistance = Math.hypot(
      e.clientX - this._pointer.startX,
      e.clientY - this._pointer.startY,
    );
    if (!this._pointer.moved && totalDistance <= 4) return;
    this._pointer.moved = true;
    this.offsetX += e.clientX - this._pointer.x;
    this.offsetY += e.clientY - this._pointer.y;
    this._pointer.x = e.clientX;
    this._pointer.y = e.clientY;
    this.mode = "custom";
    this._clampOffsets();
    this.render();
  }

  _onPointerUp(e) {
    if (this.annotationMode === "pose" && this._poseStage === "bbox" && this._annotationDraft) {
      const { start, end } = this._annotationDraft;
      const x1 = Math.min(start[0], end[0]), y1 = Math.min(start[1], end[1]);
      const x2 = Math.max(start[0], end[0]), y2 = Math.max(start[1], end[1]);
      this._annotationDraft = null;
      if (x2 - x1 >= 0.002 && y2 - y1 >= 0.002) {
        this._poseBox = {
          x: (x1 + x2) / 2, y: (y1 + y2) / 2, w: x2 - x1, h: y2 - y1,
        };
        this._poseStage = "keypoints";
        this._emitPoseProgress();
      }
      this.render();
      return;
    }
    if (this.annotationMode === "bbox" && this._annotationDraft) {
      const { start, end } = this._annotationDraft;
      const x1 = Math.min(start[0], end[0]), y1 = Math.min(start[1], end[1]);
      const x2 = Math.max(start[0], end[0]), y2 = Math.max(start[1], end[1]);
      const callback = this.annotationCallback;
      const geometry = { x: (x1 + x2) / 2, y: (y1 + y2) / 2, w: x2 - x1, h: y2 - y1 };
      this.cancelAnnotation();
      if (geometry.w >= 0.002 && geometry.h >= 0.002 && callback) callback(geometry);
      return;
    }
    if (this.annotationMode === "mask" && this._maskActiveStroke?.id === e.pointerId) {
      this._maskActiveStroke = null;
      try { this.canvas.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
      this.render();
      return;
    }
    if (this._annotationTransform?.id === e.pointerId) {
      const active = this._annotationTransform;
      if (e.type === "pointerleave" && this.canvas.hasPointerCapture?.(e.pointerId)) return;
      try { this.canvas.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
      if (e.type !== "pointerup" || !active.moved) {
        this._annotationTransform = null;
        this.render();
        return;
      }
      const geometry = this._annotationTransformGeometry(active);
      active.id = null;
      active.pending = true;
      this.canvas.style.cursor = "wait";
      this.render();
      if (!geometry || !this.onAnnotationTransform) {
        this.cancelAnnotationTransform();
        return;
      }
      try {
        Promise.resolve(
          this.onAnnotationTransform(active.index, geometry, active.kind),
        ).then((accepted) => {
          if (accepted === false) this.cancelAnnotationTransform();
        }).catch(() => this.cancelAnnotationTransform());
      } catch (_) {
        this.cancelAnnotationTransform();
      }
      return;
    }
    if (this._posePointTransform?.id === e.pointerId) {
      const active = this._posePointTransform;
      try { this.canvas.releasePointerCapture(e.pointerId); } catch (_) { /* released */ }
      if (!active.moved || !this.onPoseKeypointTransform) {
        this._posePointTransform = null;
        this.render();
        return;
      }
      active.pending = true;
      Promise.resolve(this.onPoseKeypointTransform(
        active.annotationIndex, active.pointIndex, active.point[0], active.point[1],
      )).finally(() => {
        this._posePointTransform = null;
        this.render();
      });
      return;
    }
    if (this._pointer && e.pointerId === this._pointer.id) {
      const pointer = this._pointer;
      this._pointer = null;
      this.canvas.style.cursor = (this.annotationSelectionEnabled || this.autoAnnotationSelectionEnabled)
        ? "pointer" : "grab";
      if (!pointer.moved && e.type === "pointerup" && this.annotationSelectionEnabled) {
        const index = this._annotationAtEvent(e);
        const accepted = this.onAnnotationSelect
          ? this.onAnnotationSelect(index) !== false
          : true;
        if (accepted) this.selectAnnotation(index);
      }
    }
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  _zoomTo(nextScale, anchorX, anchorY) {
    if (!this.image) return;
    const k = nextScale / this.scale;
    this.offsetX = anchorX - (anchorX - this.offsetX) * k;
    this.offsetY = anchorY - (anchorY - this.offsetY) * k;
    this.scale = nextScale;
    this.mode = "custom";
    this._clampOffsets();
    this.render();
  }

  _clampOffsets() {
    const cw = this.canvas.clientWidth;
    const ch = this.canvas.clientHeight;
    const iw = this.naturalW * this.scale;
    const ih = this.naturalH * this.scale;
    const cx = (cw - iw) / 2, cy = (ch - ih) / 2;
    const sx = Math.max(0, (iw - cw) / 2), sy = Math.max(0, (ih - ch) / 2);
    this.offsetX = clamp(this.offsetX, cx - sx, cx + sx);
    this.offsetY = clamp(this.offsetY, cy - sy, cy + sy);
  }

  render() {
    const canvas = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    if (cw === 0 || ch === 0) return;
    if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
      canvas.width = cw * dpr;
      canvas.height = ch * dpr;
    }

    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!this.image) { canvas.style.cursor = "default"; return; }

    canvas.style.cursor = this.annotationMode || this.pointPromptMode || this.cropMode
      ? "crosshair"
      : this._annotationTransform?.pending ? "wait"
          : this._posePointTransform ? "move"
            : this._annotationTransform ? annotationCursor(this._annotationTransform.handle)
          : this._pointer ? "grabbing"
            : (this.annotationSelectionEnabled || this.autoAnnotationSelectionEnabled)
              ? "pointer" : "grab";

    // Fit mode — recalculate ONLY when crop is off
    if (this.mode === "fit" && !this.cropMode) {
      this.scale = Math.min(1, cw / this.naturalW, ch / this.naturalH);
      this.offsetX = (cw - this.naturalW * this.scale) / 2;
      this.offsetY = (ch - this.naturalH * this.scale) / 2;
    }

    // Draw image
    ctx.setTransform(dpr * this.scale, 0, 0, dpr * this.scale, dpr * this.offsetX, dpr * this.offsetY);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(this.image, 0, 0);
    if (this.showAnnotations && this.annotations.length) {
      this._drawAnnotations(ctx);
    }
    if (this.autoAnnotations.length) this._drawAutoAnnotations(ctx);
    if (this.annotationMode) this._drawAnnotationDraft(ctx);
    ctx.setTransform(1, 0, 0, 1, 0, 0);

    setState({ zoom: this.scale, fit: this.mode === "fit" });
    if (this.onChange) this.onChange({ scale: this.scale, percent: this.zoomPercent(), mode: this.mode });

    // Keep the crop selection glued to the picture after any re-render
    // (resize, zoom…) — the selection lives in image space, so it simply
    // follows the image wherever it is drawn.
    if (this.cropMode) this._syncCropOverlay();
  }

  _drawAnnotations(ctx) {
    const scale = Math.max(this.scale, 0.0001);
    ctx.lineWidth = 2 / scale;
    ctx.font = `600 ${12 / scale}px Segoe UI, sans-serif`;
    ctx.textBaseline = "top";
    for (const [index, annotation] of this.annotations.entries()) {
      if (this.hiddenAnnotations.has(index)) continue;
      if (
        this.annotationMode === "mask" && this._maskBaseRle
        && index === this.selectedAnnotation
      ) continue;
      const autoMetadata = annotation?.metadata?.auto_annotate;
      const needsReview = !!autoMetadata?.needs_review;
      const color = needsReview ? "#ffad33" : annotationColor(Number(annotation.class_id) || 0);
      if (annotation.type === "classification") {
        const baseLabel = String(annotation.label || `class_${annotation.class_id ?? 0}`);
        const label = needsReview ? `${baseLabel} · Needs review` : baseLabel;
        const y = 8 + index * 24;
        const labelWidth = ctx.measureText(label).width + 12 / scale;
        ctx.fillStyle = color;
        ctx.fillRect(8, y, labelWidth, 20 / scale);
        ctx.fillStyle = "#fff";
        ctx.fillText(label, 14 / scale, y + 2 / scale);
        if (index === this.selectedAnnotation) {
          ctx.save();
          ctx.strokeStyle = "#fff";
          ctx.setLineDash([6 / scale, 4 / scale]);
          ctx.strokeRect(8, y, labelWidth, 20 / scale);
          ctx.restore();
        }
        continue;
      }
      const sourceBounds = annotationBounds(annotation);
      if (!sourceBounds) continue;
      const transform = this._annotationTransform?.index === index
        ? this._annotationTransform
        : null;
      const drawBounds = transform?.rect || sourceBounds;
      const x = drawBounds.left * this.naturalW;
      const y = drawBounds.top * this.naturalH;
      const width = (drawBounds.right - drawBounds.left) * this.naturalW;
      const height = (drawBounds.bottom - drawBounds.top) * this.naturalH;
      if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) continue;
      ctx.strokeStyle = color;
      if (annotation.type === "pose" && Array.isArray(annotation.keypoints)) {
        let points = transform
          ? scalePoseKeypoints(annotation.keypoints, sourceBounds, drawBounds)
          : annotation.keypoints;
        if (this._posePointTransform?.annotationIndex === index) {
          points = points.map((point, pointIndex) => pointIndex === this._posePointTransform.pointIndex
            ? { ...point, x: this._posePointTransform.point[0], y: this._posePointTransform.point[1] }
            : point);
        }
        const skeleton = annotation?.metadata?.pose?.skeleton || [];
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2.5 / scale;
        for (const edge of skeleton) {
          const start = points[Number(edge[0])], end = points[Number(edge[1])];
          if (!start || !end || Number(start.visibility) <= 0 || Number(end.visibility) <= 0) {
            continue;
          }
          ctx.beginPath();
          ctx.moveTo(Number(start.x) * this.naturalW, Number(start.y) * this.naturalH);
          ctx.lineTo(Number(end.x) * this.naturalW, Number(end.y) * this.naturalH);
          ctx.stroke();
        }
        if (annotation.pose_has_bbox) ctx.strokeRect(x, y, width, height);
        points.forEach((point, pointIndex) => {
          if (Number(point.visibility) <= 0) return;
          const pointX = Number(point.x) * this.naturalW;
          const pointY = Number(point.y) * this.naturalH;
          ctx.beginPath();
          ctx.fillStyle = Number(point.visibility) === 1 ? "#ffad33" : color;
          ctx.arc(pointX, pointY, 5 / scale, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.25 / scale;
          ctx.stroke();
          if (index === this.selectedAnnotation) {
            ctx.fillStyle = "#ffffff";
            ctx.font = `600 ${9 / scale}px Segoe UI, sans-serif`;
            ctx.fillText(String(pointIndex + 1), pointX + 6 / scale, pointY - 5 / scale);
          }
        });
        ctx.restore();
      } else if (annotation.type === "mask" && annotation.mask_rle) {
        const maskCanvas = this._maskCanvas(annotation.mask_rle, color);
        if (maskCanvas) {
          ctx.save();
          ctx.globalAlpha = 0.38;
          if (transform) {
            ctx.drawImage(
              maskCanvas,
              sourceBounds.left * maskCanvas.width,
              sourceBounds.top * maskCanvas.height,
              (sourceBounds.right - sourceBounds.left) * maskCanvas.width,
              (sourceBounds.bottom - sourceBounds.top) * maskCanvas.height,
              x,
              y,
              width,
              height,
            );
          } else {
            ctx.drawImage(maskCanvas, 0, 0, this.naturalW, this.naturalH);
          }
          ctx.restore();
        }
        ctx.strokeRect(x, y, width, height);
      } else if (Array.isArray(annotation.polygon) && annotation.polygon.length >= 3) {
        const points = transform
          ? scalePolygonPoints(annotation.polygon, sourceBounds, drawBounds)
          : annotation.polygon;
        ctx.beginPath();
        points.forEach((point, pointIndex) => {
          const px = Number(point[0]) * this.naturalW;
          const py = Number(point[1]) * this.naturalH;
          if (pointIndex === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        });
        ctx.closePath();
        ctx.globalAlpha = 0.18;
        ctx.fillStyle = color;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.stroke();
      } else {
        ctx.strokeRect(x, y, width, height);
      }
      const baseLabel = String(annotation.label || `class_${annotation.class_id ?? 0}`);
      const label = needsReview ? `${baseLabel} · Needs review` : baseLabel;
      const padding = 3 / scale;
      const textWidth = ctx.measureText(label).width;
      const textHeight = 15 / scale;
      const labelY = Math.max(0, y - textHeight);
      ctx.fillStyle = color;
      ctx.fillRect(x, labelY, textWidth + padding * 2, textHeight);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(label, x + padding, labelY + 1 / scale);
      if (index === this.selectedAnnotation) {
        ctx.save();
        ctx.strokeStyle = "#fff";
        ctx.setLineDash([6 / scale, 4 / scale]);
        ctx.strokeRect(x, y, width, height);
        ctx.restore();
        if (this.annotationSelectionEnabled && !this.annotationMode) {
          this._drawAnnotationHandles(ctx, drawBounds);
        }
      }
    }
  }

  _drawAnnotationHandles(ctx, bounds) {
    const scale = Math.max(this.scale, 0.0001);
    const size = 9 / scale;
    ctx.save();
    ctx.lineWidth = 1.5 / scale;
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#24c987";
    for (const point of Object.values(annotationHandles(bounds))) {
      const x = point[0] * this.naturalW - size / 2;
      const y = point[1] * this.naturalH - size / 2;
      ctx.fillRect(x, y, size, size);
      ctx.strokeRect(x, y, size, size);
    }
    ctx.restore();
  }

  _drawAutoAnnotations(ctx) {
    const scale = Math.max(this.scale, 0.0001);
    ctx.save();
    ctx.lineWidth = 2.5 / scale;
    ctx.font = `700 ${11 / scale}px Segoe UI, sans-serif`;
    ctx.textBaseline = "top";
    for (const [index, candidate] of this.autoAnnotations.entries()) {
      const enabled = candidate.enabled !== false;
      const score = Math.round(Number(candidate.score || candidate.quality || 0) * 100);
      const candidateType = String(candidate.type || "bbox");
      const candidateLabel = String(candidate.class_label || candidate.label || candidate.shape || candidateType);
      const baseColor = enabled ? "#8a7dff" : "#7c8494";
      if (candidateType === "classification") {
        const label = `${candidate.rank ? `#${candidate.rank} ` : ""}${candidateLabel} · ${score}%`;
        const y = 8 + index * (24 / scale);
        const padding = 5 / scale;
        const width = ctx.measureText(label).width + padding * 2;
        ctx.globalAlpha = enabled ? 1 : 0.45;
        ctx.fillStyle = baseColor;
        ctx.fillRect(8 / scale, y, width, 19 / scale);
        ctx.fillStyle = "#fff";
        ctx.fillText(label, 8 / scale + padding, y + 2 / scale);
        continue;
      }
      const box = candidate?.bbox || {};
      const x = (Number(box.x) - Number(box.w) / 2) * this.naturalW;
      const y = (Number(box.y) - Number(box.h) / 2) * this.naturalH;
      const width = Number(box.w) * this.naturalW;
      const height = Number(box.h) * this.naturalH;
      if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) continue;
      const needsReview = !!candidate.needs_review;
      const color = !enabled ? "#7c8494" : needsReview ? "#ffad33" : baseColor;
      ctx.globalAlpha = enabled ? 1 : 0.42;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      if (!enabled) ctx.setLineDash([5 / scale, 5 / scale]);
      else ctx.setLineDash([]);
      const polygon = Array.isArray(candidate.polygon) ? candidate.polygon : [];
      if (candidateType === "mask" && candidate.mask_rle) {
        const maskCanvas = this._maskCanvas(candidate.mask_rle, color);
        if (maskCanvas) {
          ctx.save();
          ctx.globalAlpha = enabled ? 0.3 : 0.12;
          ctx.drawImage(maskCanvas, 0, 0, this.naturalW, this.naturalH);
          ctx.restore();
        }
        ctx.strokeRect(x, y, width, height);
      } else if (candidateType === "pose" && Array.isArray(candidate.keypoints)) {
        const visible = candidate.keypoints.map(point => ({
          x: Number(point.x) * this.naturalW,
          y: Number(point.y) * this.naturalH,
          v: Number(point.visibility || 0),
        }));
        const edges = [[0,1],[0,2],[1,3],[2,4],[5,6],[5,7],[7,9],[6,8],[8,10],
          [5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16]];
        ctx.strokeStyle = color;
        ctx.setLineDash([]);
        for (const [a, b] of edges) {
          if (!visible[a]?.v || !visible[b]?.v) continue;
          ctx.beginPath(); ctx.moveTo(visible[a].x, visible[a].y);
          ctx.lineTo(visible[b].x, visible[b].y); ctx.stroke();
        }
        ctx.fillStyle = color;
        for (const point of visible) {
          if (!point.v) continue;
          ctx.beginPath(); ctx.arc(point.x, point.y, 4 / scale, 0, Math.PI * 2); ctx.fill();
        }
        ctx.strokeRect(x, y, width, height);
      } else if (polygon.length >= 3) {
        ctx.beginPath();
        polygon.forEach((point, pointIndex) => {
          const px = Number(point[0]) * this.naturalW;
          const py = Number(point[1]) * this.naturalH;
          if (pointIndex === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        });
        ctx.closePath();
        ctx.save();
        ctx.globalAlpha = enabled ? 0.12 : 0.05;
        ctx.fill();
        ctx.restore();
        ctx.stroke();
      } else {
        ctx.strokeRect(x, y, width, height);
      }
      const shape = candidateLabel;
      const quality = score;
      const mapping = candidate.class_label ? ` → ${candidate.class_label}` : "";
      const review = needsReview ? " · Needs review" : "";
      const label = `${shape}${mapping} · ${quality}%${review}`;
      const padding = 3 / scale;
      const labelHeight = 15 / scale;
      const labelY = Math.max(0, y - labelHeight);
      const labelWidth = ctx.measureText(label).width + padding * 2;
      ctx.fillStyle = color;
      ctx.fillRect(x, labelY, labelWidth, labelHeight);
      ctx.fillStyle = "#fff";
      ctx.fillText(label, x + padding, labelY + 1 / scale);
      if (index === this.selectedAutoAnnotation) {
        ctx.save();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2 / scale;
        ctx.setLineDash([7 / scale, 4 / scale]);
        ctx.strokeRect(x, y, width, height);
        ctx.restore();
      }
    }
    ctx.restore();
  }

  _maskCanvas(rle, color) {
    const size = Array.isArray(rle?.size) ? rle.size : [];
    const height = Number(size[0]), width = Number(size[1]);
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) return null;
    const raw = rle.counts;
    const key = `${height}x${width}:${color}:${Array.isArray(raw) ? raw.join(",") : String(raw)}`;
    if (this._maskCache.has(key)) return this._maskCache.get(key);
    let counts;
    try { counts = decodeCocoCounts(raw); } catch (_) { return null; }
    if (counts.reduce((sum, value) => sum + value, 0) !== width * height) return null;
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    const maskCtx = canvas.getContext("2d");
    const pixels = maskCtx.createImageData(width, height);
    let cursor = 0, foreground = false;
    for (const run of counts) {
      const end = cursor + run;
      if (foreground) {
        for (let index = cursor; index < end; index += 1) {
          const x = Math.floor(index / height), y = index % height;
          const pixel = (y * width + x) * 4;
          pixels.data[pixel] = 255;
          pixels.data[pixel + 1] = 255;
          pixels.data[pixel + 2] = 255;
          pixels.data[pixel + 3] = 255;
        }
      }
      cursor = end; foreground = !foreground;
    }
    maskCtx.putImageData(pixels, 0, 0);
    maskCtx.globalCompositeOperation = "source-in";
    maskCtx.fillStyle = color;
    maskCtx.fillRect(0, 0, width, height);
    maskCtx.globalCompositeOperation = "source-over";
    if (this._maskCache.size > 32) this._maskCache.clear();
    this._maskCache.set(key, canvas);
    return canvas;
  }

  _drawAnnotationDraft(ctx) {
    const scale = Math.max(this.scale, 0.0001);
    ctx.save();
    ctx.lineWidth = 2 / scale;
    ctx.strokeStyle = "#55a0ff";
    ctx.fillStyle = "rgba(85,160,255,.18)";
    if ((this.annotationMode === "bbox"
      || (this.annotationMode === "pose" && this._poseStage === "bbox"))
      && this._annotationDraft) {
      const { start, end } = this._annotationDraft;
      const x = Math.min(start[0], end[0]) * this.naturalW;
      const y = Math.min(start[1], end[1]) * this.naturalH;
      const w = Math.abs(end[0] - start[0]) * this.naturalW;
      const h = Math.abs(end[1] - start[1]) * this.naturalH;
      ctx.fillRect(x, y, w, h); ctx.strokeRect(x, y, w, h);
    } else if (this.annotationMode === "pose") {
      if (this._poseBox) {
        const x = (this._poseBox.x - this._poseBox.w / 2) * this.naturalW;
        const y = (this._poseBox.y - this._poseBox.h / 2) * this.naturalH;
        ctx.strokeRect(x, y, this._poseBox.w * this.naturalW, this._poseBox.h * this.naturalH);
      }
      for (const point of this._posePoints) {
        if (Number(point.visibility) <= 0) continue;
        ctx.beginPath();
        ctx.arc(point.x * this.naturalW, point.y * this.naturalH, 5 / scale, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    } else if (this.annotationMode === "polygon" && this._polygonPoints.length) {
      ctx.beginPath();
      this._polygonPoints.forEach((point, index) => {
        const x = point[0] * this.naturalW, y = point[1] * this.naturalH;
        if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      for (const point of this._polygonPoints) {
        ctx.beginPath(); ctx.arc(point[0] * this.naturalW, point[1] * this.naturalH, 4 / scale, 0, Math.PI * 2); ctx.fill();
      }
    } else if (this.annotationMode === "mask") {
      this._drawMaskDraft(ctx);
    }
    ctx.restore();
  }

  _drawMaskDraft(ctx) {
    let draft = this._maskDraftCanvas;
    if (!draft || draft.width !== this.naturalW || draft.height !== this.naturalH) {
      draft = document.createElement("canvas");
      draft.width = this.naturalW; draft.height = this.naturalH;
      this._maskDraftCanvas = draft;
    }
    const draftCtx = draft.getContext("2d");
    draftCtx.clearRect(0, 0, draft.width, draft.height);
    if (this._maskBaseRle) {
      const base = this._maskCanvas(this._maskBaseRle, "#55a0ff");
      if (base) draftCtx.drawImage(base, 0, 0, this.naturalW, this.naturalH);
    }
    draftCtx.lineCap = "round";
    draftCtx.lineJoin = "round";
    for (const stroke of this._maskStrokes) {
      if (!stroke.points.length) continue;
      draftCtx.globalCompositeOperation = stroke.erase ? "destination-out" : "source-over";
      draftCtx.lineWidth = stroke.brushSize;
      draftCtx.strokeStyle = "#55a0ff";
      draftCtx.fillStyle = "#55a0ff";
      draftCtx.beginPath();
      stroke.points.forEach((point, index) => {
        const x = point[0] * this.naturalW, y = point[1] * this.naturalH;
        if (index === 0) draftCtx.moveTo(x, y); else draftCtx.lineTo(x, y);
      });
      if (stroke.points.length === 1) {
        const point = stroke.points[0];
        draftCtx.arc(
          point[0] * this.naturalW, point[1] * this.naturalH,
          stroke.brushSize / 2, 0, Math.PI * 2,
        );
        draftCtx.fill();
      } else draftCtx.stroke();
    }
    draftCtx.globalCompositeOperation = "source-over";
    ctx.save();
    ctx.globalAlpha = 0.48;
    ctx.drawImage(draft, 0, 0);
    ctx.restore();
  }
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function annotationColor(classId) {
  const hue = ((classId * 67) + 205) % 360;
  return `hsl(${hue} 82% 55%)`;
}

function annotationBounds(annotation) {
  if (!annotation || annotation.type === "classification") return null;
  const centerX = Number(annotation.x);
  const centerY = Number(annotation.y);
  const width = Number(annotation.w);
  const height = Number(annotation.h);
  const values = [centerX, centerY, width, height];
  if (!values.every(Number.isFinite) || width <= 0 || height <= 0) return null;
  return {
    left: centerX - width / 2,
    top: centerY - height / 2,
    right: centerX + width / 2,
    bottom: centerY + height / 2,
  };
}

function annotationHandles(bounds) {
  const centerX = (bounds.left + bounds.right) / 2;
  const centerY = (bounds.top + bounds.bottom) / 2;
  return {
    nw: [bounds.left, bounds.top],
    n: [centerX, bounds.top],
    ne: [bounds.right, bounds.top],
    e: [bounds.right, centerY],
    se: [bounds.right, bounds.bottom],
    s: [centerX, bounds.bottom],
    sw: [bounds.left, bounds.bottom],
    w: [bounds.left, centerY],
  };
}

function annotationCursor(handle) {
  if (handle === "move") return "move";
  if (["nw", "se"].includes(handle)) return "nwse-resize";
  if (["ne", "sw"].includes(handle)) return "nesw-resize";
  if (["n", "s"].includes(handle)) return "ns-resize";
  return "ew-resize";
}

function scalePolygonPoints(rawPoints, source, target) {
  const sourceWidth = source.right - source.left;
  const sourceHeight = source.bottom - source.top;
  const targetWidth = target.right - target.left;
  const targetHeight = target.bottom - target.top;
  if (sourceWidth <= 0 || sourceHeight <= 0) return rawPoints;
  return rawPoints.map((point) => [
    target.left + ((Number(point[0]) - source.left) / sourceWidth) * targetWidth,
    target.top + ((Number(point[1]) - source.top) / sourceHeight) * targetHeight,
  ]);
}

function scalePoseKeypoints(rawPoints, source, target) {
  const sourceWidth = source.right - source.left;
  const sourceHeight = source.bottom - source.top;
  const targetWidth = target.right - target.left;
  const targetHeight = target.bottom - target.top;
  if (sourceWidth <= 0 || sourceHeight <= 0) return rawPoints;
  return rawPoints.map((point) => {
    if (Number(point.visibility) <= 0) return { ...point };
    return {
      ...point,
      x: target.left + ((Number(point.x) - source.left) / sourceWidth) * targetWidth,
      y: target.top + ((Number(point.y) - source.top) / sourceHeight) * targetHeight,
    };
  });
}

function pointInPolygon(x, y, rawPoints) {
  const points = rawPoints
    .map((point) => [Number(point?.[0]), Number(point?.[1])])
    .filter((point) => point.every(Number.isFinite));
  if (points.length < 3) return false;
  let inside = false;
  for (let current = 0, previous = points.length - 1; current < points.length; previous = current++) {
    const [cx, cy] = points[current];
    const [px, py] = points[previous];
    const crosses = ((cy > y) !== (py > y))
      && x < ((px - cx) * (y - cy)) / (py - cy) + cx;
    if (crosses) inside = !inside;
  }
  return inside;
}

function decodeCocoCounts(raw) {
  if (Array.isArray(raw)) return raw.map((value) => Number(value));
  if (typeof raw !== "string") throw new Error("Invalid RLE counts");
  const counts = [];
  let position = 0;
  while (position < raw.length) {
    let value = 0, shift = 0, more = true, char = 0;
    while (more) {
      if (position >= raw.length) throw new Error("Truncated RLE counts");
      char = raw.charCodeAt(position) - 48;
      position += 1;
      if (char < 0 || char > 63) throw new Error("Invalid RLE character");
      value += (char & 31) * (2 ** (5 * shift));
      more = !!(char & 32);
      shift += 1;
    }
    if (char & 16) value -= 2 ** (5 * shift);
    if (counts.length > 2) value += counts[counts.length - 2];
    if (!Number.isInteger(value) || value < 0) throw new Error("Invalid RLE run");
    counts.push(value);
  }
  return counts;
}
