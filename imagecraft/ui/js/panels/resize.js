// Resize panel — target width/height with aspect lock and Apply buttons.

import { checkboxRow } from "../controls.js";
import { registerRefresher } from "../sidebar.js";

function group(title) {
  const wrap = document.createElement("div");
  wrap.className = "panel";
  const head = document.createElement("div");
  head.className = "panel-title";
  head.textContent = title;
  const body = document.createElement("div");
  body.className = "panel-body";
  head.addEventListener("click", () => wrap.classList.toggle("collapsed"));
  wrap.append(head, body);
  return { wrap, body };
}

export function buildResizePanel(container, ctx) {
  container.innerHTML = "";

  const dims = group("Dimensions");
  const body = dims.body;

  const mkRow = (label) => {
    const row = document.createElement("label");
    row.className = "ctrl";
    const span = document.createElement("span");
    span.className = "lbl";
    span.textContent = label;
    const input = document.createElement("input");
    input.type = "number";
    input.min = 1;
    input.max = 20000;
    row.append(span, input);
    body.append(row);
    return input;
  };

  const widthIn = mkRow("Width px");
  const heightIn = mkRow("Height px");

  const lock = checkboxRow({ label: "Lock aspect ratio", checked: true });
  body.append(lock.el);

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.style.cssText = "font-size:var(--fs-xs);color:var(--text-3);margin:2px 0 0;";
  body.append(hint);
  container.append(dims.wrap);

  let sourceAspect = 1;

  function syncFromWidth() {
    const w = parseInt(widthIn.value, 10);
    if (!w) return;
    heightIn.value = Math.max(1, Math.round(w / sourceAspect));
  }
  function syncFromHeight() {
    const h = parseInt(heightIn.value, 10);
    if (!h) return;
    widthIn.value = Math.max(1, Math.round(h * sourceAspect));
  }

  widthIn.addEventListener("input", () => { if (lock.checked()) syncFromWidth(); });
  heightIn.addEventListener("input", () => { if (lock.checked()) syncFromHeight(); });

  function collect() {
    return {
      width: parseInt(widthIn.value, 10) || 0,
      height: parseInt(heightIn.value, 10) || 0,
    };
  }

  const actions = group("Actions");
  const btnRow = document.createElement("div");
  btnRow.className = "btn-row";
  const mkBtn = (text, fn, cls) => {
    const b = document.createElement("button");
    b.textContent = text;
    if (cls) b.className = cls;
    b.addEventListener("click", fn);
    btnRow.append(b);
    return b;
  };
  const applyBtn = mkBtn("Apply", () => ctx.apply("resize", collect, false), "primary");
  const applyAllBtn = mkBtn("Apply to All", () => ctx.apply("resize", collect, true));
  actions.body.append(btnRow);
  container.append(actions.wrap);

  registerRefresher("resize", (s) => {
    const enabled = !!s.current;
    const w = s.current ? s.current.w : 0;
    const h = s.current ? s.current.h : 0;
    if (enabled && w && h) {
      sourceAspect = w / h;
      widthIn.value = w;
      heightIn.value = h;
      hint.textContent = `Current: ${w} × ${h}`;
    } else {
      widthIn.value = "";
      heightIn.value = "";
      hint.textContent = "";
    }
    widthIn.disabled = !enabled;
    heightIn.disabled = !enabled;
    lock.el.querySelector("input").disabled = !enabled;
    applyBtn.disabled = !enabled;
    applyAllBtn.disabled = !enabled;
  });
}
