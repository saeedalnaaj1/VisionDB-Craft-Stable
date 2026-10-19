// Focused workflow selection and portable project lifecycle.

import { call } from "./api.js";
import { showModal } from "./modal.js";
import {
  applyLayout,
  setActive,
  setSidebarWidth,
  setSidebarWorkingMode,
} from "./sidebar.js";
import { applyBackendState, setEditParams, setState, state } from "./state.js";

export const WORKING_MODES = {
  transform: { label: "Transform", description: "Correct geometry, crop, rotate, and align images." },
  augment: { label: "Augment", description: "Build safe, reproducible dataset variations." },
  annotate: { label: "Annotate", description: "Create and edit classes, boxes, polygons, and masks." },
};

let hooks = { viewer: null, afterState: null, toast: null };
let pendingModeAfterExport = null;

export function initModeManager(runtimeHooks) {
  hooks = { ...hooks, ...runtimeHooks };
  const launcher = document.getElementById("mode-launcher");
  launcher?.querySelectorAll("[data-working-mode]").forEach((button) => {
    button.addEventListener("click", () => requestWorkingMode(button.dataset.workingMode, true));
  });
  document.getElementById("tb-mode")?.addEventListener("click", showModeLauncher);
  document.getElementById("tb-open-project")?.addEventListener("click", openProject);
  document.getElementById("tb-save-project")?.addEventListener("click", saveProject);
  document.getElementById("mode-open-project")?.addEventListener("click", openProject);
  document.getElementById("mode-launcher-close")?.addEventListener("click", hideModeLauncher);
  document.addEventListener("imagecraft:request-working-mode", (event) => {
    requestWorkingMode(event.detail?.mode);
  });
  document.addEventListener("imagecraft:workspace-exported", () => {
    if (!pendingModeAfterExport) return;
    const mode = pendingModeAfterExport;
    pendingModeAfterExport = null;
    // The backend reports this only after a complete workspace export. Keep
    // the local guard in sync before asking for the protected mode switch.
    setState({ hasUnsavedWork: false });
    requestWorkingMode(mode);
  });
  updateModeUi();
}

export function showModeLauncher() {
  const launcher = document.getElementById("mode-launcher");
  if (launcher) launcher.hidden = false;
}

export function hideModeLauncher() {
  const launcher = document.getElementById("mode-launcher");
  if (launcher) launcher.hidden = true;
}

export async function requestWorkingMode(mode, fromLauncher = false) {
  if (!Object.hasOwn(WORKING_MODES, mode)) return false;
  if (mode === state.workingMode && !fromLauncher) {
    hideModeLauncher();
    return true;
  }
  const pending = hasPendingWork();
  if (pending && state.current) {
    // The launcher sits above ordinary dialogs. Hide it before opening the
    // work-protection dialog or that dialog is present but impossible to see
    // or click. Restore the launcher if the user cancels the transition.
    if (fromLauncher) hideModeLauncher();
    const choice = await modeTransitionChoice(mode);
    if (choice === "cancel" || !choice) {
      if (fromLauncher) showModeLauncher();
      return false;
    }
    if (choice === "export") {
      pendingModeAfterExport = mode;
      hideModeLauncher();
      setActive("export");
      hooks.toast?.ok(
        "Export before switching",
        `Export the complete workspace; VisionDB Craft will then open ${WORKING_MODES[mode].label}.`,
      );
      return false;
    }
    if (choice === "project") {
      const saved = await saveProject();
      if (!saved) {
        if (fromLauncher) showModeLauncher();
        return false;
      }
    }
    if (choice === "abandon") {
      try {
        const payload = await call("abandon_workspace", mode);
        if (!payload.ok) throw new Error(payload.message || "Could not start the mode");
        applyBackendState(payload, { resetControls: true });
        applyMode(mode, true);
        return true;
      } catch (error) {
        if (fromLauncher) showModeLauncher();
        hooks.toast?.err("Mode switch failed", error.message);
        return false;
      }
    }
  }
  try {
    const payload = await call("set_working_mode", mode);
    if (!payload.ok) throw new Error(payload.message || "Could not switch mode");
    applyBackendState(payload);
    applyMode(mode, true);
    return true;
  } catch (error) {
    if (fromLauncher) showModeLauncher();
    hooks.toast?.err("Mode switch failed", error.message);
    return false;
  }
}

function applyMode(mode, refresh = false) {
  setSidebarWorkingMode(mode, { activatePrimary: true });
  updateModeUi();
  hideModeLauncher();
  if (refresh) hooks.afterState?.();
}

function hasPendingWork() {
  return !!state.hasUnsavedWork
    || Object.values(state.editParams || {}).some((params) => params != null)
    || (state.autoAnnotatePreview?.candidates || []).length > 0
    || (state.localAI?.proposal_images || 0) > 0;
}

function modeTransitionChoice(nextMode) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (choice, modal) => {
      if (settled) return;
      settled = true;
      modal?.close();
      resolve(choice);
    };
    const content = document.createElement("div");
    content.className = "mode-transition";
    const message = document.createElement("p");
    message.textContent = `There is work in ${WORKING_MODES[state.workingMode].label}. Choose how to protect it before opening ${WORKING_MODES[nextMode].label}.`;
    const actions = document.createElement("div");
    actions.className = "mode-transition-actions";
    const exportButton = actionButton("Export…", "export");
    const projectButton = actionButton("Save Project…", "project", "primary");
    const abandonButton = actionButton("Abandon Work", "abandon", "danger");
    const cancelButton = actionButton("Cancel", "cancel");
    actions.append(projectButton, exportButton, abandonButton, cancelButton);
    content.append(message, actions);
    const modal = showModal({
      title: "Switch working mode?",
      content,
      className: "mode-transition-modal",
      onClose: () => finish("cancel"),
    });
    for (const button of actions.querySelectorAll("button")) {
      button.addEventListener("click", () => finish(button.dataset.choice, modal));
    }
  });
}

