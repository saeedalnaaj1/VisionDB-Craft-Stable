// Sidebar: tabbed control panels, collapse/expand, and dock position.
// The panel builders are imported here; each returns once its controls are
// ready to be refreshed from backend state.

import { call } from "./api.js";
import { applyBackendState, setEditParams, setState, state, subscribeBackend } from "./state.js";
import { makePanelCtx } from "./panels/common.js";
import { buildTransformPanel } from "./panels/transform.js";
import { buildAugmentPanel } from "./panels/augment.js";
import { buildResizePanel } from "./panels/resize.js";
import { buildExportPanel } from "./panels/export.js";
import { buildDatasetPanel } from "./panels/dataset.js";
import { buildHistoryPanel } from "./panels/history.js";
import { buildAnnotationPanel } from "./panels/annotation.js";

const TABS = [
  { id: "transform", label: "Transform", build: buildTransformPanel },
  { id: "augment", label: "Augment", build: buildAugmentPanel },
  { id: "resize", label: "Resize", build: buildResizePanel },
  { id: "export", label: "Export", build: buildExportPanel },
  { id: "dataset", label: "Dataset", build: buildDatasetPanel },
  { id: "history", label: "History", build: buildHistoryPanel },
  { id: "annotation", label: "Annotate", build: buildAnnotationPanel },
];

const MODE_TAB = {
  transform: "transform",
  augment: "augment",
  annotate: "annotation",
  auto_annotate: "auto_annotate",
  ai_annotate: "local_ai",
};
const SHARED_TABS = new Set(["resize", "export", "history", "dataset"]);

// Panel builders can register a refresh hook so slider values re-sync with the
// backend defaults whenever an image loads or a state payload arrives.
const refreshers = new Map();

export function registerRefresher(id, fn) {
  refreshers.set(id, fn);
}

// Optional hooks run just before the user switches away from a tab — lets a
// modal panel (e.g. free-crop) cancel its transient mode so the viewer doesn't
// stay frozen while editing from another tab.
const leaveHooks = new Map();
export function onTabLeave(id, fn) {
  leaveHooks.set(id, fn);
}

const pendingApplyGuards = new Map();
export function registerPendingApplyGuard(id, fn) {
  pendingApplyGuards.set(id, fn);
}

const bodies = new Map(); // id -> element
let activeId = "transform";

// Panel context. `configurePanelHooks` (called from app.js) injects the viewer,
// status-bar writer, after-state hook and toast functions.
const panelHooks = {
  viewer: null,
  setStatus: null,
  afterState: null,
  toast: null,
  refresh: () => refreshAll(),
};
const ctx = makePanelCtx(panelHooks);

/** Inject runtime hooks (viewer, status, toasts) from the app layer. */
export function configurePanelHooks(extra) {
  Object.assign(panelHooks, extra);
}

export function initSidebar() {
  const tabsEl = document.getElementById("sidebar-tabs");
  const bodyEl = document.getElementById("sidebar-body");
  tabsEl.innerHTML = "";
  bodyEl.innerHTML = "";

  for (const tab of TABS) {
    const tabBtn = document.createElement("button");
    tabBtn.textContent = tab.label;
    tabBtn.dataset.tab = tab.id;
    tabBtn.addEventListener("click", () => setActive(tab.id));
    tabsEl.append(tabBtn);

    const body = document.createElement("div");
    body.className = "sidebar-panel";
    body.dataset.panel = tab.id;
    bodyEl.append(body);
    bodies.set(tab.id, body);

    tab.build(body, ctx);
  }
  setSidebarWorkingMode(state.workingMode || "transform", { activatePrimary: true });
  document.addEventListener("imagecraft:open-augmentation-recipes", () => {
    setActive("augment");
    document.dispatchEvent(new CustomEvent("imagecraft:show-augmentation-recipes"));
  });

  // Re-sync the active panel's controls whenever backend state changes
  // (image load, apply, undo, reset) or any UI state updates.
  subscribeBackend((s, info) => {
    const fn = refreshers.get(activeId);
    if (fn) fn(s, info);
  });

  // Collapse / expand
  document.getElementById("sb-collapse").addEventListener("click", toggleCollapsed);
  // Dock position cycle
  document.getElementById("sb-dock").addEventListener("click", cycleDock);
  initSidebarResizer();
  // Live preview toggle
  const liveCb = document.getElementById("sb-live-preview");
  if (liveCb) {
    liveCb.checked = state.livePreview;
    liveCb.addEventListener("change", () => {
      setState({ livePreview: !!liveCb.checked });
      call("set_config", "live_preview", !!liveCb.checked).catch(() => {});
    });
  }

  // Restore persisted layout.
  applyLayout(state.sidebarDock || "right", !!state.sidebarCollapsed);
}

/** Absolutely apply a dock position and collapsed state to the DOM. */
export function applyLayout(dock, collapsed) {
  setDock(dock);
  const sidebar = document.getElementById("sidebar");
  sidebar.classList.toggle("collapsed", collapsed);
  document.getElementById("sb-collapse").textContent = collapsed ? "❯" : "❮";
  setState({ sidebarDock: dock, sidebarCollapsed: collapsed });
}

export function setSidebarWidth(width) {
  const available = Math.max(300, Math.min(720, window.innerWidth - 320));
  const safeWidth = Math.max(300, Math.min(available, Number(width) || 380));
  const sidebar = document.getElementById("sidebar");
  setState({ sidebarWidth: safeWidth });
  sidebar.style.setProperty("--sidebar-current-w", `${safeWidth}px`);
}

