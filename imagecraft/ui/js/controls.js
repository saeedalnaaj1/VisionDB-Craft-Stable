// DOM helpers for building control panels. All helpers emit the same markup
// the design system styles (see css/theme.css).

export function el(tag, cls) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  return node;
}

function decimalsOf(step) {
  const s = String(step);
  const i = s.indexOf(".");
  return i >= 0 ? s.length - i - 1 : 0;
}

/** Label + range slider + live value readout. */
export function sliderRow({ label, min, max, step = 1, value = 0, onChange }) {
  const row = el("div", "ctrl");
  const lbl = el("span", "lbl");
  lbl.textContent = label;
  const input = el("input");
  input.type = "range";
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value;
  const val = el("span", "val");
  const d = decimalsOf(step);
  const fmt = (v) => (d === 0 ? String(v) : v.toFixed(d));
  val.textContent = fmt(value);
  input.addEventListener("input", () => {
    const v = parseFloat(input.value);
    val.textContent = fmt(v);
    onChange && onChange(v);
  });
  row.append(lbl, input, val);
  return {
    el: row,
    value: () => parseFloat(input.value),
    set(v) {
      input.value = v;
      val.textContent = fmt(v);
    },
    enable(on) {
      input.disabled = !on;
    },
  };
}

/** Checkbox row with an optional dependent control that toggles with it. */
export function checkboxRow({ label, checked = false, onChange }) {
  const row = el("label", "check-row");
  const input = el("input");
  input.type = "checkbox";
  input.checked = checked;
  const span = el("span");
  span.textContent = label;
  row.append(input, span);
  input.addEventListener("change", () => onChange && onChange(input.checked));
  return {
    el: row,
    checked: () => input.checked,
    set(on) {
      input.checked = on;
    },
  };
}

/** Collapsible panel with a titled header. */
export function panel({ title, body, collapsed = false }) {
  const p = el("div", "panel");
  if (collapsed) p.classList.add("collapsed");
  const head = el("div", "panel-title");
  head.textContent = title;
  const bodyEl = el("div", "panel-body");
  if (body) bodyEl.append(body);
  head.addEventListener("click", () => p.classList.toggle("collapsed"));
  p.append(head, bodyEl);
  return { el: p, body: bodyEl, collapse(on) { p.classList.toggle("collapsed", on); } };
}

/** Row of buttons. */
export function btnRow(buttons) {
  const row = el("div", "btn-row");
  for (const b of buttons) {
    const node = el("button");
    node.textContent = b.text;
    if (b.primary) node.classList.add("primary");
    if (b.disabled) node.disabled = true;
    node.addEventListener("click", b.onClick);
    row.append(node);
  }
  return row;
}

/** Simple text/select control: label + input. */
export function inputRow({ label, value = "", placeholder = "", onChange }) {
  const row = el("div", "ctrl");
  const lbl = el("span", "lbl");
  lbl.textContent = label;
  const input = el("input");
  input.type = "text";
  input.value = value;
  if (placeholder) input.placeholder = placeholder;
  input.addEventListener("input", () => onChange && onChange(input.value));
  row.append(lbl, input);
  input.style.flex = "1";
  return { el: row, value: () => input.value, set(v) { input.value = v; } };
}
