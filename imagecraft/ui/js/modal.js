// Reusable modal dialog — backdrop + centered panel with close on
// Escape / backdrop click / close button.

/**
 * Show a modal dialog.
 * @param {{ title: string, content: string|Node, onClose?: () => void, className?: string }} opts
 * @returns {{ close: () => void }}
 */
export function showModal({ title, content, onClose, className = "" }) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  if (className === "mode-transition-modal") {
    backdrop.classList.add("mode-transition-backdrop");
  }

  const modal = document.createElement("div");
  modal.className = `modal${className ? ` ${className}` : ""}`;

  // Header
  const header = document.createElement("div");
  header.className = "modal-header";
  const titleEl = document.createElement("h2");
  titleEl.className = "modal-title";
  titleEl.textContent = title;
  const closeBtn = document.createElement("button");
  closeBtn.className = "modal-close";
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", close);
  header.append(titleEl, closeBtn);

  // Body
  const body = document.createElement("div");
  body.className = "modal-body";
  if (typeof content === "string") {
    body.innerHTML = content;
  } else {
    body.append(content);
  }

  modal.append(header, body);
  backdrop.append(modal);
  document.body.append(backdrop);

  // Close handlers
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  document.addEventListener("keydown", onKey);

  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey);
    backdrop.remove();
    if (onClose) onClose();
  }

  return { close };
}
