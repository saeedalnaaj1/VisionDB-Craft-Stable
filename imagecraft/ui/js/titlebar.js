// Custom title bar: drag-to-move (frameless window), theme toggle, and the
// minimize / maximize / close buttons. Window operations go through the
// backend bridge (which forwards to pywebview's native window).

import { call } from "./api.js";
import { setState, state } from "./state.js";

export function initTitlebar() {
  const region = document.getElementById("drag-region");

  // Window movement is handled natively by pywebview through the
  // `pywebview-drag-region` class. This avoids flooding the async JS bridge
  // with one move call per mouse event, which could leave the startup window
  // apparently immovable on Windows.

  // --- Window control buttons ----------------------------------------------
  document.getElementById("btn-min").addEventListener("click", () =>
    call("minimize_window").catch(() => {}),
  );

  const maxBtn = document.getElementById("btn-max");
  const toggleMaximize = () => {
    const willMaximize = maxBtn.textContent !== "❐";
    call("toggle_maximize").catch(() => {});
    maxBtn.textContent = willMaximize ? "❐" : "▢";
  };
  maxBtn.addEventListener("click", toggleMaximize);
  region.addEventListener("dblclick", toggleMaximize);

  document.getElementById("btn-close").addEventListener("click", () =>
    call("close_window").catch(() => {}),
  );

  // --- Theme toggle ---------------------------------------------------------
  document.getElementById("btn-theme").addEventListener("click", () => {
    const next = state.theme === "dark" ? "light" : "dark";
    setTheme(next);
    call("set_config", "theme", next).catch(() => {});
  });
}

export function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  setState({ theme });
}
