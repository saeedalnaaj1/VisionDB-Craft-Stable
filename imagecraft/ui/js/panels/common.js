// Shared context for the editing control panels: debounced live preview,
// apply / apply-all, and slider reset from backend defaults.

import { call } from "../api.js";
import { applyBackendState, state, setEditParams } from "../state.js";

/** Build the `ctx` object handed to every panel builder. */
export function makePanelCtx(hooks) {
  // hooks: { viewer, setStatus, afterState, toast: { ok, err }, refresh }
  let timer = null;

  const notifyCommitted = (kind) => {
    if (kind === "augment" && !state.repeatAugmentation) {
      document.dispatchEvent(new CustomEvent("imagecraft:augmentation-committed"));
    }
    if (kind === "transform" && !state.repeatTransform) {
      document.dispatchEvent(new CustomEvent("imagecraft:transform-committed"));
    }
  };

  const preview = (kind, getParams, delay = 150) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const res = await call("preview", kind, getParams());
        if (hooks.viewer && res.dataUrl) {
          hooks.viewer.setAnnotations(res.annotations || []);
          hooks.viewer.setImage(res.dataUrl, { preserveView: true });
        }
        if (hooks.setStatus && res.latency_ms >= 0) {
          hooks.setStatus(`Preview ${res.latency_ms} ms`);
        }
      } catch (e) {
        // Transient while dragging a slider; the next input event re-runs.
      }
    }, delay);
  };

  const apply = async (kind, getParams, all = false) => {
    // Cancel any pending live-preview debounce so it can't overwrite the
    // correct post-apply image with a stale (e.g. double-augmented) preview.
    if (timer) { clearTimeout(timer); timer = null; }

    // Flush pending edits for other tools first so they aren't silently lost.
    // E.g. if the user previewed a transform (set editParams.transform) but
    // then applied an augment, the transform must be committed first.
    for (const otherKind of ["transform", "augment", "resize"]) {
      if (otherKind !== kind && state.editParams[otherKind] != null) {
        try {
          const p = await call("apply", otherKind, state.editParams[otherKind]);
          if (p && !p.error) {
            applyBackendState(p, { tool: otherKind });
            notifyCommitted(otherKind);
          }
        } catch (_) { /* best-effort */ }
      }
    }

    try {
      const payload = await call(all ? "apply_all" : "apply", kind, getParams());
      applyBackendState(payload, { tool: kind });
      notifyCommitted(kind);
      if (hooks.afterState) hooks.afterState();
      if (hooks.toast) {
        hooks.toast.ok(
          all ? "Applied to all" : "Applied",
          all ? `${payload.count ?? "all"} images updated` : "Edit applied",
        );
      }
    } catch (e) {
      if (hooks.toast) hooks.toast.err("Apply failed", e.message);
    }
  };

  /** Reset every control back to the backend defaults, then re-preview. */
  const resetDefaults = (kind, controls) => {
    if (hooks.refresh) hooks.refresh();
  };

  return {
    preview,
    previewNow: (kind, getParams) => preview(kind, getParams, 0),
    onControlChanged: (kind, getParams) => {
      setEditParams(kind, getParams());
      if (state.livePreview) {
        // Commit any pending edits for *other* tools so item.active is
        // up-to-date before this tool's live preview runs.  Without this,
        // adjusting an augment slider would preview augment on the
        // untransformed image, making the transform visually disappear.
        for (const otherKind of ["transform", "augment", "resize"]) {
          if (otherKind !== kind && state.editParams[otherKind] != null) {
            const pending = state.editParams[otherKind];
            setEditParams(otherKind, null);        // clear to prevent double-apply
            call("apply", otherKind, pending)
              .then((p) => {
                if (p && !p.error) {
                  applyBackendState(p, { tool: otherKind });
                  notifyCommitted(otherKind);
                }
              })
              .catch(() => {});
          }
        }
        preview(kind, getParams);
      }
    },
    apply,
    resetDefaults,
    // Use getters so these read the live hook values (which are injected
    // by configurePanelHooks *after* makePanelCtx returns).
    get refresh() { return hooks.refresh; },
    get setStatus() { return hooks.setStatus; },
    get afterState() { return hooks.afterState; },
    get viewer() { return hooks.viewer; },
    get toast() { return hooks.toast; },
  };
}
