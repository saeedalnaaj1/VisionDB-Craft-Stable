// Toast notifications.

export function toast({ title, message = "", type = "info", timeout = 4200 }) {
  const host = document.getElementById("toast-host");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const t = document.createElement("div");
  t.className = "t-title";
  t.textContent = title;
  const m = document.createElement("div");
  m.className = "t-msg";
  m.textContent = message;
  el.append(t, m);
  host.appendChild(el);

  let removed = false;
  const remove = () => {
    if (removed) return;
    removed = true;
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 220);
  };
  el.addEventListener("click", remove);
  if (timeout > 0) setTimeout(remove, timeout);
  return remove;
}

export const ok = (title, message) => toast({ title, message, type: "ok" });
export const warn = (title, message) => toast({ title, message, type: "warn" });
export const err = (title, message) =>
  toast({ title, message, type: "err", timeout: 6000 });
