// Dataset workspace: project overview, validation/statistics, class-aware
// splitting, deterministic augmentation recipes, conversion and safe export.

import { call } from "../api.js";
import { applyBackendState, state } from "../state.js";
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

function button(label, action, primary = false) {
  const element = document.createElement("button");
  element.textContent = label;
  if (primary) element.className = "primary";
  element.addEventListener("click", action);
  return element;
}

function numberField(label, value, min = 0, max = 100) {
  const row = document.createElement("label");
  row.className = "ctrl dataset-number";
  const text = document.createElement("span");
  text.className = "lbl";
  text.textContent = label;
  const input = document.createElement("input");
  input.type = "number";
  input.value = String(value);
  input.min = String(min);
  input.max = String(max);
  row.append(text, input);
  return { row, input };
}

function metric(label, value) {
  const card = document.createElement("div");
  card.className = "dataset-metric";
  const strong = document.createElement("strong");
  strong.textContent = String(value);
  const caption = document.createElement("span");
  caption.textContent = label;
  card.append(strong, caption);
  return card;
}

export function buildDatasetPanel(container, ctx) {
  container.innerHTML = "";

  const overview = group("Dataset project");
  const projectName = document.createElement("strong");
  projectName.className = "dataset-project-name";
  const projectMeta = document.createElement("p");
  projectMeta.className = "hint dataset-project-meta";
  const projectActions = document.createElement("div");
  projectActions.className = "btn-row";
  const recentSelect = document.createElement("select");
  recentSelect.className = "dataset-wide-input";
  const recentDefault = document.createElement("option");
  recentDefault.textContent = "Recent projects…";
  recentSelect.append(recentDefault);
  recentSelect.addEventListener("change", async () => {
    if (!recentSelect.value) return;
    try {
      applyBackendState(await call("open_dataset_path", recentSelect.value), { resetControls: true });
      if (ctx.afterState) ctx.afterState();
      await analyze();
    } catch (error) { if (ctx.toast) ctx.toast.err("Open project failed", error.message); }
  });
  const openBtn = button("Open Labelled Dataset…", () => {
    // Route through the main opener so format detection and the image-folder
    // fallback prompt stay identical everywhere in the application.
    document.getElementById("tb-dataset")?.click();
  }, true);
  const closeBtn = button("Close Dataset", async () => {
    try {
      applyBackendState(await call("close_dataset"), { resetControls: true });
      if (ctx.afterState) ctx.afterState();
    } catch (error) {
      if (ctx.toast) ctx.toast.err("Close failed", error.message);
    }
  });
  projectActions.append(openBtn, closeBtn, recentSelect);
  overview.body.append(projectName, projectMeta, projectActions);
  container.append(overview.wrap);

  const analysis = group("Health and statistics");
  const metrics = document.createElement("div");
  metrics.className = "dataset-metrics";
  const health = document.createElement("div");
  health.className = "dataset-health";
  const classList = document.createElement("div");
  classList.className = "dataset-class-list";
  const chartArea = document.createElement("div");
  chartArea.className = "dataset-charts";
  const issueList = document.createElement("div");
  issueList.className = "dataset-issues";
  const analyzeBtn = button("Analyze Dataset", analyze, true);
  const cancelBtn = button("Cancel current operation", async () => {
    try { await call("cancel"); if (ctx.toast) ctx.toast.ok("Cancellation requested", "The current batch operation will stop safely."); }
    catch (error) { if (ctx.toast) ctx.toast.err("Cancel failed", error.message); }
  });
  const fixBtn = button("Export Cleaned Copy…", async () => {
    try {
      const result = await call("export_fixed_dataset", "yolo");
      if (result.ok && ctx.toast) ctx.toast.ok("Cleaned copy exported", `${result.saved} images saved`);
    } catch (error) { if (ctx.toast) ctx.toast.err("Clean export failed", error.message); }
  });
  analysis.body.append(analyzeBtn, cancelBtn, fixBtn, metrics, health, chartArea, classList, issueList);
  container.append(analysis.wrap);

  async function analyze() {
    if (!state.dataset?.active) return;
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "Analyzing…";
    try {
      const [stats, report] = await Promise.all([
        call("get_dataset_statistics"),
        call("validate_current_dataset"),
      ]);
      renderAnalysis(stats, report);
      if (ctx.toast) {
        const summary = report.summary || {};
        const detail = `${summary.errors || 0} errors · ${summary.warnings || 0} warnings`;
        report.ok ? ctx.toast.ok("Dataset checked", detail) : ctx.toast.err("Dataset needs attention", detail);
      }
    } catch (error) {
      if (ctx.toast) ctx.toast.err("Analysis failed", error.message);
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "Analyze Dataset";
    }
  }

  function renderAnalysis(stats, report) {
    metrics.innerHTML = "";
    metrics.append(
      metric("Images", stats.images || 0),
      metric("Objects", stats.objects || 0),
      metric("Classes", stats.class_count || 0),
      metric("Empty", stats.empty_images || 0),
    );
    health.innerHTML = "";
    const score = Number(report.health_score || 0);
    const scoreLine = document.createElement("div");
    scoreLine.className = "dataset-health-line";
    const scoreText = document.createElement("strong");
    scoreText.textContent = `Health ${score}/100`;
    const summaryText = document.createElement("span");
    summaryText.textContent = `${report.summary?.errors || 0} errors · ${report.summary?.warnings || 0} warnings`;
    scoreLine.append(scoreText, summaryText);
    const track = document.createElement("div");
    track.className = "dataset-health-track";
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, score))}%`;
    fill.dataset.level = score >= 85 ? "good" : score >= 60 ? "warn" : "bad";
    track.append(fill);
    health.append(scoreLine, track);

    classList.innerHTML = "";
    const classes = stats.classes || [];
    const maxObjects = Math.max(1, ...classes.map((row) => row.objects || 0));
    for (const row of classes.slice(0, 20)) {
      const line = document.createElement("div");
      line.className = "dataset-class-row";
      const name = document.createElement("span");
      name.textContent = row.name;
      name.title = row.name;
      const bar = document.createElement("i");
      bar.style.width = `${Math.max(2, (row.objects / maxObjects) * 100)}%`;
      const count = document.createElement("b");
      count.textContent = String(row.objects);
      line.append(name, bar, count);
      classList.append(line);
    }

    chartArea.innerHTML = "";
    const splitTitle = document.createElement("strong");
    splitTitle.textContent = "Split distribution";
    chartArea.append(splitTitle);
    const maxSplit = Math.max(1, ...Object.values(stats.splits || {}).map((row) => row.images || 0));
    for (const [name, row] of Object.entries(stats.splits || {})) {
      const line = document.createElement("div");
      line.className = "dataset-chart-row";
      const label = document.createElement("span"); label.textContent = name;
      const bar = document.createElement("i"); bar.style.width = `${(row.images / maxSplit) * 100}%`;
      const count = document.createElement("b"); count.textContent = `${row.images} images`;
      line.append(label, bar, count); chartArea.append(line);
    }

    issueList.innerHTML = "";
    for (const issue of (report.issues || []).slice(0, 50)) {
      const row = document.createElement("div");
      row.className = `dataset-issue ${issue.severity || "info"}`;
      const title = document.createElement("strong");
      title.textContent = String(issue.code || "issue").replaceAll("_", " ");
      const message = document.createElement("span");
      message.textContent = issue.message || "";
      const path = document.createElement("small");
      path.textContent = issue.path ? issue.path.split(/[\\/]/).pop() : "";
      path.title = issue.path || "";
      row.append(title, message, path);
      issueList.append(row);
    }
    if ((report.issues || []).length > 50) {
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = `Showing 50 of ${report.issues.length} issues. The complete report is included with export.`;
      issueList.append(note);
    }
  }

  async function loadRecent() {
    try {
      const result = await call("get_recent_projects");
      for (const path of result.projects || []) {
        const option = document.createElement("option");
        option.value = path; option.textContent = path.split(/[\\/]/).pop() || path;
        option.title = path; recentSelect.append(option);
      }
    } catch (_) { /* recent projects are a convenience */ }
  }
  loadRecent();

  const split = group("Reproducible split");
  const splitGrid = document.createElement("div");
  splitGrid.className = "dataset-split-grid";
  const train = numberField("Train %", 70);
  const val = numberField("Validation %", 20);
  const test = numberField("Test %", 10);
  const splitSeed = numberField("Seed", 42, 0, 2147483647);
  splitGrid.append(train.row, val.row, test.row, splitSeed.row);
  const splitHint = document.createElement("p");
  splitHint.className = "hint";
  splitHint.textContent = "Class-aware and repeatable. Related output is written only when you export.";
  const splitBtn = button("Assign Splits", async () => {
    try {
      const result = await call(
        "split_current_dataset",
        Number(train.input.value), Number(val.input.value), Number(test.input.value), Number(splitSeed.input.value),
      );
      if (!result.ok) throw new Error(result.message || "Split failed");
      const payload = await call("get_state");
      applyBackendState(payload);
      if (ctx.afterState) ctx.afterState();
      if (ctx.toast) ctx.toast.ok("Splits assigned", Object.entries(result.counts || {}).map(([key, value]) => `${key} ${value}`).join(" · "));
      await analyze();
    } catch (error) {
      if (ctx.toast) ctx.toast.err("Split failed", error.message);
    }
  }, true);
  split.body.append(splitGrid, splitHint, splitBtn);
  container.append(split.wrap);

  const augmentShortcut = group("Dataset augmentation");
  const augmentHint = document.createElement("p");
  augmentHint.className = "hint";
  augmentHint.textContent = "Custom controls and seeded recipes now share one Augmentation workspace. Dataset annotations remain synchronized.";
  const augmentBtn = button("Open Augmentation Recipes →", () => {
    document.dispatchEvent(new CustomEvent("imagecraft:open-augmentation-recipes"));
  }, true);
  augmentShortcut.body.append(augmentHint, augmentBtn);
  container.append(augmentShortcut.wrap);

  const output = group("Convert and export");
  const format = document.createElement("select");
  format.className = "dataset-wide-input";
  const exportHint = document.createElement("p");
  exportHint.className = "hint";
  exportHint.textContent = "Creates a new folder with images, updated annotations, configuration, manifest and validation report. COCO keeps RLE masks losslessly; PNG writes one binary mask per instance.";
  const exportBtn = button("Export Clean Dataset…", async () => {
    exportBtn.disabled = true;
    try {
      const result = await call("export_current_dataset", format.value);
      if (result.cancelled) return;
      if (!result.ok) throw new Error(result.message || "Export failed");
      if (ctx.toast) ctx.toast.ok("Dataset exported", `${result.saved} images · ${result.format.toUpperCase()}`);
    } catch (error) {
      if (ctx.toast) ctx.toast.err("Export failed", error.message);
    } finally {
      exportBtn.disabled = !state.dataset?.active;
    }
  }, true);
  output.body.append(format, exportHint, exportBtn);
  container.append(output.wrap);

  const gated = [
    closeBtn,
    fixBtn,
    cancelBtn,
    analyzeBtn,
    train.input,
    val.input,
    test.input,
    splitSeed.input,
    splitBtn,
    augmentBtn,
    format,
    exportBtn,
  ];
  registerRefresher("dataset", (current) => {
    const dataset = current.dataset || { active: false };
    const active = !!dataset.active;
    projectName.textContent = active ? dataset.name : "No dataset open";
    projectMeta.textContent = active
      ? `${String(dataset.format || "").toUpperCase()} · ${dataset.image_count || 0} images · ${(dataset.classes || []).length} classes · ${dataset.generated || 0} generated`
      : "Open a classification, YOLO, COCO, or Pascal VOC dataset. Regular image editing remains available.";
    const poseSchemas = dataset.pose_schemas || [];
    const poseFormats = poseSchemas.length > 1
      ? [["coco_keypoints", "COCO Keypoints JSON"]]
      : [
          ["yolo_pose", "YOLO Pose TXT + data.yaml"],
          ["coco_keypoints", "COCO Keypoints JSON"],
          ...(poseSchemas[0] === "mediapipe_33"
            ? [["mediapipe", "MediaPipe 33-landmark JSON"]] : []),
        ];
    const formatsByTask = {
      classification: [["yolo", "Class folders — classification"]],
      detection: [
        ["yolo", "YOLO Detection TXT"], ["coco", "COCO Instances JSON"],
        ["voc", "Pascal VOC XML"],
      ],
      segmentation: [
        ["coco", "COCO Instance Segmentation"],
        ["yolo", "YOLO Segmentation TXT"],
        ["mask", "PNG instance masks + JSON index"],
      ],
      pose: poseFormats,
    };
    const previousFormat = format.value;
    format.innerHTML = "";
    for (const [value, label] of formatsByTask[dataset.task_type] || []) {
      const option = document.createElement("option");
      option.value = value; option.textContent = label; format.append(option);
    }
    if ([...format.options].some(option => option.value === previousFormat)) {
      format.value = previousFormat;
    }
    exportHint.textContent = dataset.task_type === "segmentation"
      ? "Only segmentation-safe formats are shown. COCO preserves RLE masks; YOLO uses polygons; PNG writes lossless instance masks."
      : dataset.task_type === "pose"
        ? poseSchemas.length > 1
          ? "This dataset mixes pose schemas, so COCO Keypoints is the safe combined export."
          : "Only compatible pose formats are shown. MediaPipe JSON requires the 33-landmark schema; YOLO Pose requires one consistent schema per export."
      : dataset.task_type === "detection"
        ? "Only bounding-box formats are shown: YOLO Detection, COCO Instances, and Pascal VOC XML."
        : "Classification exports use split/class folders for common classification training loaders.";
    for (const control of gated) control.disabled = !active;
    openBtn.disabled = false;
    if (!active) {
      metrics.innerHTML = "";
      health.innerHTML = "";
      classList.innerHTML = "";
      issueList.innerHTML = "";
    }
  });
}
