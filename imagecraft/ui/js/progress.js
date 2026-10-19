// Top progress bar — driven by `backend:progress` / `backend:operation-done`
// events plus explicit start/set/end for local async work.

const host = document.getElementById("progress-host");
const track = document.getElementById("progress-track");

let active = 0;
let lastPercent = 0;

export function progressStart() {
  active += 1;
  lastPercent = 0;
  host.classList.add("active");
  track.style.width = "0%";
}

export function progressSet(percent) {
  lastPercent = Math.max(lastPercent, percent); // monotonic
  track.style.width = `${Math.min(100, Math.max(2, lastPercent))}%`;
}

export function progressEnd() {
  active = Math.max(0, active - 1);
  if (active > 0) return;
  track.style.width = "100%";
  setTimeout(() => {
    host.classList.remove("active");
    track.style.width = "0%";
  }, 220);
}

export function initProgress() {
  let lastOperation = "";
  window.addEventListener("backend:progress", (e) => {
    const { percent, operation } = e.detail;
    progressStart();
    progressSet(percent);
    lastOperation = operation || lastOperation;
  });
  window.addEventListener("backend:operation-done", (e) => {
    progressEnd();
    lastOperation = "";
  });
}