export function setActive(id) {
  const visible = SHARED_TABS.has(id) || MODE_TAB[state.workingMode] === id;
  if (!visible) return false;
  // When leaving a tab that has pending (previewed-but-unapplied) edits,
  // commit them so item.active is up-to-date for the new tab's live preview.
  // Without this, switching from Transform → Augment and moving a slider
  // would preview augment on the *original* active image, making the
  // transform visually disappear even though it was never discarded.
  if (activeId !== id && state.editParams[activeId] != null) {
    const pending = state.editParams[activeId];
    const guard = pendingApplyGuards.get(activeId);
    if (guard && !guard(pending)) return false;
    const prevTool = activeId;              // capture before it changes
    setEditParams(prevTool, null);          // clear immediately to avoid double-apply
    call("apply", prevTool, pending)
      .then((p) => {
        if (p && !p.error) {
          applyBackendState(p, { tool: prevTool });
          if (prevTool === "augment" && !state.repeatAugmentation) {
            document.dispatchEvent(new CustomEvent("imagecraft:augmentation-committed"));
          }
          if (prevTool === "transform" && !state.repeatTransform) {
            document.dispatchEvent(new CustomEvent("imagecraft:transform-committed"));
          }
          if (panelHooks.afterState) panelHooks.afterState();
        }
      })
      .catch(() => {});
  }
  const leave = leaveHooks.get(activeId);
  if (leave) leave();
  activeId = id;
  setState({ activeTool: id });
  for (const b of document.querySelectorAll(".sidebar-tabs button")) {
    b.classList.toggle("active", b.dataset.tab === id);
  }
  for (const [pid, body] of bodies) {
    body.classList.toggle("active", pid === id);
  }
  refreshActive();
  return true;
}

/** Show one focused workflow plus the shared Resize/Export/History/Dataset tools. */
export function setSidebarWorkingMode(mode, { activatePrimary = true } = {}) {
  const normalized = Object.hasOwn(MODE_TAB, mode) ? mode : "transform";
  setState({ workingMode: normalized });
  const primary = MODE_TAB[normalized];
  const sharedOrder = { resize: 1, export: 2, history: 3, dataset: 4 };
  for (const button of document.querySelectorAll(".sidebar-tabs button")) {
    const visible = button.dataset.tab === primary || SHARED_TABS.has(button.dataset.tab);
    button.hidden = !visible;
    button.style.order = String(button.dataset.tab === primary ? 0 : (sharedOrder[button.dataset.tab] || 9));
  }
  for (const [id, body] of bodies) {
    const visible = id === primary || SHARED_TABS.has(id);
    body.dataset.modeVisible = String(visible);
    if (!visible) body.classList.remove("active");
  }
  if (activatePrimary || (!SHARED_TABS.has(activeId) && activeId !== primary)) {
    setActive(primary);
  }
  document.dispatchEvent(new CustomEvent("imagecraft:working-mode-changed", {
    detail: { mode: normalized, primaryTab: primary },
  }));
}

export function toggleCollapsed() {
  const sidebar = document.getElementById("sidebar");
  const collapsed = !state.sidebarCollapsed;
  sidebar.classList.toggle("collapsed", collapsed);
  setState({ sidebarCollapsed: collapsed });
  document.getElementById("sb-collapse").textContent = collapsed ? "❯" : "❮";
}

export function cycleDock() {
  const order = ["right", "left", "bottom"];
  const next = order[(order.indexOf(state.sidebarDock) + 1) % order.length];
  setDock(next);
  call("set_config", "sidebar_location", next).catch(() => {});
}

export function setDock(dock) {
  const sidebar = document.getElementById("sidebar");
  sidebar.dataset.dock = dock;
  const content = document.getElementById("content");
  if (content) content.dataset.dock = dock;
  setState({ sidebarDock: dock });
}

function initSidebarResizer() {
  const handle = document.getElementById("sidebar-resizer");
  const sidebar = document.getElementById("sidebar");
  if (!handle || !sidebar) return;
  let startX = 0;
  let startWidth = 0;
  let dock = "right";

  handle.addEventListener("pointerdown", (event) => {
    if (state.sidebarDock === "bottom" || state.sidebarCollapsed) return;
    startX = event.clientX;
    startWidth = sidebar.getBoundingClientRect().width;
    dock = state.sidebarDock;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing-sidebar");
    event.preventDefault();
  });
  handle.addEventListener("pointermove", (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    const delta = dock === "right" ? startX - event.clientX : event.clientX - startX;
    setSidebarWidth(startWidth + delta);
  });
  const finish = (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    handle.releasePointerCapture(event.pointerId);
    document.body.classList.remove("resizing-sidebar");
    call("set_config", "sidebar_width", state.sidebarWidth).catch(() => {});
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("dblclick", () => {
    setSidebarWidth(380);
    call("set_config", "sidebar_width", 380).catch(() => {});
  });
}

function refreshActive() {
  const fn = refreshers.get(activeId);
  if (fn) fn(state);
}

function refreshAll() {
  for (const fn of refreshers.values()) fn(state, { reset: true });
  // Re-sync the viewer so it doesn't show a stale preview after controls reset.
  if (panelHooks.afterState) panelHooks.afterState();
}

export function refreshSidebar() {
  refreshAll();
}
