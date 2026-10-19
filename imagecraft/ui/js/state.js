// Minimal reactive store. Components subscribe; the store is patched by the
// app layer after every backend call that returns state.

const backendListeners = new Set();
const uiListeners = new Set();

export const state = {
  ready: false,
  theme: "dark",
  images: [],
  currentIndex: -1,
  currentPath: null,
  current: null, // { name, w, h, modified }
  defaults: { transform: {}, augment: {} },
  editParams: { transform: null, augment: null, resize: null },
  activeTool: "transform",
  workingMode: "transform",
  livePreview: true,
  repeatAugmentation: false,
  repeatTransform: false,
  history: { canUndo: false, canRedo: false },
  historyTimeline: { position: 0, base_label: "Original", truncated: false, entries: [] },
  dataset: { active: false },
  annotationEditor: {
    available: false,
    classes: [],
    annotations: [],
    type_counts_current: { classification: 0, bbox: 0, polygon: 0, mask: 0 },
    type_counts_all: { classification: 0, bbox: 0, polygon: 0, mask: 0 },
  },
  workspace: { kind: "empty" },
  project: { path: null, name: null, ui_state: {} },
  hasUnsavedWork: false,
  autoAnnotatePreview: { candidates: [], config: {} },
  autoAnnotateUi: {},
  localAI: { task: "classification", model_id: "clip-vit-b32", proposals: [], job: { status: "idle" } },
  localAIUi: {},
  projectViewRestorePending: null,
  // Viewer / UI
  zoom: 1,
  fit: true,
  compareOn: false,
  sidebarCollapsed: false,
  sidebarDock: "right",
  sidebarWidth: 380,
  // The next decoded image should reset the viewport only when the backend
  // actually switched images. Annotation refreshes keep zoom and pan.
  viewResetRequested: true,
  busy: false,
};

export function setState(patch) {
  Object.assign(state, patch);
  for (const fn of uiListeners) fn(state);
}

export function getState() {
  return state;
}

export function subscribe(fn) {
  uiListeners.add(fn);
  return () => uiListeners.delete(fn);
}

export function subscribeBackend(fn) {
  backendListeners.add(fn);
  return () => backendListeners.delete(fn);
}

export function setEditParams(tool, params) {
  state.editParams[tool] = params ? { ...params } : null;
}

// Convenience: map a backend state payload onto the store.
export function applyBackendState(payload, opts = {}) {
  const imageSwitched =
    payload.current_path !== state.currentPath ||
    payload.current_index !== state.currentIndex;
  const reset = opts.resetControls || imageSwitched;

  // Clear only the tool being applied (or all on image switch/reset) so other pending edits survive.
  if (reset) {
    state.editParams = { transform: null, augment: null, resize: null };
  } else if (opts.tool && state.editParams[opts.tool] != null) {
    state.editParams[opts.tool] = null;
  }
  state.pendingReset = reset;
  if (imageSwitched) state.viewResetRequested = true;

  Object.assign(state, {
    images: payload.images ?? [],
    currentIndex: payload.current_index ?? -1,
    currentPath: payload.current_path ?? null,
    current: payload.current_index != null && payload.current_index >= 0
      ? (payload.images ?? [])[payload.current_index] ?? null
      : null,
    defaults: payload.defaults ?? { transform: {}, augment: {} },
    history: payload.history
      ? {
          canUndo: !!payload.history.can_undo,
          canRedo: !!payload.history.can_redo,
        }
      : { canUndo: false, canRedo: false },
    historyTimeline: payload.history_timeline ?? {
      position: 0,
      base_label: "Original",
      truncated: false,
      entries: [],
    },
    dataset: payload.dataset ?? { active: false },
    annotationEditor: payload.annotation_editor ?? {
      available: false, classes: [], annotations: [], autosave: true,
      one_class: false, default_class: 0, task_type: "mixed",
      type_counts_current: { classification: 0, bbox: 0, polygon: 0, mask: 0 },
      type_counts_all: { classification: 0, bbox: 0, polygon: 0, mask: 0 },
    },
    workspace: payload.workspace ?? { kind: "empty" },
    workingMode: payload.working_mode ?? state.workingMode,
    hasUnsavedWork: payload.has_unsaved_work ?? state.hasUnsavedWork,
    project: payload.project ?? state.project,
    autoAnnotatePreview: payload.auto_annotate_preview ?? state.autoAnnotatePreview,
    localAI: payload.local_ai ?? state.localAI,
  });

  // Notify backend listeners (panels) synchronously with reset info.
  for (const fn of backendListeners) fn(state, { reset });
  state.pendingReset = false;
}
