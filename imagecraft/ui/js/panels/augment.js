// Augmentation control panel — color, filters, geometry, flips, padding.
// Exposes every field of `AugmentParams` (including the v2 ops) and emits live
// previews via `ctx.preview("augment", collect)`.

import { checkboxRow, sliderRow } from "../controls.js";
import { call } from "../api.js";
import { registerPendingApplyGuard, registerRefresher } from "../sidebar.js";
import { applyBackendState, setEditParams, setState, state } from "../state.js";

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

/** Slider spec: [field, label, min, max, step, default]. */
const COLOR = [
  ["white_balance", "White balance", -100, 100, 1, 0],
  ["hsv_hue", "Hue", -180, 180, 1, 0],
  ["hsv_saturation", "Saturation", -100, 100, 1, 0],
  ["hsv_value", "Brightness", -100, 100, 1, 0],
  ["exposure", "Exposure", -2, 2, 0.05, 0],
];
const FILTERS = [
  ["gaussian_blur", "Blur", 0, 100, 1, 0],
  ["softness", "Softness", 0, 100, 1, 0],
  ["sharpen", "Sharpen", 0, 100, 1, 0],
  ["oil", "Oil paint", 0, 100, 1, 0],
  ["noise", "Noise", 0, 100, 1, 0],
  ["salt_pepper", "Salt & pepper", 0, 100, 1, 0],
];
const GEOMETRY = [
  ["rotation", "Rotation °", -180, 180, 1, 0],
  ["translate", "Shift px", -100, 100, 1, 0],
  ["scale", "Scale %", 50, 150, 1, 100],
  ["shear", "Shear °", -45, 45, 1, 0],
];

function hasGeometricAugmentation(params) {
  return Number(params.rotation || 0) !== 0
    || Number(params.translate || 0) !== 0
    || Number(params.scale || 100) !== 100
    || Number(params.shear || 0) !== 0
    || !!params.flip_vertical
    || !!params.flip_horizontal
    || !!params.padding_enabled;
}

