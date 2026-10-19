// Backend bridge — thin, promise-based wrapper over pywebview's js_api.
// Outside pywebview (e.g. opened directly in a browser for layout work) the
// API is unavailable and every call rejects cleanly.

export function isPyWebView() {
  return !!window.pywebview && !!window.pywebview.api;
}

export async function call(method, ...args) {
  if (!isPyWebView()) {
    throw new Error(`Backend method "${method}" unavailable (not in pywebview)`);
  }
  const fn = window.pywebview.api[method];
  if (typeof fn !== "function") {
    throw new Error(`Backend method not exposed: ${method}`);
  }
  const result = await fn(...args);
  if (result && typeof result === "object" && result.error) {
    throw new Error(result.error);
  }
  return result;
}

// --- Backend event bus ------------------------------------------------------
// The engine dispatches CustomEvents named `backend:<event>` on `window`.

export function onBackend(event, handler) {
  window.addEventListener(`backend:${event}`, (e) => handler(e.detail));
}

// Runs *handler* once the pywebview bridge is injected. Outside pywebview it
// still runs so the UI can be exercised in a plain browser.
export function onReady(handler) {
  let ran = false;
  const runOnce = () => {
    if (ran) return;
    ran = true;
    handler();
  };
  if (isPyWebView()) {
    runOnce();
    return;
  }
  // pywebview may inject `window.pywebview` shortly after the page script
  // executes. Wait briefly for its event; still boot normally in a browser.
  window.addEventListener("pywebviewready", runOnce, { once: true });
  window.setTimeout(() => {
    if (!window.pywebview) runOnce();
  }, 150);
}
