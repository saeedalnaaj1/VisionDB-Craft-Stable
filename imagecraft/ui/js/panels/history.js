// Photopea-style non-linear history navigation. The backend keeps applied
// operations plus the redo branch; this panel renders both and can jump to any
// visible state without requiring repeated toolbar clicks.

import { call } from "../api.js";
import { registerRefresher } from "../sidebar.js";
import { applyBackendState, setEditParams } from "../state.js";

const KIND_LABELS = {
  transform: "Transform",
  augment: "Augment",
  resize: "Resize",
  annotation: "Annotation",
};

function entryLabel(entry) {
  const fallback = KIND_LABELS[entry.kind] || entry.kind || "Edit";
  if (entry.kind !== "annotation") return fallback;
  const action = (entry.changes || []).find((change) =>
    change.section === "Annotation" && change.label === "Action"
  )?.value;
  if (action === "Auto Annotate (BETA)") return "Auto Annotate (BETA)";
  return action ? `Annotation · ${action}` : fallback;
}

export function buildHistoryPanel(container, ctx) {
  container.innerHTML = "";

  const intro = document.createElement("div");
  intro.className = "history-intro";
  const title = document.createElement("strong");
  title.textContent = "Edit history";
  const help = document.createElement("p");
  help.className = "hint";
  help.textContent = "Click an earlier state to undo to it. Click a dimmed later state to redo forward. A new edit replaces the dimmed future branch.";
  intro.append(title, help);

  const list = document.createElement("div");
  list.className = "history-list";
  container.append(intro, list);

  let jumping = false;

  async function jump(position) {
    if (jumping) return;
    jumping = true;
    for (const button of list.querySelectorAll("button")) button.disabled = true;
    try {
      // A timeline jump always discards transient previews; only committed
      // operations belong in history.
      setEditParams("transform", null);
      setEditParams("augment", null);
      setEditParams("resize", null);
      const payload = await call("jump_to_history", position);
      applyBackendState(payload, { resetControls: true });
      // The editor panels are currently hidden, so explicitly reset all of
      // their controls to the restored state before the user returns to them.
      if (ctx.refresh) ctx.refresh();
      else if (ctx.afterState) ctx.afterState();
      if (ctx.toast) ctx.toast.ok("History restored", `Moved to state ${position}`);
    } catch (error) {
      if (ctx.toast) ctx.toast.err("History navigation failed", error.message);
    } finally {
      jumping = false;
    }
  }

  function historyButton(index, label, options = {}) {
    const button = document.createElement("button");
    button.className = "history-entry";
    button.dataset.position = String(index);
    button.classList.toggle("active", !!options.active);
    button.classList.toggle("future", !!options.future);
    button.setAttribute("aria-current", options.active ? "step" : "false");

    const marker = document.createElement("span");
    marker.className = "history-marker";
    marker.textContent = options.active ? "●" : "○";
    const content = document.createElement("span");
    content.className = "history-entry-content";
    const heading = document.createElement("strong");
    heading.textContent = label;
    content.append(heading);

    if (options.meta) {
      const meta = document.createElement("small");
      meta.textContent = options.meta;
      content.append(meta);
    }
    for (const change of options.changes || []) {
      const row = document.createElement("span");
      row.className = "history-change";
      const section = document.createElement("b");
      section.textContent = change.section;
      const value = document.createElement("span");
      value.textContent = `${change.label}: ${change.value}`;
      row.append(section, value);
      content.append(row);
    }
    button.append(marker, content);
    button.addEventListener("click", () => jump(index));
    return button;
  }

  registerRefresher("history", (current) => {
    const timeline = current.historyTimeline || {
      position: 0,
      base_label: "Original",
      truncated: false,
      entries: [],
    };
    list.innerHTML = "";
    list.append(historyButton(0, timeline.base_label || "Original", {
      active: timeline.position === 0,
      meta: timeline.truncated ? "Oldest state retained by the history limit" : "Opened state",
    }));

    for (const entry of timeline.entries || []) {
      const kind = entryLabel(entry);
      const target = entry.target === "all"
        ? `${entry.image_count} images`
        : (entry.image_name ? `Current image · ${entry.image_name}` : "Current image");
      const changes = entry.changes?.length
        ? entry.changes
        : [{ section: "Settings", label: "Applied", value: "Default values" }];
      list.append(historyButton(entry.index, `${entry.index}. ${kind}`, {
        active: entry.index === timeline.position,
        future: entry.index > timeline.position,
        meta: target,
        changes,
      }));
    }
  });
}