function actionButton(label, choice, className = "") {
  const button = document.createElement("button");
  button.textContent = label;
  button.dataset.choice = choice;
  button.className = className;
  return button;
}

export async function saveProject() {
  try {
    if (!(await commitPendingEditsForProject())) return false;
    const uiState = {
      active_tool: state.activeTool,
      edit_params: state.editParams,
      working_mode: state.workingMode,
      live_preview: state.livePreview,
      repeat_augmentation: state.repeatAugmentation,
      repeat_transform: state.repeatTransform,
      sidebar_dock: state.sidebarDock,
      sidebar_width: state.sidebarWidth,
      sidebar_collapsed: state.sidebarCollapsed,
      viewer: hooks.viewer?.getViewState?.() || null,
      auto_annotate: state.autoAnnotateUi || {},
      local_ai: state.localAIUi || {},
    };
    const payload = await call("save_project", uiState, "");
    if (!payload.ok) {
      if (!payload.cancelled) hooks.toast?.err("Project save failed", payload.message || "Not saved");
      return false;
    }
    applyBackendState(payload);
    hooks.toast?.ok("Project saved", payload.message || payload.path);
    return true;
  } catch (error) {
    hooks.toast?.err("Project save failed", error.message);
    return false;
  }
}

async function commitPendingEditsForProject() {
  let committed = false;
  for (const tool of ["transform", "augment", "resize"]) {
    const params = state.editParams?.[tool];
    if (!params) continue;
    if (
      params.annotation_aware === false
      && (state.annotationEditor?.annotations || []).length > 0
      && !window.confirm(
        `Apply the pending ${tool} preview without moving its annotations before saving the project?`,
      )
    ) {
      return false;
    }
    const payload = await call("apply", tool, params);
    if (payload?.error || payload?.ok === false) {
      throw new Error(payload?.message || payload?.error || `Could not apply pending ${tool}`);
    }
    applyBackendState(payload, { tool });
    setEditParams(tool, null);
    if (tool === "augment" && !state.repeatAugmentation) {
      document.dispatchEvent(new CustomEvent("imagecraft:augmentation-committed"));
    }
    if (tool === "transform" && !state.repeatTransform) {
      document.dispatchEvent(new CustomEvent("imagecraft:transform-committed"));
    }
    committed = true;
  }
  if (committed) hooks.afterState?.();
  return true;
}

export async function openProject() {
  if (hasPendingWork() && state.current
      && !window.confirm("Open another project and replace the current workspace? Save anything you need first.")) {
    return false;
  }
  try {
    const payload = await call("open_project_dialog");
    if (payload.cancelled) return false;
    if (!payload.ok) throw new Error(payload.message || "Could not open project");
    applyBackendState(payload, { resetControls: true });
    const projectUi = payload.project?.ui_state || {};
    restoreProjectUi(projectUi);
    applyMode(payload.working_mode || "transform", false);
    if (projectUi.active_tool) setActive(projectUi.active_tool);
    hooks.afterState?.();
    if ((payload.missing_media || []).length) showMissingMedia(payload.missing_media);
    hooks.toast?.ok("Project opened", payload.project?.name || payload.path || "Session restored");
    return true;
  } catch (error) {
    hooks.toast?.err("Project open failed", error.message);
    return false;
  }
}

function restoreProjectUi(ui) {
  const editParams = ui.edit_params || {};
  for (const tool of ["transform", "augment", "resize"]) {
    setEditParams(tool, editParams[tool] || null);
  }
  setState({
    livePreview: ui.live_preview !== false,
    repeatAugmentation: !!ui.repeat_augmentation,
    repeatTransform: !!ui.repeat_transform,
    autoAnnotateUi: ui.auto_annotate || {},
    localAIUi: ui.local_ai || {},
    projectViewRestorePending: ui.viewer || null,
  });
  applyLayout(ui.sidebar_dock || state.sidebarDock || "right", !!ui.sidebar_collapsed);
  setSidebarWidth(ui.sidebar_width || state.sidebarWidth || 380);
  const live = document.getElementById("sb-live-preview");
  if (live) live.checked = state.livePreview;
}

function showMissingMedia(paths) {
  const content = document.createElement("div");
  const text = document.createElement("p");
  text.textContent = `${paths.length} original media file(s) moved or are unavailable. The embedded project copy still works; relink to restore source paths.`;
  const button = document.createElement("button");
  button.className = "primary";
  button.textContent = "Choose Media Folder…";
  content.append(text, button);
  const modal = showModal({ title: "Relink missing media", content });
  button.addEventListener("click", async () => {
    const result = await call("relink_missing_media");
    if (result.cancelled) return;
    if (!result.ok) {
      hooks.toast?.err("Relink failed", result.message || "No media relinked");
      return;
    }
    applyBackendState(result);
    hooks.afterState?.();
    hooks.toast?.ok("Media relinked", `${result.relinked} file(s) matched`);
    if (!(result.unresolved || []).length) modal.close();
  });
}

function updateModeUi() {
  const mode = WORKING_MODES[state.workingMode] || WORKING_MODES.transform;
  const button = document.getElementById("tb-mode");
  if (button) button.textContent = `Mode: ${mode.label}`;
  const badge = document.getElementById("st-mode");
  if (badge) badge.textContent = mode.label.toUpperCase();
  document.body.dataset.workingMode = state.workingMode;
}
