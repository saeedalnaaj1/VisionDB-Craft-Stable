// Before/after comparison slider. Draws the original image behind a clipped
// "processed" image; a draggable divider controls the clip. Clicking anywhere
// in the stage also moves the divider to that point.

import { call } from "./api.js";
import { setState, state } from "./state.js";

const host = document.getElementById("compare");
let stage;
let canvas;
let ctx;
let divider;
let original = null; // HTMLImageElement
let processed = null; // HTMLImageElement
let split = 0.5;
let dragging = false;
let ro;

export function initCompare() {
  host.innerHTML = `
    <div class="compare-stage">
      <canvas></canvas>
      <div class="divider"></div>
      <span class="tag before">Before</span>
      <span class="tag after">After</span>
    </div>`;
  stage = host.querySelector(".compare-stage");
  canvas = host.querySelector("canvas");
  ctx = canvas.getContext("2d");
  divider = host.querySelector(".divider");

  host.addEventListener("pointerdown", (e) => {
    dragging = true;
    host.setPointerCapture(e.pointerId);
    e.preventDefault();
    _moveDivider(e);
  });
  host.addEventListener("pointermove", (e) => {
    if (dragging) _moveDivider(e);
  });
  host.addEventListener("pointerup", () => {
    dragging = false;
  });
  host.addEventListener("pointercancel", () => {
    dragging = false;
  });

  ro = new ResizeObserver(() => _draw());
  if (stage) ro.observe(stage);
}

function _moveDivider(e) {
  const rect = canvas.getBoundingClientRect();
  split = clamp((e.clientX - rect.left) / rect.width, 0, 1);
  divider.style.left = `${split * 100}%`;
  _draw();
}

export async function showCompare() {
  if (!state.current) return;
  setState({ compareOn: true });
  host.hidden = false;
  try {
    const res = await call("get_compare");
    if (!res.original) {
      setState({ compareOn: false });
      host.hidden = true;
      return;
    }
    const [o, p] = await Promise.all([loadImage(res.original), loadImage(res.processed)]);
    original = o;
    processed = p;
    split = 0.5;
    divider.style.left = "50%";
    _draw();
  } catch (e) {
    console.warn("compare failed:", e);
    setState({ compareOn: false });
    host.hidden = true;
  }
}

export function hideCompare() {
  setState({ compareOn: false });
  host.hidden = true;
  original = null;
  processed = null;
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("decode failed"));
    img.src = dataUrl;
  });
}

// Fit an image "contain" style into (cw, ch), centred.
function fitRect(iw, ih, cw, ch) {
  const s = Math.min(cw / iw, ch / ih);
  const dw = iw * s;
  const dh = ih * s;
  return { x: (cw - dw) / 2, y: (ch - dh) / 2, w: dw, h: dh };
}

function _draw() {
  if (!original || !processed) return;
  const dpr = window.devicePixelRatio || 1;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  if (cw === 0 || ch === 0) return;
  if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
    canvas.width = cw * dpr;
    canvas.height = ch * dpr;
  }

  // Common box: use the larger dimensions so both images fit.
  const boxW = Math.max(original.naturalWidth, processed.naturalWidth);
  const boxH = Math.max(original.naturalHeight, processed.naturalHeight);

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = getComputedStyle(host).backgroundColor;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const ro = fitRect(boxW, boxH, canvas.width, canvas.height);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";

  // Original, full.
  _drawFitted(original, ro);

  // Processed, clipped right of the divider.
  const clipX = ro.x + ro.w * split;
  ctx.save();
  ctx.beginPath();
  ctx.rect(clipX, ro.y, canvas.width - clipX, ro.h);
  ctx.clip();
  _drawFitted(processed, ro);
  ctx.restore();

  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function _drawFitted(img, ro) {
  ctx.drawImage(img, ro.x, ro.y, ro.w, ro.h);
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}