export function buildAugmentPanel(container, ctx) {
  container.innerHTML = "";

  const modeHeader = document.createElement("div");
  modeHeader.className = "augment-mode-header";
  const customTab = document.createElement("button");
  customTab.textContent = "Custom Augmentation";
  const recipesTab = document.createElement("button");
  recipesTab.textContent = "Seeded Recipes";
  modeHeader.append(customTab, recipesTab);
  const contextCard = document.createElement("div");
  contextCard.className = "workspace-context-card";
  const contextTitle = document.createElement("strong");
  const contextText = document.createElement("span");
  contextCard.append(contextTitle, contextText);
  const customMode = document.createElement("div");
  const recipeMode = document.createElement("div");
  recipeMode.hidden = true;
  container.append(modeHeader, contextCard, customMode, recipeMode);

  const awareness = group("Annotation safety");
  const annotationAware = checkboxRow({
    label: "Annotation-aware geometry (recommended)",
    checked: true,
    onChange: () => {
      updateAwarenessStatus();
      ctx.onControlChanged("augment", collect);
    },
  });
  const awarenessStatus = document.createElement("p");
  awarenessStatus.className = "annotation-awareness-status";
  const practiceBtn = document.createElement("button");
  practiceBtn.textContent = "Open Augmentation Practice Image…";
  practiceBtn.addEventListener("click", async () => {
    if (state.current && !window.confirm("Open the built-in labelled practice image? Save any current work you need first.")) return;
    try {
      const payload = await call("open_augmentation_practice_image");
      if (!payload.ok) throw new Error(payload.message || "Could not open practice image");
      applyBackendState(payload, { resetControls: true });
      ctx.afterState?.();
      ctx.toast?.ok("Practice image opened", "Boxes, polygons, and bitmap masks are included");
    } catch (error) { ctx.toast?.err("Practice image failed", error.message); }
  });
  awareness.body.append(annotationAware.el, awarenessStatus, practiceBtn);
  container.insertBefore(awareness.wrap, customMode);

  function updateAwarenessStatus() {
    const labelled = (state.annotationEditor?.annotations || []).length > 0;
    awarenessStatus.classList.toggle("warning", labelled && !annotationAware.checked());
    awarenessStatus.textContent = annotationAware.checked()
      ? "ON — flips, rotation, translation, scaling, shear, and padding keep boxes, polygons, and bitmap masks synchronized."
      : labelled
        ? "WARNING — geometric edits will change pixels while labels stay unchanged. Training labels may become invalid."
        : "OFF — no labels are currently present, but future labels will not follow geometry.";
  }

  function setMode(mode) {
    const recipes = mode === "recipes";
    customMode.hidden = recipes;
    recipeMode.hidden = !recipes;
    customTab.classList.toggle("primary", !recipes);
    recipesTab.classList.toggle("primary", recipes);
    if (recipes) loadRecipes();
  }
  customTab.addEventListener("click", () => setMode("custom"));
  recipesTab.addEventListener("click", () => setMode("recipes"));
  document.addEventListener("imagecraft:show-augmentation-recipes", () => setMode("recipes"));
  setMode("custom");

  const rows = new Map(); // field -> slider row (or checkbox/number)
  const floatFields = new Set(["exposure"]);

  const addSlider = (body, field, label, min, max, step, def) => {
    const r = sliderRow({ label, min, max, step, value: def, onChange: () => ctx.onControlChanged("augment", collect) });
    rows.set(field, r);
    body.append(r.el);
  };

  const color = group("Color");
  for (const s of COLOR) addSlider(color.body, ...s);
  customMode.append(color.wrap);

  const filters = group("Filters");
  for (const s of FILTERS) addSlider(filters.body, ...s);
  customMode.append(filters.wrap);

  const geo = group("Geometry");
  for (const s of GEOMETRY) addSlider(geo.body, ...s);
  customMode.append(geo.wrap);

  // Flips
  const flip = group("Flip");
  const flips = {};
  for (const [field, label] of [["flip_vertical", "Flip up-down"], ["flip_horizontal", "Flip left-right"]]) {
    const r = checkboxRow({ label, checked: false, onChange: () => ctx.onControlChanged("augment", collect) });
    rows.set(field, r);
    flips[field] = r;
    flip.body.append(r.el);
  }
  customMode.append(flip.wrap);

  // Padding (checkbox + numeric target size)
  const pad = group("Padding");
  const padWrap = document.createElement("div");
  padWrap.className = "pad-row";
  padWrap.style.cssText = "display:flex;flex-direction:column;gap:6px;";
  const padCheck = checkboxRow({ label: "Add padding", checked: false, onChange: (on) => {
    padW.disabled = !on;
    padH.disabled = !on;
    rows.get("padding_enabled").set(on);
    ctx.onControlChanged("augment", collect);
  }});
  rows.set("padding_enabled", padCheck);
  padWrap.append(padCheck.el);
  const dims = document.createElement("div");
  dims.style.cssText = "display:flex;gap:6px;align-items:center;";
  const mkNum = (placeholder) => {
    const n = document.createElement("input");
    n.type = "number";
    n.min = 0;
    n.max = 10000;
    n.placeholder = placeholder;
    n.style.cssText = "flex:1;";
    return n;
  };
  const padW = mkNum("Width px");
  const padH = mkNum("Height px");
  padW.disabled = true;
  padH.disabled = true;
  padW.addEventListener("input", () => ctx.onControlChanged("augment", collect));
  padH.addEventListener("input", () => ctx.onControlChanged("augment", collect));
  dims.append(padW, padH);
  padWrap.append(dims);
  pad.body.append(padWrap);
  customMode.append(pad.wrap);

  function collect() {
    const params = { annotation_aware: annotationAware.checked() };
    for (const [field, r] of rows) {
      if (field === "padding_enabled") {
        params[field] = r.checked();
        params.padding_width = parseInt(padW.value, 10) || 0;
        params.padding_height = parseInt(padH.value, 10) || 0;
      } else if (field === "flip_vertical" || field === "flip_horizontal") {
        params[field] = r.checked();
      } else {
        params[field] = floatFields.has(field) ? r.value() : Math.round(r.value());
      }
    }
    return params;
  }

  function resetValues() {
    setEditParams("augment", null);
    ctx.refresh();
  }
  document.addEventListener("imagecraft:augmentation-committed", resetValues);

  // Actions
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
  mkBtn("Apply", () => applyAugment(false), "primary");
  mkBtn("Apply to All", () => applyAugment(true));
  const reset = mkBtn("Reset sliders", () => resetValues());
  mkBtn("Preview", () => ctx.previewNow("augment", collect));
  const repeatApply = checkboxRow({
    label: "Keep settings after Apply (allow repeated stacking)",
    checked: false,
    onChange: (enabled) => setState({ repeatAugmentation: enabled }),
  });
  const repeatHint = document.createElement("p");
  repeatHint.className = "hint";
  repeatHint.textContent = "Off by default: applied sliders reset so an earlier augmentation is not accidentally applied again with the next one.";
  actions.body.append(btnRow, repeatApply.el, repeatHint);
  customMode.append(actions.wrap);

  function applyAugment(all) {
    const hasLabels = (state.images || []).some(image => Number(image.annotations || 0) > 0);
    const geometric = hasGeometricAugmentation(collect());
    if (hasLabels && geometric && !annotationAware.checked()
        && !window.confirm("Annotation-aware geometry is OFF. Continue and leave labels unchanged even though the pixels will move?")) {
      return;
    }
    ctx.apply("augment", collect, all);
  }

  // Seeded generation uses the same augmentation pipeline, but samples a
  // repeatable set of values and keeps each generated result as a new item.
  const recipes = group("Reproducible variant generation");
  const recipeSteps = document.createElement("ol");
  recipeSteps.className = "recipe-steps";
  recipeSteps.innerHTML = "<li>Choose a preset or Custom recipe.</li><li>Enable and edit its transformation ranges.</li><li>Set variants per image and a seed, then generate.</li>";
  const recipeSelect = document.createElement("select");
  recipeSelect.className = "dataset-wide-input";
  const loadingOption = document.createElement("option");
  loadingOption.textContent = "Loading recipes…";
  loadingOption.value = "";
  recipeSelect.append(loadingOption);
  const recipeDescription = document.createElement("p");
  recipeDescription.className = "hint";
  const recipeLoadStatus = document.createElement("div");
  recipeLoadStatus.className = "recipe-load-status";
  const retryRecipes = document.createElement("button");
  retryRecipes.textContent = "Retry loading recipes";
  retryRecipes.hidden = true;
  retryRecipes.addEventListener("click", loadRecipes);
  recipeLoadStatus.append(retryRecipes);

  const settings = group("Recipe settings — editable");
  const settingsHint = document.createElement("p");
  settingsHint.className = "hint";
  settingsHint.textContent = "Checked transformations are sampled between Min and Max for every generated image. Uncheck anything you do not want.";
  const recipeSettings = document.createElement("div");
  recipeSettings.className = "recipe-settings";
  const resetPresetBtn = document.createElement("button");
  resetPresetBtn.textContent = "Reset to selected preset";
  resetPresetBtn.addEventListener("click", applySelectedRecipe);
  settings.body.append(settingsHint, recipeSettings, resetPresetBtn);
  const recipeGrid = document.createElement("div");
  recipeGrid.className = "dataset-split-grid";
  const makeNumber = (label, value, min, max) => {
    const row = document.createElement("label");
    row.className = "ctrl dataset-number";
    const caption = document.createElement("span");
    caption.className = "lbl";
    caption.textContent = label;
    const input = document.createElement("input");
    input.type = "number";
    input.value = String(value);
    input.min = String(min);
    input.max = String(max);
    row.append(caption, input);
    return { row, input };
  };
  const copies = makeNumber("Variants / image", 1, 1, 10);
  const seed = makeNumber("Seed", 42, 0, 2147483647);
  recipeGrid.append(copies.row, seed.row);
  const recipeNotice = document.createElement("p");
  recipeNotice.className = "hint augmentation-output-hint";
  const generateBtn = document.createElement("button");
  generateBtn.className = "primary dataset-wide-input";
  generateBtn.addEventListener("click", async () => {
    generateBtn.disabled = true;
    try {
      const ranges = collectRecipeRanges();
      if (Object.keys(ranges).length === 0) {
        throw new Error("Enable at least one transformation in Recipe settings");
      }
      const payload = await call(
        "generate_variants", recipeSelect.value || "custom",
        Number(copies.input.value), Number(seed.input.value), ranges,
        annotationAware.checked(),
      );
      if (!payload.ok) throw new Error(payload.message || "Generation failed");
      applyBackendState(payload);
      if (ctx.afterState) ctx.afterState();
      const labelled = !!payload.dataset?.active;
      if (ctx.toast) ctx.toast.ok(
        "Variants generated",
        `${payload.generated} ${labelled ? "annotated " : ""}images added`,
      );
    } catch (error) {
      if (ctx.toast) ctx.toast.err("Generation failed", error.message);
    }
  });
  recipes.body.append(
    recipeSteps, recipeSelect, recipeDescription, recipeLoadStatus,
    settings.wrap, recipeGrid, recipeNotice, generateBtn,
  );
  recipeMode.append(recipes.wrap);

  let recipeRows = [];
  let recipeFields = [];
  let recipesLoading = false;
  let recipesLoaded = false;
  const recipeInputs = new Map();
  async function loadRecipes() {
    if (recipesLoading || recipesLoaded) return;
    recipesLoading = true;
    retryRecipes.hidden = true;
    loadingOption.textContent = "Loading recipes…";
    try {
      const payload = await call("get_augmentation_recipes");
      recipeRows = payload.recipes || [];
      recipeFields = payload.fields || [];
      if (recipeRows.length === 0 || recipeFields.length === 0) {
        throw new Error("No recipe definitions were returned");
      }
      recipeSelect.innerHTML = "";
      for (const recipe of recipeRows) {
        const option = document.createElement("option");
        option.value = recipe.id;
        option.textContent = recipe.name;
        recipeSelect.append(option);
      }
      const customOption = document.createElement("option");
      customOption.value = "custom";
      customOption.textContent = "Custom recipe";
      recipeSelect.append(customOption);
      buildRecipeEditor();
      recipesLoaded = true;
      applySelectedRecipe();
    } catch (error) {
      loadingOption.textContent = "Recipes unavailable — retry below";
      recipeSelect.innerHTML = "";
      recipeSelect.append(loadingOption);
      recipeDescription.textContent = error.message || "Recipes could not be loaded.";
      retryRecipes.hidden = false;
    } finally {
      recipesLoading = false;
    }
  }
  window.addEventListener("pywebviewready", loadRecipes, { once: true });
  loadRecipes();
  recipeSelect.addEventListener("change", applySelectedRecipe);
  function updateRecipeDescription() {
    const selected = recipeRows.find((row) => row.id === recipeSelect.value);
    recipeDescription.textContent = selected?.description || "Build your own repeatable recipe by enabling transformations below.";
  }
  function buildRecipeEditor() {
    recipeSettings.innerHTML = "";
    recipeInputs.clear();
    const header = document.createElement("div");
    header.className = "recipe-setting-row recipe-setting-head";
    for (const label of ["On", "Transformation", "Min / Chance %", "Max"]) {
      const cell = document.createElement("span");
      cell.textContent = label;
      header.append(cell);
    }
    recipeSettings.append(header);
    for (const field of recipeFields) {
      const row = document.createElement("div");
      row.className = "recipe-setting-row";
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.title = `Enable ${field.name}`;
      const name = document.createElement("span");
      name.textContent = field.name;
      const min = document.createElement("input");
      min.type = "number";
      min.min = String(field.min);
      min.max = String(field.max);
      min.step = String(field.step);
      const max = document.createElement("input");
      max.type = "number";
      max.min = String(field.min);
      max.max = String(field.max);
      max.step = String(field.step);
      const syncDisabled = () => {
        min.disabled = !enabled.checked;
        max.disabled = !enabled.checked || !!field.probability;
      };
      enabled.addEventListener("change", syncDisabled);
      row.append(enabled, name, min, max);
      recipeSettings.append(row);
      recipeInputs.set(field.id, { enabled, min, max, field, syncDisabled });
      syncDisabled();
    }
  }
  function applySelectedRecipe() {
    updateRecipeDescription();
    const selected = recipeRows.find((row) => row.id === recipeSelect.value);
    const ranges = selected?.ranges || {};
    for (const [id, controls] of recipeInputs) {
      const value = ranges[id];
      controls.enabled.checked = value !== undefined;
      if (id.endsWith("_probability")) {
        controls.min.value = value === undefined ? "50" : String(Number(value) <= 1 ? Number(value) * 100 : value);
        controls.max.value = controls.min.value;
      } else if (Array.isArray(value)) {
        controls.min.value = String(value[0]);
        controls.max.value = String(value[1]);
      } else {
        controls.min.value = String(controls.field.min);
        controls.max.value = String(controls.field.max);
      }
      controls.syncDisabled();
    }
  }
  function collectRecipeRanges() {
    const ranges = {};
    for (const [id, controls] of recipeInputs) {
      if (!controls.enabled.checked) continue;
      if (id.endsWith("_probability")) {
        ranges[id] = Number(controls.min.value);
      } else {
        ranges[id] = [Number(controls.min.value), Number(controls.max.value)];
      }
    }
    return ranges;
  }

  // ------------------------------------------------------------------
  // Refresh: values follow backend defaults; controls enabled on image.
  // ------------------------------------------------------------------
  registerRefresher("augment", (s, info = {}) => {
    const d = s.defaults.augment || {};
    const enabled = !!s.current;
    const all = [...COLOR, ...FILTERS, ...GEOMETRY];
    if (info.reset) {
      for (const [field, , , , , def] of all) {
        const r = rows.get(field);
        if (!r) continue;
        const v = d[field] !== undefined ? d[field] : def;
        r.set(v);
        r.enable(enabled);
      }
      for (const field of ["flip_vertical", "flip_horizontal"]) {
        flips[field].set(!!d[field]);
      }
      padCheck.set(!!d.padding_enabled);
      rows.get("flip_vertical").el.querySelector("input").disabled = !enabled;
      rows.get("flip_horizontal").el.querySelector("input").disabled = !enabled;

      padW.disabled = !enabled || !(d.padding_enabled ?? false);
      padH.disabled = padW.disabled;
      padW.value = d.padding_width ?? 0;
      padH.value = d.padding_height ?? 0;
    } else {
      for (const [field, , , , , def] of all) {
        const r = rows.get(field);
        if (!r) continue;
        r.enable(enabled);
      }
      rows.get("flip_vertical").el.querySelector("input").disabled = !enabled;
      rows.get("flip_horizontal").el.querySelector("input").disabled = !enabled;

      padW.disabled = !enabled || !(rows.get("padding_enabled").checked() ?? false);
      padH.disabled = padW.disabled;
    }
    reset.disabled = !enabled;
    generateBtn.disabled = !enabled;
    recipeSelect.disabled = !enabled;
    copies.input.disabled = !enabled;
    seed.input.disabled = !enabled;
    repeatApply.set(!!state.repeatAugmentation);
    annotationAware.set(s.editParams?.augment?.annotation_aware !== false);
    updateAwarenessStatus();
    practiceBtn.disabled = false;
    if (s.workspace?.practice) {
      contextTitle.textContent = "BUILT-IN LABELLED PRACTICE IMAGE";
      contextText.textContent = "This example is not your dataset. Its box, polygon, and bitmap mask let you verify annotation-aware geometry safely.";
      generateBtn.textContent = "Generate Practice Variants";
      recipeNotice.textContent = "Practice mode: generated examples keep synchronized demonstration labels.";
      contextCard.dataset.mode = "practice";
    } else if (s.dataset?.active) {
      const format = String(s.dataset.format || "dataset").toUpperCase();
      contextTitle.textContent = `LABELLED DATASET — ${format}`;
      contextText.textContent = `${s.dataset.image_count || s.images.length} images · ${(s.dataset.classes || []).length} classes. Annotation-aware geometry supports boxes, polygons, and bitmap masks.`;
      generateBtn.textContent = "Generate Annotated Variants";
      recipeNotice.textContent = "Dataset mode: generated images retain synchronized labels, classes and split information.";
      contextCard.dataset.mode = "dataset";
    } else if (s.workspace?.kind === "image_collection") {
      contextTitle.textContent = "IMAGE COLLECTION — NO ANNOTATIONS";
      contextText.textContent = `${s.images.length} images loaded. Augmentation outputs contain images only.`;
      generateBtn.textContent = "Generate Augmented Images";
      recipeNotice.textContent = "Image-only mode: generated variants will not contain annotation files.";
      contextCard.dataset.mode = "images";
    } else if (s.workspace?.kind === "single") {
      contextTitle.textContent = "SINGLE IMAGE — NO ANNOTATIONS";
      contextText.textContent = "Use this image to preview settings or generate image-only variants.";
      generateBtn.textContent = "Generate Augmented Images";
      recipeNotice.textContent = "Image-only mode: generated variants will not contain annotation files.";
      contextCard.dataset.mode = "images";
    } else {
      contextTitle.textContent = "NO INPUT OPEN";
      contextText.textContent = "Open an images folder or a labelled dataset to begin augmentation.";
      generateBtn.textContent = "Generate Variants";
      recipeNotice.textContent = "Choose an input type first.";
      contextCard.dataset.mode = "empty";
    }
  });
  registerPendingApplyGuard("augment", (params) => {
    const labelled = (state.images || []).some(image => Number(image.annotations || 0) > 0);
    return !labelled || params.annotation_aware !== false || !hasGeometricAugmentation(params)
      || window.confirm("Annotation-aware geometry is OFF. Apply the pending augmentation and leave labels unchanged?");
  });
}
